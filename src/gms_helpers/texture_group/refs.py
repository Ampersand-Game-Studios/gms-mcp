from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ..utils import strip_trailing_commas


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
    return (
        '{ "name":' + json.dumps(name, ensure_ascii=False) + ', "path":' + json.dumps(path, ensure_ascii=False) + " }"
    )


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
