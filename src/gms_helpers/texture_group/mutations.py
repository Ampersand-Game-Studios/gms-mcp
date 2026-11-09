from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..introspection import get_asset_yy_path, read_asset_yy
from ..utils import save_pretty_json_gm
from .project import find_texture_group, get_project_configs, get_texture_groups_list, load_project_yyp
from .refs import (
    _asset_supports_texture_groups,
    _replace_asset_group_references,
    get_asset_group_assignments,
    make_group_ref,
    parse_group_ref,
    serialize_group_ref_for_config,
    set_asset_group,
)

# Texture-group settings a caller may patch. Identity/schema keys (name, %Name,
# resourceType, resourceVersion, $GMTextureGroup) and ConfigValues (use the
# configs argument) are never patchable.
PATCHABLE_GROUP_FIELDS = frozenset(
    {
        "autocrop",
        "border",
        "compressFormat",
        "customOptions",
        "directory",
        "groupParent",
        "isScaled",
        "loadType",
        "mipsToGenerate",
        "targets",
    }
)


def _reject_unknown_patch_keys(patch: Dict[str, Any]) -> Optional[str]:
    unknown = sorted(str(key) for key in patch if key not in PATCHABLE_GROUP_FIELDS)
    if unknown:
        return f"Unsupported texture group field(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(PATCHABLE_GROUP_FIELDS))}"
    return None


def _normalize_group_parent(yyp_data: Dict[str, Any], patch: Dict[str, Any]) -> Optional[str]:
    """Store groupParent as GameMaker does ({name,path} or null) and require an existing group."""
    if "groupParent" not in patch or patch["groupParent"] is None:
        return None
    parent_name = _group_parent_name(patch["groupParent"])
    hit = find_texture_group(yyp_data, parent_name) if parent_name else None
    if hit is None:
        return f"groupParent texture group '{parent_name or patch['groupParent']}' not found"
    patch["groupParent"] = make_group_ref(hit[1]["name"])
    return None


def _unknown_configs(yyp_data: Dict[str, Any], configs: Optional[List[str]]) -> List[str]:
    if not configs:
        return []
    known = set(get_project_configs(yyp_data))
    return sorted({c for c in configs if c not in known})


def _is_default_group(name: str) -> bool:
    return isinstance(name, str) and name.casefold() == "default"


def _group_parent_name(value: Any) -> Optional[str]:
    """Return the group name a groupParent value points at ({name,path}, its string form, or a bare name)."""
    ref = parse_group_ref(value)
    if ref is not None:
        return ref["name"]
    if isinstance(value, str) and value and not value.strip().startswith("{"):
        return value
    return None


def _retarget_group_parent(value: Any, new_name: str) -> Any:
    """Point a groupParent value at ``new_name`` while keeping its stored shape."""
    if isinstance(value, dict):
        return make_group_ref(new_name)
    if isinstance(value, str) and parse_group_ref(value) is not None:
        return serialize_group_ref_for_config(make_group_ref(new_name))
    return new_name


def _retarget_group_parents(yyp_data: Dict[str, Any], old_name: str, new_name: str) -> None:
    for group in get_texture_groups_list(yyp_data):
        if _group_parent_name(group.get("groupParent")) == old_name:
            group["groupParent"] = _retarget_group_parent(group.get("groupParent"), new_name)
        config_values = group.get("ConfigValues")
        if isinstance(config_values, dict):
            for config in config_values.values():
                if isinstance(config, dict) and _group_parent_name(config.get("groupParent")) == old_name:
                    config["groupParent"] = _retarget_group_parent(config.get("groupParent"), new_name)


def _logical_folder_key(value: str) -> str:
    """Normalise a logical folder path to ``folders/a/b`` (casefolded, no .yy suffix)."""
    text = value.replace("\\", "/").strip().strip("/")
    if text.casefold().endswith(".yy"):
        text = text[:-3]
    if not text.casefold().startswith("folders/") and text.casefold() != "folders":
        text = f"folders/{text}"
    return text.casefold()


