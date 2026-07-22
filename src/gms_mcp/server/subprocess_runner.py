from __future__ import annotations

import asyncio
import datetime as _dt
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..telemetry import SUPPRESS_CLI_TELEMETRY_ENV_VAR
from .debug import _dbg
from .project import _resolve_project_directory, _with_cli_pythonpath
from .results import ToolRunResult


# Completed logs are pruned oldest-first by (mtime, filename). Active logs and
# the invocation being finalized are protected. Each individual log and each
# returned stream are capped while the process is still running.
LOG_MAX_COMPLETED_FILES = 50
LOG_MAX_COMPLETED_BYTES = 20 * 1024 * 1024
LOG_MAX_ACTIVE_BYTES = 4 * 1024 * 1024
SUBPROCESS_CAPTURE_MAX_BYTES = 2 * 1024 * 1024
LOG_ACTIVE_MARKER_STALE_SECONDS = 6 * 60 * 60
PROCESS_TERMINATE_GRACE_SECONDS = 0.75
PROCESS_KILL_VERIFY_SECONDS = 3.0
_LOG_NAME_MAX_LENGTH = 64
_LOG_SEQUENCE = 0
_LOG_SEQUENCE_LOCK = threading.Lock()
_SECRET_OPTION_MARKERS = (
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "api-key",
    "apikey",
    "access-key",
    "accesskey",
)


class _BoundedByteCapture:
    """Retain a bounded tail while continuing to drain an arbitrary stream."""

    def __init__(self, limit: int):
        self.limit = max(0, limit)
        self._data = bytearray()
        self._omitted = 0
        self._lock = threading.Lock()

    def append(self, value: str | bytes) -> None:
        encoded = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
        with self._lock:
            self._data.extend(encoded)
            overflow = len(self._data) - self.limit
            if overflow > 0:
                del self._data[:overflow]
                self._omitted += overflow

    def text(self) -> str:
        with self._lock:
            retained = bytes(self._data)
            omitted = self._omitted
        text = retained.decode("utf-8", errors="replace")
        if omitted:
            return f"[output truncated: {omitted} bytes omitted]\n{text}"
        return text


class _BoundedLogWriter:
    """Append diagnostic output without allowing an active log to grow forever."""

    _TRUNCATION_MARKER = b"\n[gms-mcp] LOG TRUNCATED; further output omitted\n"

    def __init__(self, path: Path, limit: int):
        self.path = path
        self.limit = max(0, limit)
        self._written = 0
        self._truncated = False
        self._lock = threading.Lock()
        try:
            path.write_bytes(b"")
        except OSError:
            pass

    def append(self, value: str | bytes) -> None:
        encoded = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
        with self._lock:
            if self._truncated or self._written >= self.limit:
                return
            remaining = self.limit - self._written
            if len(encoded) <= remaining:
                payload = encoded
            else:
                marker = self._TRUNCATION_MARKER[:remaining]
                prefix_size = max(0, remaining - len(marker))
                payload = encoded[:prefix_size] + marker
                self._truncated = True
            try:
                with self.path.open("ab") as log_file:
                    log_file.write(payload)
                self._written += len(payload)
            except OSError:
                return


def _redact_command(cmd: List[str]) -> List[str]:
    redacted: List[str] = []
    redact_next = False
    for raw in cmd:
        token = str(raw)
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        option, separator, _value = token.partition("=")
        normalized = option.lstrip("-/").lower().replace("_", "-")
        is_secret = any(marker in normalized for marker in _SECRET_OPTION_MARKERS) or normalized == "ak"
        if is_secret and separator:
            redacted.append(f"{option}=[REDACTED]")
        else:
            redacted.append(token)
            redact_next = is_secret
    return redacted


def _cmd_to_str(cmd: List[str]) -> str:
    if os.name == "nt":
        try:
            return subprocess.list2cmdline(cmd)
        except Exception:
            return " ".join(cmd)
    return " ".join(shlex.quote(p) for p in cmd)


