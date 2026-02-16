from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .introspection import get_asset_yy_path, list_assets_by_type, read_asset_yy
from .utils import find_yyp, load_json_loose, save_pretty_json_gm, strip_trailing_commas


# -----------------------------------------------------------------------------
# Project / YYP helpers
# -----------------------------------------------------------------------------


def load_project_yyp(project_root: Path) -> Tuple[Path, Dict[str, Any]]:
    """Load the project's .yyp file (GameMaker-style JSON tolerated)."""
    yyp_path = find_yyp(Path(project_root))
    yyp_data = load_json_loose(yyp_path)
    if not isinstance(yyp_data, dict):
        raise FileNotFoundError(f"Could not load .yyp data: {yyp_path}")
    return yyp_path, yyp_data


def get_project_configs(yyp_data: Dict[str, Any]) -> List[str]:
    """
    Extract leaf config names from the .yyp `configs` tree.

    Returns leaf names excluding the root "Default".
    """
    root = yyp_data.get("configs")
    if not isinstance(root, dict):
        return []

    results: List[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        name = node.get("name")
        children = node.get("children") or []
        if not children:
            if isinstance(name, str) and name and name != "Default" and name not in seen:
                seen.add(name)
                results.append(name)
            return
        for child in children:
            walk(child)

    walk(root)
    return results


def get_texture_groups_list(yyp_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = yyp_data.get("TextureGroups", None)
    if value is None:
        value = yyp_data.get("textureGroups", None)
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def find_texture_group(
    yyp_data: Dict[str, Any],
    name: str,
    *,
    case_insensitive: bool = True,
) -> Optional[Tuple[int, Dict[str, Any]]]:
    groups = get_texture_groups_list(yyp_data)
    if not isinstance(name, str) or not name:
        return None
    target = name.lower() if case_insensitive else name
    for i, tg in enumerate(groups):
        tg_name = tg.get("name")
        if not isinstance(tg_name, str):
            continue
        cmp = tg_name.lower() if case_insensitive else tg_name
        if cmp == target:
            return i, tg
    return None


# -----------------------------------------------------------------------------
# TextureGroupRef helpers
# -----------------------------------------------------------------------------


def make_group_ref(name: str) -> Dict[str, str]:
    return {"name": name, "path": f"texturegroups/{name}"}


def parse_group_ref(value: Any) -> Optional[Dict[str, Any]]:
    """
    Parse a textureGroupId reference.

    GameMaker stores these as either:
    - dict: {"name":"...", "path":"texturegroups/..."}
    - string: "{ \"name\":\"...\", \"path\":\"texturegroups/...\" }"
    """
    if isinstance(value, dict):
        if isinstance(value.get("name"), str) and isinstance(value.get("path"), str):
            return value
        return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw.startswith("{") or not raw.endswith("}"):
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(strip_trailing_commas(raw))
            except json.JSONDecodeError:
                return None
        if isinstance(parsed, dict) and isinstance(parsed.get("name"), str) and isinstance(parsed.get("path"), str):
            return parsed
        return None

    return None


def serialize_group_ref_for_config(ref: Dict[str, Any]) -> str:
    """
    Serialize a texture group ref as a GameMaker-style string for ConfigValues.*.textureGroupId.

    Must match the common formatting:
      { "name":"X", "path":"texturegroups/X" }
    """
    name = ref.get("name", "")
    path = ref.get("path", "")
    return "{ \"name\":" + json.dumps(name, ensure_ascii=False) + ", \"path\":" + json.dumps(path, ensure_ascii=False) + " }"


# -----------------------------------------------------------------------------
# Asset textureGroupId helpers
# -----------------------------------------------------------------------------


def _asset_supports_texture_groups(asset_yy: Any) -> bool:
    if not isinstance(asset_yy, dict):
        return False
    if "textureGroupId" in asset_yy:
        return True
    cv = asset_yy.get("ConfigValues")
    if isinstance(cv, dict):
        for v in cv.values():
            if isinstance(v, dict) and "textureGroupId" in v:
                return True
    return False


def get_asset_group_assignments(asset_yy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return current group assignments for an asset.

    Returns:
      { "top": str|None, "configs": {config: str|None} }
    """
    top_group: Optional[str] = None
    if isinstance(asset_yy, dict) and "textureGroupId" in asset_yy:
        ref = parse_group_ref(asset_yy.get("textureGroupId"))
        if ref and isinstance(ref.get("name"), str):
            top_group = ref["name"]

    config_groups: Dict[str, Optional[str]] = {}
    cv = asset_yy.get("ConfigValues")
    if isinstance(cv, dict):
        for cfg_name, cfg_dict in cv.items():
            if not isinstance(cfg_name, str):
                continue
            if not isinstance(cfg_dict, dict):
                continue
            if "textureGroupId" not in cfg_dict:
                continue
            ref = parse_group_ref(cfg_dict.get("textureGroupId"))
            config_groups[cfg_name] = ref.get("name") if ref and isinstance(ref.get("name"), str) else None

    return {"top": top_group, "configs": config_groups}


def set_asset_group(
    asset_yy: Dict[str, Any],
    group_name: str,
    *,
    include_top_level: bool,
    configs_to_set: Optional[List[str]],
    update_existing_configs: bool,
) -> Tuple[bool, List[str]]:
    """
    Set asset texture group to `group_name`.

    Top-level update rule:
      - If textureGroupId is a dict: set to {name,path}
      - If textureGroupId is null: leave null and warn
      - If textureGroupId is missing: leave missing and warn

    Config update rule:
      - If configs_to_set provided: ensure ConfigValues[config] dict exists then set textureGroupId string
      - Else if update_existing_configs: for each existing ConfigValues key, set textureGroupId string
    """
    changed = False
    warnings: List[str] = []
    ref_dict = make_group_ref(group_name)
    ref_str = serialize_group_ref_for_config(ref_dict)

    if include_top_level:
        if "textureGroupId" not in asset_yy:
            warnings.append("Asset has no top-level textureGroupId; skipped top-level update")
        else:
            current = asset_yy.get("textureGroupId")
            if current is None:
                warnings.append("Asset top-level textureGroupId is null; left unchanged")
            elif isinstance(current, dict):
                if current.get("name") != ref_dict["name"] or current.get("path") != ref_dict["path"]:
                    asset_yy["textureGroupId"] = ref_dict
                    changed = True
            elif isinstance(current, str):
                # Rare, but try to normalize to dict.
                asset_yy["textureGroupId"] = ref_dict
                changed = True
                warnings.append("Asset top-level textureGroupId was a string; normalized to dict")
            else:
                warnings.append(f"Asset top-level textureGroupId has unexpected type {type(current).__name__}; skipped")

    if configs_to_set:
        cv = asset_yy.get("ConfigValues")
        if cv is None or not isinstance(cv, dict):
            asset_yy["ConfigValues"] = {}
            cv = asset_yy["ConfigValues"]
            changed = True

        for cfg in configs_to_set:
            if not isinstance(cfg, str) or not cfg:
                continue
            sub = cv.get(cfg)
            if sub is None or not isinstance(sub, dict):
                cv[cfg] = {}
                sub = cv[cfg]
                changed = True
            if sub.get("textureGroupId") != ref_str:
                sub["textureGroupId"] = ref_str
                changed = True

    elif update_existing_configs:
        cv = asset_yy.get("ConfigValues")
        if isinstance(cv, dict):
            for cfg_name, cfg_dict in cv.items():
                if not isinstance(cfg_name, str) or not isinstance(cfg_dict, dict):
                    continue
                if cfg_dict.get("textureGroupId") != ref_str:
                    cfg_dict["textureGroupId"] = ref_str
                    changed = True

    return changed, warnings


def _replace_asset_group_references(
    asset_yy: Dict[str, Any],
    *,
    from_group: str,
    to_group: str,
    include_top_level: bool,
    configs_to_consider: Optional[List[str]],
    update_existing_configs: bool,
) -> Tuple[bool, List[str]]:
    """
    Replace references to a texture group name with another.

    Unlike set_asset_group, this only changes references that currently equal from_group.
    """
    changed = False
    warnings: List[str] = []

    to_ref_dict = make_group_ref(to_group)
    to_ref_str = serialize_group_ref_for_config(to_ref_dict)

    if include_top_level and "textureGroupId" in asset_yy:
        current = asset_yy.get("textureGroupId")
        if current is None:
            # Nothing to replace at top-level.
            pass
        else:
            ref = parse_group_ref(current)
            if ref and ref.get("name") == from_group:
                if isinstance(current, dict):
                    asset_yy["textureGroupId"] = to_ref_dict
                    changed = True
                elif isinstance(current, str):
                    asset_yy["textureGroupId"] = to_ref_dict
                    changed = True
                    warnings.append("Asset top-level textureGroupId was a string; normalized to dict")

    cv = asset_yy.get("ConfigValues")
    if isinstance(cv, dict):
        if configs_to_consider:
            cfg_names = [c for c in configs_to_consider if isinstance(c, str) and c]
        elif update_existing_configs:
            cfg_names = [c for c in cv.keys() if isinstance(c, str) and c]
        else:
            cfg_names = []

        for cfg_name in cfg_names:
            cfg_dict = cv.get(cfg_name)
            if not isinstance(cfg_dict, dict):
                continue
            if "textureGroupId" not in cfg_dict:
                continue
            ref = parse_group_ref(cfg_dict.get("textureGroupId"))
            if ref and ref.get("name") == from_group:
                if cfg_dict.get("textureGroupId") != to_ref_str:
                    cfg_dict["textureGroupId"] = to_ref_str
                    changed = True

    return changed, warnings


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
        {tg.get("name") for tg in get_texture_groups_list(yyp_data) if isinstance(tg.get("name"), str)}
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
        return {"ok": False, "dry_run": dry_run, "error": f"Template texture group '{template}' not found", "changed_files": []}

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
    filtered_keys = [k for k in patch.keys() if k not in ("ConfigValues", "$GMTextureGroup", "resourceType", "resourceVersion")]
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
        return {"ok": False, "dry_run": dry_run, "error": f"Texture group '{new_name}' already exists", "changed_files": []}

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
                rel = str(yy_path.relative_to(project_root))
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


def texture_group_delete(
    project_root: Path,
    name: str,
    *,
    reassign_to: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    yyp_path, yyp_data = load_project_yyp(project_root)
    hit = find_texture_group(yyp_data, name)
    if hit is None:
        return {"ok": False, "dry_run": dry_run, "error": f"Texture group '{name}' not found", "changed_files": []}

    # Scan references in assets.
    references: List[Dict[str, Any]] = []
    affected_assets: List[Dict[str, Any]] = []
    for asset in _iter_resource_assets(project_root):
        yy = read_asset_yy(project_root, asset["path"])
        if not isinstance(yy, dict) or not _asset_supports_texture_groups(yy):
            continue
        assignments = get_asset_group_assignments(yy)
        top = assignments["top"]
        cfgs: Dict[str, Optional[str]] = assignments["configs"]
        where: List[str] = []
        if top == name:
            where.append("top")
        for cfg_name, cfg_val in cfgs.items():
            if cfg_val == name:
                where.append(f"ConfigValues.{cfg_name}")
        if where:
            references.append({"name": asset["name"], "type": asset["type"], "path": asset["path"], "where": where})
            affected_assets.append(asset)

    # Scan groupParent references.
    for tg in get_texture_groups_list(yyp_data):
        if not isinstance(tg, dict):
            continue
        if tg.get("groupParent") == name:
            references.append({"kind": "texture_group", "name": tg.get("name"), "where": ["groupParent"]})
        cv = tg.get("ConfigValues")
        if isinstance(cv, dict):
            for cfg_name, cfg_dict in cv.items():
                if isinstance(cfg_dict, dict) and cfg_dict.get("groupParent") == name:
                    references.append({"kind": "texture_group", "name": tg.get("name"), "where": [f"ConfigValues.{cfg_name}.groupParent"]})

    if references and not reassign_to:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": f"Texture group '{name}' is referenced; provide reassign_to to delete safely",
            "changed_files": [],
            "details": {"references_found": references},
        }

    if reassign_to:
        if find_texture_group(yyp_data, reassign_to) is None:
            return {
                "ok": False,
                "dry_run": dry_run,
                "error": f"Reassign target texture group '{reassign_to}' not found",
                "changed_files": [],
            }

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
                rel = str(yy_path.relative_to(project_root))
                changed_files.append(rel)
                if not dry_run:
                    save_pretty_json_gm(yy_path, yy)
            else:
                assets_skipped.append(asset["name"])

    if "TextureGroups" in yyp_data:
        groups_key = "TextureGroups"
    elif "textureGroups" in yyp_data:
        groups_key = "textureGroups"
    else:
        groups_key = "TextureGroups"
    groups = yyp_data.get(groups_key)
    if not isinstance(groups, list):
        return {"ok": False, "dry_run": dry_run, "error": "YYP TextureGroups is not a list", "changed_files": []}

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
        return {"ok": False, "dry_run": dry_run, "error": f"Texture group '{name}' could not be removed", "changed_files": []}

    changed_files.append(str(yyp_path.relative_to(project_root)))
    if not dry_run:
        save_pretty_json_gm(yyp_path, yyp_data)

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
        return {"ok": False, "dry_run": dry_run, "error": f"Texture group '{group_name}' not found", "changed_files": []}

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
            rel = str(yy_path.relative_to(project_root))
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
            rel = str(yy_path.relative_to(project_root))
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
