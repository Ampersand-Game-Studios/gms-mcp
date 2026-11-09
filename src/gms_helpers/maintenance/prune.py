"""
Asset Pruning - Remove missing asset references from project file
"""

from pathlib import Path
from typing import List, Tuple

from ..path_safety import assert_project_tree_contained, project_relative_path
from ..transactions import transactional_copy2
from ..utils import load_json, save_json, find_yyp
from .path_utils import find_case_variant, is_options_path


def prune_missing_assets(project_root: str = ".", dry_run: bool = False) -> List[Tuple[str, str]]:
    """
    Remove references to missing assets from the .yyp file.

    An asset whose files exist under a different letter case is not missing: it is
    reported as a case mismatch and kept, because unregistering it would orphan a
    live asset on case-sensitive filesystems.

    Args:
        project_root: Root directory of the project
        dry_run: If True, don't modify files, just report what would be removed

    Returns:
        List of (asset_path, asset_type) tuples for removed entries
    """
    root = assert_project_tree_contained(Path(project_root))
    yyp_path = find_yyp(root)
    yyp_data = load_json(yyp_path)

    removed_entries: List[Tuple[str, str]] = []
    case_mismatches: List[Tuple[str, str]] = []

    original_resources = yyp_data.get("resources", [])
    valid_resources = []
    for resource in original_resources:
        resource_id = resource.get("id", {}) if isinstance(resource, dict) else {}
        path = resource_id.get("path", "") if isinstance(resource_id, dict) else ""
        if not path or is_options_path(path):
            valid_resources.append(resource)
            continue

        asset_type = _get_asset_type_from_path(path)
        # Folders are logical only - treat them as always existing
        if asset_type == "folder":
            valid_resources.append(resource)
            continue

        normalized = path.replace("\\", "/")
        project_relative_path(normalized, project_root=root, kind="resource path")
        actual = find_case_variant(root, normalized)
        if actual == normalized:
            valid_resources.append(resource)
        elif actual is not None:
            case_mismatches.append((path, actual))
            valid_resources.append(resource)
        else:
            removed_entries.append((path, asset_type))

    for registered, actual in case_mismatches:
        print(f"[WARN]  Case mismatch (kept, fix the spelling): {registered} -> {actual}")

    removed_paths = {path.replace("\\", "/") for path, _ in removed_entries}

    def _order_path(entry) -> str:
        if isinstance(entry, str):
            return entry.replace("\\", "/")
        if isinstance(entry, dict):
            return str(entry.get("path", "")).replace("\\", "/")
        return ""

    original_resource_order = yyp_data.get("resourceOrder", [])
    valid_resource_order = [entry for entry in original_resource_order if _order_path(entry) not in removed_paths]

    if not dry_run and removed_entries:
        transactional_copy2(yyp_path, f"{yyp_path}.bak")
        yyp_data["resources"] = valid_resources
        if "resourceOrder" in yyp_data:
            yyp_data["resourceOrder"] = valid_resource_order
        save_json(yyp_data, yyp_path)

    return removed_entries


def _get_asset_type_from_path(path: str) -> str:
    """Determine asset type from file path."""
    # Normalize path separators for consistent matching
    normalized_path = path.replace("\\", "/").lower()

    if normalized_path.startswith("scripts/"):
        return "script"
    elif normalized_path.startswith("objects/"):
        return "object"
    elif normalized_path.startswith("sprites/"):
        return "sprite"
    elif normalized_path.startswith("rooms/"):
        return "room"
    elif normalized_path.startswith("sounds/"):
        return "sound"
    elif normalized_path.startswith("fonts/"):
        return "font"
    elif normalized_path.startswith("shaders/"):
        return "shader"
    elif normalized_path.startswith("animcurves/"):
        return "animcurve"
    elif normalized_path.startswith("folders/"):
        return "folder"
    else:
        return "unknown"


def print_prune_report(removed_entries: List[Tuple[str, str]], dry_run: bool = False):
    """Print a formatted report of pruning results."""

    action = "Would remove" if dry_run else "Removed"

    print(f"\n[CLEAN] Asset Pruning Report")
    print(f"   {action}: {len(removed_entries)} missing reference(s)")
    print("-" * 50)

    if removed_entries:
        # Group by type
        by_type = {}
        for path, asset_type in removed_entries:
            if asset_type not in by_type:
                by_type[asset_type] = []
            by_type[asset_type].append(path)

        print(f"\n{action.upper()}:")
        for asset_type, paths in by_type.items():
            print(f"\n  {asset_type.upper()}S ({len(paths)}):")
            for path in sorted(paths):
                print(f"    [DELETE]  {path}")

        if dry_run:
            print(f"\n[INFO] Run without --dry-run to apply changes")
        else:
            print("\n[OK] Project backup created")
            print(f"[OK] Project file cleaned and formatted")
    else:
        print("\n[OK] No missing asset references found!")
        print("Project file is already clean.")
