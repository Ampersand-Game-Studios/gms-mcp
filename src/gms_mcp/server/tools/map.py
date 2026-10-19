"""MCP tools for GameMaker room tilemaps."""

from __future__ import annotations

from typing import Any, Dict

from ..dry_run_policy import _dry_run_policy_blocked_result, _requires_dry_run_for_tool
from ..mcp_types import Context
from ..project import _resolve_project_directory


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    def _fail(exc: Exception) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": str(exc),
            "issues": [{"code": type(exc).__name__, "message": str(exc)}],
            "data": None,
        }

    @mcp.tool()
    def gm_room_tilemap_query(
        room_name: str,
        layer_name: str = "",
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
        index: int | None = None,
        index_min: int | None = None,
        index_max: int | None = None,
        include_cells: bool = True,
        include_clusters: bool = True,
        include_empty: bool = False,
        max_cells: int = 4096,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Decode a room tilemap and return cells, histogram, and connected clusters.

        Coordinates are cell units. Leave layer_name empty to query every tile layer.
        index/index_min/index_max omitted means unset. width/height 0 means the full layer.
        max_cells caps cells and cluster summaries across all selected layers;
        truncated/clusters_truncated flag omitted details. Counts remain complete.
        Queries exceeding cell, layer or histogram budgets return a validation error.
        """
        _ = ctx
        from gms_helpers.exceptions import GMSError
        from gms_helpers.tilemap_ops import query_tilemap

        try:
            project_directory = _resolve_project_directory(project_root)
            return query_tilemap(
                room_name,
                layer_name=layer_name,
                x=x,
                y=y,
                width=width,
                height=height,
                index=index,
                index_min=index_min,
                index_max=index_max,
                include_cells=include_cells,
                include_clusters=include_clusters,
                include_empty=include_empty,
                max_cells=max_cells,
                project_root=project_directory,
            )
        except GMSError as exc:
            return _fail(exc)
        except Exception as exc:
            return _fail(exc)

    @mcp.tool()
    def gm_room_tilemap_patch(
        room_name: str,
        layer_name: str,
        op: str,
        x: int = 0,
        y: int = 0,
        width: int = 1,
        height: int = 1,
        tile: int = 0,
        from_index: int | None = None,
        to_tile: int | None = None,
        stamp_json: str = "",
        cells_json: str = "",
        use_raw: bool = False,
        dry_run: bool = True,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Patch a tile layer with set/fill/replace/clear/stamp.

        Defaults to dry_run=true. Writes backup the room file and roll back if the
        compressed stream does not round-trip.
        """
        _ = ctx
        from gms_helpers.exceptions import GMSError
        from gms_helpers.tilemap_ops import patch_tilemap

        if not dry_run and _requires_dry_run_for_tool("gm_room_tilemap_patch"):
            return _dry_run_policy_blocked_result(
                "gm_room_tilemap_patch",
                "Use dry_run=true, add gm_room_tilemap_patch to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN.",
            )
        try:
            project_directory = _resolve_project_directory(project_root)
            return patch_tilemap(
                room_name,
                layer_name,
                op,
                x=x,
                y=y,
                width=width,
                height=height,
                tile=tile,
                from_index=from_index,
                to_tile=to_tile,
                stamp_json=stamp_json,
                cells_json=cells_json,
                use_raw=use_raw,
                dry_run=dry_run,
                project_root=project_directory,
            )
        except GMSError as exc:
            return _fail(exc)
        except Exception as exc:
            return _fail(exc)

    @mcp.tool()
    def gm_room_map_validate(
        room_name: str = "",
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Validate compressed tile streams, layer sizes, tileset paths, and out-of-range indices."""
        _ = ctx
        from gms_helpers.exceptions import GMSError
        from gms_helpers.tilemap_ops import validate_maps

        try:
            project_directory = _resolve_project_directory(project_root)
            return validate_maps(room_name=room_name, project_root=project_directory)
        except GMSError as exc:
            return _fail(exc)
        except Exception as exc:
            return _fail(exc)
