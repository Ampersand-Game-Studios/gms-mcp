from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from ..project_detection import (
    _list_yyp_files as _shared_list_yyp_files,
    _search_upwards_for_gamemaker_yyp as _shared_search_upwards_for_gamemaker_yyp,
    _search_upwards_for_yyp as _shared_search_upwards_for_yyp,
    find_yyp_name,
    resolve_project_directory,
)


# Direct helpers temporarily change the process cwd.  Project arguments received
# by the long-running MCP server must therefore be anchored to the directory in
# which the server started, never to whatever transient cwd another tool owns.
_SERVER_START_DIRECTORY = Path.cwd().resolve()


def _stable_project_candidate(project_root: str | None) -> Path:
    raw = str(project_root or "").strip()
    if not raw or raw == ".":
        raw = next(
            (value for key in ("GM_PROJECT_ROOT", "PROJECT_ROOT") if (value := os.environ.get(key))),
            str(_SERVER_START_DIRECTORY),
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = _SERVER_START_DIRECTORY / candidate
    return candidate.resolve()


def _list_yyp_files(directory: Path) -> list[Path]:
    return _shared_list_yyp_files(directory)


def _search_upwards_for_yyp(start_dir: Path) -> Path | None:
    return _shared_search_upwards_for_yyp(start_dir)


def _search_upwards_for_gamemaker_yyp(start_dir: Path) -> Path | None:
    return _shared_search_upwards_for_gamemaker_yyp(start_dir)


def _resolve_project_directory_no_deps(project_root: str | None) -> Path:
    return resolve_project_directory(_stable_project_candidate(project_root))


def _resolve_repo_root(project_root: str | None) -> Path:
    """
    Resolve the project root path.

    If project_root is provided, resolve it to an absolute path.
    Otherwise, use the current working directory.
    """
    return _stable_project_candidate(project_root)


def _cli_package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_cli_on_sys_path(_repo_root: Path) -> None:
    package_root = str(_cli_package_root())
    if package_root not in sys.path:
        sys.path.insert(0, package_root)


def _with_cli_pythonpath(env: dict[str, str] | None) -> dict[str, str]:
    merged = dict(env or os.environ)
    package_root = str(_cli_package_root())
    current = merged.get("PYTHONPATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    if package_root not in parts:
        merged["PYTHONPATH"] = os.pathsep.join([package_root, *parts]) if parts else package_root
    return merged


def _resolve_project_directory(project_root: str | None) -> Path:
    return resolve_project_directory(_stable_project_candidate(project_root))


def _find_yyp_file(project_directory: Path) -> Optional[str]:
    try:
        return find_yyp_name(project_directory)
    except Exception:
        return None
