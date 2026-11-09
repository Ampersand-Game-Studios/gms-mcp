"""
Orphan cleanup functionality for GameMaker projects.
Moves orphaned asset files that are not referenced in the .yyp file to the project trash.
"""

from pathlib import Path
from typing import List, Set, Dict, Any, Optional

from ..path_safety import assert_project_tree_contained, project_file_path, project_relative_path
from ..transactions import transactional_rmdir
from ..utils import load_json
from .orphans import find_missing_assets, find_orphaned_assets
from .trash import move_to_trash


def find_delete_candidates(project_root: str, skip_types: Optional[Set[str]] = None) -> List[str]:
    """
    Find orphaned assets that are candidates for deletion.

    Args:
        project_root: Path to the GameMaker project root
        skip_types: Set of asset types to skip (default: {"folder"})

    Returns:
        List of file paths that can be safely deleted
    """
    if skip_types is None:
        skip_types = {"folder"}

    orphaned_assets = find_orphaned_assets(project_root)
    candidates = []

    for orphan_data in orphaned_assets:
        # orphan_data is a tuple of (path, asset_type) from find_orphaned_assets
        if isinstance(orphan_data, tuple) and len(orphan_data) == 2:
            orphan_path, asset_type = orphan_data
        else:
            # Fallback for unexpected format
            orphan_path = str(orphan_data)
            asset_type = _get_asset_type_from_path(orphan_path)

        # Skip types we don't want to delete
        if asset_type in skip_types:
            continue

        candidates.append(orphan_path)

    return candidates


def _get_asset_type_from_path(asset_path: str) -> str:
    """
    Determine the asset type from the file path.

    Args:
        asset_path: Path to the asset file

    Returns:
        Asset type string (script, object, sprite, room, etc.)
    """
    path_parts = asset_path.split("/")
    if len(path_parts) >= 1:
        first_dir = path_parts[0].lower()

        # Map directory names to asset types
        type_mapping = {
            "scripts": "script",
            "objects": "object",
            "sprites": "sprite",
            "rooms": "room",
            "sounds": "sound",
            "fonts": "font",
            "shaders": "shader",
            "animcurves": "animcurve",
            "folders": "folder",
        }

        return type_mapping.get(first_dir, "unknown")

    return "unknown"


def _check_directory_safety(asset_file: str, project_root: str) -> bool:
    """
    Check if it's safe to delete companion files for an orphaned asset.
    Returns True only if the orphaned asset is the ONLY asset in the directory.

    Args:
        asset_file: Path to the orphaned asset file (.yy)
        project_root: Path to the GameMaker project root

    Returns:
        True if safe to delete companion files, False otherwise
    """
    asset_path = Path(project_root) / asset_file
    asset_dir = asset_path.parent

    # Count all .yy files in the directory
    yy_files = list(asset_dir.glob("*.yy"))

    # If there's more than one .yy file, it's not safe to delete companion files
    if len(yy_files) > 1:
        return False

    # If there's exactly one .yy file and it's the orphaned one, it's safe
    return len(yy_files) == 1 and yy_files[0].name == Path(asset_file).name


def _get_sprite_companion_files(asset_file: str, project_root: str) -> List[str]:
    """
    Get companion files for a sprite, matching UUIDs from the .yy file.
    This ensures we only delete files that actually belong to the orphaned sprite.

    Args:
        asset_file: Path to the sprite .yy file
        project_root: Path to the GameMaker project root

    Returns:
        List of companion file paths that belong to this specific sprite
    """
    companion_files = []
    asset_path = project_file_path(asset_file, project_root=Path(project_root))
    asset_dir = asset_path.parent

    try:
        # Load the sprite's .yy file to get the correct UUIDs
        sprite_data = load_json(asset_path)

        # Extract frame UUIDs from the sprite data
        frame_uuids = set()
        for frame in sprite_data.get("frames", []):
            frame_id = frame.get("name", "")
            if frame_id:
                frame_uuids.add(frame_id)

        # Only include PNG files that match the sprite's UUIDs
        for png_file in asset_dir.glob("*.png"):
            if png_file.stem in frame_uuids:
                companion_files.append(str(png_file.relative_to(project_root)))

        # Handle layers directory - only include directories and files that match UUIDs
        layers_dir = asset_dir / "layers"
        if layers_dir.exists():
            for layer_dir in layers_dir.iterdir():
                if layer_dir.is_dir() and layer_dir.name in frame_uuids:
                    for layer_file in layer_dir.rglob("*"):
                        if layer_file.is_file():
                            companion_files.append(str(layer_file.relative_to(project_root)))

    except Exception as e:
        # If we can't parse the .yy file, don't delete any companion files for safety
        print(f"Warning: Could not parse {asset_file} to determine companion files: {e}")
        return []

    return companion_files


