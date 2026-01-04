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
