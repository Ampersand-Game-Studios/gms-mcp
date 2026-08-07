from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import List, Optional

from .log_paths import diagnostic_log_dir, secure_private_file


_MAX_LOG_BYTES = 2 * 1024 * 1024
_MAX_BACKUPS = 3
_MAX_STRING_CHARS = 4000
_SENSITIVE_KEY_MARKERS = ("authorization", "cookie", "password", "secret", "token", "api_key", "apikey")
_COMMAND_KEYS = {"argv", "cmd", "command", "cmd_head"}
_WRITE_LOCK = threading.Lock()


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
                    return diagnostic_log_dir(p) / "debug.log"
            except Exception:
                continue

        # No GameMaker project found - skip debug logging
        return None
    except Exception:
        return None


def _dbg(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append one bounded, redacted NDJSON line to the private rotating debug log."""
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
            "data": _sanitize_value(data),
            "timestamp": int(time.time() * 1000),
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with _WRITE_LOCK:
            _rotate_if_needed(log_path, len(line.encode("utf-8")))
            secure_private_file(log_path)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        return


def _sanitize_value(value, *, key: str = ""):
    if any(marker in key.lower() for marker in _SENSITIVE_KEY_MARKERS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _sanitize_value(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)) and key.lower() in _COMMAND_KEYS:
        return _sanitize_command(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
        return f"{value[:_MAX_STRING_CHARS]}...[truncated {len(value) - _MAX_STRING_CHARS} chars]"
    return value


def _sanitize_command(values) -> list:
    redacted = []
    redact_next = False
    for value in values:
        token = str(value)
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        option, separator, _value = token.partition("=")
        normalized = option.lstrip("-/").lower().replace("_", "-")
        is_secret = any(marker.replace("_", "-") in normalized for marker in _SENSITIVE_KEY_MARKERS)
        if is_secret and separator:
            redacted.append(f"{option}=[REDACTED]")
        else:
            redacted.append(token)
            redact_next = is_secret
    return redacted


def _rotate_if_needed(log_path: Path, incoming_bytes: int) -> None:
    current_bytes = log_path.stat().st_size if log_path.exists() else 0
    if current_bytes + incoming_bytes <= _MAX_LOG_BYTES:
        return
    oldest = log_path.with_name(f"{log_path.name}.{_MAX_BACKUPS}")
    oldest.unlink(missing_ok=True)
    for index in range(_MAX_BACKUPS - 1, 0, -1):
        source = log_path.with_name(f"{log_path.name}.{index}")
        if source.exists():
            source.replace(log_path.with_name(f"{log_path.name}.{index + 1}"))
    if log_path.exists():
        log_path.replace(log_path.with_name(f"{log_path.name}.1"))
