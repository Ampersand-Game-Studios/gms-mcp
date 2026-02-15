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

import os
import sys
import time

from .server.debug import _dbg
from .server.register_all import register_all


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