def _resolve_gms_candidates_windows() -> List[str]:
    """
    On Windows, `shutil.which('gms')` can pick the WindowsApps shim first.
    Prefer real executables when multiple exist.
    """
    try:
        completed = subprocess.run(["where", "gms"], capture_output=True, text=True)
        if completed.returncode != 0:
            return []
        lines = [l.strip() for l in (completed.stdout or "").splitlines() if l.strip()]
        return lines
    except Exception:
        return []


def _select_gms_executable() -> Tuple[Optional[str], List[str]]:
    """
    Returns (selected, candidates).
    If `gms` isn't found, selected is None.
    """
    override = os.environ.get("GMS_MCP_GMS_PATH", "").strip()
    if override:
        try:
            p = Path(override).expanduser()
            if p.exists():
                return str(p), [str(p)]
        except Exception:
            # Fall through to discovery
            pass

    candidates: List[str] = []
    if os.name == "nt":
        candidates = _resolve_gms_candidates_windows()
        # Prefer non-WindowsApps shims
        for c in candidates:
            lc = c.lower()
            if "windowsapps" not in lc:
                return c, candidates
        if candidates:
            return candidates[0], candidates
    selected = shutil.which("gms")
    if selected:
        candidates = [selected]
    return selected, candidates


def _default_timeout_seconds_for_cli_args(cli_args: List[str]) -> int:
    # "Never hang forever" by default, but do not be aggressive.
    # Can be overridden by `timeout_seconds` param or env var.
    env = os.environ.get("GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "").strip()
    if env:
        try:
            v = int(env)
            if v > 0:
                return v
        except Exception:
            pass

    category = (cli_args[0] if cli_args else "").strip().lower()
    if category == "maintenance":
        return 60 * 30  # 30 min
    if category == "run":
        action = (cli_args[1] if len(cli_args) > 1 else "").strip().lower()
        if action in {"status", "stop"}:
            return 60 * 2  # 2 min
        if action == "background-start":
            return 60 * 30  # 30 min
        return 60 * 60 * 2  # 2 hours
    # asset/event/workflow/room are typically quick
    return 60 * 10  # 10 min


def _ensure_log_dir(project_directory: Path) -> Path:
    # Keep logs in-project so users can attach them to bug reports.
    log_dir = project_directory / ".gms_mcp" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Best effort: fallback to CWD
        log_dir = Path.cwd() / ".gms_mcp" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _sanitize_tool_name(tool_name: str | None) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", tool_name or "tool")
    normalized = normalized.strip("._-")[:_LOG_NAME_MAX_LENGTH]
    return normalized or "tool"


def _active_marker_path(log_path: Path) -> Path:
    return log_path.with_suffix(log_path.suffix + ".active")


def _prune_log_dir(log_dir: Path, *, keep: Path | None = None) -> None:
    """Bound completed diagnostic logs without deleting active/latest logs."""
    now = time.time()
    records: List[tuple[Path, int, int]] = []
    protected: set[Path] = {keep.resolve()} if keep is not None else set()
    for log_path in log_dir.glob("*.log"):
        try:
            stat_result = log_path.stat()
        except OSError:
            continue
        marker = _active_marker_path(log_path)
        if marker.exists():
            try:
                marker_age = now - marker.stat().st_mtime
            except OSError:
                marker_age = 0
            if marker_age <= LOG_ACTIVE_MARKER_STALE_SECONDS:
                protected.add(log_path.resolve())
            else:
                try:
                    marker.unlink()
                except OSError:
                    protected.add(log_path.resolve())
        records.append((log_path, stat_result.st_mtime_ns, stat_result.st_size))

    records.sort(key=lambda record: (record[1], record[0].name))
    remaining_count = len(records)
    remaining_bytes = sum(record[2] for record in records)
    for log_path, _mtime_ns, size in records:
        if remaining_count <= LOG_MAX_COMPLETED_FILES and remaining_bytes <= LOG_MAX_COMPLETED_BYTES:
            break
        if log_path.resolve() in protected:
            continue
        try:
            log_path.unlink()
        except OSError:
            continue
        remaining_count -= 1
        remaining_bytes -= size


def _new_log_path(project_directory: Path, tool_name: str | None) -> Path:
    global _LOG_SEQUENCE
    log_dir = _ensure_log_dir(project_directory)
    _prune_log_dir(log_dir)
    with _LOG_SEQUENCE_LOCK:
        _LOG_SEQUENCE += 1
        sequence = _LOG_SEQUENCE
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    safe_tool = _sanitize_tool_name(tool_name)
    return log_dir / f"{safe_tool}-{timestamp}-{os.getpid()}-{sequence}.log"


def _mark_log_active(log_path: Path) -> None:
    try:
        _active_marker_path(log_path).write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _finalize_log(log_path: Path) -> None:
    try:
        _active_marker_path(log_path).unlink(missing_ok=True)
    except OSError:
        pass
    _prune_log_dir(log_path.parent, keep=log_path)


def _spawn_kwargs() -> Dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)}
    return {"start_new_session": True}


