"""
Trash system for GameMaker maintenance.
Safely moves assets to a trash folder instead of permanent deletion.
"""

import os
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from ...transactions import transactional_rename
from ...exceptions import ValidationError
from ...path_safety import assert_project_tree_contained, project_relative_path, validate_resource_name
from ...utils import atomic_write_text


def move_to_trash(project_root: str, files_to_move: List[str], trash_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Move a list of project files to a timestamped trash folder.

    Args:
        project_root: Path to the GameMaker project root
        files_to_move: List of paths relative to project root
        trash_name: Optional custom name for the trash subfolder

    Returns:
        Dictionary with statistics and manifest of moved files
    """
    project_root_path = assert_project_tree_contained(Path(project_root))
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_folder_name = validate_resource_name(trash_name or f"trash_{timestamp}", "trash folder")
    trash_root = project_root_path / ".maintenance_trash" / trash_folder_name

    # Validate the entire batch before even creating the trash directory.
    moves = []
    for rel_path in files_to_move:
        src = project_relative_path(rel_path, project_root=project_root_path, kind="trash source")
        if src == project_root_path or src.is_relative_to(project_root_path / ".maintenance_trash"):
            raise ValidationError("Cannot trash the project root or its recovery directory")
        dst = project_relative_path(rel_path, project_root=trash_root, kind="trash destination")
        if dst.exists():
            raise ValidationError("Trash destination already exists; use a new trash folder")
        moves.append((rel_path, src, dst))

    os.makedirs(trash_root, exist_ok=True)

    moved_count = 0
    errors = []
    manifest = []

    for rel_path, src, dst in moves:
        if not src.exists():
            continue

        os.makedirs(dst.parent, exist_ok=True)

        try:
            # Move the file
            transactional_rename(src, dst)
            moved_count += 1
            manifest.append(rel_path)
        except Exception as e:
            errors.append(f"Failed to move {rel_path}: {e}")

    # Write manifest file
    if manifest:
        manifest_path = trash_root / "MANIFEST.txt"
        manifest_text = f"Maintenance Trash Manifest - {timestamp}\n" + "=" * 40 + "\n"
        manifest_text += "".join(f"{item}\n" for item in manifest)
        atomic_write_text(manifest_path, manifest_text)

    return {
        "trash_folder": str(trash_root.relative_to(project_root_path)),
        "moved_count": moved_count,
        "errors": errors,
        "manifest": manifest,
    }


def get_keep_patterns(project_root: str) -> List[str]:
    """Load patterns from maintenance_keep.txt."""
    keep_file = Path(project_root) / "maintenance_keep.txt"
    if not keep_file.exists():
        return []

    patterns = []
    with open(keep_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns
