"""
Orphan Detection - Find assets that exist on disk but aren't referenced in the project
"""

import glob
from pathlib import Path
from typing import List, Optional, Tuple

from ..utils import load_json, find_yyp
from ..path_safety import assert_project_tree_contained, project_relative_path
from .path_utils import is_options_path


def _project_root_path(project_root: Optional[str]) -> Path:
    """Resolve the project to scan; "." means the working directory, never an env override."""
    if not project_root or str(project_root) == ".":
        return assert_project_tree_contained(Path.cwd())
    return assert_project_tree_contained(Path(project_root))


def find_orphaned_assets(project_root: str = ".") -> List[Tuple[str, str]]:
    """
    Find assets that exist on disk but aren't referenced in the .yyp file.

    Raises on unreadable projects instead of reporting a clean result.

    Returns:
        List of (asset_path, asset_type) tuples for orphaned assets
    """
    root = _project_root_path(project_root)
    yyp_data = load_json(find_yyp(root))

    # Compare case-insensitively: GameMaker resolves resource paths that way on
    # Windows/macOS, so a case-only difference is not an orphan.
    referenced_paths = set()
    for resource in yyp_data.get("resources", []):
        resource_id = resource.get("id", {}) if isinstance(resource, dict) else {}
        path = resource_id.get("path", "") if isinstance(resource_id, dict) else ""
        if path:
            referenced_paths.add(path.replace("\\", "/").casefold())

    asset_patterns = [
        "scripts/**/*.yy",
        "objects/**/*.yy",
        "sprites/**/*.yy",
        "rooms/**/*.yy",
        "sounds/**/*.yy",
        "fonts/**/*.yy",
        "shaders/**/*.yy",
        "animcurves/**/*.yy",
        "folders/**/*.yy",
    ]

    orphans = []
    escaped_root = Path(glob.escape(str(root)))
    for pattern in asset_patterns:
        for asset_file in glob.glob(str(escaped_root / pattern), recursive=True):
            # Retain the real spelling for cleanup on case-sensitive filesystems.
            actual_path = Path(asset_file).relative_to(root).as_posix()
            if actual_path.casefold() in referenced_paths:
                continue
            project_relative_path(actual_path, project_root=root, kind="orphan path")
            orphans.append((actual_path, _get_asset_type_from_path(actual_path)))

    return orphans


def _get_asset_type_from_path(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    if normalized.startswith("scripts/"):
        return "script"
    if normalized.startswith("objects/"):
        return "object"
    if normalized.startswith("sprites/"):
        return "sprite"
    if normalized.startswith("rooms/"):
        return "room"
    if normalized.startswith("sounds/"):
        return "sound"
    if normalized.startswith("fonts/"):
        return "font"
    if normalized.startswith("shaders/"):
        return "shader"
    if normalized.startswith("animcurves/"):
        return "animcurve"
    if normalized.startswith("folders/"):
        return "folder"
    return "unknown"


def find_missing_assets(project_root: str = ".") -> List[Tuple[str, str]]:
    """
    Find assets referenced in .yyp but missing from disk.

    Raises on unreadable projects instead of reporting a clean result.

    Returns:
        List of (asset_path, asset_type) tuples for missing assets
    """
    root = _project_root_path(project_root)
    yyp_data = load_json(find_yyp(root))

    missing = []
    for resource in yyp_data.get("resources", []):
        resource_id = resource.get("id", {}) if isinstance(resource, dict) else {}
        path = resource_id.get("path", "") if isinstance(resource_id, dict) else ""
        # Options files have a special format and location.
        if not path or is_options_path(path):
            continue

        asset_type = _get_asset_type_from_path(path)
        # Folders are logical-only; they should not have physical files.
        if asset_type == "folder":
            continue

        if not project_relative_path(path, project_root=root, kind="resource path").exists():
            missing.append((path, asset_type))

    return missing


def print_orphan_report(orphans: List[Tuple[str, str]], missing: List[Tuple[str, str]]):
    """Print a formatted report of orphaned and missing assets."""

    print(f"\n[SCAN] Asset Orphan Report")
    print(f"   Orphaned (on disk, not in .yyp): {len(orphans)}")
    print(f"   Missing (in .yyp, not on disk): {len(missing)}")
    print("-" * 50)

    if orphans:
        print(f"\nORPHANED ASSETS:")

        # Group by type
        by_type = {}
        for path, asset_type in orphans:
            if asset_type not in by_type:
                by_type[asset_type] = []
            by_type[asset_type].append(path)

        for asset_type, paths in by_type.items():
            print(f"\n  {asset_type.upper()}S ({len(paths)}):")
            for path in sorted(paths):
                print(f"    - {path}")

    if missing:
        print(f"\nMISSING ASSETS:")

        # Group by type
        by_type = {}
        for path, asset_type in missing:
            if asset_type not in by_type:
                by_type[asset_type] = []
            by_type[asset_type].append(path)

        for asset_type, paths in by_type.items():
            print(f"\n  {asset_type.upper()}S ({len(paths)}):")
            for path in sorted(paths):
                print(f"    [ERROR] {path}")

    if not orphans and not missing:
        print("\n[OK] No orphaned or missing assets found!")
    elif orphans and not missing:
        print(f"\n[INFO] Consider adding orphaned assets to the project or removing them from disk")
    elif missing and not orphans:
        print(f"\n[WARN]  Missing assets should be restored or removed from the .yyp file")
    else:
        print(f"\n[MAINT] Project has both orphaned and missing assets - cleanup recommended")