def _posix_process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_for_posix_process_group_exit(
    process_group_id: int,
    timeout: float,
    proc: subprocess.Popen | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None:
            proc.poll()
        if not _posix_process_group_exists(process_group_id):
            return True
        time.sleep(0.05)
    if proc is not None:
        proc.poll()
    return not _posix_process_group_exists(process_group_id)


def _terminate_process_tree(proc: subprocess.Popen) -> bool:
    """Terminate the isolated child tree and verify it is no longer running."""
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
            try:
                proc.wait(timeout=PROCESS_KILL_VERIFY_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=PROCESS_KILL_VERIFY_SECONDS)
            return completed.returncode == 0 and proc.poll() is not None

        try:
            process_group_id = os.getpgid(proc.pid)
        except ProcessLookupError:
            return proc.poll() is not None

        if process_group_id != proc.pid:
            # Never signal a group we did not create; it could be the server's.
            proc.terminate()
            try:
                proc.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=PROCESS_KILL_VERIFY_SECONDS)
            return proc.poll() is not None

        os.killpg(process_group_id, signal.SIGTERM)
        if _wait_for_posix_process_group_exit(process_group_id, PROCESS_TERMINATE_GRACE_SECONDS, proc):
            return True
        os.killpg(process_group_id, signal.SIGKILL)
        return _wait_for_posix_process_group_exit(process_group_id, PROCESS_KILL_VERIFY_SECONDS, proc)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
            proc.wait(timeout=PROCESS_KILL_VERIFY_SECONDS)
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.poll() is not None


