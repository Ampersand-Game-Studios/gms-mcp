from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dry_run_policy import _dry_run_policy_blocked_result, _requires_dry_run_for_tool
from ..mcp_types import Context
from ..project import _resolve_project_directory


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Texture group tools
    # -----------------------------

    @mcp.tool()
    async def gm_texture_group_list(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List texture groups and available configs."""
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import get_project_configs, get_texture_groups_list, load_project_yyp

        yyp_path, yyp_data = load_project_yyp(project_directory)
        configs = get_project_configs(yyp_data)
        groups = get_texture_groups_list(yyp_data)
        return {
            "ok": True,
            "project_directory": str(project_directory),
            "yyp": yyp_path.name,
            "configs": configs,
            "texture_groups": groups,
            "count": len(groups),
        }

    @mcp.tool()
    async def gm_texture_group_read(
        name: str,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Read a texture group entry from the .yyp."""
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import find_texture_group, load_project_yyp

        yyp_path, yyp_data = load_project_yyp(project_directory)
        hit = find_texture_group(yyp_data, name)
        if hit is None:
            return {
                "ok": False,
                "project_directory": str(project_directory),
                "yyp": yyp_path.name,
                "error": f"Texture group '{name}' not found",
            }
        _, tg = hit
        return {
            "ok": True,
            "project_directory": str(project_directory),
            "yyp": yyp_path.name,
            "texture_group": tg,
        }

    @mcp.tool()
    async def gm_texture_group_members(
        group_name: str,
        asset_types: Optional[List[str]] = None,
        configs: Optional[List[str]] = None,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List members of a texture group (top-level and ConfigValues overrides)."""
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import load_project_yyp, texture_group_members

        yyp_path, _ = load_project_yyp(project_directory)
        result = texture_group_members(project_directory, group_name, asset_types=asset_types, configs=configs)
        result.setdefault("project_directory", str(project_directory))
        result.setdefault("yyp", yyp_path.name)
        return result

    @mcp.tool()
    async def gm_texture_group_scan(
        asset_types: Optional[List[str]] = None,
        configs: Optional[List[str]] = None,
        include_assets: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Scan a project for texture group health issues (missing groups, mismatches)."""
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import load_project_yyp, texture_group_scan

        yyp_path, _ = load_project_yyp(project_directory)
        result = texture_group_scan(
            project_directory,
            asset_types=asset_types,
            configs=configs,
            include_assets=include_assets,
        )
        result.setdefault("project_directory", str(project_directory))
        result.setdefault("yyp", yyp_path.name)
        return result

    # -----------------------------
    # Destructive tools (dry-run aware)
    # -----------------------------

    @mcp.tool()
    async def gm_texture_group_create(
        name: str,
        template: str = "Default",
        patch: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a new texture group by cloning an existing template group."""
        _ = ctx
        if not dry_run and _requires_dry_run_for_tool("gm_texture_group_create"):
            return _dry_run_policy_blocked_result(
                "gm_texture_group_create",
                "Use dry_run=true, add gm_texture_group_create to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import load_project_yyp, texture_group_create

        yyp_path, _ = load_project_yyp(project_directory)
        result = texture_group_create(project_directory, name, template=template, patch=patch, dry_run=dry_run)
        result.setdefault("project_directory", str(project_directory))
        result.setdefault("yyp", yyp_path.name)
        return result

    @mcp.tool()
    async def gm_texture_group_update(
        name: str,
        patch: Dict[str, Any],
        configs: Optional[List[str]] = None,
        update_existing_configs: bool = True,
        dry_run: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Update an existing texture group entry."""
        _ = ctx
        if not dry_run and _requires_dry_run_for_tool("gm_texture_group_update"):
            return _dry_run_policy_blocked_result(
                "gm_texture_group_update",
                "Use dry_run=true, add gm_texture_group_update to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import load_project_yyp, texture_group_update

        yyp_path, _ = load_project_yyp(project_directory)
        result = texture_group_update(
            project_directory,
            name,
            patch=patch,
            configs=configs,
            update_existing_configs=update_existing_configs,
            dry_run=dry_run,
        )
        result.setdefault("project_directory", str(project_directory))
        result.setdefault("yyp", yyp_path.name)
        return result

    @mcp.tool()
    async def gm_texture_group_rename(
        old_name: str,
        new_name: str,
        update_references: bool = True,
        dry_run: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Rename a texture group and (optionally) rewrite asset references."""
        _ = ctx
        if not dry_run and _requires_dry_run_for_tool("gm_texture_group_rename"):
            return _dry_run_policy_blocked_result(
                "gm_texture_group_rename",
                "Use dry_run=true, add gm_texture_group_rename to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import load_project_yyp, texture_group_rename

        yyp_path, _ = load_project_yyp(project_directory)
        result = texture_group_rename(
            project_directory,
            old_name,
            new_name,
            update_references=update_references,
            dry_run=dry_run,
        )
        result.setdefault("project_directory", str(project_directory))
        result.setdefault("yyp", yyp_path.name)
        return result

    @mcp.tool()
    async def gm_texture_group_delete(
        name: str,
        reassign_to: Optional[str] = None,
        dry_run: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Delete a texture group (blocks by default if referenced unless reassign_to is provided)."""
        _ = ctx
        if not dry_run and _requires_dry_run_for_tool("gm_texture_group_delete"):
            return _dry_run_policy_blocked_result(
                "gm_texture_group_delete",
                "Use dry_run=true, add gm_texture_group_delete to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import load_project_yyp, texture_group_delete

        yyp_path, _ = load_project_yyp(project_directory)
        result = texture_group_delete(project_directory, name, reassign_to=reassign_to, dry_run=dry_run)
        result.setdefault("project_directory", str(project_directory))
        result.setdefault("yyp", yyp_path.name)
        return result

    @mcp.tool()
    async def gm_texture_group_assign(
        group_name: str,
        asset_identifiers: Optional[List[str]] = None,
        asset_type: Optional[str] = None,
        name_contains: Optional[str] = None,
        folder_prefix: Optional[str] = None,
        from_group: Optional[str] = None,
        configs: Optional[List[str]] = None,
        include_top_level: bool = True,
        update_existing_configs: bool = True,
        dry_run: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Assign assets to a texture group."""
        _ = ctx
        if not dry_run and _requires_dry_run_for_tool("gm_texture_group_assign"):
            return _dry_run_policy_blocked_result(
                "gm_texture_group_assign",
                "Use dry_run=true, add gm_texture_group_assign to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.texture_groups import load_project_yyp, texture_group_assign

        yyp_path, _ = load_project_yyp(project_directory)
        result = texture_group_assign(
            project_directory,
            group_name,
            asset_identifiers=asset_identifiers,
            asset_type=asset_type,
            name_contains=name_contains,
            folder_prefix=folder_prefix,
            from_group=from_group,
            configs=configs,
            include_top_level=include_top_level,
            update_existing_configs=update_existing_configs,
            dry_run=dry_run,
        )
        result.setdefault("project_directory", str(project_directory))
        result.setdefault("yyp", yyp_path.name)
        return result

