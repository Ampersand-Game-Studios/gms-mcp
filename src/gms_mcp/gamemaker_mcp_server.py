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

from .server.debug import _dbg
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


_TRANSACTIONAL_TOOL_PREFIXES = (
    "gm_create_",
    "gm_event_",
    "gm_room_layer_",
    "gm_room_instance_",
    "gm_sprite_",
    "gm_texture_group_",
    "gm_workflow_",
)
_TRANSACTIONAL_TOOL_NAMES = {
    "gm_bridge_install",
    "gm_bridge_uninstall",
    "gm_bridge_enable_one_shot",
    "gm_maintenance_auto",
    "gm_maintenance_lint",
    "gm_maintenance_prune_missing",
    "gm_maintenance_dedupe_resources",
    "gm_maintenance_sync_events",
    "gm_maintenance_normalize_names",
    "gm_maintenance_clean_old_files",
    "gm_maintenance_clean_orphans",
    "gm_maintenance_fix_issues",
    "gm_room_ops_duplicate",
    "gm_room_ops_rename",
    "gm_room_ops_delete",
    "gm_safe_delete",
}
_NON_TRANSACTIONAL_TOOL_NAMES = {
    "gm_event_list",
    "gm_event_validate",
    "gm_room_layer_list",
    "gm_room_instance_list",
    "gm_room_ops_list",
    "gm_texture_group_list",
    "gm_texture_group_read",
    "gm_texture_group_members",
    "gm_texture_group_scan",
    "gm_sprite_frame_count",
}
_READ_ONLY_TOOL_NAMES = {
    "gm_bridge_status",
    "gm_capabilities",
    "gm_check_updates",
    "gm_diagnostics",
    "gm_doc_cache_stats",
    "gm_doc_categories",
    "gm_doc_list",
    "gm_doc_lookup",
    "gm_doc_search",
    "gm_event_list",
    "gm_event_validate",
    "gm_find_definition",
    "gm_find_references",
    "gm_get_asset_graph",
    "gm_get_project_stats",
    "gm_list_assets",
    "gm_list_symbols",
    "gm_maintenance_list_orphans",
    "gm_maintenance_validate_json",
    "gm_maintenance_validate_paths",
    "gm_mcp_health",
    "gm_project_info",
    "gm_project_dashboard",
    "gm_read_asset",
    "gm_room_instance_list",
    "gm_room_layer_list",
    "gm_room_ops_list",
    "gm_run_logs",
    "gm_run_status",
    "gm_runtime_list",
    "gm_runtime_verify",
    "gm_search_references",
    "gm_sprite_frame_count",
    "gm_texture_group_list",
    "gm_texture_group_members",
    "gm_texture_group_read",
    "gm_texture_group_scan",
    "gm_verification_status",
}
_DESTRUCTIVE_TOOL_MARKERS = (
    "_clean_",
    "_dedupe_",
    "_delete",
    "_fix",
    "_normalize_",
    "_prune_",
    "_remove",
    "_rename",
    "_stop",
    "_swap_",
    "_sync_",
    "_uninstall",
)


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
    if isinstance(value, dict) and value.get("ok") is False:
        return "error"
    return "ok"


def _is_committed_mutation_result(value: Any) -> bool:
    structured_content = (
        value.get("structuredContent") if isinstance(value, dict) else getattr(value, "structured_content", None)
    )
    if isinstance(structured_content, dict):
        value = structured_content.get("result", structured_content)
    if not isinstance(value, dict) or value.get("ok") is False:
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


def _tool_call_is_dry_run(arguments: dict[str, Any]) -> bool:
    return bool(arguments.get("dry_run")) or (
        arguments.get("fix") is False
        and arguments.get("delete") is False
        and any(name in arguments for name in ("fix", "delete"))
    )


def _tool_should_use_transaction(tool_name: str, arguments: dict[str, Any]) -> bool:
    if tool_name in _NON_TRANSACTIONAL_TOOL_NAMES:
        return False
    if _tool_call_is_dry_run(arguments):
        return False
    if tool_name.startswith("gm_maintenance_"):
        if tool_name == "gm_maintenance_fix_issues":
            return True
        if "dry_run" in arguments:
            return not bool(arguments.get("dry_run"))
        if "fix" in arguments:
            return bool(arguments.get("fix"))
        if "delete" in arguments:
            return bool(arguments.get("delete"))
        return False
    if tool_name.startswith("gm_texture_group_") and tool_name not in _TRANSACTIONAL_TOOL_NAMES:
        if tool_name in {
            "gm_texture_group_list",
            "gm_texture_group_read",
            "gm_texture_group_members",
            "gm_texture_group_scan",
        }:
            return False
        return True
    return tool_name in _TRANSACTIONAL_TOOL_NAMES or tool_name.startswith(_TRANSACTIONAL_TOOL_PREFIXES)


def _resolve_transaction_project_root(arguments: dict[str, Any]) -> Path:
    from gms_mcp.server.project import _resolve_project_directory_no_deps

    return _resolve_project_directory_no_deps(str(arguments.get("project_root") or "."))


