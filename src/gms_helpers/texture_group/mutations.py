from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..introspection import get_asset_yy_path, read_asset_yy
from ..utils import save_pretty_json_gm
from .project import find_texture_group, get_texture_groups_list, load_project_yyp
from .refs import (
    _asset_supports_texture_groups,
    _replace_asset_group_references,
    get_asset_group_assignments,
    parse_group_ref,
    set_asset_group,
)
from .scan import _iter_resource_assets


# -----------------------------------------------------------------------------
# CRUD operations (with dry-run)
# -----------------------------------------------------------------------------


def texture_group_create(
    project_root: Path,
    name: str,
    *,
    template: str = "Default",
    patch: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    yyp_path, yyp_data = load_project_yyp(project_root)
    if "TextureGroups" in yyp_data:
        groups_key = "TextureGroups"
    elif "textureGroups" in yyp_data:
        groups_key = "textureGroups"
    else:
        groups_key = "TextureGroups"

    groups = yyp_data.get(groups_key)
    if groups is None:
        yyp_data[groups_key] = []
        groups = yyp_data[groups_key]

    if not isinstance(groups, list):
        return {"ok": False, "dry_run": dry_run, "error": "YYP TextureGroups is not a list", "changed_files": []}

    if find_texture_group(yyp_data, name) is not None:
        return {"ok": False, "dry_run": dry_run, "error": f"Texture group '{name}' already exists", "changed_files": []}

    template_hit = find_texture_group(yyp_data, template)
    if template_hit is None:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Template texture group '{template}' not found",
            "changed_files": [],
        }

    _, template_group = template_hit
    new_group = copy.deepcopy(template_group)
    if "%Name" in new_group:
        new_group["%Name"] = name
    new_group["name"] = name

    warnings: List[str] = []
    if patch:
        if not isinstance(patch, dict):
            warnings.append("patch was not a dict; ignored")
        else:
            new_group.update(patch)
            # Ensure name fields remain correct
            if "%Name" in new_group:
                new_group["%Name"] = name
            new_group["name"] = name

    groups.append(new_group)

    changed_files = [str(yyp_path.relative_to(project_root))]
    if not dry_run:
        save_pretty_json_gm(yyp_path, yyp_data)

    return {
        "ok": True,
        "dry_run": dry_run,
        "message": f"Created texture group '{name}'",
        "warnings": warnings,
        "changed_files": changed_files,
        "details": {"template": template},
    }


