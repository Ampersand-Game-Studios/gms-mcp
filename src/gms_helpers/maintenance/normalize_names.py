"""Opt-in asset naming normalization for imported GameMaker projects."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..naming_config import get_config
from ..utils import find_yyp, load_json_loose, validate_name
from ..workflow import rename_asset

_ASSET_TYPES_BY_RESOURCE_DIR = {
    "scripts": "script",
    "objects": "object",
    "sprites": "sprite",
    "rooms": "room",
    "fonts": "font",
    "shaders": "shader",
    "sounds": "sound",
    "paths": "path",
    "tilesets": "tileset",
    "timelines": "timeline",
    "sequences": "sequence",
    "animcurves": "animcurve",
    "notes": "note",
}


def _resource_asset_type(resource_path: str) -> str | None:
    first_part = resource_path.replace("\\", "/").split("/", 1)[0]
    return _ASSET_TYPES_BY_RESOURCE_DIR.get(first_part)


def _first_prefix(prefixes: list[str]) -> str | None:
    for prefix in prefixes:
        if prefix:
            return prefix
    return None


def _base_name(name: str, prefixes: list[str]) -> str:
    lowered = name.lower()
    for prefix in sorted((p for p in prefixes if p), key=len, reverse=True):
        if lowered.startswith(prefix.lower()):
            return name[len(prefix) :]
    return name


def _snake_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip())
    name = re.sub(r"_+", "_", name).strip("_")
    return name.lower() or "asset"


def _candidate_name(name: str, prefixes: list[str]) -> str | None:
    prefix = _first_prefix(prefixes)
    if not prefix:
        return None
    return f"{prefix}{_snake_name(_base_name(name, prefixes))}"


def _resource_names(yyp_data: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for resource in yyp_data.get("resources", []):
        resource_id = resource.get("id", {})
        name = resource_id.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def plan_name_normalization(
    project_root: str | Path = ".",
    *,
    asset_type: str | None = None,
) -> dict[str, Any]:
    """Return naming-convention renames that can be safely applied."""

    root = Path(project_root).resolve()
    yyp_path = find_yyp(root)
    yyp_data = load_json_loose(yyp_path)
    if not isinstance(yyp_data, dict):
        return {"ok": False, "error": f"Could not read project file: {yyp_path}", "planned": [], "skipped": []}

    config = get_config(root)
    if not config.naming_enabled:
        return {"ok": True, "planned": [], "skipped": [], "message": "Naming validation is disabled."}

    existing_names = _resource_names(yyp_data)
    planned: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    reserved_targets: set[str] = set()

    for resource in yyp_data.get("resources", []):
        resource_id = resource.get("id", {})
        name = resource_id.get("name")
        path = resource_id.get("path")
        if not isinstance(name, str) or not isinstance(path, str):
            continue

        current_asset_type = _resource_asset_type(path)
        if current_asset_type is None:
            continue
        if asset_type and current_asset_type != asset_type:
            continue

        prefixes = config.get_prefixes(current_asset_type)
        if not prefixes:
            continue

        try:
            validate_name(name, current_asset_type, config=config)
            continue
        except ValueError:
            pass

        candidate = _candidate_name(name, prefixes)
        if candidate is None or candidate == name:
            skipped.append(
                {
                    "asset_type": current_asset_type,
                    "asset_name": name,
                    "asset_path": path,
                    "reason": "No prefix-based normalization is available.",
                }
            )
            continue

        try:
            validate_name(candidate, current_asset_type, config=config)
        except ValueError as exc:
            skipped.append(
                {
                    "asset_type": current_asset_type,
                    "asset_name": name,
                    "asset_path": path,
                    "target_name": candidate,
                    "reason": str(exc),
                }
            )
            continue

        if candidate in existing_names or candidate in reserved_targets:
            skipped.append(
                {
                    "asset_type": current_asset_type,
                    "asset_name": name,
                    "asset_path": path,
                    "target_name": candidate,
                    "reason": f"Target name '{candidate}' already exists.",
                }
            )
            continue

        reserved_targets.add(candidate)
        planned.append(
            {
                "asset_type": current_asset_type,
                "asset_name": name,
                "asset_path": path,
                "target_name": candidate,
            }
        )

    return {"ok": True, "planned": planned, "skipped": skipped}


def normalize_asset_names(
    project_root: str | Path = ".",
    *,
    fix: bool = False,
    asset_type: str | None = None,
) -> dict[str, Any]:
    """Plan or apply prefix-based asset renames."""

    root = Path(project_root).resolve()
    plan = plan_name_normalization(root, asset_type=asset_type)
    if not plan.get("ok"):
        return plan

    planned = plan.get("planned", [])
    if not fix:
        return {**plan, "dry_run": True, "applied": [], "changed_count": 0}

    applied: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for item in planned:
        try:
            result = rename_asset(root, item["asset_path"], item["target_name"])
        except Exception as exc:
            failed.append({**item, "reason": str(exc)})
            continue
        applied.append({**item, "result": result.message})

    return {
        **plan,
        "ok": not failed,
        "dry_run": False,
        "applied": applied,
        "failed": failed,
        "changed_count": len(applied),
    }
