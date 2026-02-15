from __future__ import annotations

import json
from typing import Any

from .project import _resolve_project_directory
from ..update_notifier import check_for_updates


def register(mcp: Any) -> None:
    @mcp.resource("gms://project/index")
    async def gm_project_index() -> str:
        """Return the full project index as JSON."""
        project_directory = _resolve_project_directory(".")
        from gms_helpers.introspection import build_project_index

        index = build_project_index(project_directory)
        return json.dumps(index, indent=2)

    @mcp.resource("gms://project/asset-graph")
    async def gm_asset_graph_resource() -> str:
        """Return the asset dependency graph as JSON (structural refs only, use gm_get_asset_graph tool for deep mode)."""
        project_directory = _resolve_project_directory(".")
        from gms_helpers.introspection import build_asset_graph

        graph = build_asset_graph(project_directory, deep=False)
        return json.dumps(graph, indent=2)

    @mcp.resource("gms://system/updates")
    async def gm_updates_resource() -> str:
        """Check for updates and return the status as a human-readable message."""
        info = check_for_updates()
        return info["message"]