def _get_companion_files(asset_file: str, project_root: str) -> List[str]:
    """
    Find companion files that should be deleted along with an orphaned asset.

    Args:
        asset_file: Path to the main asset file (.yy)
        project_root: Path to the GameMaker project root

    Returns:
        List of companion file paths that should also be deleted
    """
    companion_files = []
    asset_path = Path(project_root) / asset_file
    asset_dir = asset_path.parent
    asset_name = asset_path.stem

    asset_type = _get_asset_type_from_path(asset_file)

    if asset_type == "script":
        # Look for .gml file with same name
        gml_file = asset_dir / f"{asset_name}.gml"
        if gml_file.exists():
            companion_files.append(str(gml_file.relative_to(project_root)))

    elif asset_type == "object":
        # Look for event files (Create_0.gml, Step_0.gml, etc.)
        for event_file in asset_dir.glob("*.gml"):
            companion_files.append(str(event_file.relative_to(project_root)))

    elif asset_type == "sprite":
        # Use improved sprite companion file detection
        companion_files = _get_sprite_companion_files(asset_file, project_root)

    return companion_files


def delete_orphan_files(
    project_root: str, fix_issues: bool = False, skip_types: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """
    Move orphaned asset files and their companions to the project trash.

    An orphan whose name matches a registered-but-missing resource is skipped: it
    may be the only (relocated) copy of that asset.

    Args:
        project_root: Path to the GameMaker project root
        fix_issues: If True, move files to the trash. If False, just report what would be moved
        skip_types: Set of asset types to skip (default: {"folder"})

    Returns:
        Dictionary with statistics and details. ``deleted_files``/``total_deleted``
        count files moved to ``trash_folder`` (restorable with ``restore_from_trash``).
    """
    root = assert_project_tree_contained(Path(project_root))
    project_root = str(root)
    if skip_types is None:
        skip_types = {"folder"}

    result = {
        "deleted_files": [],
        "deleted_directories": [],
        "skipped_files": [],
        "safety_warnings": [],
        "errors": [],
        "total_deleted": 0,
        "total_skipped": 0,
        "trash_folder": None,
    }

    candidates = find_delete_candidates(project_root, skip_types)
    # Reject the full selection before any move; a compromised scanner
    # result must not allow partial cleanup or an external destination.
    for candidate in candidates:
        project_relative_path(candidate, project_root=root, kind="orphan candidate")

    missing_names = {Path(path.replace("\\", "/")).stem.casefold() for path, _ in find_missing_assets(project_root)}

    files_to_trash: List[str] = []
    orphan_dirs: List[Path] = []
    for orphan_file in candidates:
        try:
            orphan_path = project_relative_path(orphan_file, project_root=root, kind="orphan candidate")

            if not orphan_path.exists():
                result["skipped_files"].append(f"File not found: {orphan_file}")
                result["total_skipped"] += 1
                continue

            if Path(orphan_file).stem.casefold() in missing_names:
                safety_msg = f"SAFETY: Kept {orphan_file} - its name matches a registered asset whose files are missing"
                result["safety_warnings"].append(safety_msg)
                result["skipped_files"].append(orphan_file)
                result["total_skipped"] += 1
                if fix_issues:
                    print(f"[WARN]  {safety_msg}")
                continue

            # CRITICAL SAFETY CHECK: Only include companion files if this is the only asset in the directory
            if _check_directory_safety(orphan_file, project_root):
                companions = _get_companion_files(orphan_file, project_root)
                selected = [orphan_file] + companions
            else:
                selected = [orphan_file]
                safety_msg = f"SAFETY: Skipped companion files for {orphan_file} - directory contains other assets"
                result["safety_warnings"].append(safety_msg)
                if fix_issues:
                    print(f"[WARN]  {safety_msg}")

            for file_path in selected:
                normalized = Path(file_path).as_posix()
                if normalized not in files_to_trash:
                    files_to_trash.append(normalized)
            orphan_dirs.append(orphan_path.parent)

        except Exception as e:
            result["errors"].append(f"Error processing {orphan_file}: {str(e)}")

    if not fix_issues:
        for file_path in files_to_trash:
            result["deleted_files"].append(f"[DRY RUN] {file_path}")
            result["total_deleted"] += 1
        return result

    if files_to_trash:
        trash_result = move_to_trash(project_root, files_to_trash)
        result["trash_folder"] = trash_result["trash_folder"]
        result["deleted_files"].extend(trash_result["manifest"])
        result["total_deleted"] += trash_result["moved_count"]
        result["errors"].extend(trash_result["errors"])

    # Remove directories the move left empty.
    for parent_dir in dict.fromkeys(orphan_dirs):
        if parent_dir.is_dir() and not any(parent_dir.iterdir()):
            try:
                transactional_rmdir(parent_dir)
                result["deleted_directories"].append(parent_dir.relative_to(root).as_posix())
            except OSError as e:
                result["errors"].append(f"Could not remove empty directory {parent_dir}: {e}")

    return result
