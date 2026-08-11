from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceNotFoundError

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

    @mcp.resource(
        "gms://project/assets/{asset_type}/{asset_name}",
        name="gm_asset_resource",
        description="Read one GameMaker asset's project metadata by exact type and name.",
        mime_type="application/json",
    )
    def gm_asset_resource(asset_type: str, asset_name: str) -> str:
        """Return one exact asset entry and its .yy metadata when applicable."""
        project_directory = project_access_policy.authorize(".")
        from gms_helpers.introspection import list_assets_by_type, read_asset_yy

        assets = list_assets_by_type(
            project_directory,
            asset_type_filter=asset_type,
            include_included_files=True,
        ).get(asset_type, [])
        asset = next((item for item in assets if item.get("name") == asset_name), None)
        if asset is None:
            raise ResourceNotFoundError(f"Asset '{asset_name}' of type '{asset_type}' was not found")

        metadata = read_asset_yy(project_directory, str(asset.get("path") or asset_name))
        if metadata is None and asset_type != "includedfile":
            raise ResourceNotFoundError(f"Metadata for asset '{asset_name}' of type '{asset_type}' was not found")

        payload = {"ok": True, "asset": asset, "metadata": metadata}
        return json.dumps(
            public_mcp_result(
                payload,
                project_root=project_directory,
                expose_host_diagnostics=expose_host_diagnostics,
            ),
            indent=2,
        )

    @mcp.resource(
        "gms://project/rooms/{room_name}",
        name="gm_room_resource",
        description="Read one GameMaker room's .yy metadata by exact room name.",
        mime_type="application/json",
    )
    def gm_room_resource(room_name: str) -> str:
        """Return one exact room's .yy metadata."""
        project_directory = project_access_policy.authorize(".")
        from gms_helpers.introspection import list_assets_by_type, read_asset_yy

        rooms = list_assets_by_type(project_directory, asset_type_filter="room").get("room", [])
        room = next((item for item in rooms if item.get("name") == room_name), None)
        if room is None:
            raise ResourceNotFoundError(f"Room '{room_name}' was not found")

        metadata = read_asset_yy(project_directory, str(room.get("path") or room_name))
        if metadata is None:
            raise ResourceNotFoundError(f"Metadata for room '{room_name}' was not found")

        payload = {"ok": True, "room": room, "metadata": metadata}
        return json.dumps(
            public_mcp_result(
                payload,
                project_root=project_directory,
                expose_host_diagnostics=expose_host_diagnostics,
            ),
            indent=2,
        )
