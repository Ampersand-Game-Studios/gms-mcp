from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


def _project_identifier(project_directory: Path) -> str:
    resolved = project_directory.expanduser().resolve(strict=False)
    normalized = os.path.normcase(str(resolved))
    return hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.expanduser().resolve(strict=False).relative_to(directory.expanduser().resolve(strict=False))
    except ValueError:
        return False
    return True


def _make_private_directory(path: Path) -> Path:
    path.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    try:
        path.chmod(_PRIVATE_DIRECTORY_MODE)
    except OSError:
        pass
    return path


def _candidate_roots(project_directory: Path) -> tuple[Path, ...]:
    home_root = Path.home() / ".gms-mcp"
    fallback_owner = hashlib.sha256(str(Path.home()).encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    temp_root = Path(tempfile.gettempdir()) / f"gms-mcp-{fallback_owner}"
    return tuple(root for root in (home_root, temp_root) if not _is_within(root, project_directory))


def diagnostic_log_dir(project_directory: Path) -> Path:
    """Return a private, opaque diagnostic directory outside the project."""
    project_id = _project_identifier(project_directory)
    last_error: OSError | None = None
    for root in _candidate_roots(project_directory):
        try:
            private_root = _make_private_directory(root)
            logs_root = _make_private_directory(private_root / "logs")
            return _make_private_directory(logs_root / project_id)
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError("No diagnostic log location is available outside the GameMaker project.")


def secure_private_file(path: Path) -> None:
    """Create a private file if needed and restrict it to the current user."""
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, _PRIVATE_FILE_MODE)
    os.close(descriptor)
    try:
        path.chmod(_PRIVATE_FILE_MODE)
    except OSError:
        pass
