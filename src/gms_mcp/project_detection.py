from __future__ import annotations

import os
from pathlib import Path


def _list_yyp_files(directory: Path) -> list[Path]:
    try:
        return sorted(directory.glob("*.yyp"))
    except Exception:
        return []


def _normalize_candidate(raw: str | Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    return candidate


def _search_upwards_for_yyp(start_dir: Path) -> Path | None:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        if _list_yyp_files(candidate):
            return candidate
    return None


def _search_upwards_for_gamemaker_yyp(start_dir: Path) -> Path | None:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        gamemaker_dir = candidate / "gamemaker"
        if gamemaker_dir.is_dir() and _list_yyp_files(gamemaker_dir):
            return gamemaker_dir
    return None


def _resolve_candidate(candidate: Path) -> Path | None:
    if not candidate.exists() or not candidate.is_dir():
        return None

    if _list_yyp_files(candidate):
        return candidate

    gamemaker_dir = candidate / "gamemaker"
    if gamemaker_dir.is_dir() and _list_yyp_files(gamemaker_dir):
        return gamemaker_dir

    found = _search_upwards_for_yyp(candidate)
    if found is not None:
        return found

    return _search_upwards_for_gamemaker_yyp(candidate)


def resolve_project_directory(project_root: str | Path | None = None) -> Path:
    explicit_candidate: Path | None = None
    if project_root is not None:
        project_root_str = str(project_root).strip()
        if project_root_str and project_root_str != ".":
            explicit_candidate = _normalize_candidate(Path(project_root_str))
            resolved = _resolve_candidate(explicit_candidate)
            if resolved is not None:
                return resolved
            raise FileNotFoundError(
                "No GameMaker project (.yyp) found.\n"
                f"Tried: {explicit_candidate}\n"
                "Fix: pass a directory that contains your .yyp, a .yyp file path, or a nested path inside the target project."
            )

    candidates: list[Path] = []
    for env_key in ("GM_PROJECT_ROOT", "PROJECT_ROOT"):
        env_value = os.environ.get(env_key)
        if env_value:
            candidates.append(Path(env_value))

    candidates.append(Path.cwd())

    tried: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        candidate = _normalize_candidate(raw)
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        tried.append(candidate_key)

        resolved = _resolve_candidate(candidate)
        if resolved is not None:
            return resolved

    raise FileNotFoundError(
        "No GameMaker project (.yyp) found.\n"
        f"Tried: {', '.join(tried)}\n"
        "Fix: cd into the directory that contains your .yyp, or pass --project-root, "
        "or set GM_PROJECT_ROOT or PROJECT_ROOT to the absolute path."
    )


def find_yyp_path(project_directory: Path) -> Path | None:
    yyp_files = _list_yyp_files(Path(project_directory))
    return yyp_files[0] if yyp_files else None


def find_yyp_name(project_directory: Path) -> str | None:
    yyp_path = find_yyp_path(project_directory)
    return yyp_path.name if yyp_path is not None else None