def _in_logical_folder(asset_yy: Dict[str, Any], folder_prefix: str) -> bool:
    parent = asset_yy.get("parent")
    parent_path = parent.get("path") if isinstance(parent, dict) else None
    if not isinstance(parent_path, str) or not parent_path.replace("\\", "/").startswith("folders/"):
        return False
    parent_key = _logical_folder_key(parent_path)
    prefix_key = _logical_folder_key(folder_prefix)
    return parent_key == prefix_key or parent_key.startswith(prefix_key + "/")


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

    if patch is not None and not isinstance(patch, dict):
        return {"ok": False, "dry_run": dry_run, "error": "patch must be a dict", "changed_files": []}
    patch = dict(patch or {})
    patch_error = _reject_unknown_patch_keys(patch) or _normalize_group_parent(yyp_data, patch)
    if patch_error:
        return {"ok": False, "dry_run": dry_run, "error": patch_error, "changed_files": []}

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
        new_group.update(patch)

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
    if isinstance(value, dict) and parse_group_ref(value) is not None:
        return serialize_group_ref_for_config(value)
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
    patch = dict(patch)
    patch_error = _reject_unknown_patch_keys(patch)
    if patch_error and ("name" in patch or "%Name" in patch):
        patch_error += " (use rename to change the name)"
    patch_error = patch_error or _normalize_group_parent(yyp_data, patch)
    if patch_error:
        return {"ok": False, "dry_run": dry_run, "error": patch_error, "changed_files": []}
    unknown_configs = _unknown_configs(yyp_data, configs)
    if unknown_configs:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Unknown project config(s): {', '.join(unknown_configs)}",
            "changed_files": [],
        }

    warnings: List[str] = []
    if patch:
        tg.update(patch)

    # ConfigValues updates use string values (GameMaker's convention).
    filtered_keys = list(patch.keys())
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
    _, tg = hit
    # References store the exact registered spelling; match on that, not the argument.
    old_name = tg["name"]
    if _is_default_group(old_name):
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": "The Default texture group cannot be renamed; GameMaker requires it",
            "changed_files": [],
        }
    clash = find_texture_group(yyp_data, new_name)
    if clash is not None and clash[1] is not tg:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Texture group '{new_name}' already exists",
            "changed_files": [],
        }

    if "%Name" in tg:
        tg["%Name"] = new_name
    tg["name"] = new_name

    _retarget_group_parents(yyp_data, old_name, new_name)

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
        if _group_parent_name(texture_group.get("groupParent")) == name:
            references.append({"kind": "texture_group", "name": texture_group.get("name"), "where": ["groupParent"]})
        config_values = texture_group.get("ConfigValues")
        if isinstance(config_values, dict):
            for config_name, config in config_values.items():
                if isinstance(config, dict) and _group_parent_name(config.get("groupParent")) == name:
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
    # Work with the registered spellings; references store them exactly.
    name = hit[1]["name"]
    if _is_default_group(name):
        return {
            "ok": False,
            "ready": False,
            "name": name,
            "reassign_to": reassign_to,
            "error": "The Default texture group cannot be deleted; GameMaker requires it",
            "references_found": [],
        }
    reassign_hit = find_texture_group(yyp_data, reassign_to) if reassign_to else None
    if reassign_hit is not None:
        reassign_to = reassign_hit[1]["name"]
    if reassign_to == name:
        return {
            "ok": False,
            "ready": False,
            "name": name,
            "reassign_to": reassign_to,
            "error": "Reassign target must be a different texture group than the deleted group",
            "references_found": [],
        }
    if reassign_to and reassign_hit is None:
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

    name = preflight["name"]
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
    name = final_preflight["name"]
    reassign_to = final_preflight["reassign_to"]
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
        _retarget_group_parents(yyp_data, name, reassign_to)

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
    group_hit = find_texture_group(yyp_data, group_name)
    if group_hit is None:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Texture group '{group_name}' not found",
            "changed_files": [],
        }
    group_name = group_hit[1]["name"]
    unknown_configs = _unknown_configs(yyp_data, configs)
    if unknown_configs:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Unknown project config(s): {', '.join(unknown_configs)}",
            "changed_files": [],
        }
    if from_group:
        from_hit = find_texture_group(yyp_data, from_group)
        if from_hit is not None:
            from_group = from_hit[1]["name"]

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
        targets = _iter_resource_assets(project_root, asset_type=asset_type, name_contains=name_contains)
        if folder_prefix:
            # Match the asset's logical IDE folder (parent.path), not a substring of its file path.
            targets = [
                asset
                for asset in targets
                if isinstance(yy := read_asset_yy(project_root, asset["path"]), dict)
                and _in_logical_folder(yy, folder_prefix)
            ]

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
        if not _asset_supports_texture_groups(yy):
            # Only assets that carry a textureGroupId (sprites, fonts, tilesets) can be assigned.
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
