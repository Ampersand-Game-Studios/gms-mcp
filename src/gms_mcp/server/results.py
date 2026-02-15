from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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