def _annotate_transaction_result(result: Any, transaction: dict[str, Any]) -> Any:
    if isinstance(result, dict):
        if not result.get("transaction"):
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

    project_root = _resolve_transaction_project_root(arguments)
    decision = decide_mutation_verification(tool_name)
    tx = GameMakerProjectTransaction(project_root, tool_name)
    tx.begin()
    try:
        result = call()
        tx.capture_mutation_state()
        if _result_from_value(result) == "error":
            tx.rollback()
            return _annotate_transaction_result(result, tx.to_dict())
        transaction = tx.commit(verify_compile=decision.action == "compile")
        transaction = _apply_verification_decision(
            project_root=project_root,
            tool_name=tool_name,
            decision=decision,
            transaction=transaction,
        )
        return _annotate_transaction_result(result, transaction)
    except Exception:
        if not tx.committed:
            tx.capture_mutation_state()
            tx.rollback()
        raise
    finally:
        tx.cleanup()


async def _run_transactional_async(tool_name: str, arguments: dict[str, Any], call):
    from gms_helpers.transactions import GameMakerProjectTransaction

    project_root = _resolve_transaction_project_root(arguments)
    decision = decide_mutation_verification(tool_name)
    tx = GameMakerProjectTransaction(project_root, tool_name)
    await tx.begin_async()
    try:
        result = await call()
        await tx.capture_mutation_state_async()
        if _result_from_value(result) == "error":
            await tx.rollback_async()
            return _annotate_transaction_result(result, tx.to_dict())
        transaction = await tx.commit_async(verify_compile=decision.action == "compile")
        transaction = _apply_verification_decision(
            project_root=project_root,
            tool_name=tool_name,
            decision=decision,
            transaction=transaction,
        )
        return _annotate_transaction_result(result, transaction)
    except BaseException:
        if not tx.committed:
            await tx.capture_mutation_state_async()
            await tx.rollback_async()
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
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapped(*args, **kwargs):
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
                    if validation_errors:
                        result = invalid_arguments_result(tool_name, validation_errors)
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
                    _record_mcp_event(
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
                        _record_mcp_event(
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
                        _record_mcp_event(
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
                    _record_mcp_event(
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
                if validation_errors:
                    result = invalid_arguments_result(tool_name, validation_errors)
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
                _record_mcp_event(
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
                    _record_mcp_event(
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
                    _record_mcp_event(
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
                _record_mcp_event(
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

                is_read_only = tool_name in _READ_ONLY_TOOL_NAMES
                registration_kwargs["annotations"] = ToolAnnotations(
                    read_only_hint=is_read_only,
                    destructive_hint=(
                        not is_read_only and any(marker in tool_name for marker in _DESTRUCTIVE_TOOL_MARKERS)
                    ),
                    idempotent_hint=is_read_only,
                )
            decorator = original_tool(*tool_args, **registration_kwargs)
            return decorator(wrapped)

        return _decorate

    mcp.tool = instrumented_tool


def build_server():
    """
    Create and return the MCP server instance.

    Kept in a function so importing this module doesn't require MCP installed.
    """
    from mcp.server.mcpserver import Context, MCPServer

    # region agent log
    _dbg(
        "H2",
        "src/gms_mcp/gamemaker_mcp_server.py:build_server:entry",
        "build_server entry",
        {"pid": os.getpid(), "exe": sys.executable, "cwd": os.getcwd(), "py_path_head": sys.path[:5]},
    )
    # endregion

    # MCPServer evaluates annotation strings at runtime. Keep Context available
    # in this module's globals for compatibility.
    globals()["Context"] = Context

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
        extensions=[dashboard_app],
        middleware=[
            MutationSerializationMiddleware(
                runtime,
                lambda name: name in _READ_ONLY_TOOL_NAMES,
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

    # region agent log
    _dbg(
        "H2",
        "src/gms_mcp/gamemaker_mcp_server.py:build_server:exit",
        "build_server returning MCPServer instance",
        {"pid": os.getpid()},
    )
    # endregion
    return mcp


def _parse_server_arguments(argv: list[str]) -> tuple[argparse.Namespace | None, int]:
    parser = argparse.ArgumentParser(prog="gms-mcp server", description="Run the GameMaker MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport (default: stdio).",
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
        sys.stderr.write("gms-mcp server: error: unauthenticated HTTP transport is restricted to loopback hosts.\n")
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


def main(argv: list[str] | None = None) -> int:
    # Suppress MCP SDK INFO logging to stderr (Cursor displays stderr as [error] which is confusing)
    import logging

    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.server").setLevel(logging.WARNING)

    server_args, argument_exit_code = _parse_server_arguments(list(argv or []))
    if server_args is None:
        return argument_exit_code

    # region agent log
    _dbg(
        "H1",
        "src/gms_mcp/gamemaker_mcp_server.py:main:entry",
        "server main entry",
        {
            "pid": os.getpid(),
            "exe": sys.executable,
            "argv": argv if argv is not None else sys.argv,
            "cwd": os.getcwd(),
            "stdin_isatty": bool(getattr(sys.stdin, "isatty", lambda: False)()),
            "stdout_isatty": bool(getattr(sys.stdout, "isatty", lambda: False)()),
        },
    )
    # endregion
    try:
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

    # region agent log
    _dbg(
        "H1",
        "src/gms_mcp/gamemaker_mcp_server.py:main:before_run",
        "calling server.run()",
        {"pid": os.getpid()},
    )
    # endregion
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
