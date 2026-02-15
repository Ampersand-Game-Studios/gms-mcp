from __future__ import annotations

import asyncio
import datetime as _dt
import os
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

from .debug import _dbg
from .project import _resolve_project_directory
from .results import ToolRunResult


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


def _new_log_path(project_directory: Path, tool_name: str | None) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_tool = (tool_name or "tool").replace(" ", "_")
    return _ensure_log_dir(project_directory) / f"{safe_tool}-{ts}-{os.getpid()}.log"


def _spawn_kwargs() -> Dict[str, Any]:
    return {}


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            # Best effort: terminate the whole tree.
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
            return
        # POSIX: kill the process group if we created one
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


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
    project_root_value = project_root or "."
    project_directory = _resolve_project_directory(project_root)

    # NOTE (Windows/Cursor): running the `gms.exe` console-script wrapper under MCP stdio pipes has been
    # observed to hang indefinitely (even for `--help`). The most robust invocation is via the Python
    # module entrypoint, which avoids the wrapper entirely.
    #
    # You can opt back into `gms.exe` by setting:
    #   GMS_MCP_PREFER_GMS_EXE=1
    selected_gms, gms_candidates = _select_gms_executable()
    prefer_exe = os.environ.get("GMS_MCP_PREFER_GMS_EXE", "").strip().lower() in ("1", "true", "yes", "on")
    if prefer_exe and selected_gms:
        cmd = [selected_gms, "--project-root", str(project_root_value), *cli_args]
        execution_mode = "subprocess:gms-exe"
    else:
        # -u: unbuffered for more predictable output when stdout/stderr are pipes
        cmd = [sys.executable, "-u", "-m", "gms_helpers.gms", "--project-root", str(project_root_value), *cli_args]
        execution_mode = "subprocess:python-module"

    effective_timeout = timeout_seconds
    if effective_timeout is None:
        effective_timeout = _default_timeout_seconds_for_cli_args(cli_args)
    if effective_timeout <= 0:
        effective_timeout = None

    return await _run_subprocess_async(
        cmd,
        cwd=project_directory,
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
            "cmd_head": cmd[:6],
        },
    )
    # endregion
    log_path = _new_log_path(cwd, tool_name)
    start = time.monotonic()

    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    last_output_lock = threading.Lock()
    last_output_time = [time.monotonic()]
    _ = ctx
    _ = heartbeat_seconds

    # Header logging (best-effort)
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as fh:
            fh.write(f"[gms-mcp] tool={tool_name or ''}\n")
            fh.write(f"[gms-mcp] cwd={cwd}\n")
            fh.write(f"[gms-mcp] mode={execution_mode or ''}\n")
            if candidates:
                fh.write(f"[gms-mcp] candidates={candidates}\n")
            fh.write(f"[gms-mcp] cmd={_cmd_to_str(cmd)}\n")
            fh.write(f"[gms-mcp] timeout_seconds={timeout_seconds}\n\n")
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            **_spawn_kwargs(),
        )
    except Exception:
        return ToolRunResult(
            ok=False,
            stdout="",
            stderr="",
            direct_used=False,
            exit_code=None,
            error=traceback.format_exc(),
            pid=None,
            elapsed_seconds=time.monotonic() - start,
            timed_out=False,
            command=cmd,
            cwd=str(cwd),
            log_file=str(log_path),
            execution_mode=execution_mode,
        )
    # region agent log
    _dbg(
        "H3",
        "src/gms_mcp/gamemaker_mcp_server.py:_run_subprocess_async:popen_ok",
        "subprocess Popen ok",
        {"pid": getattr(proc, "pid", None), "tool_name": tool_name, "mode": execution_mode},
    )
    # endregion

    def _append_and_log(stream: str, line: str) -> None:
        now = time.monotonic()
        with last_output_lock:
            last_output_time[0] = now

        if stream == "stdout":
            stdout_chunks.append(line)
        else:
            stderr_chunks.append(line)

        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"[{stream}] {line}")
                if not line.endswith("\n"):
                    fh.write("\n")
        except Exception:
            pass

    def _reader(pipe: Any, stream: str) -> None:
        try:
            for line in iter(pipe.readline, ""):
                if not line:
                    break
                _append_and_log(stream, line)
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
                _terminate_process_tree(proc)
                break

            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        _append_and_log("stderr", "[gms-mcp] CANCELLED by client; terminating process tree\n")
        _terminate_process_tree(proc)
        raise
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        t_out.join(timeout=1)
        t_err.join(timeout=1)

    exit_code = proc.poll()
    elapsed = time.monotonic() - start
    stdout_text = "".join(stdout_chunks)
    stderr_text = "".join(stderr_chunks)
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
        command=cmd,
        cwd=str(cwd),
        log_file=str(log_path),
        execution_mode=execution_mode,
    )

