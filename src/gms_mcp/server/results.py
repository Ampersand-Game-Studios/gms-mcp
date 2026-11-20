from __future__ import annotations

import base64
import contextvars
import datetime as dt
import json
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
    "save_directory",
    "traceback",
}
_PROJECT_ROOT_RESULT_KEYS = {"project_directory", "project_path", "project_root"}
_TRUTHY_VALUES = {"1", "true", "yes", "on"}

# Larger images are left on disk: a client that inlines every tool result would pay for them.
MAX_INLINE_IMAGE_BYTES = 1_500_000
_RESULT_IMAGES: contextvars.ContextVar[tuple[tuple[bytes, str], ...]] = contextvars.ContextVar(
    "gms_mcp_result_images", default=()
)


def attach_result_image(data: bytes, *, mime_type: str = "image/png") -> None:
    """Return an image beside the current tool call's structured result.

    Call it from the tool's own task; ``mcp_tool_result`` collects it when the call returns.
    """
    _RESULT_IMAGES.set((*_RESULT_IMAGES.get(), (data, mime_type)))


# How a command-backed tool ran is the server's business. A caller needs the outcome, the output
# and how long it took, so fields that only repeat "nothing unusual happened" are left out.
_RUN_PLUMBING_DEFAULTS: dict[str, Any] = {
    "stderr": "",
    "error": None,
    "direct_error": None,
    "timed_out": False,
    "result": None,
    "transaction": None,
    "validation": None,
    "exit_code": 0,
}
_RUN_PLUMBING_ALWAYS = ("direct_used", "execution_mode", "fallback_skipped", "fallback_skipped_reason")
_SLOW_CALL_SECONDS = 2.0


def _compact_handler_result(value: Any) -> Any:
    """Keep what a handler reported; drop its empty slots and the second copy of its outcome."""
    if not isinstance(value, dict):
        return value
    compact = {
        key: item
        for key, item in value.items()
        if not (key in ("warnings", "data") and not item) and not (key == "error" and item is None)
    }
    if compact.get("success") == compact.get("ok"):
        compact.pop("success", None)
    return compact


def _compact_transaction(value: Any) -> Any:
    """Reduce a committed transaction to what changed and anything that needs attention.

    A change that was rolled back, or left a recovery directory, keeps every field: that is when
    the bookkeeping matters. A clean commit repeated two dozen fields of it after every edit,
    including a sample of problems the project already had before the edit.
    """
    if not isinstance(value, dict) or value.get("recovery_path") or value.get("rollback_conflicts"):
        return value
    if value.get("committed") is True and not value.get("rolled_back"):
        compact: Dict[str, Any] = {"committed": True}
    elif value.get("rolled_back") is True and value.get("rollback_complete") is True:
        # Undone cleanly: the project is as it was. What matters is why, which the error carries.
        compact = {"committed": False, "rolled_back": True}
    else:
        return value
    changes = value.get("changes")
    if isinstance(changes, dict):
        listed = {key: changes[key] for key in ("created", "modified", "deleted") if changes.get(key)}
        if changes.get("truncated"):
            listed.update({key: changes[key] for key in changes if key.endswith("_count")}, truncated=True)
        if compact["committed"]:
            compact["changes"] = listed
            if not listed:
                compact["changed"] = False
        elif listed:
            compact["changes_undone"] = listed
    validation = value.get("validation")
    if isinstance(validation, dict):
        for key in ("errors", "warnings"):
            if validation.get(key):
                compact.setdefault("validation", {})[key] = validation[key]
        if validation.get("success") is False:
            compact.setdefault("validation", {})["success"] = False
        preexisting = validation.get("preexisting_error_count")
        if preexisting:
            compact["preexisting_issues"] = (
                f"{preexisting} validation issue(s) were already in the project before this change; "
                "gm_project_check lists them under asset_reference_issues."
            )
    for key in ("compile_verification", "gamemaker_ide"):
        if value.get(key) is not None:
            compact[key] = value[key]
    if value.get("warnings"):
        compact["warnings"] = value["warnings"]
    policy = value.get("verification_policy")
    if isinstance(policy, dict) and policy.get("action") != "skip":
        compact["verification_policy"] = policy
    extra = set(value) - _TRANSACTION_KNOWN_KEYS
    compact.update({key: value[key] for key in sorted(extra) if value[key] not in (None, [], {}, False)})
    return compact


_TRANSACTION_KNOWN_KEYS = {
    "enabled",
    "tool",
    "project_root",
    "committed",
    "recovery_path",
    "rolled_back",
    "rollback_complete",
    "rollback_conflicts",
    "ownership_checkpoint_captured",
    "owned_path_count",
    "changes",
    "validation",
    "compile_verification",
    "gamemaker_ide",
    "warnings",
    "verification_policy",
}


def _without_run_plumbing(value: Any) -> Any:
    if not isinstance(value, dict) or "execution_mode" not in value or "stdout" not in value:
        return value
    compact = {
        key: item
        for key, item in value.items()
        if key not in _RUN_PLUMBING_ALWAYS
        and not (key in _RUN_PLUMBING_DEFAULTS and item == _RUN_PLUMBING_DEFAULTS[key] and item is not True)
    }
    if isinstance(compact.get("elapsed_seconds"), float):
        compact["elapsed_seconds"] = round(compact["elapsed_seconds"], 2)
    if "result" in compact:
        compact["result"] = _compact_handler_result(compact["result"])
    if "transaction" in compact:
        compact["transaction"] = _compact_transaction(compact["transaction"])
    return compact