async def _run_cli_async(
    cli_args: List[str],
    project_root: str | None,
    *,
    timeout_seconds: int | None = None,
    heartbeat_seconds: float = 5.0,
    tool_name: str | None = None,
    ctx: Any | None = None,
) -> ToolRunResult:
    """
    Run the CLI in a subprocess with:
    - stdout/stderr drained concurrently to prevent subprocess pipe deadlocks
    - a generous, category-aware max runtime timeout (overrideable)
    - always writes a local log file for post-mortems
    """
    project_directory = _resolve_project_directory(project_root)
    project_root_value = str(project_directory)
    from gms_helpers.transactions import (
        journaled_gms_cli_command,
        transaction_subprocess_environment,
    )

    transaction_env = transaction_subprocess_environment()

    # NOTE (Windows/Cursor): running the `gms.exe` console-script wrapper under MCP stdio pipes has been
    # observed to hang indefinitely (even for `--help`). The most robust invocation is via the Python
    # module entrypoint, which avoids the wrapper entirely.
    #
    # You can opt back into `gms.exe` by setting:
    #   GMS_MCP_PREFER_GMS_EXE=1
    selected_gms, gms_candidates = _select_gms_executable()
    prefer_exe = os.environ.get("GMS_MCP_PREFER_GMS_EXE", "").strip().lower() in ("1", "true", "yes", "on")
    cli_invocation = ["--project-root", str(project_root_value), *cli_args]
    if transaction_env:
        cmd = journaled_gms_cli_command(cli_invocation)
        execution_mode = "subprocess:python-module-journaled"
    elif prefer_exe and selected_gms:
        cmd = [selected_gms, "--project-root", str(project_root_value), *cli_args]
        execution_mode = "subprocess:gms-exe"
    else:
        # -u: unbuffered for more predictable output when stdout/stderr are pipes
        cmd = [sys.executable, "-u", "-m", "gms_helpers.gms", "--project-root", str(project_root_value), *cli_args]
        execution_mode = "subprocess:python-module"
    nested_cli_env = _with_cli_pythonpath(os.environ.copy())
    nested_cli_env[SUPPRESS_CLI_TELEMETRY_ENV_VAR] = "1"
    nested_cli_env.update(transaction_env)

    effective_timeout = timeout_seconds
    if effective_timeout is None:
        effective_timeout = _default_timeout_seconds_for_cli_args(cli_args)
    if effective_timeout <= 0:
        effective_timeout = None

    return await _run_subprocess_async(
        cmd,
        cwd=project_directory,
        env=nested_cli_env,
        timeout_seconds=effective_timeout,
        heartbeat_seconds=heartbeat_seconds,
        tool_name=tool_name,
        ctx=ctx,
        execution_mode=execution_mode,
        candidates=gms_candidates,
    )