def _stringify_config_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def texture_group_update(
    project_root: Path,
    name: str,
    *,
    patch: Dict[str, Any],
    configs: Optional[List[str]] = None,
    update_existing_configs: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    yyp_path, yyp_data = load_project_yyp(project_root)
    hit = find_texture_group(yyp_data, name)
    if hit is None:
        return {"ok": False, "dry_run": dry_run, "error": f"Texture group '{name}' not found", "changed_files": []}

    _, tg = hit
    if not isinstance(patch, dict):
        return {"ok": False, "dry_run": dry_run, "error": "patch must be a dict", "changed_files": []}

    warnings: List[str] = []
    # Avoid accidental renames through patch.
    if "name" in patch or "%Name" in patch:
        warnings.append("patch contained name/%Name; ignored (use rename instead)")
        patch = {k: v for k, v in patch.items() if k not in ("name", "%Name")}

    if patch:
        tg.update(patch)

    # ConfigValues updates use string values (GameMaker's convention).
    filtered_keys = [
        k for k in patch.keys() if k not in ("ConfigValues", "$GMTextureGroup", "resourceType", "resourceVersion")
    ]
    if filtered_keys:
        cv = tg.get("ConfigValues")
        if cv is None or not isinstance(cv, dict):
            tg["ConfigValues"] = {}
            cv = tg["ConfigValues"]

        if configs:
            target_cfgs = [c for c in configs if isinstance(c, str) and c]
            for cfg in target_cfgs:
                sub = cv.get(cfg)
                if sub is None or not isinstance(sub, dict):
                    cv[cfg] = {}
                    sub = cv[cfg]
                for key in filtered_keys:
                    sub[key] = _stringify_config_value(patch.get(key))

        elif update_existing_configs:
            for cfg_name, cfg_dict in cv.items():
                if not isinstance(cfg_name, str) or not isinstance(cfg_dict, dict):
                    continue
                for key in filtered_keys:
                    if key in cfg_dict:
                        cfg_dict[key] = _stringify_config_value(patch.get(key))

    changed_files = [str(yyp_path.relative_to(project_root))]
    if not dry_run:
        save_pretty_json_gm(yyp_path, yyp_data)

    return {
        "ok": True,
        "dry_run": dry_run,
        "message": f"Updated texture group '{name}'",
        "warnings": warnings,
        "changed_files": changed_files,
        "details": {"patched_keys": sorted(patch.keys())},
    }


def texture_group_rename(
    project_root: Path,
    old_name: str,
    new_name: str,
    *,
    update_references: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    yyp_path, yyp_data = load_project_yyp(project_root)
    hit = find_texture_group(yyp_data, old_name)
    if hit is None:
        return {"ok": False, "dry_run": dry_run, "error": f"Texture group '{old_name}' not found", "changed_files": []}
    if find_texture_group(yyp_data, new_name) is not None:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Texture group '{new_name}' already exists",
            "changed_files": [],
        }

    _, tg = hit
    if "%Name" in tg:
        tg["%Name"] = new_name
    tg["name"] = new_name

    # Update groupParent references in other texture groups (best-effort).
    for other in get_texture_groups_list(yyp_data):
        if not isinstance(other, dict):
            continue
        if other.get("groupParent") == old_name:
            other["groupParent"] = new_name
        cv = other.get("ConfigValues")
        if isinstance(cv, dict):
            for cfg_dict in cv.values():
                if isinstance(cfg_dict, dict) and cfg_dict.get("groupParent") == old_name:
                    cfg_dict["groupParent"] = new_name

    changed_files: List[str] = [str(yyp_path.relative_to(project_root))]
    warnings: List[str] = []
    assets_changed = 0
    assets_skipped: List[str] = []

    if update_references:
        for asset in _iter_resource_assets(project_root):
            yy_path = get_asset_yy_path(project_root, asset["path"])
            yy = read_asset_yy(project_root, asset["path"])
            if not isinstance(yy, dict) or yy_path is None:
                continue
            if not _asset_supports_texture_groups(yy):
                continue
            changed, warn = _replace_asset_group_references(
                yy,
                from_group=old_name,
                to_group=new_name,
                include_top_level=True,
                configs_to_consider=None,
                update_existing_configs=True,
            )
            if warn:
                warnings.extend([f"{asset['name']}: {w}" for w in warn])
            if changed:
                assets_changed += 1
                rel = yy_path.resolve(strict=False).relative_to(project_root.resolve()).as_posix()
                changed_files.append(rel)
                if not dry_run:
                    save_pretty_json_gm(yy_path, yy)
            else:
                assets_skipped.append(asset["name"])

    if not dry_run:
        save_pretty_json_gm(yyp_path, yyp_data)

    return {
        "ok": True,
        "dry_run": dry_run,
        "message": f"Renamed texture group '{old_name}' -> '{new_name}'",
        "warnings": warnings,
        "changed_files": sorted(set(changed_files)),
        "details": {"assets_changed": assets_changed, "assets_skipped": assets_skipped},
    }


def texture_group_reference_evidence(project_root: Path, name: str) -> Dict[str, Any]:
    """Collect read-only texture-group reference evidence from assets and .yyp."""
    _, yyp_data = load_project_yyp(project_root)
    references: List[Dict[str, Any]] = []
    affected_assets: List[Dict[str, Any]] = []
    for asset in _iter_resource_assets(project_root):
        yy = read_asset_yy(project_root, asset["path"])
        if not isinstance(yy, dict) or not _asset_supports_texture_groups(yy):
            continue
        assignments = get_asset_group_assignments(yy)
        where: List[str] = []
        if assignments["top"] == name:
            where.append("top")
        for cfg_name, cfg_value in assignments["configs"].items():
            if cfg_value == name:
                where.append(f"ConfigValues.{cfg_name}")
        if where:
            references.append({"name": asset["name"], "type": asset["type"], "path": asset["path"], "where": where})
            affected_assets.append(asset)

    for texture_group in get_texture_groups_list(yyp_data):
        if not isinstance(texture_group, dict):
            continue
        if texture_group.get("groupParent") == name:
            references.append({"kind": "texture_group", "name": texture_group.get("name"), "where": ["groupParent"]})
        config_values = texture_group.get("ConfigValues")
        if isinstance(config_values, dict):
            for config_name, config in config_values.items():
                if isinstance(config, dict) and config.get("groupParent") == name:
                    references.append(
                        {
                            "kind": "texture_group",
                            "name": texture_group.get("name"),
                            "where": [f"ConfigValues.{config_name}.groupParent"],
                        }
                    )
    return {"references": references, "affected_assets": affected_assets}


def texture_group_delete_preflight(
    project_root: Path,
    name: str,
    *,
    reassign_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Return read-only evidence and validated reassignment requirements."""
    _, yyp_data = load_project_yyp(project_root)
    groups = yyp_data.get("TextureGroups", yyp_data.get("textureGroups"))
    if not isinstance(groups, list):
        return {
            "ok": False,
            "ready": False,
            "name": name,
            "reassign_to": reassign_to,
            "error": "YYP TextureGroups is not a list",
            "references_found": [],
        }
    hit = find_texture_group(yyp_data, name)
    if hit is None or not 0 <= hit[0] < len(groups):
        return {
            "ok": False,
            "ready": False,
            "name": name,
            "reassign_to": reassign_to,
            "error": f"Texture group '{name}' not found",
            "references_found": [],
        }
    if reassign_to == name:
        return {
            "ok": False,
            "ready": False,
            "name": name,
            "reassign_to": reassign_to,
            "error": "Reassign target must be a different texture group than the deleted group",
            "references_found": [],
        }
    if reassign_to and find_texture_group(yyp_data, reassign_to) is None:
        return {
            "ok": False,
            "ready": False,
            "name": name,
            "reassign_to": reassign_to,
            "error": f"Reassign target texture group '{reassign_to}' not found",
            "references_found": [],
        }

    evidence = texture_group_reference_evidence(project_root, name)
    references = evidence["references"]
    blocked = bool(references) and not reassign_to
    return {
        "ok": not blocked,
        "ready": not blocked,
        "blocked": blocked,
        "name": name,
        "reassign_to": reassign_to,
        "references_found": references,
        "affected_assets": evidence["affected_assets"],
        "resolution_required": "reassign_to" if blocked else None,
    }


def texture_group_delete(
    project_root: Path,
    name: str,
    *,
    reassign_to: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    project_root = Path(project_root).resolve()
    preflight = texture_group_delete_preflight(project_root, name, reassign_to=reassign_to)
    if not preflight["ok"]:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": preflight["error"]
            if "error" in preflight
            else f"Texture group '{name}' is referenced; provide reassign_to to delete safely",
            "changed_files": [],
            "details": preflight,
        }

    if dry_run:
        changed_files = [asset["path"] for asset in preflight["affected_assets"]]
        yyp_path, _ = load_project_yyp(project_root)
        changed_files.append(str(yyp_path.relative_to(project_root)))
        return {
            "ok": True,
            "dry_run": True,
            "message": f"Would delete texture group '{name}'",
            "warnings": [],
            "changed_files": sorted(set(changed_files)),
            "details": {**preflight, "assets_changed": len(preflight["affected_assets"]), "assets_skipped": []},
        }

    # Revalidate directly before the first write so stale Resolve choices do
    # not delete a newly referenced group or assign to a removed target.
    final_preflight = texture_group_delete_preflight(project_root, name, reassign_to=reassign_to)
    if not final_preflight["ok"]:
        return {
            "ok": False,
            "dry_run": False,
            "error": final_preflight.get("error")
            or f"Texture group '{name}' is referenced; provide reassign_to to delete safely",
            "changed_files": [],
            "details": {"preflight": preflight, "revalidation": final_preflight},
        }

    yyp_path, yyp_data = load_project_yyp(project_root)
    references = final_preflight["references_found"]
    affected_assets = final_preflight["affected_assets"]
    if "TextureGroups" in yyp_data:
        groups_key = "TextureGroups"
    elif "textureGroups" in yyp_data:
        groups_key = "textureGroups"
    else:
        groups_key = "TextureGroups"
    groups = yyp_data.get(groups_key)
    if not isinstance(groups, list):
        return {"ok": False, "dry_run": False, "error": "YYP TextureGroups is not a list", "changed_files": []}

    changed_files: List[str] = []
    warnings: List[str] = []
    assets_changed = 0
    assets_skipped: List[str] = []

    if reassign_to:
        for asset in affected_assets:
            yy_path = get_asset_yy_path(project_root, asset["path"])
            yy = read_asset_yy(project_root, asset["path"])
            if not isinstance(yy, dict) or yy_path is None:
                continue
            changed, warn = _replace_asset_group_references(
                yy,
                from_group=name,
                to_group=reassign_to,
                include_top_level=True,
                configs_to_consider=None,
                update_existing_configs=True,
            )
            if warn:
                warnings.extend([f"{asset['name']}: {w}" for w in warn])
            if changed:
                assets_changed += 1
                rel = yy_path.resolve(strict=False).relative_to(project_root.resolve()).as_posix()
                changed_files.append(rel)
                if not dry_run:
                    save_pretty_json_gm(yy_path, yy)
            else:
                assets_skipped.append(asset["name"])

        # groupParent references live in the project file, so they must move
        # with asset assignments before the deleted group is removed.
        for texture_group in get_texture_groups_list(yyp_data):
            if not isinstance(texture_group, dict):
                continue
            if texture_group.get("groupParent") == name:
                texture_group["groupParent"] = reassign_to
            config_values = texture_group.get("ConfigValues")
            if isinstance(config_values, dict):
                for config in config_values.values():
                    if isinstance(config, dict) and config.get("groupParent") == name:
                        config["groupParent"] = reassign_to

    # Remove by index in the actual list stored in the .yyp (not the filtered dict-only list).
    removed = False
    for i in range(len(groups)):
        item = groups[i]
        if isinstance(item, dict) and item.get("name") == name:
            groups.pop(i)
            removed = True
            break
    if not removed:
        # Shouldn't happen if find_texture_group succeeded, but be defensive.
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Texture group '{name}' could not be removed",
            "changed_files": [],
        }

    changed_files.append(str(yyp_path.relative_to(project_root)))
    save_pretty_json_gm(yyp_path, yyp_data)

    final_references = texture_group_reference_evidence(project_root, name)["references"]
    if final_references:
        return {
            "ok": False,
            "dry_run": False,
            "error": f"Texture group deletion validation found {len(final_references)} stale reference(s)",
            "changed_files": sorted(set(changed_files)),
            "details": {
                "preflight": preflight,
                "revalidation": final_preflight,
                "remaining_references": final_references,
            },
        }

    return {
        "ok": True,
        "dry_run": dry_run,
        "message": f"Deleted texture group '{name}'",
        "warnings": warnings,
        "changed_files": sorted(set(changed_files)),
        "details": {
            "assets_changed": assets_changed,
            "assets_skipped": assets_skipped,
            "references_found": references,
            "reassign_to": reassign_to,
            "preflight": preflight,
            "revalidation": final_preflight,
            "final_validation": {
                "references_remaining": 0,
                "group_removed": find_texture_group(yyp_data, name) is None,
            },
        },
    }


def texture_group_assign(
    project_root: Path,
    group_name: str,
    *,
    asset_identifiers: Optional[List[str]] = None,
    asset_type: Optional[str] = None,
    name_contains: Optional[str] = None,
    folder_prefix: Optional[str] = None,
    from_group: Optional[str] = None,
    configs: Optional[List[str]] = None,
    include_top_level: bool = True,
    update_existing_configs: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    _, yyp_data = load_project_yyp(project_root)
    if find_texture_group(yyp_data, group_name) is None:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Texture group '{group_name}' not found",
            "changed_files": [],
        }

    warnings: List[str] = []
    assets_changed = 0
    assets_skipped: List[str] = []
    changed_files: List[str] = []

    # Resolve target assets
    targets: List[Dict[str, Any]] = []
    if asset_identifiers:
        for ident in asset_identifiers:
            if not isinstance(ident, str) or not ident:
                continue
            yy_path = get_asset_yy_path(project_root, ident)
            if yy_path is None:
                assets_skipped.append(ident)
                continue
            rel = yy_path.resolve(strict=False).relative_to(project_root.resolve()).as_posix()
            targets.append({"name": Path(rel).stem, "path": rel, "type": "unknown"})
    else:
        targets = _iter_resource_assets(
            project_root,
            asset_type=asset_type,
            name_contains=name_contains,
            folder_prefix=folder_prefix,
        )

    # Apply from_group filter if requested
    if from_group:
        filtered: List[Dict[str, Any]] = []
        for asset in targets:
            yy = read_asset_yy(project_root, asset["path"])
            if not isinstance(yy, dict):
                continue
            assignments = get_asset_group_assignments(yy)
            top = assignments["top"]
            cfgs: Dict[str, Optional[str]] = assignments["configs"]
            if top == from_group or any(v == from_group for v in cfgs.values() if v):
                filtered.append(asset)
        targets = filtered

    # Apply assignments
    for asset in targets:
        yy_path = get_asset_yy_path(project_root, asset["path"])
        yy = read_asset_yy(project_root, asset["path"])
        if yy_path is None or not isinstance(yy, dict):
            assets_skipped.append(asset.get("name") or asset.get("path") or "unknown")
            continue

        changed, warn = set_asset_group(
            yy,
            group_name,
            include_top_level=include_top_level,
            configs_to_set=configs,
            update_existing_configs=update_existing_configs,
        )
        if warn:
            warnings.extend([f"{asset.get('name', asset['path'])}: {w}" for w in warn])
        if changed:
            assets_changed += 1
            rel = yy_path.resolve(strict=False).relative_to(project_root.resolve()).as_posix()
            changed_files.append(rel)
            if not dry_run:
                save_pretty_json_gm(yy_path, yy)
        else:
            assets_skipped.append(asset.get("name") or asset.get("path") or "unknown")

    return {
        "ok": True,
        "dry_run": dry_run,
        "message": f"Assigned {assets_changed} assets to texture group '{group_name}'",
        "warnings": warnings,
        "changed_files": sorted(set(changed_files)),
        "details": {
            "assets_changed": assets_changed,
            "assets_skipped": assets_skipped,
            "group_name": group_name,
            "from_group": from_group,
            "configs": configs,
            "include_top_level": include_top_level,
            "update_existing_configs": update_existing_configs,
        },
    }
