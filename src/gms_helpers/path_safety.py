"""Filesystem path safety helpers for project-local asset tools."""

import os
import stat
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
        or any(character in candidate for character in '\x00<>:"|?*')
        or any(ord(character) < 32 for character in candidate)
        or candidate.endswith(".")
        or candidate.split(".", 1)[0].casefold()
        in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
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


def project_relative_path(path: Any, *, project_root: Path, kind: str = "path") -> Path:
    """Validate an untrusted project-relative path on POSIX and Windows."""
    candidate = str(path)
    windows = PureWindowsPath(candidate)
    if (
        not candidate
        or Path(candidate).is_absolute()
        or windows.drive
        or windows.root
        or "\\" in candidate
        or ".." in Path(candidate).parts
        or "\x00" in candidate
        or ":" in candidate
    ):
        raise ValidationError(f"Invalid {kind}: expected a project-relative path without traversal")
    return project_child_path(candidate, project_root=project_root, kind=kind)


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
                if candidate.stat().st_nlink > 1:
                    raise ValidationError(
                        "Project contains a multiply-linked file; external write confinement cannot be proven"
                    )
                continue
            try:
                target = candidate.resolve(strict=False)
                target.relative_to(root)
            except (OSError, ValueError):
                raise ValidationError("Project contains a filesystem link that escapes the approved project root")

    return root


def validate_git_ref(ref: str) -> str:
    if not isinstance(ref, str) or not ref.strip() or ref.startswith("-") or "\x00" in ref:
        raise ValidationError("Invalid ref: expected a commit, branch or tag, never an option")
    return ref


def private_directory(path: Path) -> Path:
    """Create a private directory without trusting symlinked or foreign-owned parents."""
    path = Path(os.path.abspath(path.expanduser()))
    missing = []
    current = path
    while not current.exists() and not current.is_symlink():
        missing.append(current)
        current = current.parent
    for parent in [current, *current.parents]:
        info = parent.lstat()
        if os.name == "nt":
            from .windows_security import windows_path_trust_issue

            if getattr(info, "st_file_attributes", 0) & 0x400 or windows_path_trust_issue(parent, ancestor=True):
                raise ValidationError(f"Unsafe private directory parent: {parent}")
        elif hasattr(os, "getuid"):
            # Root-owned links such as macOS /var and /tmp can only be replaced by root.
            trusted_link = stat.S_ISLNK(info.st_mode) and info.st_uid == 0
            if (stat.S_ISLNK(info.st_mode) and not trusted_link) or info.st_uid not in {0, os.getuid()}:
                raise ValidationError(f"Unsafe private directory parent: {parent}")
            if trusted_link:
                info = parent.stat()
            if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                raise ValidationError(f"Replaceable private directory parent: {parent}")
        elif stat.S_ISLNK(info.st_mode):
            raise ValidationError(f"Unsafe private directory parent: {parent}")
    for directory in reversed(missing):
        if os.name == "nt":
            from .windows_security import create_private_directory

            try:
                create_private_directory(directory)
            except (AttributeError, OSError, ValueError) as exc:
                raise ValidationError(f"Cannot create private directory: {directory}") from exc
        else:
            directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if stat.S_ISLNK(info.st_mode) or (hasattr(os, "getuid") and info.st_uid != os.getuid()):
            raise ValidationError(f"Unsafe private directory parent: {directory}")
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or (hasattr(os, "getuid") and info.st_uid != os.getuid())
        or (os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077)
    ):
        raise ValidationError(f"Private directory must be owned by this user with mode 0700: {path}")
    if os.name == "nt":
        from .windows_security import windows_path_trust_issue

        if issue := windows_path_trust_issue(path, private=True):
            raise ValidationError(f"Unsafe private directory: {issue}")
    return path


def project_file_path(path: Any, *, project_root: Path, kind: str = "metadata path") -> Path:
    target = project_relative_path(path, project_root=project_root, kind=kind)
    if not target.is_file():
        raise ValidationError(f"Invalid {kind}: expected a regular file")
    return target
