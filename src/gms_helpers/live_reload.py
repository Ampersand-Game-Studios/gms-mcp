"""Start, stop and query an external live-reload tool (for example GMS Fire).

gms-mcp does not implement hot reload. A project that uses a live-reload tool tells
gms-mcp how to drive it in the user config ``~/.gms-mcp/config.json``:

    "live_reload": {
      "start":  ["gms-fire", "start", "--project", "{project}"],
      "stop":   ["gms-fire", "stop", "--project", "{project}"],
      "status": ["gms-fire", "status", "--json", "--project", "{project}"],
      "status_file": ".gms-fire/status.json"
    }

``{project}`` is replaced with the project directory. Commands are argument lists (never
shell strings) and run with the project directory as the working directory. ``start`` is
launched detached and must return control quickly or keep running as the tool's server;
``status`` should print one JSON object. When ``status_file`` is set it is read instead of
(or in addition to) running ``status``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .agent_locks import DirectoryLock
from .exceptions import ValidationError
from .mac_runtime import project_identity
from .project_config import global_setting, project_setting, project_live_reload_command_warnings
from .path_safety import project_relative_path
from .transactions import _assert_plain_infrastructure
from .utils import _read_text_preserving_newlines, atomic_write_text


class LiveReloadError(ValidationError):
    pass


def _command(project_root: Path, action: str) -> list[str]:
    configured = global_setting(f"live_reload.{action}")
    if not configured:
        raise LiveReloadError(
            f"No live-reload '{action}' command is configured for this project. Add "
            f'"live_reload": {{"{action}": ["<tool>", "<args>", ...]}} to ~/.gms-mcp/config.json '
            "(see documentation/CONFIGURATION.md, 'Live reload'). "
            + " ".join(project_live_reload_command_warnings(project_root))
        )
    if not isinstance(configured, list) or not all(isinstance(part, str) and part for part in configured):
        raise LiveReloadError(
            f"live_reload.{action} in ~/.gms-mcp/config.json must be a list of strings, for example "
            '["gms-fire", "start"]; shell command strings are not accepted.'
        )
    command = [part.replace("{project}", str(project_root)) for part in configured]
    if shutil.which(command[0]) is None and not Path(command[0]).is_file():
        raise LiveReloadError(
            f"The live-reload tool '{command[0]}' is not installed or not on PATH. Install it, or correct "
            f"live_reload.{action} in ~/.gms-mcp/config.json."
        )
    return command


def _read_status_file(project_root: Path) -> dict[str, Any] | None:
    configured = project_setting(project_root, "live_reload.status_file")
    if not configured:
        return None
    path = project_relative_path(configured, project_root=project_root, kind="live_reload.status_file")
    try:
        data = json.loads(_read_text_preserving_newlines(path))
        return data if isinstance(data, dict) else {"raw": data}
    except (OSError, ValueError):
        return None


def status(project_root: str | Path, timeout_seconds: float = 10.0) -> dict[str, Any]:
    root = Path(project_root).resolve()
    warnings = project_live_reload_command_warnings(root)
    result: dict[str, Any] = {"ok": True, "configured": True, "warnings": warnings}
    from_file = _read_status_file(root)
    if from_file is not None:
        result["status"] = from_file
    if global_setting("live_reload.status"):
        command = _command(root, "status")
        try:
            completed = subprocess.run(
                command, cwd=str(root), capture_output=True, timeout=timeout_seconds, check=False
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"The live-reload status command did not answer within {int(timeout_seconds)}s.",
                "warnings": warnings,
            }
        output = completed.stdout.decode("utf-8", "replace").strip()
        try:
            parsed = json.loads(output)
            result["status"] = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except ValueError:
            result["status"] = {**result.get("status", {}), "output": output[-2000:]}
        result["exit_code"] = completed.returncode
        result["ok"] = completed.returncode == 0
        if completed.returncode != 0:
            result["error"] = completed.stderr.decode("utf-8", "replace").strip()[-1000:] or "status command failed"
    elif from_file is None:
        if not global_setting("live_reload.start"):
            return {
                "ok": True,
                "configured": False,
                "message": "This project has no live-reload tool configured in ~/.gms-mcp/config.json.",
                "warnings": warnings,
            }
        result["status"] = {}
        result["message"] = "No status command or status file is configured; start/stop are available."
    return result


def _state_path(project_root: Path) -> Path:
    """Host-side record of the start process this server spawned (outside the project tree)."""
    return Path.home() / ".gms-mcp" / "live_reload" / f"{project_identity(project_root)}.json"


def _running_start_process(project_root: Path) -> int | None:
    """PID of a start process we launched that is still the same process, else None."""
    from .run_session import process_identity

    try:
        state = json.loads(_state_path(project_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = state.get("pid") if isinstance(state, dict) else None
    if not isinstance(pid, int) or not state.get("started"):
        return None
    return pid if process_identity(pid) == (state.get("started"), state.get("exe")) else None


def start(project_root: str | Path) -> dict[str, Any]:
    """Start the tool once; while a start process we launched is still running, report it instead."""
    root = Path(project_root).resolve()
    command = _command(root, "start")
    guard = DirectoryLock(f"live_reload_{project_identity(root)}.lock", purpose=f"live-reload start {root}")
    guard.acquire(timeout_seconds=30)
    try:
        running = _running_start_process(root)
        if running is not None:
            return {
                "ok": True,
                "started": False,
                "already_running": True,
                "pid": running,
                "log": ".gms_mcp/live_reload.log",
                "warnings": project_live_reload_command_warnings(root),
                "message": "The live-reload tool is already running for this project; stop it before starting again.",
            }
        return _start_process(root, command)
    finally:
        guard.release()


def _start_process(root: Path, command: list[str]) -> dict[str, Any]:
    log_path = root / ".gms_mcp" / "live_reload.log"
    project_relative_path(".gms_mcp/live_reload.log", project_root=root, kind="live-reload log")
    _assert_plain_infrastructure(root, log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "ab") as log:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    try:
        exit_code = process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        exit_code = None
    if exit_code is None:
        from .run_session import process_identity

        identity = process_identity(process.pid)
        if identity is not None:
            state_path = _state_path(root)
            state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_text(
                state_path, json.dumps({"pid": process.pid, "started": identity[0], "exe": identity[1]}) + "\n"
            )
    if exit_code not in (None, 0):
        _assert_plain_infrastructure(root, log_path)
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        return {
            "ok": False,
            "error": f"The live-reload start command exited with code {exit_code}.",
            "log_tail": tail,
            "log": ".gms_mcp/live_reload.log",
            "warnings": project_live_reload_command_warnings(root),
        }
    return {
        "ok": True,
        "started": True,
        "pid": process.pid if exit_code is None else None,
        "log": ".gms_mcp/live_reload.log",
        "warnings": project_live_reload_command_warnings(root),
        "message": "Started. Call gm_live_reload_status to confirm it is serving.",
    }


def stop(project_root: str | Path, timeout_seconds: float = 30.0) -> dict[str, Any]:
    root = Path(project_root).resolve()
    command = _command(root, "stop")
    try:
        completed = subprocess.run(command, cwd=str(root), capture_output=True, timeout=timeout_seconds, check=False)
        if completed.returncode == 0:
            _state_path(root).unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"The live-reload stop command did not finish within {int(timeout_seconds)}s.",
            "warnings": project_live_reload_command_warnings(root),
        }
    return {
        "ok": completed.returncode == 0,
        "stopped": completed.returncode == 0,
        "warnings": project_live_reload_command_warnings(root),
        "exit_code": completed.returncode,
        "output": (completed.stdout + completed.stderr).decode("utf-8", "replace").strip()[-1500:],
    }
