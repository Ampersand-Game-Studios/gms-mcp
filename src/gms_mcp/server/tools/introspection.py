from __future__ import annotations

from typing import Any, Dict, Optional

from ..mcp_types import Context
from ..project import _resolve_project_directory


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Introspection tools
    # -----------------------------
    @mcp.tool()
    async def gm_list_assets(
        asset_type: Optional[str] = None,
        name_contains: Optional[str] = None,
        folder_prefix: Optional[str] = None,
        include_included_files: bool = True,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List all assets in the project, optionally filtered by type, name, or folder.
        
        Args:
            asset_type: Optional type filter (e.g., 'script', 'object').
            name_contains: Filter assets by name (case-insensitive).
            folder_prefix: Filter assets by their path/folder (case-insensitive).
            include_included_files: Whether to include datafiles (default True).
            project_root: Path to project root.
        
        Supports all GameMaker asset types including extensions and datafiles.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import list_assets_by_type
        
        assets = list_assets_by_type(
            project_directory, 
            asset_type, 
            include_included_files,
            name_contains=name_contains,
            folder_prefix=folder_prefix
        )
        return {
            "project_directory": str(project_directory),
            "assets": assets,
            "count": sum(len(l) for l in assets.values()),
            "types_found": list(assets.keys()),
            "filters": {
                "asset_type": asset_type,
                "name_contains": name_contains,
                "folder_prefix": folder_prefix
            }
        }

    @mcp.tool()
    async def gm_read_asset(
        asset_identifier: str,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Read the .yy JSON data for a given asset by name or path.
        Returns the complete metadata for any asset type.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import read_asset_yy
        
        asset_data = read_asset_yy(project_directory, asset_identifier)
        if not asset_data:
            return {"ok": False, "error": f"Asset '{asset_identifier}' not found"}
            
        return {"ok": True, "asset_data": asset_data}

    @mcp.tool()
    async def gm_search_references(
        pattern: str,
        scope: str = "all",
        is_regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Search for a pattern in project files.
        
        Scopes: 'all', 'gml', 'yy', 'scripts', 'objects', 'extensions', 'datafiles'.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import search_references
        
        results = search_references(
            project_directory,
            pattern,
            scope=scope,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            max_results=max_results
        )
        return {
            "pattern": pattern,
            "scope": scope,
            "results": results,
            "count": len(results)
        }

    @mcp.tool()
    async def gm_get_asset_graph(
        deep: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Build a dependency graph of assets.
        
        Args:
            deep: If True, parse all GML code for references (slower but complete).
                  If False, only parse .yy structural references (fast).
        
        Returns nodes (assets) and edges (relationships like parent, sprite, code_reference).
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import build_asset_graph
        
        graph = build_asset_graph(project_directory, deep=deep)
        return graph

    @mcp.tool()
    async def gm_get_project_stats(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Get quick statistics about a project (asset counts by type).
        Faster than building a full index.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import get_project_stats
        
        return get_project_stats(project_directory)
