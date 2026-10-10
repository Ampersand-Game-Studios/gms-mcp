#!/usr/bin/env python3
"""
GameMaker MCP Server

Exposes common GameMaker project actions as MCP tools by reusing the existing
Python helper modules in `gms_helpers`.

Public entrypoints:
- build_server(): constructs and returns the MCPServer instance
- main(): stdio server entrypoint (used by `gms-mcp` and bootstrap runners)

Implementation details live under `gms_mcp.server.*`.
"""

from __future__ import annotations

import argparse
import functools
import inspect
import ipaddress
import os
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .server.http_security import local_bearer_auth, validate_local_bearer_token
from .server.mcp_v2 import MCP_CACHE_HINTS, MCPV2Runtime, MutationSerializationMiddleware
from .server.project import ProjectAccessError, ProjectAccessPolicy
from .server.register_all import register_all
from .server.results import expose_host_diagnostics_from_environment, mcp_tool_result
from .server.validation import invalid_arguments_result, validate_mcp_tool_arguments
from .server.verification_policy import (
    MutationVerificationDecision,
    clear_pending_compile_verification,
    decide_mutation_verification,
    mark_compile_verification_pending,
)
from .telemetry import (
    classify_error_family,
    get_tool_execution_context,
    maybe_start_background_flush,
    queue_event,
    reset_tool_execution_context,
    resolve_state,
)


from gms_helpers.operation_policy import is_project_mutation, is_real_destructive_operation, operation_scope

_HTTP_AUTH_ENV_NAME = "GMS_MCP_HTTP_BEARER_TOKEN"
_HTTP_MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024


def _tool_family_for_function(func) -> str:
    module_name = getattr(func, "__module__", "")
    base = module_name.rsplit(".", 1)[-1]
    mapping = {
        "asset_creation": "asset",
        "bridge": "bridge",
        "code_intel": "code_intel",
        "docs": "docs",
        "events": "event",
        "introspection": "introspection",
        "maintenance": "maintenance",
        "project_health": "health",
        "rooms": "room",
        "runner": "runner",
        "runtime": "runtime",
        "texture_groups": "texture_group",
        "workflow": "workflow",
    }
    return mapping.get(base, base or "mcp")


def _record_mcp_event(
    *,
    event_type: str,
    action: str,
    tool_name: str,
    tool_family: str,
    result: str,
    duration_ms: int,
    error_family: str | None = None,
    execution_mode: str | None = None,
) -> None:
    if os.environ.get("GMS_MCP_READ_ONLY", "").strip() == "1" or operation_scope(tool_name) in {"read", "cache"}:
        return
    state = resolve_state()
    if not queue_event(
        state=state,
        surface="mcp",
        event_type=event_type,
        action=action,
        tool_name=tool_name,
        tool_family=tool_family,
        result=result,
        error_family=error_family,
        duration_ms=duration_ms,
        execution_mode=execution_mode,
    ):
        return
    maybe_start_background_flush()


def _result_from_value(value) -> str:
    from gms_helpers.operation_policy import operation_succeeded

    return "ok" if operation_succeeded(value) else "error"


def _is_committed_mutation_result(value: Any) -> bool:
    structured_content = (
        value.get("structuredContent") if isinstance(value, dict) else getattr(value, "structured_content", None)
    )
    if isinstance(structured_content, dict):
        value = structured_content.get("result", structured_content)
    if not isinstance(value, dict) or _result_from_value(value) == "error":
        return False
    transaction = value.get("transaction")
    return isinstance(transaction, dict) and transaction.get("committed") is True


def _bind_tool_call(
    func,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    project_access_policy: ProjectAccessPolicy,
) -> tuple[dict[str, Any], tuple[Any, ...], dict[str, Any]]:
    signature = inspect.signature(func)
    bound = signature.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    if "project_root" in bound.arguments:
        bound.arguments["project_root"] = str(
            project_access_policy.authorize(str(bound.arguments.get("project_root") or "."))
        )
    return dict(bound.arguments), bound.args, bound.kwargs


