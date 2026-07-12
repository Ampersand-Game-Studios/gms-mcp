from __future__ import annotations

import os
from typing import Any

from . import resources
from .tools import (
    asset_creation,
    bridge,
    capabilities,
    code_intel,
    docs,
    events,
    introspection,
    maintenance,
    project_health,
    rooms,
    runner,
    runtime,
    texture_groups,
    verification,
    workflow,
)


_OPTIONAL_TOOLSETS = {
    "assets": asset_creation,
    "bridge": bridge,
    "docs": docs,
    "events": events,
    "maintenance": maintenance,
    "rooms": rooms,
    "runtime": runtime,
    "texture-groups": texture_groups,
}


def enabled_toolsets() -> tuple[str, ...]:
    """Return the deterministic MCP toolsets enabled for this server process."""
    raw = os.environ.get("GMS_MCP_TOOLSETS", "core").strip().lower()
    requested = {token.strip().replace("_", "-") for token in raw.replace(";", ",").split(",") if token.strip()}
    if not requested or requested == {"core"}:
        return ("core",)
    if "all" in requested:
        return ("core", *sorted(_OPTIONAL_TOOLSETS))
    unknown = requested - {"core", *_OPTIONAL_TOOLSETS}
    if unknown:
        supported = ", ".join(("core", *_OPTIONAL_TOOLSETS, "all"))
        raise ValueError(f"Unknown GMS_MCP_TOOLSETS value(s): {', '.join(sorted(unknown))}. Supported: {supported}")
    return ("core", *sorted(requested - {"core"}))


def register_all(mcp: Any, Context: Any) -> None:
    toolsets = enabled_toolsets()
    capabilities.register(mcp, Context, enabled=toolsets, optional=tuple(sorted(_OPTIONAL_TOOLSETS)))
    project_health.register(mcp, Context)
    runner.register(mcp, Context)
    verification.register(mcp, Context)
    workflow.register(mcp, Context)
    introspection.register(mcp, Context)
    code_intel.register(mcp, Context)
    for toolset in toolsets:
        module = _OPTIONAL_TOOLSETS.get(toolset)
        if module is not None:
            module.register(mcp, Context)
    resources.register(mcp)
