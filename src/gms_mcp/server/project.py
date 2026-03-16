from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..project_detection import (
    _list_yyp_files as _shared_list_yyp_files,
    _search_upwards_for_gamemaker_yyp as _shared_search_upwards_for_gamemaker_yyp,
    _search_upwards_for_yyp as _shared_search_upwards_for_yyp,
    find_yyp_name,
    resolve_project_directory,
)


def _list_yyp_files(directory: Path) -> list[Path]:
    return _shared_list_yyp_files(directory)


def _search_upwards_for_yyp(start_dir: Path) -> Path | None:
    return _shared_search_upwards_for_yyp(start_dir)


def _search_upwards_for_gamemaker_yyp(start_dir: Path) -> Path | None:
    return _shared_search_upwards_for_gamemaker_yyp(start_dir)


def _resolve_project_directory_no_deps(project_root: str | None) -> Path:
    return resolve_project_directory(project_root)


def _resolve_repo_root(project_root: str | None) -> Path:
    """
    Resolve the project root path.

    If project_root is provided, resolve it to an absolute path.
    Otherwise, use the current working directory.
    """
    if project_root:
        return Path(project_root).resolve()
    return Path.cwd()


def _ensure_cli_on_sys_path(_repo_root: Path) -> None:
    # Compatibility shim (no-op in installed mode).
    return None


def _resolve_project_directory(project_root: str | None) -> Path:
    return resolve_project_directory(project_root)


def _find_yyp_file(project_directory: Path) -> Optional[str]:
    try:
        return find_yyp_name(project_directory)
    except Exception:
        return None
