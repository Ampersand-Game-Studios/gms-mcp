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

from .server.debug import _dbg
from .server.register_all import register_all
from .telemetry import (
    classify_error_family,
    get_tool_execution_context,
    maybe_start_background_flush,
    queue_event,
    reset_tool_execution_context,
    resolve_state,
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


def _wrap_tool_registration(mcp) -> None:
    if not hasattr(mcp, "tool"):
        return
    original_tool = mcp.tool

    def _instrument_callable(func, tool_name: str, tool_family: str):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapped(*args, **kwargs):
                reset_tool_execution_context()
                start = time.monotonic()
                try:
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

            return wrapped

        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            reset_tool_execution_context()
            start = time.monotonic()
            try:
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

        return wrapped

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
            "MCP dependency is missing.\n"
            "Install it with:\n"
            f"  {sys.executable} -m pip install -U gms-mcp\n"
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