async def _run_subprocess_async(
    cmd: List[str],
    *,
    cwd: Path,
    env: Dict[str, str] | None = None,
    timeout_seconds: int | None = None,
    heartbeat_seconds: float = 5.0,
    tool_name: str | None = None,
    ctx: Any | None = None,
    execution_mode: str | None = None,
    candidates: List[str] | None = None,
) -> ToolRunResult:
    """
    Generic subprocess runner with safe stdout/stderr draining + timeout + cancellation.

    IMPORTANT:
    Do NOT call `ctx.log()` (or emit any MCP notifications) while a subprocess is running.
    Cursor's MCP transport shares stdio; attempting to stream logs can deadlock the server
    if the client applies backpressure or stops consuming notifications.
    Instead, we write a complete local log file and return stdout/stderr when finished.
    """
    safe_command = _redact_command(cmd)
    # region agent log
    _dbg(
        "H3",
        "src/gms_mcp/gamemaker_mcp_server.py:_run_subprocess_async:entry",
        "subprocess runner entry",
        {
            "tool_name": tool_name,
            "cwd": str(cwd),
            "timeout_seconds": timeout_seconds,
            "heartbeat_seconds": heartbeat_seconds,
            "execution_mode": execution_mode,
            "cmd_head": safe_command[:6],
        },
    )
    # endregion
    log_path = _new_log_path(cwd, tool_name)
    _mark_log_active(log_path)
    start = time.monotonic()

    stdout_capture = _BoundedByteCapture(SUBPROCESS_CAPTURE_MAX_BYTES)
    stderr_capture = _BoundedByteCapture(SUBPROCESS_CAPTURE_MAX_BYTES)
    last_output_lock = threading.Lock()
    last_output_time = [time.monotonic()]
    _ = ctx
    _ = heartbeat_seconds

    log_writer = _BoundedLogWriter(log_path, LOG_MAX_ACTIVE_BYTES)
    log_writer.append(f"[gms-mcp] tool={tool_name or ''}\n")
    log_writer.append(f"[gms-mcp] cwd={cwd}\n")
    log_writer.append(f"[gms-mcp] mode={execution_mode or ''}\n")
    if candidates:
        log_writer.append(f"[gms-mcp] candidates={candidates}\n")
    log_writer.append(f"[gms-mcp] cmd={_cmd_to_str(safe_command)}\n")
    log_writer.append(f"[gms-mcp] timeout_seconds={timeout_seconds}\n\n")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
            **_spawn_kwargs(),
        )
    except Exception:
        error_text = traceback.format_exc()
        log_writer.append(f"[stderr] [gms-mcp] SPAWN FAILED\n{error_text}\n")
        result = ToolRunResult(
            ok=False,
            stdout="",
            stderr="",
            direct_used=False,
            exit_code=None,
            error=error_text,
            pid=None,
            elapsed_seconds=time.monotonic() - start,
            timed_out=False,
            command=safe_command,
            cwd=str(cwd),
            log_file=str(log_path),
            execution_mode=execution_mode,
        )
        _finalize_log(log_path)
        return result
    # region agent log
    _dbg(
        "H3",
        "src/gms_mcp/gamemaker_mcp_server.py:_run_subprocess_async:popen_ok",
        "subprocess Popen ok",
        {"pid": getattr(proc, "pid", None), "tool_name": tool_name, "mode": execution_mode},
    )
    # endregion

    def _append_and_log(stream: str, chunk: str | bytes) -> None:
        now = time.monotonic()
        with last_output_lock:
            last_output_time[0] = now

        if stream == "stdout":
            stdout_capture.append(chunk)
        else:
            stderr_capture.append(chunk)

        encoded = chunk.encode("utf-8", errors="replace") if isinstance(chunk, str) else chunk
        log_writer.append(f"[{stream}] ".encode() + encoded)
        if not encoded.endswith(b"\n"):
            log_writer.append(b"\n")

    def _reader(pipe: Any, stream: str) -> None:
        try:
            while chunk := pipe.read(64 * 1024):
                _append_and_log(stream, chunk)
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    t_out = threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)  # type: ignore[arg-type]
    t_err = threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True)  # type: ignore[arg-type]
    t_out.start()
    t_err.start()

    timed_out = False
    termination_verified: bool | None = None
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                break

            elapsed = time.monotonic() - start
            if timeout_seconds is not None and elapsed > float(timeout_seconds):
                timed_out = True
                _append_and_log(
                    "stderr",
                    f"[gms-mcp] TIMEOUT after {timeout_seconds}s; terminating process tree (pid={proc.pid})\n",
                )
                termination_verified = _terminate_process_tree(proc)
                if not termination_verified:
                    _append_and_log("stderr", "[gms-mcp] Process-tree exit could not be verified\n")
                break

            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        _append_and_log("stderr", "[gms-mcp] CANCELLED by client; terminating process tree\n")
        termination_verified = _terminate_process_tree(proc)
        if not termination_verified:
            _append_and_log("stderr", "[gms-mcp] Process-tree exit could not be verified\n")
        raise
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            termination_verified = _terminate_process_tree(proc)
            try:
                proc.wait(timeout=PROCESS_KILL_VERIFY_SECONDS)
            except subprocess.TimeoutExpired:
                termination_verified = False
        except OSError:
            termination_verified = False

        t_out.join(timeout=1)
        t_err.join(timeout=1)
        if termination_verified is False:
            _append_and_log("stderr", "[gms-mcp] WARNING: process-tree cleanup was not verified\n")
        _finalize_log(log_path)

    exit_code = proc.poll()
    elapsed = time.monotonic() - start
    stdout_text = stdout_capture.text()
    stderr_text = stderr_capture.text()
    ok = (exit_code == 0) and not timed_out
    return ToolRunResult(
        ok=ok,
        stdout=stdout_text,
        stderr=stderr_text,
        direct_used=False,
        exit_code=exit_code,
        error=None if ok else ("CLI timed out" if timed_out else f"Process exited with code {exit_code}"),
        pid=proc.pid,
        elapsed_seconds=elapsed,
        timed_out=timed_out,
        command=safe_command,
        cwd=str(cwd),
        log_file=str(log_path),
        execution_mode=execution_mode,
    )
