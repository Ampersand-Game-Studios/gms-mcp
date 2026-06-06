#!/usr/bin/env python3
"""
GameMaker MCP Server

Exposes common GameMaker project actions as MCP tools by reusing the existing
Python helper modules in `gms_helpers`.

Public entrypoints:
- build_server(): constructs and returns the FastMCP instance
- main(): stdio server entrypoint (used by `gms-mcp` and bootstrap runners)

Implementation details live under `gms_mcp.server.*`.
"""

from __future__ import annotations

import functools
import inspect
import os
import sys
import time
from pathlib import Path
from typing import Any

from .server.debug import _dbg
from .server.register_all import register_all
from .server.validation import invalid_arguments_result, validate_mcp_tool_arguments
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
    "gm_asset_delete",
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


def _bind_tool_arguments(func, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(func)
    bound = signature.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


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


def _run_transactional_sync(tool_name: str, arguments: dict[str, Any], call):
    from gms_helpers.transactions import GameMakerProjectTransaction, should_compile_verify_after_mutation

    tx = GameMakerProjectTransaction(_resolve_transaction_project_root(arguments), tool_name)
    tx.begin()
    try:
        result = call()
        if _result_from_value(result) == "error":
            tx.rollback()
            return _annotate_transaction_result(result, tx.to_dict())
        transaction = tx.commit(verify_compile=should_compile_verify_after_mutation())
        return _annotate_transaction_result(result, transaction)
    except Exception:
        tx.rollback()
        raise
    finally:
        tx.cleanup()


async def _run_transactional_async(tool_name: str, arguments: dict[str, Any], call):
    from gms_helpers.transactions import GameMakerProjectTransaction, should_compile_verify_after_mutation

    tx = GameMakerProjectTransaction(_resolve_transaction_project_root(arguments), tool_name)
    tx.begin()
    try:
        result = await call()
        if _result_from_value(result) == "error":
            tx.rollback()
            return _annotate_transaction_result(result, tx.to_dict())
        transaction = tx.commit(verify_compile=should_compile_verify_after_mutation())
        return _annotate_transaction_result(result, transaction)
    except Exception:
        tx.rollback()
        raise
    finally:
        tx.cleanup()


def _wrap_tool_registration(mcp) -> None:
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
                    arguments = _bind_tool_arguments(func, args, kwargs)
                    validation_errors = validate_mcp_tool_arguments(tool_name, arguments)
                    if validation_errors:
                        result = invalid_arguments_result(tool_name, validation_errors)
                    elif _tool_should_use_transaction(tool_name, arguments):
                        result = await _run_transactional_async(
                            tool_name,
                            arguments,
                            lambda: func(*args, **kwargs),
                        )
                    else:
                        result = await func(*args, **kwargs)
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
                    return result
                except Exception as exc:
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
                        return result
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
                    raise
                finally:
                    reset_tool_execution_context()

            return async_wrapped

        @functools.wraps(func)
        def sync_wrapped(*args, **kwargs):
            reset_tool_execution_context()
            start = time.monotonic()
            try:
                arguments = _bind_tool_arguments(func, args, kwargs)
                validation_errors = validate_mcp_tool_arguments(tool_name, arguments)
                if validation_errors:
                    result = invalid_arguments_result(tool_name, validation_errors)
                elif _tool_should_use_transaction(tool_name, arguments):
                    result = _run_transactional_sync(
                        tool_name,
                        arguments,
                        lambda: func(*args, **kwargs),
                    )
                else:
                    result = func(*args, **kwargs)
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
                return result
            except Exception as exc:
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
                    return result
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
                raise
            finally:
                reset_tool_execution_context()

        return sync_wrapped

    def instrumented_tool(*tool_args, **tool_kwargs):
        decorator = original_tool(*tool_args, **tool_kwargs)

        def _decorate(func):
            registered = decorator(func)
            tool_name = str(tool_kwargs.get("name") or getattr(func, "__name__", "tool"))
            tool_family = _tool_family_for_function(func)
            tool_manager = getattr(mcp, "_tool_manager", None)
            if tool_manager is not None:
                tool = tool_manager.get_tool(tool_name)
                if tool is not None:
                    tool.fn = _instrument_callable(tool.fn, tool_name, tool_family)
            return registered

        return _decorate

    mcp.tool = instrumented_tool


def build_server():
    """
    Create and return the MCP server instance.

    Kept in a function so importing this module doesn't require MCP installed.
    """
    from mcp.server.fastmcp import Context, FastMCP

    # region agent log
    _dbg(
        "H2",
        "src/gms_mcp/gamemaker_mcp_server.py:build_server:entry",
        "build_server entry",
        {"pid": os.getpid(), "exe": sys.executable, "cwd": os.getcwd(), "py_path_head": sys.path[:5]},
    )
    # endregion

    # Some MCP clients/FastMCP paths evaluate annotation strings at runtime. Keep Context available
    # in this module's globals for compatibility.
    globals()["Context"] = Context

    mcp = FastMCP("GameMaker MCP")
    _wrap_tool_registration(mcp)
    register_all(mcp, Context)

    # region agent log
    _dbg(
        "H2",
        "src/gms_mcp/gamemaker_mcp_server.py:build_server:exit",
        "build_server returning FastMCP instance",
        {"pid": os.getpid()},
    )
    # endregion
    return mcp


def main() -> int:
    # Suppress MCP SDK INFO logging to stderr (Cursor displays stderr as [error] which is confusing)
    import logging

    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.server").setLevel(logging.WARNING)

    # region agent log
    _dbg(
        "H1",
        "src/gms_mcp/gamemaker_mcp_server.py:main:entry",
        "server main entry",
        {
            "pid": os.getpid(),
            "exe": sys.executable,
            "argv": sys.argv,
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
            execution_mode="stdio",
        )
    except ModuleNotFoundError as e:
        sys.stderr.write(
            f"MCP dependency is missing.\nInstall it with:\n  {sys.executable} -m pip install -U gms-mcp\n"
        )
        sys.stderr.write(f"\nDetails: {e}\n")
        return 1

    # region agent log
    # Instrument the MCP protocol boundary: log every incoming request type.
    # This tells us whether Cursor is hanging during initialize/list-tools/call-tool,
    # or whether the request never arrives.
    try:
        import mcp.server.lowlevel.server as _lls

        if not getattr(_lls.Server, "_gms_mcp_patched", False):
            _orig_handle_request = _lls.Server._handle_request

            async def _patched_handle_request(self, message, req, session, lifespan_context, raise_exceptions):
                t0 = time.monotonic()
                req_type = type(req).__name__
                req_id = getattr(message, "request_id", None)
                # Best-effort extraction of tool name for CallToolRequest (helps confirm if Cursor ever sends it)
                tool_name = None
                try:
                    tool_name = getattr(req, "params", None) and getattr(req.params, "name", None)
                except Exception:
                    tool_name = None
                _dbg(
                    "H4",
                    "src/gms_mcp/gamemaker_mcp_server.py:lowlevel:_handle_request:entry",
                    "received request",
                    {"pid": os.getpid(), "req_type": req_type, "request_id": req_id, "tool_name": tool_name},
                )
                try:
                    result = await _orig_handle_request(self, message, req, session, lifespan_context, raise_exceptions)
                    dt_ms = int((time.monotonic() - t0) * 1000)
                    _dbg(
                        "H4",
                        "src/gms_mcp/gamemaker_mcp_server.py:lowlevel:_handle_request:exit",
                        "request handled",
                        {"pid": os.getpid(), "req_type": req_type, "request_id": req_id, "elapsed_ms": dt_ms},
                    )
                    return result
                except Exception as e:
                    dt_ms = int((time.monotonic() - t0) * 1000)
                    _dbg(
                        "H4",
                        "src/gms_mcp/gamemaker_mcp_server.py:lowlevel:_handle_request:error",
                        "request handler raised",
                        {
                            "pid": os.getpid(),
                            "req_type": req_type,
                            "request_id": req_id,
                            "elapsed_ms": dt_ms,
                            "error": str(e),
                        },
                    )
                    raise

            _lls.Server._handle_request = _patched_handle_request  # type: ignore[assignment]
            _lls.Server._gms_mcp_patched = True  # type: ignore[attr-defined]
            _dbg(
                "H4",
                "src/gms_mcp/gamemaker_mcp_server.py:main:patch_ok",
                "patched lowlevel Server._handle_request",
                {"pid": os.getpid()},
            )
    except Exception as e:
        _dbg(
            "H4",
            "src/gms_mcp/gamemaker_mcp_server.py:main:patch_failed",
            "failed to patch lowlevel request handler",
            {"pid": os.getpid(), "error": str(e)},
        )
    # endregion

    # region agent log
    _dbg(
        "H1",
        "src/gms_mcp/gamemaker_mcp_server.py:main:before_run",
        "calling server.run()",
        {"pid": os.getpid()},
    )
    # endregion
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
