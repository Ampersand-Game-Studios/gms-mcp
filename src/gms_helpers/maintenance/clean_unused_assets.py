#!/usr/bin/env python3
"""
Clean Unused Asset Folders
Moves asset folders (objects, sprites, scripts, etc.) not referenced in the .yyp file to the
project trash. Default is dry-run (prints what would be moved). Use --delete to move them.
"""

import argparse
import os
from pathlib import Path
import sys

from ..utils import load_json_loose, find_yyp, resolve_project_directory
from ..exceptions import ProjectNotFoundError, GMSError, ValidationError
from ..path_safety import assert_project_tree_contained, project_relative_path
from .trash import move_to_trash


def collect_referenced_folders(yyp_data, asset_type):
    """Return the casefolded asset-folder names registered under ``asset_type``/."""
    referenced = set()
    prefix = asset_type.casefold()
    for resource in yyp_data.get("resources", []):
        resource_id = resource.get("id", {}) if isinstance(resource, dict) else {}
        path = resource_id.get("path", "") if isinstance(resource_id, dict) else ""
        # e.g., objects/o_enemy_boss/o_enemy_boss.yy -> o_enemy_boss
        parts = [part for part in str(path).replace("\\", "/").split("/") if part]
        if len(parts) > 1 and parts[0].casefold() == prefix:
            referenced.add(parts[1].casefold())
    return referenced


def _is_asset_folder(folder: Path) -> bool:
    """True only for a folder holding a parseable ``<folder>/<folder>.yy`` asset file."""
    yy_files = [
        child
        for child in folder.iterdir()
        if child.is_file() and child.name.casefold() == f"{folder.name}.yy".casefold()
    ]
    if len(yy_files) != 1:
        return False
    try:
        data = load_json_loose(yy_files[0])
    except Exception:
        return False
    return isinstance(data, dict)


def clean_unused_folders(project_root, asset_type, do_delete=False):
    """Find (and with ``do_delete`` move to the project trash) unregistered asset folders.

    Only folders that contain a parseable ``<name>/<name>.yy`` are considered asset
    folders; anything else in the directory is user data and is left alone.
    """
    project_root = assert_project_tree_contained(Path(project_root))
    allowed_types = {
        "objects",
        "sprites",
        "scripts",
        "rooms",
        "sounds",
        "paths",
        "fonts",
        "shaders",
        "animcurves",
        "tilesets",
        "timelines",
        "sequences",
        "notes",
    }
    if asset_type not in allowed_types:
        raise ValidationError(f"Invalid asset directory type: {asset_type}")
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if not yyp_data:
        return 0, 0

    referenced = collect_referenced_folders(yyp_data, asset_type)
    asset_dir = project_relative_path(asset_type, project_root=project_root, kind="asset directory")
    if not asset_dir.exists():
        print(f"[SKIP] {asset_type}/ directory does not exist.")
        return 0, 0
    found = 0
    unused = []
    for folder in sorted(asset_dir.iterdir()):
        if not folder.is_dir():
            continue
        found += 1
        if folder.name.casefold() in referenced or not _is_asset_folder(folder):
            continue
        unused.append(folder)
        if not do_delete:
            print(f"[UNUSED]  {folder}")
    if not do_delete or not unused:
        return found, 0
    result = move_to_trash(str(project_root), [folder.relative_to(project_root).as_posix() for folder in unused])
    for error in result["errors"]:
        print(f"[ERROR] {error}")
    for moved in result["manifest"]:
        print(f"[TRASHED] {moved} -> {result['trash_folder']}")
    return found, result["moved_count"]


def main():
    parser = argparse.ArgumentParser(description="Clean unused asset folders not referenced in the .yyp file.")
    parser.add_argument("--delete", action="store_true", help="Actually delete unused folders (default: dry-run)")
    parser.add_argument(
        "--types",
        type=str,
        default="objects,sprites,scripts",
        help="Comma-separated asset types (default: objects,sprites,scripts)",
    )
    parser.add_argument("--project-root", type=str, help="Project root directory (will auto-detect if not provided)")
    args = parser.parse_args()

    # Use proper project root detection
    project_root = resolve_project_directory(args.project_root)
    print(f"[FOLDER] Using GameMaker project: {project_root}")

    asset_types = [t.strip() for t in args.types.split(",") if t.strip()]
    total_found = 0
    total_deleted = 0
    for asset_type in asset_types:
        print(f"\nScanning {asset_type}/ for unused folders...")
        found, deleted = clean_unused_folders(project_root, asset_type, do_delete=args.delete)
        total_found += found
        total_deleted += deleted
    print(f"\nSummary: {total_found} folders scanned, {total_deleted} deleted.")
    if not args.delete:
        print("\nRun with --delete to actually remove unused folders.")


def clean_old_yy_files(project_root: str, do_delete: bool = False) -> tuple[int, int]:
    """
    Find and optionally move .old.yy files throughout the project to the project trash.
    """
    project_path = assert_project_tree_contained(Path(project_root))

    # Common asset directories to scan
    search_dirs = [
        "objects",
        "sprites",
        "scripts",
        "rooms",
        "sounds",
        "paths",
        "fonts",
        "shaders",
        "animcurves",
        "tilesets",
        "timelines",
        "sequences",
    ]

    old_files = []
    for d in search_dirs:
        dir_path = project_path / d
        if not dir_path.exists():
            continue
        for file_path in sorted(dir_path.rglob("*.old.yy")):
            old_files.append(file_path)
            if not do_delete:
                print(f"[OLD FILE] {file_path}")

    if not do_delete or not old_files:
        return len(old_files), 0
    result = move_to_trash(str(project_path), [path.relative_to(project_path).as_posix() for path in old_files])
    for error in result["errors"]:
        print(f"[ERROR] {error}")
    for moved in result["manifest"]:
        print(f"[TRASHED] {moved} -> {result['trash_folder']}")
    return len(old_files), result["moved_count"]


if __name__ == "__main__":
    try:
        main()
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        sys.exit(e.exit_code)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
