"""Typed result objects for GMS helper operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Optional, TypeVar


@dataclass
class ErrorInfo:
    """Structured error information for helper operations."""

    code: str
    message: str
    type: str = "operation_error"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OperationResult:
    """Base result for all operations."""

    success: bool
    message: str
    warnings: List[str] = field(default_factory=list)
    error: ErrorInfo | Dict[str, Any] | None = None
    data: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Keep legacy truthiness behavior for CLI tests and callers."""
        return self.success

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to a dictionary for JSON-RPC/MCP compatibility."""
        payload = asdict(self)
        payload["ok"] = self.success
        if self.error is None and not self.success:
            payload["error"] = ErrorInfo(code="operation_failed", message=self.message).to_dict()
        elif self.error is not None:
            payload["error"] = _jsonable(self.error)
        return payload

    @classmethod
    def ok(cls, message: str, *, warnings: List[str] | None = None, data: Dict[str, Any] | None = None):
        return cls(success=True, message=message, warnings=warnings or [], data=data or {})

    @classmethod
    def fail(
        cls,
        message: str,
        *,
        code: str = "operation_failed",
        error_type: str = "operation_error",
        details: Dict[str, Any] | None = None,
        warnings: List[str] | None = None,
        data: Dict[str, Any] | None = None,
    ):
        return cls(
            success=False,
            message=message,
            warnings=warnings or [],
            error=ErrorInfo(code=code, message=message, type=error_type, details=details or {}),
            data=data or {},
        )


@dataclass
class AssetResult(OperationResult):
    """Result from asset creation/modification."""

    asset_name: Optional[str] = None
    asset_type: Optional[str] = None
    asset_path: Optional[str] = None


@dataclass
class MaintenanceResult(OperationResult):
    """Result from maintenance operations."""

    issues_found: int = 0
    issues_fixed: int = 0
    details: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunnerResult(OperationResult):
    """Result from compile/run operations."""

    pid: Optional[int] = None
    exit_code: Optional[int] = None
    output_path: Optional[str] = None


@dataclass
class IntrospectionResult(OperationResult):
    """Result from project introspection."""

    data: Dict[str, Any] = field(default_factory=dict)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


_ResultT = TypeVar("_ResultT", bound=OperationResult)


def result_dict_is_ok(result: Dict[str, Any]) -> bool:
    """Interpret legacy dict status fields consistently."""
    if result.get("ok") is False or result.get("success") is False:
        return False
    if "error" in result and "ok" not in result and "success" not in result:
        return False
    return True


def _coerce_warnings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []


def _message_from_dict(result: Dict[str, Any], *, operation: str, ok: bool) -> str:
    message = result.get("message")
    if message:
        return str(message)
    error = result.get("error")
    if isinstance(error, dict):
        error_message = error.get("message")
        if error_message:
            return str(error_message)
    elif error:
        return str(error)
    return f"{operation} completed." if ok else f"{operation} failed."


def _data_from_dict(result: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data")
    if isinstance(data, dict):
        return dict(data)
    return dict(result)


def normalize_result(
    result: Any,
    *,
    operation: str,
    data_key: str | None = None,
    result_cls: type[_ResultT] = OperationResult,
    success_message: str | None = None,
    failure_message: str | None = None,
    code: str = "operation_failed",
    error_type: str = "operation_error",
    data: Dict[str, Any] | None = None,
) -> _ResultT:
    """Normalize helper returns into one structured operation result contract."""
    if isinstance(result, OperationResult):
        return result  # type: ignore[return-value]

    if isinstance(result, bool):
        if result:
            return result_cls.ok(success_message or f"{operation} completed.", data=data)  # type: ignore[return-value]
        return result_cls.fail(
            failure_message or f"{operation} failed.",
            code="legacy_helper_failed",
            error_type="legacy_boolean_result",
            details={"operation": operation, **(data or {})},
            data=data,
        )  # type: ignore[return-value]

    if isinstance(result, dict):
        ok = result_dict_is_ok(result)
        message = success_message if ok and success_message else failure_message if not ok and failure_message else None
        message = message or _message_from_dict(result, operation=operation, ok=ok)
        warnings = _coerce_warnings(result.get("warnings"))
        result_data = _data_from_dict(result)
        if data:
            result_data = {**result_data, **data}
        if ok:
            return result_cls.ok(message, warnings=warnings, data=result_data)  # type: ignore[return-value]

        error = result.get("error")
        error_code = code
        error_kind = error_type
        details: Dict[str, Any] = dict(result)
        if isinstance(error, dict):
            error_code = str(error.get("code") or code)
            error_kind = str(error.get("type") or error_type)
            error_details = error.get("details")
            if isinstance(error_details, dict):
                details = {**details, **error_details}
        elif error:
            error_code = "legacy_dict_error"
            error_kind = "legacy_dict_result"

        return result_cls.fail(
            message,
            code=error_code,
            error_type=error_kind,
            details=details,
            warnings=warnings,
            data=result_data,
        )  # type: ignore[return-value]

    if isinstance(result, list):
        payload_key = data_key or "items"
        payload: Dict[str, Any] = {payload_key: result, "count": len(result)}
        if data:
            payload.update(data)
        return result_cls.ok(success_message or f"{operation} completed.", data=payload)  # type: ignore[return-value]

    payload = dict(data or {})
    if result is not None:
        payload[data_key or "value"] = result
    if result is None:
        return result_cls.fail(
            failure_message or f"{operation} returned no result.",
            code=code,
            error_type=error_type,
            details={"operation": operation},
            data=payload,
        )  # type: ignore[return-value]
    return result_cls.ok(success_message or f"{operation} completed.", data=payload)  # type: ignore[return-value]


def structured_error(
    code: str,
    message: str,
    *,
    error_type: str = "operation_error",
    details: Dict[str, Any] | None = None,
) -> ErrorInfo:
    return ErrorInfo(code=code, message=message, type=error_type, details=details or {})


def result_from_exception(
    exc: Exception, *, code: str = "exception", details: Dict[str, Any] | None = None
) -> ErrorInfo:
    return structured_error(
        code,
        str(exc),
        error_type=type(exc).__name__,
        details=details,
    )


def legacy_bool_result(
    success: bool,
    *,
    operation: str,
    message: str | None = None,
    details: Dict[str, Any] | None = None,
) -> OperationResult:
    if success:
        return OperationResult.ok(message or f"{operation} completed.", data=details)
    return OperationResult.fail(
        message or f"{operation} failed.",
        code="legacy_helper_failed",
        error_type="legacy_boolean_result",
        details=details,
    )
