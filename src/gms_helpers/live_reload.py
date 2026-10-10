"""Start, stop and query an external live-reload tool (for example GMS Fire).

gms-mcp does not implement hot reload. A project that uses a live-reload tool tells
gms-mcp how to drive it in ``.gms-mcp.json``:

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
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .exceptions import ValidationError
from .project_config import project_setting


class LiveReloadError(ValidationError):
    pass


def _command(project_root: Path, action: str) -> list[str]:
    configured = project_setting(project_root, f"live_reload.{action}")
    if not configured:
        raise LiveReloadError(
            f"No live-reload '{action}' command is configured for this project. Add "
            f'"live_reload": {{"{action}": ["<tool>", "<args>", ...]}} to .gms-mcp.json '
            "(see documentation/CONFIGURATION.md, 'Live reload')."
        )
    if not isinstance(configured, list) or not all(isinstance(part, str) and part for part in configured):
        raise LiveReloadError(
            f"live_reload.{action} in .gms-mcp.json must be a list of strings, for example "
            '["gms-fire", "start"]; shell command strings are not accepted.'
        )
    command = [part.replace("{project}", str(project_root)) for part in configured]
    if shutil.which(command[0]) is None and not Path(command[0]).is_file():
        raise LiveReloadError(
            f"The live-reload tool '{command[0]}' is not installed or not on PATH. Install it, or correct "
            f"live_reload.{action} in .gms-mcp.json."
        )
    return command


def _read_status_file(project_root: Path) -> dict[str, Any] | None:
    configured = project_setting(project_root, "live_reload.status_file")
    if not configured:
        return None
    path = Path(str(configured))
    if not path.is_absolute():
        path = project_root / path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"raw": data}
    except (OSError, ValueError):
        return None


def status(project_root: str | Path, timeout_seconds: float = 10.0) -> dict[str, Any]:
    root = Path(project_root).resolve()
    result: dict[str, Any] = {"ok": True, "configured": True}
    from_file = _read_status_file(root)
    if from_file is not None:
        result["status"] = from_file
    if project_setting(root, "live_reload.status"):
        command = _command(root, "status")
        try:
            completed = subprocess.run(
                command, cwd=str(root), capture_output=True, timeout=timeout_seconds, check=False
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"The live-reload status command did not answer within {int(timeout_seconds)}s."}
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
        if not project_setting(root, "live_reload.start"):
            return {
                "ok": True,
                "configured": False,
                "message": "This project has no live-reload tool configured in .gms-mcp.json.",
            }
        result["status"] = {}
        result["message"] = "No status command or status file is configured; start/stop are available."
    return result


def start(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    command = _command(root, "start")
    log_path = root / ".gms_mcp" / "live_reload.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command, cwd=str(root), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True
        )
    try:
        exit_code = process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        exit_code = None
    if exit_code not in (None, 0):
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        return {
            "ok": False,
            "error": f"The live-reload start command exited with code {exit_code}.",
            "log_tail": tail,
            "log": ".gms_mcp/live_reload.log",
        }
    return {
        "ok": True,
        "started": True,
        "pid": process.pid if exit_code is None else None,
        "log": ".gms_mcp/live_reload.log",
        "message": "Started. Call gm_live_reload_status to confirm it is serving.",
    }


def stop(project_root: str | Path, timeout_seconds: float = 30.0) -> dict[str, Any]:
    root = Path(project_root).resolve()
    command = _command(root, "stop")
    try:
        completed = subprocess.run(command, cwd=str(root), capture_output=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"The live-reload stop command did not finish within {int(timeout_seconds)}s."}
    return {
        "ok": completed.returncode == 0,
        "stopped": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output": (completed.stdout + completed.stderr).decode("utf-8", "replace").strip()[-1500:],
    }