def mcp_tool_result(
    value: Any,
    *,
    project_root: str | Path | None,
    expose_host_diagnostics: bool = False,
    total_seconds: float | None = None,
) -> Any:
    """Return a native v2 tool result with structured, sanitized failure data.

    ``total_seconds`` is the whole call as the caller experienced it. It is added when the call
    was slow, because a tool's own timer covers only its work and not the locking, snapshots and
    validation around it, and a result claiming 0.2 s for a 20 s wait is worse than no timer.
    """
    from mcp.types import CallToolResult, ImageContent, TextContent

    images = _RESULT_IMAGES.get()
    _RESULT_IMAGES.set(())
    if isinstance(value, CallToolResult):
        return value
    public_value = public_mcp_result(
        value,
        project_root=project_root,
        expose_host_diagnostics=expose_host_diagnostics,
    )
    public_value = _without_run_plumbing(public_value)
    if isinstance(public_value, dict) and "success" in public_value and "ok" in public_value:
        # An operation result reported directly by a tool: same tidy-up as a nested one.
        public_value = _compact_handler_result(public_value)
    if isinstance(public_value, dict):
        for holder in (public_value, public_value.get("data")):
            if isinstance(holder, dict) and isinstance(holder.get("transaction"), dict):
                holder["transaction"] = _compact_transaction(holder["transaction"])
    if (
        total_seconds is not None
        and total_seconds >= _SLOW_CALL_SECONDS
        and isinstance(public_value, dict)
        # A report on another call's run carries that run's own times; how long the look took is not one of them.
        and "finished" not in public_value
    ):
        public_value = {**public_value, "total_seconds": round(total_seconds, 1)}
    # A report that another call's run failed is a successful look at it: `ok` there is the run's own.
    is_report = isinstance(public_value, Mapping) and public_value.get("finished") is True
    is_error = isinstance(public_value, Mapping) and public_value.get("ok") is False and not is_report
    if is_error and isinstance(public_value, Mapping) and "error_code" not in public_value:
        error_type = public_value.get("error_type")
        if "validation_errors" in public_value:
            error_code = "invalid_arguments"
        elif error_type == "ProjectAccessError":
            error_code = "project_access_denied"
        elif error_type == "TransactionValidationError":
            error_code = "transaction_validation_failed"
        elif error_type == "InternalToolError":
            error_code = "internal_error"
        else:
            error_code = "tool_failed"
        public_value = {**public_value, "error_code": error_code}
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                # No indentation: the model reads this text, and whitespace is a third of its cost.
                text=json.dumps(public_value, ensure_ascii=False),
            ),
            *(
                ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mime_type=mime_type)
                for data, mime_type in images
            ),
        ],
        # Every registered GMS tool returns Dict[str, Any], whose SDK output
        # schema uses a sole `result` envelope.
        structured_content={"result": public_value},
        is_error=is_error,
    )


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


_HOST_ROOT_NAMES = (
    "Applications|Library|Network|System|Users|Volumes|bin|cores|dev|etc|home|media|mnt|nix|opt|private|root|run"
    "|sbin|snap|srv|tmp|usr|var"
)
_PATH_SEGMENT = r"[A-Za-z0-9_~@+-][A-Za-z0-9_.~@+-]*"
# Redact only text that is unambiguously a host path. Known filesystem roots
# consume the rest of the line (host paths often contain spaces); any other
# absolute POSIX path must be a multi-segment path or a rooted file name, and
# must not follow an identifier, bracket or URL/relative-path character, so
# code such as ``(room_width)/2`` or ``a /b`` is never rewritten.
_HOST_PATH_PATTERNS = (
    re.compile(r"(?i)(?<![A-Z0-9])[A-Z]:[\\/][^\r\n\"'<>]*"),
    re.compile(r"(?i)(?<![A-Z0-9])\\\\[^\\/\r\n\"'<>]+\\[^\r\n\"'<>]*"),
    re.compile(rf"(?i)(?<![A-Z0-9])\\(?:{_HOST_ROOT_NAMES})\\[^\r\n\"'<>]*"),
    re.compile(rf"(?<![\w.:/~)\]}}-])/(?:{_HOST_ROOT_NAMES})(?![\w.~@+-])(?:/[^\r\n\"'<>]*)?"),
    re.compile(rf"(?<![\w.:/~)\]}}-])/{_PATH_SEGMENT}(?:(?:/{_PATH_SEGMENT})+/?|\.[A-Za-z0-9]{{1,10}})(?![\w/])"),
)


def _redact_host_text(value: str, project_root: str | Path | None) -> str:
    if "Traceback (most recent call last)" in value:
        return "Internal tool error; host details were withheld."

    exact_relative = _project_relative_string(value, project_root)
    if exact_relative is not None:
        return exact_relative

    if any(pattern.fullmatch(value) for pattern in _HOST_PATH_PATTERNS):
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

    for pattern in _HOST_PATH_PATTERNS:
        redacted = pattern.sub("<host-path>", redacted)
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
