"""Typed result objects for GMS helper operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Optional


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


def structured_error(
    code: str,
    message: str,
    *,
    error_type: str = "operation_error",
    details: Dict[str, Any] | None = None,
) -> ErrorInfo:
    return ErrorInfo(code=code, message=message, type=error_type, details=details or {})


def result_from_exception(exc: Exception, *, code: str = "exception", details: Dict[str, Any] | None = None) -> ErrorInfo:
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
