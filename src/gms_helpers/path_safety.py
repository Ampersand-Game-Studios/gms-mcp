"""Filesystem path safety helpers for project-local asset tools."""

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from .exceptions import ValidationError


def validate_resource_name(name: Any, kind: str) -> str:
    """Reject resource names that can be interpreted as filesystem paths."""
    if name is None:
        raise ValidationError(f"Invalid {kind} name: cannot be empty")

    candidate = str(name)
    if not candidate.strip():
        raise ValidationError(f"Invalid {kind} name: cannot be empty")
    if candidate != candidate.strip():
        # A stripped copy would be checked while the caller writes the original ("My Note "),
        # so the name is refused instead of silently normalised.
        raise ValidationError(f"Invalid {kind} name: {name!r} has leading or trailing whitespace")

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


_ESCAPING_LINK_MESSAGE = "Project contains a filesystem link that escapes the approved project root"
_MULTIPLY_LINKED_MESSAGE = "Project contains a multiply-linked file; external write confinement cannot be proven"


@dataclass(frozen=True)
class ProjectTreeViolation:
    """The first entry that stops a project tree from being provably contained."""

    kind: str
    relative_path: str
    message: str


def _resolves_inside(path: str, root: Path) -> bool:
    try:
        Path(path).resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def find_project_tree_violation(project_root: Path) -> ProjectTreeViolation | None:
    """Return the first link that leaves ``project_root``, which must already be resolved.

    Entries are visited in name order so the same tree always reports the same entry.
    """
    root = Path(project_root)
    root_text = os.fspath(root)
    # Windows junctions and other reparse points are not reported as symlinks, so every
    # directory is resolved there. Elsewhere a directory that is not a symlink cannot leave
    # a resolved root, and resolving each one costs a realpath per directory on every call.
    resolve_directories = os.name == "nt"

    def violation(kind: str, path: str) -> ProjectTreeViolation:
        relative = Path(os.path.relpath(path, root_text)).as_posix()
        message = _ESCAPING_LINK_MESSAGE if kind == "escaping_link" else _MULTIPLY_LINKED_MESSAGE
        return ProjectTreeViolation(kind=kind, relative_path=relative, message=message)

    pending = [root_text]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except OSError:
            # Matches os.walk: a directory that cannot be listed contributes no entries.
            continue
        subdirectories: list[str] = []
        for entry in entries:
            if entry.is_symlink():
                if not _resolves_inside(entry.path, root):
                    return violation("escaping_link", entry.path)
                continue
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_directory = False
            if is_directory:
                if resolve_directories and not _resolves_inside(entry.path, root):
                    return violation("escaping_link", entry.path)
                subdirectories.append(entry.path)
                continue
            try:
                # DirEntry.stat() reports st_nlink as zero on Windows, so ask the filesystem there.
                link_count = (
                    _windows_link_count(entry.path) if os.name == "nt" else entry.stat(follow_symlinks=False).st_nlink
                )
            except FileNotFoundError:
                # Gone since the directory was listed, as a temporary file is once its writer has put
                # it in place (a run's status file, every second). Nothing is left there to judge.
                continue
            if link_count > 1:
                return violation("multiply_linked", entry.path)
        pending.extend(reversed(subdirectories))
    return None


def _windows_link_count(path: str, *, patience_seconds: float = 0.5) -> int:
    """How many names a file has, waiting out the moment in which it is being replaced.

    Windows refuses to look at a file while another process is replacing or deleting it. That
    lasts as long as the replacement does, so the question is asked again for a short while; a
    file that then turns out to be gone raises FileNotFoundError like any other vanished entry,
    and one that stays out of reach still fails the check.
    """
    deadline = time.monotonic() + patience_seconds
    while True:
        try:
            return os.stat(path).st_nlink
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def assert_project_tree_contained(project_root: Path) -> Path:
    """Reject a project containing any symlink whose target leaves the project."""
    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise ValidationError("Invalid project root: expected a directory")

    found = find_project_tree_violation(root)
    if found is not None:
        raise ValidationError(found.message)
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
            raise ValidationError(f"Unsafe private directory: {path}: {issue}")
    return path


def project_file_path(path: Any, *, project_root: Path, kind: str = "metadata path") -> Path:
    target = project_relative_path(path, project_root=project_root, kind=kind)
    if not target.is_file():
        raise ValidationError(f"Invalid {kind}: expected a regular file")
    return target
