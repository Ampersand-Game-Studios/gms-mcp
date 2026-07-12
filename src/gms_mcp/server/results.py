from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


def _jsonable_result(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable_result(value.to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable_result(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _jsonable_result(value.value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable_result(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable_result(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


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
    result: Any = None
    transaction: Optional[Dict[str, Any]] = None
    validation: Optional[Dict[str, Any]] = None

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
            "result": _jsonable_result(self.result),
            "transaction": self.transaction,
            "validation": self.validation,
        }
