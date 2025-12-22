#!/usr/bin/env python3
"""
Bootstrap runner for the GameMaker MCP server.

This script is intended to be referenced from an MCP client's config.

In the packaged (pip) install flow, dependencies should already be installed.
So this script intentionally does not attempt to run pip automatically.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _dbg(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append a single NDJSON debug line to .cursor/debug.log (best-effort)."""
    try:
        log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug.log"
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


def main() -> int:
    # region agent log
    _dbg(
        "H1",
        "src/gms_mcp/bootstrap_server.py:main:entry",
        "bootstrap main entry",
        {
            "pid": os.getpid(),
            "exe": sys.executable,
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "stdin_isatty": bool(getattr(sys.stdin, "isatty", lambda: False)()),
            "stdout_isatty": bool(getattr(sys.stdout, "isatty", lambda: False)()),
            "env_GM_PROJECT_ROOT": os.environ.get("GM_PROJECT_ROOT"),
            "env_PYTHONPATH": os.environ.get("PYTHONPATH"),
            "py_path_head": sys.path[:5],
        },
    )
    # endregion
    try:
        from .gamemaker_mcp_server import main as server_main
        # region agent log
        _dbg(
            "H1",
            "src/gms_mcp/bootstrap_server.py:main:imported",
            "imported gamemaker_mcp_server.main",
            {"module": getattr(server_main, "__module__", None)},
        )
        # endregion
        return int(server_main() or 0)
    except ModuleNotFoundError as e:
        # region agent log
        _dbg(
            "H1",
            "src/gms_mcp/bootstrap_server.py:main:module_not_found",
            "ModuleNotFoundError starting server",
            {"error": str(e), "pid": os.getpid()},
        )
        # endregion
        sys.stderr.write(
            "Missing dependency while starting the GameMaker MCP server.\n"
            "If you installed via pipx/pip, reinstall/upgrade:\n"
            "  pipx install gms-mcp --force\n"
            "  # or\n"
            f"  {sys.executable} -m pip install -U gms-mcp\n"
            f"\nDetails: {e}\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
