"""Discovery for the curated GameMaker MCP tool surface."""

from __future__ import annotations

from typing import Any, Dict

from ..mcp_types import Context


def register(
    mcp: Any,
    ContextType: Any,
    *,
    enabled: tuple[str, ...],
    optional: tuple[str, ...],
) -> None:
    globals()["Context"] = ContextType

    @mcp.tool()
    async def gm_capabilities(ctx: Context | None = None) -> Dict[str, Any]:
        """List enabled MCP toolsets and the single restart-time setting used to enable optional domains."""
        _ = ctx
        enabled_set = set(enabled)
        return {
            "ok": True,
            "profile": "all" if enabled_set == {"core", *optional} else "curated",
            "enabled_toolsets": list(enabled),
            "optional_toolsets": list(optional),
            "disabled_toolsets": [name for name in optional if name not in enabled_set],
            "configuration": {
                "environment_variable": "GMS_MCP_TOOLSETS",
                "all_value": "all",
                "example": "maintenance,texture-groups",
                "restart_required": True,
            },
        }
