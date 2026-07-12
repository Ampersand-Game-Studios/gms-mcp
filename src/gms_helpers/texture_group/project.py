from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils import find_yyp, load_json_loose


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
