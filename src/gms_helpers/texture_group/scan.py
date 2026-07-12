from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..introspection import list_assets_by_type, read_asset_yy
from .project import get_texture_groups_list, load_project_yyp
from .refs import _asset_supports_texture_groups, get_asset_group_assignments


# -----------------------------------------------------------------------------
# Membership scanning
# -----------------------------------------------------------------------------


def _iter_resource_assets(
    project_root: Path,
    *,
    asset_type: Optional[str] = None,
    asset_types: Optional[List[str]] = None,
    name_contains: Optional[str] = None,
    folder_prefix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    assets_by_type = list_assets_by_type(
        project_root,
        asset_type_filter=asset_type,
        include_included_files=False,
        name_contains=name_contains,
        folder_prefix=folder_prefix,
    )
    results: List[Dict[str, Any]] = []
    if not isinstance(assets_by_type, dict):
        return results
    allowed: Optional[set[str]] = None
    if asset_types:
        allowed = {t for t in asset_types if isinstance(t, str) and t}
    for typ, items in assets_by_type.items():
        if allowed is not None and typ not in allowed:
            continue
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("name"), str) and isinstance(it.get("path"), str):
                results.append(it)
    return results


def texture_group_members(
    project_root: Path,
    group_name: str,
    *,
    asset_types: Optional[List[str]] = None,
    configs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    _, yyp_data = load_project_yyp(project_root)
    defined = {tg.get("name") for tg in get_texture_groups_list(yyp_data) if isinstance(tg.get("name"), str)}
    warnings: List[str] = []
    if group_name not in defined:
        warnings.append(f"Texture group '{group_name}' is not defined in the .yyp (references may still exist)")

    members: List[Dict[str, Any]] = []
    by_asset_type: Dict[str, int] = {}
    by_config: Dict[str, int] = {}

    for asset in _iter_resource_assets(project_root, asset_types=asset_types):
        yy = read_asset_yy(project_root, asset["path"])
        if not isinstance(yy, dict) or not _asset_supports_texture_groups(yy):
            continue
        assignments = get_asset_group_assignments(yy)
        top = assignments["top"]
        cfgs: Dict[str, Optional[str]] = assignments["configs"]

        hit = (top == group_name) or any(v == group_name for v in cfgs.values() if v)
        if not hit:
            continue

        if configs is None:
            config_groups = {k: v for k, v in cfgs.items() if v is not None}
        else:
            config_groups = {cfg: cfgs.get(cfg) for cfg in configs if isinstance(cfg, str) and cfg}

        members.append(
            {
                "name": asset["name"],
                "type": asset["type"],
                "path": asset["path"],
                "top_level_group": top,
                "config_groups": config_groups,
            }
        )

        by_asset_type[asset["type"]] = by_asset_type.get(asset["type"], 0) + 1
        for cfg_name, cfg_val in config_groups.items():
            if cfg_val == group_name:
                by_config[cfg_name] = by_config.get(cfg_name, 0) + 1

    return {
        "ok": True,
        "group_name": group_name,
        "members": members,
        "count": len(members),
        "by_asset_type": by_asset_type,
        "by_config": by_config,
        "warnings": warnings,
    }


def texture_group_scan(
    project_root: Path,
    *,
    asset_types: Optional[List[str]] = None,
    configs: Optional[List[str]] = None,
    include_assets: bool = False,
) -> Dict[str, Any]:
    _, yyp_data = load_project_yyp(project_root)
    groups_defined = sorted(
        tg_name for tg in get_texture_groups_list(yyp_data) if isinstance((tg_name := tg.get("name")), str)
    )

    referenced: set[str] = set()
    missing: Dict[str, List[Dict[str, Any]]] = {}
    mismatched: List[Dict[str, Any]] = []
    assets_rows: List[Dict[str, Any]] = []

    for asset in _iter_resource_assets(project_root, asset_types=asset_types):
        yy = read_asset_yy(project_root, asset["path"])
        if not isinstance(yy, dict) or not _asset_supports_texture_groups(yy):
            continue
        assignments = get_asset_group_assignments(yy)
        top = assignments["top"]
        cfgs: Dict[str, Optional[str]] = assignments["configs"]

        # Optionally restrict which configs we consider for scan reporting.
        cfgs_considered: Dict[str, Optional[str]]
        if configs is None:
            cfgs_considered = cfgs
        else:
            cfgs_considered = {cfg: cfgs.get(cfg) for cfg in configs if isinstance(cfg, str) and cfg}

        if top:
            referenced.add(top)
            if top not in groups_defined:
                missing.setdefault(top, []).append(
                    {"name": asset["name"], "type": asset["type"], "path": asset["path"], "where": "top"}
                )

        for cfg_name, cfg_val in cfgs_considered.items():
            if not cfg_val:
                continue
            referenced.add(cfg_val)
            if cfg_val not in groups_defined:
                missing.setdefault(cfg_val, []).append(
                    {
                        "name": asset["name"],
                        "type": asset["type"],
                        "path": asset["path"],
                        "where": f"ConfigValues.{cfg_name}",
                    }
                )

        # Mismatch: config override differs from top-level (when top-level exists).
        if top and any((v is not None and v != top) for v in cfgs_considered.values()):
            mismatched.append(
                {
                    "name": asset["name"],
                    "type": asset["type"],
                    "path": asset["path"],
                    "top_level_group": top,
                    "config_groups": {k: v for k, v in cfgs_considered.items() if v is not None},
                }
            )

        if include_assets:
            assets_rows.append(
                {
                    "name": asset["name"],
                    "type": asset["type"],
                    "path": asset["path"],
                    "top_level_group": top,
                    "config_groups": {k: v for k, v in cfgs_considered.items() if v is not None},
                }
            )

    return {
        "ok": True,
        "groups_defined": groups_defined,
        "groups_referenced": sorted(referenced),
        "missing_groups_referenced": missing,
        "mismatched_assets": mismatched,
        "assets": assets_rows if include_assets else None,
    }
