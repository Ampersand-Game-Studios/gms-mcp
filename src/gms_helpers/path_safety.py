"""Filesystem path safety helpers for project-local asset tools."""

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
