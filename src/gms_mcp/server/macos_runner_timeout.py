"""Parent-side cleanup for macOS runners detached from failed workers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


MACOS_OWNERSHIP_MANIFEST_ENV = "GMS_MCP_MACOS_OWNERSHIP_MANIFEST"


def cleanup_macos_ownership_manifest(manifest_path: Path | None) -> None:
    """Clean only helpers newer than the worker's immediate pre-launch baseline."""
    if manifest_path is None or not manifest_path.exists():
        return
    try:
        payload: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        project_root = Path(str(payload["project_root"])).resolve()
        game_path = Path(str(payload["game_path"]))
        debug_log_path = Path(str(payload["debug_log_path"]))
        baseline = payload.get("baseline")
        if not isinstance(baseline, dict):
            return

        from gms_helpers.runner import GameMakerRunner
        from gms_helpers.runner_support.macos import MacOSProcess

        runner = GameMakerRunner(project_root)
        owned_temp_root = payload.get("owned_temp_root")
        if isinstance(owned_temp_root, str) and owned_temp_root:
            setattr(runner, "_macos_timeout_temp_root_override", Path(owned_temp_root))
        raw_launch_token = payload.get("launch_token")
        launch_token = raw_launch_token if isinstance(raw_launch_token, str) and raw_launch_token else None
        baseline_processes = {
            int(pid): MacOSProcess(
                pid=int(identity.get("pid", pid)),
                ppid=int(identity.get("ppid", 0)),
                command=str(identity.get("command") or ""),
                started=str(identity.get("started") or ""),
            )
            for pid, identity in baseline.items()
            if isinstance(identity, dict)
        }
        baseline_runner_pids = {
            pid: process for pid, process in baseline_processes.items() if "/Mac_Runner" in process.command
        }
        baseline_tail_pids = {
            pid: process for pid, process in baseline_processes.items() if "tail -F" in process.command
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return

    # LaunchServices can finish a queued app launch after the worker/Igor has
    # exited. Keep the exact-token scan bounded but long enough to cover that
    # detached handoff without widening ownership to time/path heuristics.
    deadline = time.monotonic() + 3.0
    while True:
        processes = runner._snapshot_macos_processes()
        active_igor_pids = set(runner._find_active_igor_processes())
        owned_igor = next(
            (
                process
                for process in processes.values()
                if process.pid in active_igor_pids and runner._macos_process_has_launch_token(process.pid, launch_token)
            ),
            None,
        )
        runner._cleanup_macos_validation_helpers(
            game_path,
            debug_log_path,
            baseline_runner_pids,
            baseline_tail_pids,
            owned_igor.pid if owned_igor is not None else None,
            owned_igor.command if owned_igor is not None else None,
            owned_igor.started if owned_igor is not None else None,
            launch_token,
        )
        if time.monotonic() >= deadline:
            return
        time.sleep(0.2)
