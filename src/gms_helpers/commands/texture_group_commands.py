"""Texture group command implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..results import OperationResult
from ..texture_groups import (
    find_texture_group,
    get_project_configs,
    get_texture_groups_list,
    load_project_yyp,
    texture_group_assign,
    texture_group_create,
    texture_group_delete,
    texture_group_members,
    texture_group_rename,
    texture_group_scan,
    texture_group_update,
)


def _parse_csv(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]


def _parse_set_kv(pairs: Optional[List[str]]) -> Dict[str, Any]:
    """Parse repeated --set key=value items into a patch dict with basic typing."""
    patch: Dict[str, Any] = {}
    if not pairs:
        return patch
    for item in pairs:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, raw = item.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        low = raw.lower()
        if low in ("true", "false"):
            patch[key] = low == "true"
            continue
        if low in ("null", "none"):
            patch[key] = None
            continue
        try:
            patch[key] = int(raw)
            continue
        except ValueError:
            pass
        try:
            patch[key] = float(raw)
            continue
        except ValueError:
            pass
        patch[key] = raw
    return patch


def handle_texture_groups_list(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    yyp_path, yyp_data = load_project_yyp(project_root)
    configs = get_project_configs(yyp_data)
    groups = get_texture_groups_list(yyp_data)
    print(f"[OK] {yyp_path.name}")
    if configs:
        print(f"Configs: {', '.join(configs)}")
    print(f"Texture groups ({len(groups)}):")
    for tg in groups:
        name = tg.get("name", "?")
        load_type = tg.get("loadType")
        compress = tg.get("compressFormat")
        autocrop = tg.get("autocrop")
        border = tg.get("border")
        extra = []
        if load_type is not None:
            extra.append(f"loadType={load_type}")
        if compress is not None:
            extra.append(f"compressFormat={compress}")
        if autocrop is not None:
            extra.append(f"autocrop={autocrop}")
        if border is not None:
            extra.append(f"border={border}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        print(f"- {name}{suffix}")
    return OperationResult(success=True, message="Listed texture groups")


def handle_texture_groups_show(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    name = getattr(args, "name", "")
    yyp_path, yyp_data = load_project_yyp(project_root)
    hit = find_texture_group(yyp_data, name)
    if hit is None:
        print(f"[ERROR] Texture group '{name}' not found in {yyp_path.name}")
        return OperationResult(success=False, message="Not found")
    _, tg = hit
    print(f"[OK] Texture group: {name}")
    for k in sorted(tg.keys()):
        print(f"{k}: {tg.get(k)}")
    return OperationResult(success=True, message="Shown texture group")


def handle_texture_groups_members(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    group = getattr(args, "group", "")
    types = _parse_csv(getattr(args, "types", None))
    configs = _parse_csv(getattr(args, "configs", None))
    result = texture_group_members(project_root, group, asset_types=types, configs=configs)
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Failed')}")
        return OperationResult(success=False, message="Failed")
    for w in result.get("warnings", []) or []:
        print(f"[WARN]  {w}")
    print(f"[OK] Members of '{group}': {result.get('count', 0)}")
    for m in result.get("members", []) or []:
        print(f"- {m.get('type')} {m.get('name')} ({m.get('path')}) top={m.get('top_level_group')} cfg={m.get('config_groups')}")
    return OperationResult(success=True, message="Listed texture group members")


def handle_texture_groups_scan(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    types = _parse_csv(getattr(args, "types", None))
    configs = _parse_csv(getattr(args, "configs", None))
    include_assets = bool(getattr(args, "include_assets", False))
    result = texture_group_scan(project_root, asset_types=types, configs=configs, include_assets=include_assets)
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Failed')}")
        return OperationResult(success=False, message="Failed")
    print(f"Groups defined: {len(result.get('groups_defined') or [])}")
    print(f"Groups referenced: {len(result.get('groups_referenced') or [])}")
    missing = result.get("missing_groups_referenced") or {}
    mismatched = result.get("mismatched_assets") or []
    print(f"Missing groups referenced: {len(missing)}")
    for g, refs in missing.items():
        print(f"- {g}: {len(refs)}")
    print(f"Mismatched assets: {len(mismatched)}")
    return OperationResult(success=True, message="Scanned texture groups")


def handle_texture_groups_create(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    name = getattr(args, "name", "")
    template = getattr(args, "template", "Default")
    patch = _parse_set_kv(getattr(args, "set", None))
    dry_run = bool(getattr(args, "dry_run", False))
    result = texture_group_create(project_root, name, template=template, patch=patch or None, dry_run=dry_run)
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Failed')}")
        return OperationResult(success=False, message="Failed")
    for w in result.get("warnings", []) or []:
        print(f"[WARN]  {w}")
    print(f"[OK] {result.get('message')}")
    if dry_run:
        print(f"[DRY] Would change: {result.get('changed_files')}")
    return OperationResult(success=True, message=result.get("message", "Created"))


def handle_texture_groups_update(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    name = getattr(args, "name", "")
    patch = _parse_set_kv(getattr(args, "set", None))
    configs = _parse_csv(getattr(args, "configs", None))
    update_existing_configs = bool(getattr(args, "update_existing_configs", True))
    dry_run = bool(getattr(args, "dry_run", False))
    result = texture_group_update(
        project_root,
        name,
        patch=patch,
        configs=configs,
        update_existing_configs=update_existing_configs,
        dry_run=dry_run,
    )
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Failed')}")
        return OperationResult(success=False, message="Failed")
    for w in result.get("warnings", []) or []:
        print(f"[WARN]  {w}")
    print(f"[OK] {result.get('message')}")
    if dry_run:
        print(f"[DRY] Would change: {result.get('changed_files')}")
    return OperationResult(success=True, message=result.get("message", "Updated"))


def handle_texture_groups_rename(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    old = getattr(args, "old_name", "")
    new = getattr(args, "new_name", "")
    update_references = bool(getattr(args, "update_references", True))
    dry_run = bool(getattr(args, "dry_run", False))
    result = texture_group_rename(
        project_root,
        old,
        new,
        update_references=update_references,
        dry_run=dry_run,
    )
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Failed')}")
        return OperationResult(success=False, message="Failed")
    for w in result.get("warnings", []) or []:
        print(f"[WARN]  {w}")
    print(f"[OK] {result.get('message')}")
    if dry_run:
        print(f"[DRY] Would change: {result.get('changed_files')}")
    return OperationResult(success=True, message=result.get("message", "Renamed"))


def handle_texture_groups_delete(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    name = getattr(args, "name", "")
    reassign_to = getattr(args, "reassign_to", None)
    dry_run = bool(getattr(args, "dry_run", False))
    result = texture_group_delete(project_root, name, reassign_to=reassign_to, dry_run=dry_run)
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Failed')}")
        details = result.get("details") or {}
        refs = details.get("references_found")
        if refs:
            print(f"References found: {len(refs)}")
        return OperationResult(success=False, message="Failed")
    for w in result.get("warnings", []) or []:
        print(f"[WARN]  {w}")
    print(f"[OK] {result.get('message')}")
    if dry_run:
        print(f"[DRY] Would change: {result.get('changed_files')}")
    return OperationResult(success=True, message=result.get("message", "Deleted"))


def handle_texture_groups_assign(args) -> OperationResult:
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    group = getattr(args, "group", "")
    assets = _parse_csv(getattr(args, "assets", None))
    asset_type = getattr(args, "asset_type", None)
    name_contains = getattr(args, "name_contains", None)
    folder_prefix = getattr(args, "folder_prefix", None)
    from_group = getattr(args, "from_group", None)
    configs = _parse_csv(getattr(args, "configs", None))
    include_top_level = not bool(getattr(args, "no_top_level", False))
    update_existing_configs = not bool(getattr(args, "no_update_existing_configs", False))
    dry_run = bool(getattr(args, "dry_run", False))

    result = texture_group_assign(
        project_root,
        group,
        asset_identifiers=assets,
        asset_type=asset_type,
        name_contains=name_contains,
        folder_prefix=folder_prefix,
        from_group=from_group,
        configs=configs,
        include_top_level=include_top_level,
        update_existing_configs=update_existing_configs,
        dry_run=dry_run,
    )
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Failed')}")
        return OperationResult(success=False, message="Failed")
    for w in result.get("warnings", []) or []:
        print(f"[WARN]  {w}")
    print(f"[OK] {result.get('message')}")
    if dry_run:
        print(f"[DRY] Would change: {result.get('changed_files')}")
    return OperationResult(success=True, message=result.get("message", "Assigned"))

