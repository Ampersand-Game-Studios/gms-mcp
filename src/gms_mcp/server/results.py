from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, List, Optional


def _jsonable_result(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (dict, list, str, int, float, bool)):
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
