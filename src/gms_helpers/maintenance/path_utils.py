import os
import platform
from functools import lru_cache
from pathlib import Path
from typing import Set, Dict, List, Optional


def _volume_entry_is_case_sensitive(entry: Path) -> bool:
    alternate = entry.with_name(entry.name.swapcase())
    return not alternate.exists() or not alternate.samefile(entry)


@lru_cache(maxsize=64)
def _directory_volume_case_sensitive(absolute_root: str) -> bool:
    """Probe the volume holding ``absolute_root`` (or its nearest existing ancestor) once."""
    candidate = Path(absolute_root).resolve()
    directory = next((d for d in (candidate, *candidate.parents) if d.is_dir()), None)
    if directory is None:
        return False
    device = directory.stat().st_dev
    # Use an existing entry on that volume; read-only diagnostics must not create a
    # temporary probe simply to inspect case sensitivity.
    for current in (directory, *directory.parents):
        if current.stat().st_dev != device:
            break
        if current.name and current.name.swapcase() != current.name:
            return _volume_entry_is_case_sensitive(current)
        for entry in current.iterdir():
            if entry.name.swapcase() != entry.name:
                return _volume_entry_is_case_sensitive(entry)
    return False


def _is_macos_case_sensitive(probe_root: str | Path = ".") -> bool:
    """Detect whether the macOS volume holding ``probe_root`` (default: the working directory) is case-sensitive.

    APFS and HFS+ volumes can each be formatted either way, so the volume holding the project
    decides, never the volume this package is installed on.
    """
    if platform.system().lower() != "darwin":
        return False

    try:
        return _directory_volume_case_sensitive(os.path.abspath(probe_root))
    except Exception:
        # Conservative fallback: assume case-insensitive for compatibility
        return False


def normalize_path(path: str, project_root: str | Path | None = None) -> str:
    """
    Normalize a path for cross-platform comparison.
    On Windows, or case-insensitive macOS filesystems, convert to lowercase
    for case-insensitive comparison. ``project_root`` names the directory whose volume
    decides (default: the working directory, which relative paths are resolved against).
    """
    normalized = str(Path(path)).replace("\\", "/")

    # macOS can be case-sensitive or case-insensitive depending on volume format.
    if platform.system().lower() == "windows" or (
        platform.system().lower() == "darwin" and not _is_macos_case_sensitive(project_root or ".")
    ):
        normalized = normalized.lower()

    return normalized


def build_filesystem_map(root_dir: str) -> Dict[str, str]:
    """
    Build a mapping of normalized paths to actual filesystem paths.
    This allows case-insensitive lookups while preserving actual casing.
    """
    filesystem_map = {}

    for root, dirs, files in os.walk(root_dir):
        # Skip certain directories
        skip_dirs = {".git", "__pycache__", "node_modules", ".vscode"}
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for file in files:
            actual_path = os.path.join(root, file)
            relative_path = os.path.relpath(actual_path, root_dir)
            normalized_path = normalize_path(relative_path, root_dir)
            filesystem_map[normalized_path] = relative_path

    return filesystem_map


def find_file_case_insensitive(
    target_path: str, filesystem_map: Dict[str, str], project_root: str | Path | None = None
) -> Optional[str]:
    """
    Find a file using case-insensitive matching.
    Returns the actual filesystem path if found, None otherwise. Pass the ``project_root`` the
    map was built from so both sides are normalised for the same volume.
    """
    normalized_target = normalize_path(target_path, project_root)
    return filesystem_map.get(normalized_target)


def get_gamemaker_files(root_dir: str) -> Set[str]:
    """
    Get all GameMaker-related files from the filesystem.
    Filters out non-GameMaker files like tools/, docs/, .py files, etc.
    """
    gamemaker_files = set()

    # GameMaker file extensions
    gm_extensions = {".yy", ".yyp", ".gml", ".png", ".jpg", ".jpeg", ".wav", ".mp3", ".ogg", ".fnt", ".ttf"}

    # Directories to skip
    skip_dirs = {
        "tools",
        "docs",
        "__pycache__",
        ".git",
        "node_modules",
        ".vscode",
        "maintenance_keep.txt",
        "maintenance_report.json",
    }

    for root, dirs, files in os.walk(root_dir):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        # Skip if we're in a tools or docs directory
        rel_root = os.path.relpath(root, root_dir)
        if any(skip_part in rel_root.split(os.sep) for skip_part in skip_dirs):
            continue

        for file in files:
            # Skip non-GameMaker files
            if file.startswith(".") or file.endswith(".py") or file.endswith(".md"):
                continue

            file_ext = os.path.splitext(file)[1].lower()
            if file_ext in gm_extensions or file.endswith(".resource_order"):
                actual_path = os.path.join(root, file)
                relative_path = os.path.relpath(actual_path, root_dir)
                gamemaker_files.add(relative_path.replace("\\", "/"))

    return gamemaker_files


def project_relative_parts(path: str | os.PathLike, project_root: str | os.PathLike | None = None) -> tuple[str, ...]:
    """Split a project path (relative or absolute inside ``project_root``) into POSIX parts."""
    text = str(path).replace("\\", "/")
    candidate = Path(text)
    if candidate.is_absolute() and project_root is not None:
        root = Path(project_root)
        for base, target in ((root, candidate), (root.resolve(), candidate.resolve())):
            try:
                candidate = target.relative_to(base)
                break
            except ValueError:
                continue
        else:
            return ()
    return tuple(part for part in candidate.as_posix().split("/") if part and part != ".")


def is_options_path(path: str | os.PathLike, project_root: str | os.PathLike | None = None) -> bool:
    """True when ``path`` lives in the project's top-level ``options/`` directory.

    Only the first project-relative component counts, so a project directory or
    asset whose name merely contains "options" is not mistaken for one.
    """
    parts = project_relative_parts(path, project_root)
    return bool(parts) and parts[0].casefold() == "options"


def find_case_variant(project_root: str | os.PathLike, relative_path: str) -> Optional[str]:
    """Return the on-disk spelling of ``relative_path`` matched case-insensitively.

    Each component is matched against the real directory listing, so the result
    is the actual spelling on case-sensitive and case-insensitive filesystems.
    When several spellings exist (case-sensitive filesystems) the sorted first
    one is returned. Returns ``None`` when no case-insensitive match exists.
    """
    current = Path(project_root)
    actual_parts: List[str] = []
    for part in [p for p in str(relative_path).replace("\\", "/").split("/") if p]:
        try:
            names = os.listdir(current)
        except OSError:
            return None
        if part in names:
            match = part
        else:
            folded = part.casefold()
            candidates = sorted(name for name in names if name.casefold() == folded)
            if not candidates:
                return None
            match = candidates[0]
        actual_parts.append(match)
        current = current / match
    return "/".join(actual_parts) if actual_parts else None
