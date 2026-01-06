#!/usr/bin/env python3
"""
GameMaker MCP Server

Exposes common GameMaker project actions as MCP tools by reusing the existing
Python helper modules in `gms_helpers`.

Design:
- Prefer **direct imports** (call handlers in-process).
- If a direct call throws, **fallback** to running the `gms` CLI as a module (`python -m gms_helpers.gms`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as _dt
import io
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .execution_policy import policy_manager, ExecutionMode


def _get_debug_log_path() -> Optional[Path]:
    """Resolve the debug log path safely (best-effort)."""
    try:
        candidates: List[Path] = []
        # 1. Environment overrides
        for env_var in ["GM_PROJECT_ROOT", "PROJECT_ROOT"]:
            val = os.environ.get(env_var)
            if val:
                candidates.append(Path(val))
        
        # 2. CWD
        candidates.append(Path.cwd())

        for raw in candidates:
            try:
                p = Path(raw).expanduser().resolve()
                if p.is_file():
                    p = p.parent
                if not p.exists():
                    continue
                
                # Check for .yyp or gamemaker/ folder
                if list(p.glob("*.yyp")) or (p / "gamemaker").is_dir():
                    log_dir = p / ".gms_mcp" / "logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    return log_dir / "debug.log"
            except Exception:
                continue
        
        # Fallback to CWD
        fallback_dir = Path.cwd() / ".gms_mcp" / "logs"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / "debug.log"
    except Exception:
        return None


def _dbg(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append a single NDJSON debug line to .gms_mcp/logs/debug.log (best-effort)."""
    try:
        log_path = _get_debug_log_path()
        if not log_path:
            return
            
        payload = {
            "sessionId": "debug-session",
            "runId": os.environ.get("GMS_MCP_DEBUG_RUN_ID", "cursor-repro"),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def _list_yyp_files(directory: Path) -> List[Path]:
    try:
        return sorted(directory.glob("*.yyp"))
    except Exception:
        return []


def _search_upwards_for_yyp(start_dir: Path) -> Optional[Path]:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        if _list_yyp_files(candidate):
            return candidate
    return None


def _search_upwards_for_gamemaker_yyp(start_dir: Path) -> Optional[Path]:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        gm = candidate / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm
    return None


def _resolve_project_directory_no_deps(project_root: str | None) -> Path:
    """
    Resolve the GameMaker project directory (the folder containing a .yyp)
    without importing `gms_helpers` (so we don't need to know repo root yet).
    """
    candidates: List[Path] = []
    if project_root is not None:
        root_str = str(project_root).strip()
        if root_str and root_str != ".":
            candidates.append(Path(root_str))

    # Environment overrides (handy for agents)
    env_gm_root = os.environ.get("GM_PROJECT_ROOT")
    if env_gm_root:
        candidates.append(Path(env_gm_root))
    env_root = os.environ.get("PROJECT_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(Path.cwd())

    tried: List[str] = []
    for raw in candidates:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        if p.is_file():
            p = p.parent
        tried.append(str(p))
        if not p.exists() or not p.is_dir():
            continue

        if _list_yyp_files(p):
            return p

        gm = p / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm

        found = _search_upwards_for_yyp(p)
        if found:
            return found

        found_gm = _search_upwards_for_gamemaker_yyp(p)
        if found_gm:
            return found_gm

    raise FileNotFoundError(
        "Could not find a GameMaker project directory (.yyp) from the provided project_root or CWD. "
        f"Tried: {tried}"
    )


def _resolve_repo_root(project_root: str | None) -> Path:
    """
    Compatibility shim: older versions of this server expected a "repo root" that contained `cli/`.

    In the packaged install, the tool code is importable as Python packages and does not require a repo root.
    """
    _ = project_root
    return Path(__file__).resolve().parents[1]


def _ensure_cli_on_sys_path(_repo_root: Path) -> None:
    # Compatibility shim (no-op in installed mode).
    return None


@contextlib.contextmanager
def _pushd(target_directory: Path):
    """Temporarily change working directory."""
    previous_directory = Path.cwd()
    os.chdir(target_directory)
    try:
        yield
    finally:
        os.chdir(previous_directory)


@dataclass
class ToolRunResult:
    ok: bool
    stdout: str
    stderr: str
    direct_used: bool
    exit_code: Optional[int] = None
    error: Optional[str] = None
    direct_error: Optional[str] = None
    pid: Optional[int] = None
    elapsed_seconds: Optional[float] = None
    timed_out: bool = False
    command: Optional[List[str]] = None
    cwd: Optional[str] = None
    log_file: Optional[str] = None
    execution_mode: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "direct_used": self.direct_used,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
            "direct_error": self.direct_error,
            "pid": self.pid,
            "elapsed_seconds": self.elapsed_seconds,
            "timed_out": self.timed_out,
            "command": self.command,
            "cwd": self.cwd,
            "log_file": self.log_file,
            "execution_mode": self.execution_mode,
        }


def _apply_output_mode(
    result: Dict[str, Any],
    *,
    output_mode: str = "full",
    tail_lines: int = 120,
    max_chars: int = 40000,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Pure output-shaping helper (no side effects, no command execution).
    """
    normalized_mode = output_mode
    if quiet and output_mode == "full":
        normalized_mode = "tail"

    def _tail(text: str) -> Tuple[str, bool]:
        if not text:
            return "", False
        lines = text.splitlines()
        if tail_lines > 0 and len(lines) > tail_lines:
            lines = lines[-tail_lines:]
        out = "\n".join(lines)
        if max_chars > 0 and len(out) > max_chars:
            out = out[-max_chars:]
            return out, True
        return out, False

    if normalized_mode not in ("full", "tail", "none"):
        normalized_mode = "tail"

    stdout_text = str(result.get("stdout", "") or "")
    stderr_text = str(result.get("stderr", "") or "")

    if normalized_mode == "full":
        return result
    if normalized_mode == "none":
        result["stdout"] = ""
        result["stderr"] = ""
        result["stdout_truncated"] = bool(stdout_text)
        result["stderr_truncated"] = bool(stderr_text)
        return result

    stdout_tail, stdout_truncated = _tail(stdout_text)
    stderr_tail, stderr_truncated = _tail(stderr_text)
    result["stdout"] = stdout_tail
    result["stderr"] = stderr_tail
    result["stdout_truncated"] = stdout_truncated or (tail_lines > 0 and len(stdout_text.splitlines()) > tail_lines)
    result["stderr_truncated"] = stderr_truncated or (tail_lines > 0 and len(stderr_text.splitlines()) > tail_lines)
    return result


def _resolve_project_directory(project_root: str | None) -> Path:
    # Prefer in-repo resolution (no imports) so server doesn't depend on process CWD.
    return _resolve_project_directory_no_deps(project_root)


def _find_yyp_file(project_directory: Path) -> Optional[str]:
    try:
        yyp_files = sorted(project_directory.glob("*.yyp"))
        if not yyp_files:
            return None
        return yyp_files[0].name
    except Exception:
        return None


def _capture_output(callable_to_run: Callable[[], Any]) -> Tuple[bool, str, str, Any, Optional[str], Optional[int]]:
    # ... buffers ...
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    stdout_buffer = io.TextIOWrapper(stdout_bytes, encoding="utf-8", errors="replace", line_buffering=True)
    stderr_buffer = io.TextIOWrapper(stderr_bytes, encoding="utf-8", errors="replace", line_buffering=True)
    result_value: Any = None
    error_text: Optional[str] = None

    system_exit_code: Any | None = None
    from gms_helpers.exceptions import GMSError

    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        try:
            result_value = callable_to_run()
            if hasattr(result_value, "success"):
                ok = result_value.success
            elif isinstance(result_value, bool):
                ok = result_value
            else:
                ok = True
        except GMSError as e:
            ok = False
            error_text = f"{type(e).__name__}: {e.message}"
            system_exit_code = e.exit_code
        except SystemExit as e:
            system_exit_code = getattr(e, "code", None)
            ok = system_exit_code in (0, None)
        except Exception:
            ok = False
            error_text = traceback.format_exc()

    try:
        stdout_buffer.flush()
        stderr_buffer.flush()
    except Exception:
        pass

    stdout_text = ""
    stderr_text = ""
    try:
        stdout_text = stdout_bytes.getvalue().decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.getvalue().decode("utf-8", errors="replace")
    except Exception:
        # Best-effort fallback
        stdout_text = ""
        stderr_text = ""

    if system_exit_code is not None and not ok and not error_text:
        pieces = [f"SystemExit: {system_exit_code!r}"]
        if stdout_text:
            pieces.append("stdout:\n" + stdout_text)
        if stderr_text:
            pieces.append("stderr:\n" + stderr_text)
        error_text = "\n".join(pieces)

    return ok, stdout_text, stderr_text, result_value, error_text, system_exit_code


def _run_direct(handler: Callable[[argparse.Namespace], Any], args: argparse.Namespace, project_root: str | None) -> ToolRunResult:
    project_directory = _resolve_project_directory(project_root)

    def _invoke() -> Any:
        from gms_helpers.utils import validate_working_directory

        with _pushd(project_directory):
            # Mirror CLI behavior: validate and then run in the resolved directory.
            validate_working_directory()
            # Normalize project_root after chdir so downstream handlers behave consistently.
            setattr(args, "project_root", ".")
            return handler(args)

    ok, stdout_text, stderr_text, _result_value, error_text, exit_code = _capture_output(_invoke)
    return ToolRunResult(
        ok=ok,
        stdout=stdout_text,
        stderr=stderr_text,
        direct_used=True,
        exit_code=exit_code,
        error=error_text,
    )


def _run_gms_inprocess(cli_args: List[str], project_root: str | None) -> ToolRunResult:
    """
    Run `gms_helpers/gms.py` in-process (no subprocess), by importing it and calling `main()`.

    This avoids the class of hangs where a spawned Python process wedges (pip, PATH, antivirus, etc.).
    """
    project_root_value = project_root or "."

    def _invoke() -> bool:
        # Import the CLI entrypoint and run it as if invoked from command line.
        from gms_helpers import gms as gms_module

        previous_argv = sys.argv[:]
        try:
            sys.argv = ["gms", "--project-root", str(project_root_value), *cli_args]
            try:
                return bool(gms_module.main())
            except SystemExit as e:
                # argparse throws SystemExit on invalid args / help, etc.
                code = int(getattr(e, "code", 1) or 0)
                return code == 0
        finally:
            sys.argv = previous_argv

    ok, stdout_text, stderr_text, _result_value, error_text, exit_code = _capture_output(_invoke)
    return ToolRunResult(
        ok=ok,
        stdout=stdout_text,
        stderr=stderr_text,
        direct_used=True,
        exit_code=exit_code if exit_code is not None else (0 if ok else 1),
        error=error_text,
    )


def _run_cli(cli_args: List[str], project_root: str | None, timeout_seconds: int | None = None) -> ToolRunResult:
    raise RuntimeError("_run_cli is now async; call _run_cli_async")


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
    loop = asyncio.get_running_loop()

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
                _append_and_log("stderr", f"[gms-mcp] TIMEOUT after {timeout_seconds}s; terminating process tree (pid={proc.pid})\n")
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


async def _run_with_fallback(
    *,
    direct_handler: Callable[[argparse.Namespace], Any],
    direct_args: argparse.Namespace,
    cli_args: List[str],
    project_root: str | None,
    prefer_cli: bool,
    output_mode: str = "full",
    tail_lines: int = 120,
    max_chars: int = 40000,
    quiet: bool = False,
    timeout_seconds: int | None = None,
    tool_name: str | None = None,
    ctx: Any | None = None,
) -> Dict[str, Any]:
    derived_tool_name = tool_name
    if not derived_tool_name:
        head = [p for p in (cli_args[:3] if cli_args else []) if p]
        derived_tool_name = "-".join(head) if head else "tool"

    # Get execution policy for this tool
    policy = policy_manager.get_policy(derived_tool_name)
    effective_mode = policy.mode
    effective_timeout = timeout_seconds if timeout_seconds is not None else policy.timeout_seconds

    # Respect manual override via prefer_cli
    if prefer_cli:
        effective_mode = ExecutionMode.SUBPROCESS

    if effective_mode == ExecutionMode.SUBPROCESS:
        return _apply_output_mode(
            (await _run_cli_async(cli_args, project_root, timeout_seconds=effective_timeout, tool_name=derived_tool_name, ctx=ctx)).as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )

    # ExecutionMode.DIRECT
    _ = ctx

    direct_result = _run_direct(direct_handler, direct_args, project_root)
    if direct_result.ok:
        return _apply_output_mode(
            direct_result.as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )

    # If the direct call threw (or otherwise failed), fall back to subprocess for resilience.
    cli_result = await _run_cli_async(cli_args, project_root, timeout_seconds=timeout_seconds, tool_name=derived_tool_name, ctx=ctx)
    cli_result.direct_error = direct_result.error or "Direct call failed"
    return _apply_output_mode(
        cli_result.as_dict(),
        output_mode=output_mode,
        tail_lines=tail_lines,
        max_chars=max_chars,
        quiet=quiet,
    )


def build_server():
    """
    Create and return the MCP server instance.
    Kept in a function so importing this module doesn't require MCP installed.
    """
    from mcp.server.fastmcp import Context, FastMCP
    from .update_notifier import check_for_updates

    # region agent log
    _dbg(
        "H2",
        "src/gms_mcp/gamemaker_mcp_server.py:build_server:entry",
        "build_server entry",
        {"pid": os.getpid(), "exe": sys.executable, "cwd": os.getcwd(), "py_path_head": sys.path[:5]},
    )
    # endregion

    # FastMCP evaluates type annotations at runtime (inspect.signature(..., eval_str=True)).
    # Because we use `from __future__ import annotations`, annotations are strings and must be
    # resolvable from the function's *globals* dict. Ensure `Context` is available there.
    globals()["Context"] = Context

    mcp = FastMCP("GameMaker MCP")

    @mcp.tool()
    async def gm_project_info(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Resolve GameMaker project directory (where the .yyp lives) and return basic info.
        """
        _ = ctx
        project_directory = _resolve_project_directory_no_deps(project_root)
        
        # Check for updates in a separate thread to avoid blocking (best-effort)
        # However, for a quick check, we can just call it.
        # We'll use a 2s timeout in the notifier to keep it snappy.
        update_info = check_for_updates()
        
        return {
            "project_directory": str(project_directory),
            "yyp": _find_yyp_file(project_directory),
            "tools_mode": "installed",
            "updates": update_info,
        }

    @mcp.tool()
    async def gm_mcp_health(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Perform a comprehensive health check of the GameMaker development environment.
        Verifies project validity, GameMaker runtimes/Igor, licenses, and Python dependencies.
        """
        from gms_helpers.health import gm_mcp_health as health_check
        import argparse
        
        return await _run_with_fallback(
            direct_handler=lambda args: health_check(args.project_root),
            direct_args=argparse.Namespace(project_root=project_root),
            cli_args=["maintenance", "health"],
            project_root=project_root,
            prefer_cli=False,
            tool_name="gm-mcp-health",
            ctx=ctx
        )

    @mcp.tool()
    async def gm_cli(
        args: List[str],
        project_root: str = ".",
        prefer_cli: bool = True,
        timeout_seconds: int = 30,
        output_mode: str = "tail",
        tail_lines: int = 120,
        quiet: bool = True,
        fallback_to_subprocess: bool = True,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Run the existing `gms` CLI.

        - If `prefer_cli=true` (default): run in a subprocess with captured output + timeout.
        - If `prefer_cli=false`: try in-process first, and (optionally) fall back to subprocess.
        Example args: ["maintenance", "auto", "--fix", "--verbose"]
        """
        # If prefer_cli=True, run the subprocess path (streamed + cancellable).
        if prefer_cli:
            cli_dict = (await _run_cli_async(args, project_root, timeout_seconds=timeout_seconds, tool_name="gm_cli", ctx=ctx)).as_dict()
            return _apply_output_mode(
                cli_dict,
                output_mode=output_mode,
                tail_lines=tail_lines,
                quiet=quiet,
            )

        # Otherwise, attempt in-process first (legacy behavior).
        inprocess_dict = _run_gms_inprocess(args, project_root).as_dict()
        shaped_inprocess = _apply_output_mode(
            inprocess_dict,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )
        if shaped_inprocess.get("ok"):
            return shaped_inprocess

        if not fallback_to_subprocess:
            shaped_inprocess["error"] = shaped_inprocess.get("error") or "In-process gms execution failed"
            return shaped_inprocess

        # Backup: subprocess with timeout (streamed + cancellable).
        cli_dict = (await _run_cli_async(args, project_root, timeout_seconds=timeout_seconds, tool_name="gm_cli", ctx=ctx)).as_dict()
        cli_dict["direct_error"] = shaped_inprocess.get("error") or "In-process gms execution failed"
        return _apply_output_mode(
            cli_dict,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Diagnostic tools
    # -----------------------------
    @mcp.tool()
    async def gm_diagnostics(
        depth: str = "quick",
        include_info: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Run project diagnostics and return structured issues.
        
        Args:
            depth: "quick" runs fast lint checks only; "deep" adds reference 
                   analysis, orphan detection, and GML string search.
            include_info: Whether to include info-level diagnostics.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.diagnostics_commands import handle_diagnostics

        args = argparse.Namespace(
            depth=depth,
            include_info=include_info,
            project_root=project_root,
        )
        cli_args = ["diagnostics", "--depth", depth]
        if include_info:
            cli_args.append("--include-info")

        return await _run_with_fallback(
            direct_handler=handle_diagnostics,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Asset creation tools
    # -----------------------------
    @mcp.tool()
    async def gm_create_script(
        name: str,
        parent_path: str = "",
        is_constructor: bool = False,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker script asset."""
        # region agent log
        _dbg(
            "H2",
            "src/gms_mcp/gamemaker_mcp_server.py:gm_create_script:entry",
            "gm_create_script tool entry",
            {
                "name": name,
                "parent_path": parent_path,
                "project_root": project_root,
                "prefer_cli": prefer_cli,
                "skip_maintenance": skip_maintenance,
            },
        )
        # endregion
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="script",
            name=name,
            parent_path=parent_path,
            constructor=is_constructor,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "script",
            name,
            "--parent-path",
            parent_path,
        ]
        if is_constructor:
            cli_args.append("--constructor")
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_object(
        name: str,
        parent_path: str = "",
        sprite_id: str = "",
        parent_object: str = "",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker object asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="object",
            name=name,
            parent_path=parent_path,
            sprite_id=sprite_id or None,
            parent_object=parent_object or None,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "object",
            name,
            "--parent-path",
            parent_path,
        ]
        if sprite_id:
            cli_args.extend(["--sprite-id", sprite_id])
        if parent_object:
            cli_args.extend(["--parent-object", parent_object])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_sprite(
        name: str,
        parent_path: str = "",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker sprite asset (includes required image structure via your helpers)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sprite",
            name=name,
            parent_path=parent_path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "sprite",
            name,
            "--parent-path",
            parent_path,
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_room(
        name: str,
        parent_path: str = "",
        width: int = 1024,
        height: int = 768,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker room asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="room",
            name=name,
            parent_path=parent_path,
            width=width,
            height=height,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "room",
            name,
            "--parent-path",
            parent_path,
            "--width",
            str(width),
            "--height",
            str(height),
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_folder(
        name: str,
        path: str,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker folder asset (`folders/My Folder.yy`)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="folder",
            name=name,
            path=path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "folder",
            name,
            "--path",
            path,
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_font(
        name: str,
        parent_path: str = "",
        font_name: str = "Arial",
        size: int = 12,
        bold: bool = False,
        italic: bool = False,
        aa_level: int = 1,
        uses_sdf: bool = True,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker font asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="font",
            name=name,
            parent_path=parent_path,
            font_name=font_name,
            size=size,
            bold=bold,
            italic=italic,
            aa_level=aa_level,
            uses_sdf=uses_sdf,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )

        cli_args = ["asset", "create", "font", name, "--parent-path", parent_path, "--font-name", font_name, "--size", str(size), "--aa-level", str(aa_level)]
        if bold:
            cli_args.append("--bold")
        if italic:
            cli_args.append("--italic")
        cli_args.extend(["--uses-sdf" if uses_sdf else "--no-uses-sdf"])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_shader(
        name: str,
        parent_path: str = "",
        shader_type: int = 1,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker shader asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="shader",
            name=name,
            parent_path=parent_path,
            shader_type=shader_type,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "shader", name, "--parent-path", parent_path, "--shader-type", str(shader_type)]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_animcurve(
        name: str,
        parent_path: str = "",
        curve_type: str = "linear",
        channel_name: str = "curve",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create an animation curve asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="animcurve",
            name=name,
            parent_path=parent_path,
            curve_type=curve_type,
            channel_name=channel_name,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "animcurve", name, "--parent-path", parent_path, "--curve-type", curve_type, "--channel-name", channel_name]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_sound(
        name: str,
        parent_path: str = "",
        volume: float = 1.0,
        pitch: float = 1.0,
        sound_type: int = 0,
        bitrate: int = 128,
        sample_rate: int = 44100,
        format: int = 0,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a sound asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sound",
            name=name,
            parent_path=parent_path,
            volume=volume,
            pitch=pitch,
            sound_type=sound_type,
            bitrate=bitrate,
            sample_rate=sample_rate,
            format=format,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "sound",
            name,
            "--parent-path",
            parent_path,
            "--volume",
            str(volume),
            "--pitch",
            str(pitch),
            "--sound-type",
            str(sound_type),
            "--bitrate",
            str(bitrate),
            "--sample-rate",
            str(sample_rate),
            "--format",
            str(format),
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_path(
        name: str,
        parent_path: str = "",
        closed: bool = False,
        precision: int = 4,
        path_type: str = "straight",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a path asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="path",
            name=name,
            parent_path=parent_path,
            closed=closed,
            precision=precision,
            path_type=path_type,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "path", name, "--parent-path", parent_path, "--precision", str(precision), "--path-type", path_type]
        if closed:
            cli_args.append("--closed")
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_tileset(
        name: str,
        parent_path: str = "",
        sprite_id: str = "",
        tile_width: int = 32,
        tile_height: int = 32,
        tile_xsep: int = 0,
        tile_ysep: int = 0,
        tile_xoff: int = 0,
        tile_yoff: int = 0,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a tileset asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="tileset",
            name=name,
            parent_path=parent_path,
            sprite_id=sprite_id or None,
            tile_width=tile_width,
            tile_height=tile_height,
            tile_xsep=tile_xsep,
            tile_ysep=tile_ysep,
            tile_xoff=tile_xoff,
            tile_yoff=tile_yoff,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "tileset",
            name,
            "--parent-path",
            parent_path,
            "--tile-width",
            str(tile_width),
            "--tile-height",
            str(tile_height),
            "--tile-xsep",
            str(tile_xsep),
            "--tile-ysep",
            str(tile_ysep),
            "--tile-xoff",
            str(tile_xoff),
            "--tile-yoff",
            str(tile_yoff),
        ]
        if sprite_id:
            cli_args.extend(["--sprite-id", sprite_id])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_timeline(
        name: str,
        parent_path: str = "",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a timeline asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="timeline",
            name=name,
            parent_path=parent_path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "timeline", name]
        if parent_path:
            cli_args.extend(["--parent-path", parent_path])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_sequence(
        name: str,
        parent_path: str = "",
        length: float = 60.0,
        playback_speed: float = 30.0,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a sequence asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sequence",
            name=name,
            parent_path=parent_path,
            length=length,
            playback_speed=playback_speed,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "sequence", name]
        if parent_path:
            cli_args.extend(["--parent-path", parent_path])
        cli_args.extend(["--length", str(length), "--playback-speed", str(playback_speed)])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_create_note(
        name: str,
        parent_path: str = "",
        content: str = "",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a note asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="note",
            name=name,
            parent_path=parent_path,
            content=content if content else None,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "note", name]
        if parent_path:
            cli_args.extend(["--parent-path", parent_path])
        if content:
            cli_args.extend(["--content", content])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_asset_delete(
        asset_type: str,
        name: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Delete an asset (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_delete

        args = argparse.Namespace(
            asset_type=asset_type,
            name=name,
            dry_run=dry_run,
            project_root=project_root,
        )
        cli_args = ["asset", "delete", asset_type, name]
        if dry_run:
            cli_args.append("--dry-run")

        return await _run_with_fallback(
            direct_handler=handle_asset_delete,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Maintenance tools
    # -----------------------------
    @mcp.tool()
    async def gm_maintenance_auto(
        fix: bool = False,
        verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Run your auto-maintenance pipeline."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_auto

        args = argparse.Namespace(
            fix=fix,
            verbose=verbose,
            project_root=project_root,
        )
        cli_args = ["maintenance", "auto"]
        if fix:
            cli_args.append("--fix")
        cli_args.append("--verbose" if verbose else "--no-verbose")

        return await _run_with_fallback(
            direct_handler=handle_maintenance_auto,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_lint(
        fix: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Run maintenance lint (optionally with fixes)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_lint

        args = argparse.Namespace(fix=fix, project_root=project_root)
        cli_args = ["maintenance", "lint"]
        if fix:
            cli_args.append("--fix")

        return await _run_with_fallback(
            direct_handler=handle_maintenance_lint,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_validate_json(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Validate JSON files in the project."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_validate_json

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["maintenance", "validate-json"]

        return await _run_with_fallback(
            direct_handler=handle_maintenance_validate_json,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_list_orphans(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Find orphaned and missing assets."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_list_orphans

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["maintenance", "list-orphans"]

        return await _run_with_fallback(
            direct_handler=handle_maintenance_list_orphans,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_prune_missing(
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove missing asset references from project file."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_prune_missing

        args = argparse.Namespace(dry_run=dry_run, project_root=project_root)
        cli_args = ["maintenance", "prune-missing"]
        if dry_run:
            cli_args.append("--dry-run")

        return await _run_with_fallback(
            direct_handler=handle_maintenance_prune_missing,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_validate_paths(
        strict_disk_check: bool = False,
        include_parent_folders: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Validate folder paths referenced in assets."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_validate_paths

        args = argparse.Namespace(
            strict_disk_check=strict_disk_check,
            include_parent_folders=include_parent_folders,
            project_root=project_root,
        )
        cli_args = ["maintenance", "validate-paths"]
        if strict_disk_check:
            cli_args.append("--strict-disk-check")
        if include_parent_folders:
            cli_args.append("--include-parent-folders")

        return await _run_with_fallback(
            direct_handler=handle_maintenance_validate_paths,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_dedupe_resources(
        auto: bool = True,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove duplicate resource entries from .yyp."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_dedupe_resources

        args = argparse.Namespace(auto=auto, dry_run=dry_run, project_root=project_root)
        cli_args = ["maintenance", "dedupe-resources"]
        if auto:
            cli_args.append("--auto")
        if dry_run:
            cli_args.append("--dry-run")

        return await _run_with_fallback(
            direct_handler=handle_maintenance_dedupe_resources,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_sync_events(
        fix: bool = False,
        object: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Synchronize object events (dry-run unless fix=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_sync_events

        args = argparse.Namespace(fix=fix, object=object if object else None, project_root=project_root)
        cli_args = ["maintenance", "sync-events"]
        if fix:
            cli_args.append("--fix")
        if object:
            cli_args.extend(["--object", object])

        return await _run_with_fallback(
            direct_handler=handle_maintenance_sync_events,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_clean_old_files(
        delete: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove .old.yy backup files (dry-run unless delete=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_clean_old_files

        args = argparse.Namespace(delete=delete, project_root=project_root)
        cli_args = ["maintenance", "clean-old-files"]
        if delete:
            cli_args.append("--delete")

        return await _run_with_fallback(
            direct_handler=handle_maintenance_clean_old_files,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_clean_orphans(
        delete: bool = False,
        skip_types: List[str] | None = None,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove orphaned asset files (dry-run unless delete=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_clean_orphans

        skip_types_value = skip_types if skip_types is not None else ["folder"]
        args = argparse.Namespace(delete=delete, skip_types=skip_types_value, project_root=project_root)
        cli_args = ["maintenance", "clean-orphans"]
        if delete:
            cli_args.append("--delete")
        if skip_types is not None:
            cli_args.append("--skip-types")
            cli_args.extend(skip_types_value)

        return await _run_with_fallback(
            direct_handler=handle_maintenance_clean_orphans,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_fix_issues(
        verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Run comprehensive maintenance with fixes enabled."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_fix_issues

        args = argparse.Namespace(verbose=verbose, project_root=project_root)
        cli_args = ["maintenance", "fix-issues"]
        if verbose:
            cli_args.append("--verbose")

        return await _run_with_fallback(
            direct_handler=handle_maintenance_fix_issues,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Runtime management tools
    # -----------------------------
    @mcp.tool()
    async def gm_runtime_list(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List all installed GameMaker runtimes.
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        installed = manager.list_installed()
        pinned = manager.get_pinned()
        active = manager.select()
        
        return {
            "runtimes": [r.to_dict() for r in installed],
            "pinned_version": pinned,
            "active_version": active.version if active else None,
            "count": len(installed)
        }

    @mcp.tool()
    async def gm_runtime_pin(
        version: str,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Pin a specific runtime version for this project.
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        success = manager.pin(version)
        
        return {
            "ok": success,
            "pinned_version": version if success else None,
            "error": None if success else f"Runtime version {version} is not installed or invalid."
        }

    @mcp.tool()
    async def gm_runtime_unpin(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Remove runtime pin, reverting to auto-select (newest).
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        success = manager.unpin()
        
        return {
            "ok": True,  # Always true even if no pin existed
            "message": "Runtime pin removed." if success else "No runtime pin existed."
        }

    @mcp.tool()
    async def gm_runtime_verify(
        version: str | None = None,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Verify a runtime is valid and ready to use.
        If version is None, verifies the currently selected runtime.
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        return manager.verify(version)

    # -----------------------------
    # Runner tools
    # -----------------------------
    @mcp.tool()
    async def gm_compile(
        platform: str = "Windows",
        runtime: str = "VM",
        runtime_version: str | None = None,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Compile the project using Igor."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_compile

        args = argparse.Namespace(
            platform=platform,
            runtime=runtime,
            runtime_version=runtime_version,
            project_root=project_root,
        )
        cli_args = ["run", "compile", "--platform", platform, "--runtime", runtime]
        if runtime_version:
            cli_args.extend(["--runtime-version", runtime_version])

        return await _run_with_fallback(
            direct_handler=handle_runner_compile,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_run(
        platform: str = "Windows",
        runtime: str = "VM",
        runtime_version: str | None = None,
        background: bool = False,
        output_location: str = "temp",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Run the project using Igor."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_run

        args = argparse.Namespace(
            platform=platform,
            runtime=runtime,
            runtime_version=runtime_version,
            background=background,
            output_location=output_location,
            project_root=project_root,
        )
        cli_args = [
            "run",
            "start",
            "--platform",
            platform,
            "--runtime",
            runtime,
            "--output-location",
            output_location,
        ]
        if runtime_version:
            cli_args.extend(["--runtime-version", runtime_version])
        if background:
            cli_args.append("--background")

        return await _run_with_fallback(
            direct_handler=handle_runner_run,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_run_stop(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Stop the running game (if any)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_stop

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["run", "stop"]

        return await _run_with_fallback(
            direct_handler=handle_runner_stop,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_run_status(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Check whether the game is running."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_status

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["run", "status"]

        return await _run_with_fallback(
            direct_handler=handle_runner_status,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Event tools
    # -----------------------------
    @mcp.tool()
    async def gm_event_add(
        object: str,
        event: str,
        template: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add an event to an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_add

        args = argparse.Namespace(object=object, event=event, template=template if template else None, project_root=project_root)
        cli_args = ["event", "add", object, event]
        if template:
            cli_args.extend(["--template", template])

        return await _run_with_fallback(
            direct_handler=handle_event_add,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_event_remove(
        object: str,
        event: str,
        keep_file: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove an event from an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_remove

        args = argparse.Namespace(object=object, event=event, keep_file=keep_file, project_root=project_root)
        cli_args = ["event", "remove", object, event]
        if keep_file:
            cli_args.append("--keep-file")

        return await _run_with_fallback(
            direct_handler=handle_event_remove,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_event_duplicate(
        object: str,
        source_event: str,
        target_num: int,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an event within an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_duplicate

        args = argparse.Namespace(object=object, source_event=source_event, target_num=target_num, project_root=project_root)
        cli_args = ["event", "duplicate", object, source_event, str(target_num)]

        return await _run_with_fallback(
            direct_handler=handle_event_duplicate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_event_list(
        object: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List all events for an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_list

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "list", object]

        return await _run_with_fallback(
            direct_handler=handle_event_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_event_validate(
        object: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Validate object events."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_validate

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "validate", object]

        return await _run_with_fallback(
            direct_handler=handle_event_validate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_event_fix(
        object: str,
        safe_mode: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Fix object event issues (safe_mode defaults true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_fix

        args = argparse.Namespace(object=object, safe_mode=safe_mode, project_root=project_root)
        cli_args = ["event", "fix", object]
        if not safe_mode:
            cli_args.append("--no-safe-mode")

        return await _run_with_fallback(
            direct_handler=handle_event_fix,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Workflow tools
    # -----------------------------
    @mcp.tool()
    async def gm_workflow_duplicate(
        asset_path: str,
        new_name: str,
        yes: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an asset (.yy path relative to project root)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_duplicate

        args = argparse.Namespace(asset_path=asset_path, new_name=new_name, yes=yes, project_root=project_root)
        cli_args = ["workflow", "duplicate", asset_path, new_name]
        if yes:
            cli_args.append("--yes")

        return await _run_with_fallback(
            direct_handler=handle_workflow_duplicate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_workflow_rename(
        asset_path: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Rename an asset (.yy path relative to project root)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_rename

        args = argparse.Namespace(asset_path=asset_path, new_name=new_name, project_root=project_root)
        cli_args = ["workflow", "rename", asset_path, new_name]

        return await _run_with_fallback(
            direct_handler=handle_workflow_rename,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_workflow_delete(
        asset_path: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Delete an asset by .yy path (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_delete

        args = argparse.Namespace(asset_path=asset_path, dry_run=dry_run, project_root=project_root)
        cli_args = ["workflow", "delete", asset_path]
        if dry_run:
            cli_args.append("--dry-run")

        return await _run_with_fallback(
            direct_handler=handle_workflow_delete,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_workflow_swap_sprite(
        asset_path: str,
        png: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Replace a sprite's PNG source."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_swap_sprite

        args = argparse.Namespace(asset_path=asset_path, png=png, project_root=project_root)
        cli_args = ["workflow", "swap-sprite", asset_path, png]

        return await _run_with_fallback(
            direct_handler=handle_workflow_swap_sprite,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Room tools
    # -----------------------------
    @mcp.tool()
    async def gm_room_ops_duplicate(
        source_room: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an existing room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_duplicate

        args = argparse.Namespace(source_room=source_room, new_name=new_name, project_root=project_root)
        cli_args = ["room", "ops", "duplicate", source_room, new_name]

        return await _run_with_fallback(
            direct_handler=handle_room_duplicate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_ops_rename(
        room_name: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Rename an existing room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_rename

        args = argparse.Namespace(room_name=room_name, new_name=new_name, project_root=project_root)
        cli_args = ["room", "ops", "rename", room_name, new_name]

        return await _run_with_fallback(
            direct_handler=handle_room_rename,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_ops_delete(
        room_name: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Delete a room (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_delete

        args = argparse.Namespace(room_name=room_name, dry_run=dry_run, project_root=project_root)
        cli_args = ["room", "ops", "delete", room_name]
        if dry_run:
            cli_args.append("--dry-run")

        return await _run_with_fallback(
            direct_handler=handle_room_delete,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_ops_list(
        verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List rooms."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_list

        args = argparse.Namespace(verbose=verbose, project_root=project_root)
        cli_args = ["room", "ops", "list"]
        if verbose:
            cli_args.append("--verbose")

        return await _run_with_fallback(
            direct_handler=handle_room_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_layer_add(
        room_name: str,
        layer_type: str,
        layer_name: str,
        depth: int = 0,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add a layer to a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_add

        args = argparse.Namespace(room_name=room_name, layer_type=layer_type, layer_name=layer_name, depth=depth, project_root=project_root)
        cli_args = ["room", "layer", "add", room_name, layer_type, layer_name]
        if depth:
            cli_args.extend(["--depth", str(depth)])

        return await _run_with_fallback(
            direct_handler=handle_room_layer_add,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_layer_remove(
        room_name: str,
        layer_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove a layer from a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_remove

        args = argparse.Namespace(room_name=room_name, layer_name=layer_name, project_root=project_root)
        cli_args = ["room", "layer", "remove", room_name, layer_name]

        return await _run_with_fallback(
            direct_handler=handle_room_layer_remove,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_layer_list(
        room_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List layers in a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_list

        args = argparse.Namespace(room_name=room_name, project_root=project_root)
        cli_args = ["room", "layer", "list", room_name]

        return await _run_with_fallback(
            direct_handler=handle_room_layer_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_instance_add(
        room_name: str,
        object_name: str,
        x: float,
        y: float,
        layer: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add an object instance to a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_add

        args = argparse.Namespace(room_name=room_name, object_name=object_name, x=x, y=y, layer=layer if layer else None, project_root=project_root)
        cli_args = ["room", "instance", "add", room_name, object_name, str(x), str(y)]
        if layer:
            cli_args.extend(["--layer", layer])

        return await _run_with_fallback(
            direct_handler=handle_room_instance_add,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_instance_remove(
        room_name: str,
        instance_id: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove an instance from a room by instance id."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_remove

        args = argparse.Namespace(room_name=room_name, instance_id=instance_id, project_root=project_root)
        cli_args = ["room", "instance", "remove", room_name, instance_id]

        return await _run_with_fallback(
            direct_handler=handle_room_instance_remove,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_room_instance_list(
        room_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List instances in a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_list

        args = argparse.Namespace(room_name=room_name, project_root=project_root)
        cli_args = ["room", "instance", "list", room_name]

        return await _run_with_fallback(
            direct_handler=handle_room_instance_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Introspection tools
    # -----------------------------
    @mcp.tool()
    async def gm_list_assets(
        asset_type: Optional[str] = None,
        name_contains: Optional[str] = None,
        folder_prefix: Optional[str] = None,
        include_included_files: bool = True,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List all assets in the project, optionally filtered by type, name, or folder.
        
        Args:
            asset_type: Optional type filter (e.g., 'script', 'object').
            name_contains: Filter assets by name (case-insensitive).
            folder_prefix: Filter assets by their path/folder (case-insensitive).
            include_included_files: Whether to include datafiles (default True).
            project_root: Path to project root.
        
        Supports all GameMaker asset types including extensions and datafiles.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import list_assets_by_type
        
        assets = list_assets_by_type(
            project_directory, 
            asset_type, 
            include_included_files,
            name_contains=name_contains,
            folder_prefix=folder_prefix
        )
        return {
            "project_directory": str(project_directory),
            "assets": assets,
            "count": sum(len(l) for l in assets.values()),
            "types_found": list(assets.keys()),
            "filters": {
                "asset_type": asset_type,
                "name_contains": name_contains,
                "folder_prefix": folder_prefix
            }
        }

    @mcp.tool()
    async def gm_read_asset(
        asset_identifier: str,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Read the .yy JSON data for a given asset by name or path.
        Returns the complete metadata for any asset type.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import read_asset_yy
        
        asset_data = read_asset_yy(project_directory, asset_identifier)
        if not asset_data:
            return {"ok": False, "error": f"Asset '{asset_identifier}' not found"}
            
        return {"ok": True, "asset_data": asset_data}

    @mcp.tool()
    async def gm_search_references(
        pattern: str,
        scope: str = "all",
        is_regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Search for a pattern in project files.
        
        Scopes: 'all', 'gml', 'yy', 'scripts', 'objects', 'extensions', 'datafiles'.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import search_references
        
        results = search_references(
            project_directory,
            pattern,
            scope=scope,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            max_results=max_results
        )
        return {
            "pattern": pattern,
            "scope": scope,
            "results": results,
            "count": len(results)
        }

    @mcp.tool()
    async def gm_get_asset_graph(
        deep: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Build a dependency graph of assets.
        
        Args:
            deep: If True, parse all GML code for references (slower but complete).
                  If False, only parse .yy structural references (fast).
        
        Returns nodes (assets) and edges (relationships like parent, sprite, code_reference).
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import build_asset_graph
        
        graph = build_asset_graph(project_directory, deep=deep)
        return graph

    @mcp.tool()
    async def gm_get_project_stats(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Get quick statistics about a project (asset counts by type).
        Faster than building a full index.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import get_project_stats
        
        return get_project_stats(project_directory)

    # -----------------------------
    # Code Intelligence Tools
    # -----------------------------
    @mcp.tool()
    async def gm_build_index(
        project_root: str = ".",
        force: bool = False,
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Build or rebuild the GML symbol index for code intelligence features.
        
        Args:
            force: If True, rebuild from scratch. If False, use cache if valid.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_build_index

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            force=force,
        )
        
        cli_args = ["symbol", "build"]
        if force:
            cli_args.append("--force")
        
        return await _run_with_fallback(
            direct_handler=handle_build_index,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-build-index",
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_find_definition(
        symbol_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Find definition(s) of a GML symbol (function, enum, macro, globalvar).
        
        Args:
            symbol_name: Name of the symbol to find.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_find_definition

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            symbol_name=symbol_name,
        )
        
        cli_args = ["symbol", "find-definition", symbol_name]
        
        return await _run_with_fallback(
            direct_handler=handle_find_definition,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-find-definition",
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_find_references(
        symbol_name: str,
        project_root: str = ".",
        max_results: int = 50,
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Find all references to a GML symbol.
        
        Args:
            symbol_name: Name of the symbol to find references for.
            max_results: Maximum number of references to return.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_find_references

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            symbol_name=symbol_name,
            max_results=max_results,
        )
        
        cli_args = ["symbol", "find-references", symbol_name, "--max", str(max_results)]
        
        return await _run_with_fallback(
            direct_handler=handle_find_references,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-find-references",
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_list_symbols(
        project_root: str = ".",
        kind: str | None = None,
        name_filter: str | None = None,
        file_filter: str | None = None,
        max_results: int = 100,
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List all GML symbols in the project, optionally filtered.
        
        Args:
            kind: Filter by symbol kind (function, enum, macro, globalvar, constructor).
            name_filter: Filter symbols by name (case-insensitive substring match).
            file_filter: Filter symbols by file path (case-insensitive substring match).
            max_results: Maximum number of symbols to return.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_list_symbols

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            kind=kind,
            name_filter=name_filter,
            file_filter=file_filter,
            max_results=max_results,
        )
        
        cli_args = ["symbol", "list"]
        if kind:
            cli_args.extend(["--kind", kind])
        if name_filter:
            cli_args.extend(["--name", name_filter])
        if file_filter:
            cli_args.extend(["--file", file_filter])
        cli_args.extend(["--max", str(max_results)])
        
        return await _run_with_fallback(
            direct_handler=handle_list_symbols,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-list-symbols",
            ctx=ctx,
        )

    # -----------------------------
    # MCP Resources
    # -----------------------------
    @mcp.resource("gms://project/index")
    async def gm_project_index() -> str:
        """Return the full project index as JSON."""
        project_directory = _resolve_project_directory(".")
        from gms_helpers.introspection import build_project_index
        
        index = build_project_index(project_directory)
        return json.dumps(index, indent=2)

    @mcp.resource("gms://project/asset-graph")
    async def gm_asset_graph_resource() -> str:
        """Return the asset dependency graph as JSON (structural refs only, use gm_get_asset_graph tool for deep mode)."""
        project_directory = _resolve_project_directory(".")
        from gms_helpers.introspection import build_asset_graph
        
        graph = build_asset_graph(project_directory, deep=False)
        return json.dumps(graph, indent=2)

    @mcp.tool()
    async def gm_check_updates() -> Dict[str, Any]:
        """Check for newer versions of gms-mcp on PyPI."""
        return check_for_updates()

    @mcp.resource("gms://system/updates")
    async def gm_updates_resource() -> str:
        """Check for updates and return the status as a human-readable message."""
        info = check_for_updates()
        return info["message"]

    # region agent log
    _dbg(
        "H2",
        "src/gms_mcp/gamemaker_mcp_server.py:build_server:exit",
        "build_server returning FastMCP instance",
        {"pid": os.getpid()},
    )
    # endregion
    return mcp


def main() -> int:
    # Suppress MCP SDK INFO logging to stderr (Cursor displays stderr as [error] which is confusing)
    import logging
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.server").setLevel(logging.WARNING)
    
    # region agent log
    _dbg(
        "H1",
        "src/gms_mcp/gamemaker_mcp_server.py:main:entry",
        "server main entry",
        {
            "pid": os.getpid(),
            "exe": sys.executable,
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "stdin_isatty": bool(getattr(sys.stdin, "isatty", lambda: False)()),
            "stdout_isatty": bool(getattr(sys.stdout, "isatty", lambda: False)()),
        },
    )
    # endregion
    try:
        server = build_server()
    except ModuleNotFoundError as e:
        sys.stderr.write(
            "MCP dependency is missing.\n"
            "Install it with:\n"
            f"  {sys.executable} -m pip install -U gms-mcp\n"
        )
        sys.stderr.write(f"\nDetails: {e}\n")
        return 1

    # region agent log
    # Instrument the MCP protocol boundary: log every incoming request type.
    # This tells us whether Cursor is hanging during initialize/list-tools/call-tool,
    # or whether the request never arrives.
    try:
        import mcp.server.lowlevel.server as _lls

        if not getattr(_lls.Server, "_gms_mcp_patched", False):
            _orig_handle_request = _lls.Server._handle_request

            async def _patched_handle_request(self, message, req, session, lifespan_context, raise_exceptions):
                t0 = time.monotonic()
                req_type = type(req).__name__
                req_id = getattr(message, "request_id", None)
                # Best-effort extraction of tool name for CallToolRequest (helps confirm if Cursor ever sends it)
                tool_name = None
                try:
                    tool_name = getattr(req, "params", None) and getattr(req.params, "name", None)
                except Exception:
                    tool_name = None
                _dbg(
                    "H4",
                    "src/gms_mcp/gamemaker_mcp_server.py:lowlevel:_handle_request:entry",
                    "received request",
                    {"pid": os.getpid(), "req_type": req_type, "request_id": req_id, "tool_name": tool_name},
                )
                try:
                    result = await _orig_handle_request(self, message, req, session, lifespan_context, raise_exceptions)
                    dt_ms = int((time.monotonic() - t0) * 1000)
                    _dbg(
                        "H4",
                        "src/gms_mcp/gamemaker_mcp_server.py:lowlevel:_handle_request:exit",
                        "request handled",
                        {"pid": os.getpid(), "req_type": req_type, "request_id": req_id, "elapsed_ms": dt_ms},
                    )
                    return result
                except Exception as e:
                    dt_ms = int((time.monotonic() - t0) * 1000)
                    _dbg(
                        "H4",
                        "src/gms_mcp/gamemaker_mcp_server.py:lowlevel:_handle_request:error",
                        "request handler raised",
                        {"pid": os.getpid(), "req_type": req_type, "request_id": req_id, "elapsed_ms": dt_ms, "error": str(e)},
                    )
                    raise

            _lls.Server._handle_request = _patched_handle_request  # type: ignore[assignment]
            _lls.Server._gms_mcp_patched = True  # type: ignore[attr-defined]
            _dbg(
                "H4",
                "src/gms_mcp/gamemaker_mcp_server.py:main:patch_ok",
                "patched lowlevel Server._handle_request",
                {"pid": os.getpid()},
            )
    except Exception as e:
        _dbg(
            "H4",
            "src/gms_mcp/gamemaker_mcp_server.py:main:patch_failed",
            "failed to patch lowlevel request handler",
            {"pid": os.getpid(), "error": str(e)},
        )
    # endregion

    # region agent log
    _dbg(
        "H1",
        "src/gms_mcp/gamemaker_mcp_server.py:main:before_run",
        "calling server.run()",
        {"pid": os.getpid()},
    )
    # endregion
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