def _tool_should_use_transaction(tool_name: str, arguments: dict[str, Any]) -> bool:
    from gms_helpers.operation_policy import is_project_mutation

    return is_project_mutation(tool_name, arguments)


def _resolve_transaction_project_root(arguments: dict[str, Any]) -> Path:
    from gms_mcp.server.project import _resolve_project_directory_no_deps

    return _resolve_project_directory_no_deps(str(arguments.get("project_root") or "."))


def _annotate_transaction_result(result: Any, transaction: dict[str, Any]) -> Any:
    from gms_helpers.results import OperationResult

    if isinstance(result, OperationResult):
        result = result.to_dict()
    if isinstance(result, dict):
        result["ok"] = _result_from_value(result) == "ok"
        result["transaction"] = transaction
        return result
    return {"ok": _result_from_value(result) == "ok", "result": result, "transaction": transaction}


def _transaction_error_result(tool_name: str, exc: Exception) -> dict[str, Any]:
    details = getattr(exc, "details", {}) or {}
    return {
        "ok": False,
        "tool": tool_name,
        "error": str(exc),
        "error_type": type(exc).__name__,
        **details,
    }


def _apply_verification_decision(
    *,
    project_root: Path,
    tool_name: str,
    decision: MutationVerificationDecision,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    transaction["verification_policy"] = decision.to_dict()
    if decision.action == "defer":
        transaction["pending_compile_verification"] = mark_compile_verification_pending(
            project_root,
            tool_name=tool_name,
            decision=decision,
            transaction=transaction,
        )
    elif decision.action == "compile":
        compile_verification = transaction.get("compile_verification")
        if isinstance(compile_verification, dict) and compile_verification.get("ok"):
            cleared = clear_pending_compile_verification(project_root)
            if cleared:
                transaction["cleared_pending_compile_verification"] = cleared
    return transaction


def _run_transactional_sync(tool_name: str, arguments: dict[str, Any], call):
    from gms_helpers.transactions import GameMakerProjectTransaction
    from gms_helpers.operation_policy import validate_project_operation

    project_root = _resolve_transaction_project_root(arguments)
    validate_project_operation(project_root, arguments)
    decision = decide_mutation_verification(tool_name, project_root)
    tx = GameMakerProjectTransaction(project_root, tool_name)
    tx.begin()
    try:
        result = call()
        tx.capture_mutation_state()
        if _result_from_value(result) == "error":
            tx.rollback()
            return _annotate_transaction_result(result, tx.to_dict())
        transaction = tx.commit(
            verify_compile=decision.action == "compile",
            before_commit=lambda state: _apply_verification_decision(
                project_root=project_root,
                tool_name=tool_name,
                decision=decision,
                transaction=state,
            ),
        )
        return _annotate_transaction_result(result, transaction)
    except BaseException as exc:
        if not tx.committed:
            tx.capture_mutation_state()
            tx.rollback()
        setattr(exc, "details", {**(getattr(exc, "details", {}) or {}), "transaction": tx.to_dict()})
        raise
    finally:
        tx.cleanup()


async def _run_transactional_async(tool_name: str, arguments: dict[str, Any], call):
    from gms_helpers.transactions import GameMakerProjectTransaction
    from gms_helpers.operation_policy import validate_project_operation

    project_root = _resolve_transaction_project_root(arguments)
    validate_project_operation(project_root, arguments)
    decision = decide_mutation_verification(tool_name, project_root)
    tx = GameMakerProjectTransaction(project_root, tool_name)
    await tx.begin_async()
    try:
        result = await call()
        await tx.capture_mutation_state_async()
        if _result_from_value(result) == "error":
            await tx.rollback_async()
            return _annotate_transaction_result(result, tx.to_dict())
        transaction = await tx.commit_async(
            verify_compile=decision.action == "compile",
            before_commit=lambda state: _apply_verification_decision(
                project_root=project_root,
                tool_name=tool_name,
                decision=decision,
                transaction=state,
            ),
        )
        return _annotate_transaction_result(result, transaction)
    except BaseException as exc:
        if not tx.committed:
            await tx.capture_mutation_state_async()
            await tx.rollback_async()
        setattr(exc, "details", {**(getattr(exc, "details", {}) or {}), "transaction": tx.to_dict()})
        raise
    finally:
        await tx.cleanup_async()


def _project_access_error_result(tool_name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool_name,
        "error": "Project access denied.",
        "error_type": "ProjectAccessError",
    }


def _wrap_tool_registration(
    mcp,
    *,
    project_access_policy: ProjectAccessPolicy,
    expose_host_diagnostics: bool,
    runtime: MCPV2Runtime,
) -> None:
    if not hasattr(mcp, "tool"):
        return
    original_tool = mcp.tool

    def _instrument_callable(func, tool_name: str, tool_family: str):
        def call_event_recorder(args, kwargs):
            try:
                bound = inspect.signature(func).bind_partial(*args, **kwargs)
                bound.apply_defaults()
                arguments = dict(bound.arguments)
                suppressed = bool(arguments.get("dry_run")) or (
                    operation_scope(tool_name) == "project" and not is_project_mutation(tool_name, arguments)
                )
            except TypeError:
                suppressed = True

            def record_event(**event):
                if not suppressed:
                    _record_mcp_event(**event)

            return record_event

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapped(*args, **kwargs):
                record_event = call_event_recorder(args, kwargs)
                reset_tool_execution_context()
                start = time.monotonic()
                try:
                    arguments, call_args, call_kwargs = _bind_tool_call(
                        func,
                        args,
                        kwargs,
                        project_access_policy,
                    )
                    validation_errors = validate_mcp_tool_arguments(tool_name, arguments)
                    from gms_mcp.server.dry_run_policy import destructive_policy_preflight

                    policy_error = destructive_policy_preflight(tool_name, arguments)
                    if validation_errors:
                        result = invalid_arguments_result(tool_name, validation_errors)
                    elif policy_error is not None:
                        result = policy_error
                    elif _tool_should_use_transaction(tool_name, arguments):
                        result = await _run_transactional_async(
                            tool_name,
                            arguments,
                            lambda: func(*call_args, **call_kwargs),
                        )
                    else:
                        result = await func(*call_args, **call_kwargs)
                    duration_ms = int((time.monotonic() - start) * 1000)
                    execution = get_tool_execution_context() or {}
                    record_event(
                        event_type="mcp.tool",
                        action=tool_name,
                        tool_name=tool_name,
                        tool_family=tool_family,
                        result=execution.get("result") or _result_from_value(result),
                        error_family=execution.get("error_family"),
                        duration_ms=duration_ms,
                        execution_mode=execution.get("execution_mode") or "inline",
                    )
                    return mcp_tool_result(
                        result,
                        project_root=project_access_policy.project_root,
                        expose_host_diagnostics=expose_host_diagnostics,
                    )
                except Exception as exc:
                    if isinstance(exc, ProjectAccessError):
                        result = _project_access_error_result(tool_name)
                        duration_ms = int((time.monotonic() - start) * 1000)
                        record_event(
                            event_type="mcp.tool",
                            action=tool_name,
                            tool_name=tool_name,
                            tool_family=tool_family,
                            result="error",
                            error_family="project_access",
                            duration_ms=duration_ms,
                            execution_mode="inline",
                        )
                        return mcp_tool_result(
                            result,
                            project_root=project_access_policy.project_root,
                            expose_host_diagnostics=expose_host_diagnostics,
                        )
                    if type(exc).__name__ == "TransactionValidationError":
                        result = _transaction_error_result(tool_name, exc)
                        duration_ms = int((time.monotonic() - start) * 1000)
                        record_event(
                            event_type="mcp.tool",
                            action=tool_name,
                            tool_name=tool_name,
                            tool_family=tool_family,
                            result="error",
                            error_family=classify_error_family(exc),
                            duration_ms=duration_ms,
                            execution_mode="inline",
                        )
                        return mcp_tool_result(
                            result,
                            project_root=project_access_policy.project_root,
                            expose_host_diagnostics=expose_host_diagnostics,
                        )
                    duration_ms = int((time.monotonic() - start) * 1000)
                    record_event(
                        event_type="mcp.tool",
                        action=tool_name,
                        tool_name=tool_name,
                        tool_family=tool_family,
                        result="error",
                        error_family=classify_error_family(exc),
                        duration_ms=duration_ms,
                        execution_mode="inline",
                    )
                    if expose_host_diagnostics:
                        raise
                    return mcp_tool_result(
                        {
                            "ok": False,
                            "tool": tool_name,
                            "error": "Internal tool error; host details were withheld.",
                            "error_type": "InternalToolError",
                        },
                        project_root=project_access_policy.project_root,
                        expose_host_diagnostics=False,
                    )
                finally:
                    reset_tool_execution_context()

            return async_wrapped

        @functools.wraps(func)
        def sync_wrapped(*args, **kwargs):
            record_event = call_event_recorder(args, kwargs)
            reset_tool_execution_context()
            start = time.monotonic()
            try:
                arguments, call_args, call_kwargs = _bind_tool_call(
                    func,
                    args,
                    kwargs,
                    project_access_policy,
                )
                validation_errors = validate_mcp_tool_arguments(tool_name, arguments)
                from gms_mcp.server.dry_run_policy import destructive_policy_preflight

                policy_error = destructive_policy_preflight(tool_name, arguments)
                if validation_errors:
                    result = invalid_arguments_result(tool_name, validation_errors)
                elif policy_error is not None:
                    result = policy_error
                elif _tool_should_use_transaction(tool_name, arguments):
                    result = _run_transactional_sync(
                        tool_name,
                        arguments,
                        lambda: func(*call_args, **call_kwargs),
                    )
                else:
                    result = func(*call_args, **call_kwargs)
                duration_ms = int((time.monotonic() - start) * 1000)
                execution = get_tool_execution_context() or {}
                record_event(
                    event_type="mcp.tool",
                    action=tool_name,
                    tool_name=tool_name,
                    tool_family=tool_family,
                    result=execution.get("result") or _result_from_value(result),
                    error_family=execution.get("error_family"),
                    duration_ms=duration_ms,
                    execution_mode=execution.get("execution_mode") or "inline",
                )
                return mcp_tool_result(
                    result,
                    project_root=project_access_policy.project_root,
                    expose_host_diagnostics=expose_host_diagnostics,
                )
            except Exception as exc:
                if isinstance(exc, ProjectAccessError):
                    result = _project_access_error_result(tool_name)
                    duration_ms = int((time.monotonic() - start) * 1000)
                    record_event(
                        event_type="mcp.tool",
                        action=tool_name,
                        tool_name=tool_name,
                        tool_family=tool_family,
                        result="error",
                        error_family="project_access",
                        duration_ms=duration_ms,
                        execution_mode="inline",
                    )
                    return mcp_tool_result(
                        result,
                        project_root=project_access_policy.project_root,
                        expose_host_diagnostics=expose_host_diagnostics,
                    )
                if type(exc).__name__ == "TransactionValidationError":
                    result = _transaction_error_result(tool_name, exc)
                    duration_ms = int((time.monotonic() - start) * 1000)
                    record_event(
                        event_type="mcp.tool",
                        action=tool_name,
                        tool_name=tool_name,
                        tool_family=tool_family,
                        result="error",
                        error_family=classify_error_family(exc),
                        duration_ms=duration_ms,
                        execution_mode="inline",
                    )
                    return mcp_tool_result(
                        result,
                        project_root=project_access_policy.project_root,
                        expose_host_diagnostics=expose_host_diagnostics,
                    )
                duration_ms = int((time.monotonic() - start) * 1000)
                record_event(
                    event_type="mcp.tool",
                    action=tool_name,
                    tool_name=tool_name,
                    tool_family=tool_family,
                    result="error",
                    error_family=classify_error_family(exc),
                    duration_ms=duration_ms,
                    execution_mode="inline",
                )
                if expose_host_diagnostics:
                    raise
                return mcp_tool_result(
                    {
                        "ok": False,
                        "tool": tool_name,
                        "error": "Internal tool error; host details were withheld.",
                        "error_type": "InternalToolError",
                    },
                    project_root=project_access_policy.project_root,
                    expose_host_diagnostics=False,
                )
            finally:
                reset_tool_execution_context()

        return sync_wrapped

    def instrumented_tool(*tool_args, **tool_kwargs):
        def _decorate(func):
            tool_name = str(tool_kwargs.get("name") or getattr(func, "__name__", "tool"))
            tool_family = _tool_family_for_function(func)
            wrapped = _instrument_callable(func, tool_name, tool_family)
            registration_kwargs = dict(tool_kwargs)
            if "annotations" not in registration_kwargs:
                from mcp.types import ToolAnnotations

                is_read_only = operation_scope(tool_name) == "read"
                registration_kwargs["annotations"] = ToolAnnotations(
                    read_only_hint=is_read_only,
                    destructive_hint=(
                        is_real_destructive_operation(tool_name, {"fix": True, "delete": True, "apply": True})
                    ),
                    idempotent_hint=is_read_only,
                )
            decorator = original_tool(*tool_args, **registration_kwargs)
            return decorator(wrapped)

        return _decorate

    mcp.tool = instrumented_tool


def build_server(*, http_auth_value: str | None = None, http_auth_issuer_url: str | None = None):
    """
    Create and return the MCP server instance.

    Kept in a function so importing this module doesn't require MCP installed.
    """
    from mcp.server.mcpserver import Context, MCPServer

    # MCPServer evaluates annotation strings at runtime. Keep Context available
    # in this module's globals for compatibility.
    globals()["Context"] = Context

    if (http_auth_value is None) != (http_auth_issuer_url is None):
        raise ValueError("HTTP bearer authentication requires both token and issuer URL.")
    auth, token_verifier = (
        local_bearer_auth(http_auth_value, http_auth_issuer_url)
        if http_auth_value is not None and http_auth_issuer_url is not None
        else (None, None)
    )
    project_access_policy = ProjectAccessPolicy.from_server_environment()
    expose_host_diagnostics = expose_host_diagnostics_from_environment()
    runtime = MCPV2Runtime(project_access_policy)
    from .server.mcp_apps import create_project_dashboard_app

    dashboard_app = create_project_dashboard_app(project_access_policy, expose_host_diagnostics)
    mcp = MCPServer(
        "GameMaker MCP",
        title="GameMaker MCP",
        description="Safe, structured GameMaker project tooling.",
        version=version("gms-mcp"),
        cache_hints=MCP_CACHE_HINTS,
        subscriptions=runtime.subscriptions,
        lifespan=runtime.lifespan,
        auth=auth,
        token_verifier=token_verifier,
        extensions=[dashboard_app],
        middleware=[
            MutationSerializationMiddleware(
                runtime,
                lambda name: operation_scope(name) == "read",
                _is_committed_mutation_result,
            )
        ],
    )
    _wrap_tool_registration(
        mcp,
        project_access_policy=project_access_policy,
        expose_host_diagnostics=expose_host_diagnostics,
        runtime=runtime,
    )
    register_all(
        mcp,
        Context,
        project_access_policy=project_access_policy,
        expose_host_diagnostics=expose_host_diagnostics,
        resolution_runtime=runtime.resolution,
    )

    return mcp


def _parse_server_arguments(argv: list[str]) -> tuple[argparse.Namespace | None, int]:
    parser = argparse.ArgumentParser(prog="gms-mcp server", description="Run the GameMaker MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help=(
            "MCP transport (default: stdio). Streamable HTTP requires a non-empty "
            f"{_HTTP_AUTH_ENV_NAME} environment variable."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (loopback only).")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port (default: 8000).")
    parser.add_argument("--path", default="/mcp", help="Streamable HTTP endpoint path (default: /mcp).")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return None, int(exc.code or 0)

    args.host = str(args.host).strip().removeprefix("[").removesuffix("]")
    try:
        loopback = args.host.lower() == "localhost" or ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = False
    if args.transport == "streamable-http" and not loopback:
        parser.print_usage(sys.stderr)
        sys.stderr.write("gms-mcp server: error: HTTP transport is restricted to loopback hosts.\n")
        return None, 2
    if not 1 <= args.port <= 65_535:
        parser.print_usage(sys.stderr)
        sys.stderr.write("gms-mcp server: error: --port must be between 1 and 65535.\n")
        return None, 2
    if not args.path.startswith("/") or any(character.isspace() for character in args.path):
        parser.print_usage(sys.stderr)
        sys.stderr.write("gms-mcp server: error: --path must be an absolute URL path without whitespace.\n")
        return None, 2
    return args, 0


def _http_transport_security(host: str, port: int):
    from mcp.server.transport_security import TransportSecuritySettings

    authority = f"[{host}]" if ":" in host else host
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[authority, f"{authority}:{port}"],
        allowed_origins=[f"http://{authority}:{port}"],
    )


