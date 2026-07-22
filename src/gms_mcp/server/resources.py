from __future__ import annotations

import json
from typing import Any

from .project import ProjectAccessPolicy
from .results import public_mcp_result
from ..update_status import get_update_status


def register(
    mcp: Any,
    *,
    project_access_policy: ProjectAccessPolicy,
    expose_host_diagnostics: bool,
) -> None:
    @mcp.resource("gms://project/index")
    async def gm_project_index() -> str:
        """Return the full project index as JSON."""
        try:
            project_directory = project_access_policy.authorize(".")
            from gms_helpers.introspection import build_project_index

            index = build_project_index(project_directory)
            return json.dumps(
                public_mcp_result(
                    index,
                    project_root=project_directory,
                    expose_host_diagnostics=expose_host_diagnostics,
                ),
                indent=2,
            )
        except Exception:
            if expose_host_diagnostics:
                raise
            return json.dumps({"ok": False, "error": "Resource unavailable; host details were withheld."})

    @mcp.resource("gms://project/asset-graph")
    async def gm_asset_graph_resource() -> str:
        """Return the asset dependency graph as JSON (structural refs only, use gm_get_asset_graph tool for deep mode)."""
        try:
            project_directory = project_access_policy.authorize(".")
            from gms_helpers.introspection import build_asset_graph

            graph = build_asset_graph(project_directory, deep=False)
            return json.dumps(
                public_mcp_result(
                    graph,
                    project_root=project_directory,
                    expose_host_diagnostics=expose_host_diagnostics,
                ),
                indent=2,
            )
        except Exception:
            if expose_host_diagnostics:
                raise
            return json.dumps({"ok": False, "error": "Resource unavailable; host details were withheld."})

    @mcp.resource("gms://system/updates")
    async def gm_updates_resource() -> str:
        """Check for updates and return the status as a human-readable message."""
        try:
            return str(
                public_mcp_result(
                    get_update_status().message,
                    project_root=project_access_policy.project_root,
                    expose_host_diagnostics=expose_host_diagnostics,
                )
            )
        except Exception:
            if expose_host_diagnostics:
                raise
            return "Update status unavailable; host details were withheld."
