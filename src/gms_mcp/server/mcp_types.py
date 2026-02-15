from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Only imported for static type checking; tool modules still set the runtime Context global
    # at registration time to satisfy FastMCP's annotation evaluation.
    from mcp.server.fastmcp import Context as Context
else:
    Context = Any  # type: ignore[misc,assignment]

