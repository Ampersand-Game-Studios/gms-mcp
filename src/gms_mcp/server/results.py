from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional


_HOST_ONLY_RESULT_KEYS = {
    "candidates",
    "command",
    "cwd",
    "executable",
    "gms_candidates",
    "igor_path",
    "license_file",
    "licence_file",
    "log_file",
    "pid",
    "python_executable",
    "runtime_path",
    "traceback",
}
_PROJECT_ROOT_RESULT_KEYS = {"project_directory", "project_path", "project_root"}
_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def unwrap_call_tool_result(result: Any) -> Any:
    """Return the structured tool value from an MCP SDK v2 ``CallToolResult``.

    ``MCPServer.call_tool()`` exposes tool output through the result model's
    ``structured_content`` field. Typed dict outputs are exposed there directly;
    GMS MCP's generic ``Dict[str, Any]`` tools use a sole ``result`` envelope.
    """
    structured_content = getattr(result, "structured_content", None)
    if not isinstance(structured_content, Mapping):
        raise AssertionError(f"Unexpected MCP SDK v2 CallToolResult: {result!r}")
    if set(structured_content) == {"result"}:
        return structured_content["result"]
    return structured_content


def _jsonable_result(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable_result(value.to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable_result(asdict(value))
    if isinstance(value, Path):
        # MCP payloads are platform-neutral JSON. Keep path separators stable
        # for clients regardless of the server host operating system.
        return value.as_posix()
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


def expose_host_diagnostics_from_environment() -> bool:
    """Capture the explicit server-launch escape hatch for local-only diagnostics."""
    import os

    return os.environ.get("GMS_MCP_EXPOSE_HOST_DIAGNOSTICS", "").strip().lower() in _TRUTHY_VALUES


def _native_resolved_root(project_root: str | Path | None) -> Path | None:
    if project_root is None:
        return None
    try:
        root = Path(project_root)
        return root.resolve(strict=False) if root.is_absolute() else None
    except (OSError, ValueError):
        return None


def _project_relative_string(value: str, project_root: str | Path | None) -> str | None:
    if project_root is None:
        return None

    native_root = _native_resolved_root(project_root)
    if native_root is not None:
        try:
            candidate = Path(value)
            if candidate.is_absolute():
                relative = candidate.resolve(strict=False).relative_to(native_root)
                return relative.as_posix() or "."
        except (OSError, ValueError):
            pass

    root_text = str(project_root)
    pure_path_pairs = (
        (
            PurePosixPath(value.replace("\\", "/")),
            PurePosixPath(root_text.replace("\\", "/")),
        ),
        (
            PureWindowsPath(value.replace("/", "\\")),
            PureWindowsPath(root_text.replace("/", "\\")),
        ),
    )
    for candidate, root in pure_path_pairs:
        if not candidate.is_absolute() or not root.is_absolute():
            continue
        try:
            relative = candidate.relative_to(root)
            return relative.as_posix() or "."
        except ValueError:
            continue
    return None


def _redact_host_text(value: str, project_root: str | Path | None) -> str:
    if "Traceback (most recent call last)" in value:
        return "Internal tool error; host details were withheld."

    exact_relative = _project_relative_string(value, project_root)
    if exact_relative is not None:
        return exact_relative

    posix_value = PurePosixPath(value.replace("\\", "/"))
    windows_value = PureWindowsPath(value.replace("/", "\\"))
    if Path(value).is_absolute() or posix_value.is_absolute() or windows_value.is_absolute() or windows_value.root:
        return "<host-path>"

    redacted = value
    if project_root is not None:
        root_variants = {str(project_root), str(project_root).replace("\\", "/")}
        native_root = _native_resolved_root(project_root)
        if native_root is not None:
            root_variants.update({str(native_root), native_root.as_posix()})
        for root_value in sorted((item for item in root_variants if item), key=len, reverse=True):
            redacted, substitutions = re.subn(re.escape(root_value), ".", redacted, flags=re.IGNORECASE)
            if substitutions:
                redacted = redacted.replace("\\", "/")

    # Consume the rest of a line after a private/local filesystem root. This is
    # intentionally conservative: normal MCP output should not teach a remote
    # client anything about the host layout.
    host_path_patterns = (
        r"(?i)(?<![A-Z0-9])[A-Z]:[\\/][^\r\n\"'<>]*",
        r"(?i)(?<![A-Z0-9])\\\\[^\\/\r\n\"'<>]+\\[^\r\n\"'<>]*",
        r"(?i)(?<![A-Z0-9])\\(?:Applications|Library|System|Users|Volumes|etc|home|media|mnt|opt|private|root|srv|tmp|usr|var)\\[^\r\n\"'<>]*",
        r"(?<![:/.A-Za-z0-9])/(?![/\s])[^\r\n\"'<>]*",
    )
    for pattern in host_path_patterns:
        redacted = re.sub(pattern, "<host-path>", redacted)
    return redacted


def public_mcp_result(
    value: Any,
    *,
    project_root: str | Path | None,
    expose_host_diagnostics: bool = False,
) -> Any:
    """Return a JSON-safe MCP payload with host-only metadata removed by default."""
    jsonable = _jsonable_result(value)
    if expose_host_diagnostics:
        return jsonable

    redaction_root = project_root if project_root not in (None, "") else None

    def _sanitize(item: Any) -> Any:
        if isinstance(item, dict):
            sanitized: Dict[str, Any] = {}
            for raw_key, nested in item.items():
                key = str(raw_key)
                if key in _HOST_ONLY_RESULT_KEYS:
                    continue
                if key in _PROJECT_ROOT_RESULT_KEYS:
                    sanitized[key] = "."
                    continue
                public_key = _redact_host_text(key, redaction_root)
                sanitized[public_key] = _sanitize(nested)
            return sanitized
        if isinstance(item, list):
            return [_sanitize(nested) for nested in item]
        if isinstance(item, str):
            return _redact_host_text(item, redaction_root)
        return item

    return _sanitize(jsonable)


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
