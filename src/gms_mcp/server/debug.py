from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional


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

        # No GameMaker project found - skip debug logging
        return None
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

