from __future__ import annotations

import os
from typing import Any

from . import prompts, resources
from .project import ProjectAccessPolicy
from .resolution import ResolutionRuntime
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
    resourcetool,
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
    "resourcetool": resourcetool,
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


def register_all(
    mcp: Any,
    Context: Any,
    *,
    project_access_policy: ProjectAccessPolicy,
    expose_host_diagnostics: bool,
    resolution_runtime: ResolutionRuntime,
) -> None:
    toolsets = enabled_toolsets()
    read_only = os.environ.get("GMS_MCP_READ_ONLY", "").strip() == "1"
    if read_only and toolsets != ("core",):
        raise ValueError("GMS_MCP_READ_ONLY=1 only supports GMS_MCP_TOOLSETS=core.")
    capabilities.register(mcp, Context, enabled=toolsets, optional=tuple(sorted(_OPTIONAL_TOOLSETS)))
    project_health.register(mcp, Context)
    runner.register(mcp, Context, read_only=read_only)
    verification.register(mcp, Context, read_only=read_only)
    if not read_only:
        workflow.register(mcp, Context, resolution_runtime)
    introspection.register(mcp, Context)
    code_intel.register(mcp, Context, read_only=read_only)
    for toolset in toolsets:
        module = _OPTIONAL_TOOLSETS.get(toolset)
        if module is not None:
            if module in {asset_creation, rooms, texture_groups}:
                module.register(mcp, Context, resolution_runtime)
            elif module is resourcetool:
                module.register(mcp, Context, project_access_policy=project_access_policy)
            else:
                module.register(mcp, Context)
    prompts.register(mcp, enabled_toolsets=toolsets, read_only=read_only)
    resources.register(
        mcp,
        project_access_policy=project_access_policy,
        expose_host_diagnostics=expose_host_diagnostics,
    )
