"""
Trash system for GameMaker maintenance.
Safely moves assets to a trash folder instead of permanent deletion.
"""

import os
import datetime
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

from ...transactions import transactional_rename
from ...exceptions import ValidationError
from ...path_safety import assert_project_tree_contained, project_relative_path, validate_resource_name
from ...utils import atomic_write_text

TRASH_DIR_NAME = ".maintenance_trash"
MANIFEST_NAME = "MANIFEST.txt"
_MANIFEST_RULE = "=" * 40


def _new_trash_folder_name() -> str:
    """Return a trash folder name that cannot collide with another batch."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"trash_{timestamp}_{uuid.uuid4().hex[:8]}"


def read_manifest(trash_root: Path) -> List[str]:
    """Return the project-relative paths recorded in a trash folder's manifest."""
    manifest_path = trash_root / MANIFEST_NAME
    if not manifest_path.is_file():
        return []
    entries: List[str] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("Maintenance Trash Manifest") or line == _MANIFEST_RULE:
            continue
        entries.append(line)
    return entries


def _write_manifest(trash_root: Path, entries: List[str]) -> None:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    text = f"Maintenance Trash Manifest - {timestamp}\n" + _MANIFEST_RULE + "\n"
    text += "".join(f"{item}\n" for item in entries)
    atomic_write_text(trash_root / MANIFEST_NAME, text)


def move_to_trash(project_root: str, files_to_move: List[str], trash_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Move project files or folders to a trash folder.

    Args:
        project_root: Path to the GameMaker project root
        files_to_move: List of paths relative to project root
        trash_name: Optional custom name for the trash subfolder. Reusing a name
            adds to that batch; existing trashed paths are never overwritten.

    Returns:
        Dictionary with statistics and manifest of moved files
    """
    project_root_path = assert_project_tree_contained(Path(project_root))
    trash_folder_name = validate_resource_name(trash_name or _new_trash_folder_name(), "trash folder")
    trash_root = project_root_path / TRASH_DIR_NAME / trash_folder_name

    # Validate the entire batch before even creating the trash directory.
    moves = []
    for rel_path in files_to_move:
        src = project_relative_path(rel_path, project_root=project_root_path, kind="trash source")
        if src == project_root_path or src.is_relative_to(project_root_path / TRASH_DIR_NAME):
            raise ValidationError("Cannot trash the project root or its recovery directory")
        dst = project_relative_path(rel_path, project_root=trash_root, kind="trash destination")
        if dst.exists():
            raise ValidationError("Trash destination already exists; use a new trash folder")
        moves.append((Path(rel_path).as_posix(), src, dst))

    os.makedirs(trash_root, exist_ok=True)

    moved_count = 0
    errors = []
    manifest = []

    for rel_path, src, dst in moves:
        if not src.exists():
            continue

        os.makedirs(dst.parent, exist_ok=True)

        try:
            transactional_rename(src, dst)
            moved_count += 1
            manifest.append(rel_path)
        except Exception as e:
            errors.append(f"Failed to move {rel_path}: {e}")

    # Append to (never replace) the batch manifest so earlier moves stay restorable.
    if manifest:
        _write_manifest(trash_root, read_manifest(trash_root) + manifest)

    return {
        "trash_folder": str(trash_root.relative_to(project_root_path)),
        "moved_count": moved_count,
        "errors": errors,
        "manifest": manifest,
    }


def restore_from_trash(project_root: str, trash_name: str) -> Dict[str, Any]:
    """
    Move every manifest entry of a trash batch back to its original project path.

    Entries whose original path is occupied again are left in the trash and
    reported; nothing in the project is overwritten.
    """
    project_root_path = assert_project_tree_contained(Path(project_root))
    trash_folder_name = validate_resource_name(trash_name, "trash folder")
    trash_root = project_root_path / TRASH_DIR_NAME / trash_folder_name
    if not trash_root.is_dir():
        raise ValidationError(f"Trash folder not found: {TRASH_DIR_NAME}/{trash_folder_name}")

    entries = read_manifest(trash_root)
    restored: List[str] = []
    errors: List[str] = []
    remaining: List[str] = []
    for rel_path in entries:
        src = project_relative_path(rel_path, project_root=trash_root, kind="trash entry")
        dst = project_relative_path(rel_path, project_root=project_root_path, kind="restore destination")
        if not src.exists():
            errors.append(f"Missing from trash: {rel_path}")
            continue
        if dst.exists():
            errors.append(f"Restore destination already exists: {rel_path}")
            remaining.append(rel_path)
            continue
        try:
            os.makedirs(dst.parent, exist_ok=True)
            transactional_rename(src, dst)
            restored.append(rel_path)
        except Exception as e:
            errors.append(f"Failed to restore {rel_path}: {e}")
            remaining.append(rel_path)

    if entries:
        # Keep the manifest describing exactly what is still restorable.
        _write_manifest(trash_root, remaining)

    return {
        "trash_folder": str(trash_root.relative_to(project_root_path)),
        "restored_count": len(restored),
        "restored": restored,
        "remaining": remaining,
        "errors": errors,
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
