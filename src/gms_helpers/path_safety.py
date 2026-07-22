"""Filesystem path safety helpers for project-local asset tools."""

import os
from pathlib import Path, PureWindowsPath
from typing import Any

from .exceptions import ValidationError


def validate_resource_name(name: Any, kind: str) -> str:
    """Reject resource names that can be interpreted as filesystem paths."""
    if name is None:
        raise ValidationError(f"Invalid {kind} name: cannot be empty")

    candidate = str(name).strip()
    if not candidate:
        raise ValidationError(f"Invalid {kind} name: cannot be empty")

    windows_path = PureWindowsPath(candidate)
    if (
        Path(candidate).is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or "/" in candidate
        or "\\" in candidate
        or candidate in {".", ".."}
    ):
        raise ValidationError(f"Invalid {kind} name: {name}")

    return candidate


def project_child_path(*parts: Any, project_root: Path | None = None, kind: str = "path") -> Path:
    """Resolve a child path and ensure it remains inside the project root."""
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    target = root.joinpath(*(str(part) for part in parts)).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        raise ValidationError(f"Invalid {kind}: resolved path escapes the project root")

    return target


def assert_project_tree_contained(project_root: Path) -> Path:
    """Reject a project containing any symlink whose target leaves the project."""
    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise ValidationError("Invalid project root: expected a directory")

    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        # Resolve every directory entry so Windows junctions/reparse points are
        # treated as boundaries even when pathlib does not report a symlink.
        for name in directory_names:
            candidate = directory_path / name
            try:
                candidate.resolve(strict=False).relative_to(root)
            except (OSError, ValueError):
                raise ValidationError("Project contains a filesystem link that escapes the approved project root")
        for name in file_names:
            candidate = directory_path / name
            if not candidate.is_symlink():
                continue
            try:
                target = candidate.resolve(strict=False)
                target.relative_to(root)
            except (OSError, ValueError):
                raise ValidationError("Project contains a filesystem link that escapes the approved project root")

    return root
