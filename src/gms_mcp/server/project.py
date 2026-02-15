from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


def _list_yyp_files(directory: Path) -> List[Path]:
    try:
        return sorted(directory.glob("*.yyp"))
    except Exception:
        return []


def _search_upwards_for_yyp(start_dir: Path) -> Optional[Path]:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        if _list_yyp_files(candidate):
            return candidate
    return None


def _search_upwards_for_gamemaker_yyp(start_dir: Path) -> Optional[Path]:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        gm = candidate / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm
    return None


def _resolve_project_directory_no_deps(project_root: str | None) -> Path:
    """
    Resolve the GameMaker project directory (the folder containing a .yyp)
    without importing `gms_helpers` (so we don't need to know repo root yet).
    """
    candidates: List[Path] = []
    if project_root is not None:
        root_str = str(project_root).strip()
        if root_str and root_str != ".":
            candidates.append(Path(root_str))

    # Environment overrides (handy for agents)
    env_gm_root = os.environ.get("GM_PROJECT_ROOT")
    if env_gm_root:
        candidates.append(Path(env_gm_root))
    env_root = os.environ.get("PROJECT_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(Path.cwd())

    tried: List[str] = []
    for raw in candidates:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        if p.is_file():
            p = p.parent
        tried.append(str(p))
        if not p.exists() or not p.is_dir():
            continue

        if _list_yyp_files(p):
            return p

        gm = p / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm

        found = _search_upwards_for_yyp(p)
        if found:
            return found

        found_gm = _search_upwards_for_gamemaker_yyp(p)
        if found_gm:
            return found_gm

    raise FileNotFoundError(
        "Could not find a GameMaker project directory (.yyp) from the provided project_root or CWD. "
        f"Tried: {tried}"
    )


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
    # Prefer in-repo resolution (no imports) so server doesn't depend on process CWD.
    return _resolve_project_directory_no_deps(project_root)


def _find_yyp_file(project_directory: Path) -> Optional[str]:
    try:
        yyp_files = sorted(project_directory.glob("*.yyp"))
        if not yyp_files:
            return None
        return yyp_files[0].name
    except Exception:
        return None

