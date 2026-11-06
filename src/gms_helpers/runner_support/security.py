from __future__ import annotations

import os
import stat
from pathlib import Path


def private_directory(path: Path) -> Path:
    """Create private build directories and reject unsafe existing components."""
    if os.name == "nt":
        from ..exceptions import ValidationError
        from ..path_safety import private_directory as checked_directory

        try:
            return checked_directory(path)
        except ValidationError as exc:
            raise OSError(str(exc)) from exc
    if path.is_symlink():
        raise OSError(f"Refusing symlink directory: {path}")
    if not path.exists():
        if not path.parent.exists():
            private_directory(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise OSError(f"Not a private directory: {path}")
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise OSError(f"Unsafe directory ownership or permissions: {path}")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)
    return path