def _http_origin(host: str, port: int) -> str:
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}:{port}"


def _http_auth_value_from_environment() -> str | None:
    return os.environ.get(_HTTP_AUTH_ENV_NAME) or None


def main(argv: list[str] | None = None) -> int:
    # Suppress MCP SDK INFO logging to stderr (Cursor displays stderr as [error] which is confusing)
    import logging

    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.server").setLevel(logging.WARNING)

    server_args, argument_exit_code = _parse_server_arguments(list(argv or []))
    if server_args is None:
        return argument_exit_code

    try:
        if server_args.transport == "streamable-http":
            http_auth_value = _http_auth_value_from_environment()
            if http_auth_value is None:
                sys.stderr.write(
                    "gms-mcp server: error: streamable HTTP requires a non-empty "
                    f"{_HTTP_AUTH_ENV_NAME} environment variable.\n"
                )
                return 2
            try:
                validate_local_bearer_token(http_auth_value)
            except ValueError:
                sys.stderr.write(
                    "gms-mcp server: error: streamable HTTP requires a bearer token with 32-4096 "
                    "ASCII bearer-token characters.\n"
                )
                return 2
            server = build_server(
                http_auth_value=http_auth_value,
                http_auth_issuer_url=f"{_http_origin(server_args.host, server_args.port)}{server_args.path}",
            )
        else:
            server = build_server()
        _record_mcp_event(
            event_type="mcp.server_start",
            action="server.start",
            tool_name="server.start",
            tool_family="server",
            result="ok",
            duration_ms=0,
            execution_mode=server_args.transport,
        )
    except ModuleNotFoundError as e:
        sys.stderr.write("MCP dependency is missing. Reinstall or upgrade the gms-mcp package.\n")
        if expose_host_diagnostics_from_environment():
            sys.stderr.write(f"Details: {e}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(
            "MCP server could not start because its approved GameMaker project is unavailable or unsafe.\n"
        )
        if expose_host_diagnostics_from_environment():
            sys.stderr.write(f"Details: {exc}\n")
        return 1

    try:
        if server_args.transport == "stdio":
            server.run()
        else:
            server.run(
                "streamable-http",
                host=server_args.host,
                port=server_args.port,
                streamable_http_path=server_args.path,
                stateless_http=True,
                max_request_body_size=_HTTP_MAX_REQUEST_BODY_BYTES,
                transport_security=_http_transport_security(server_args.host, server_args.port),
            )
        return 0
    except Exception as exc:
        sys.stderr.write("MCP server stopped after an internal error; host details were withheld.\n")
        if expose_host_diagnostics_from_environment():
            sys.stderr.write(f"Details: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(list(sys.argv[1:])))
