from __future__ import annotations

import os
import subprocess
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


def _git_workspace_root(directory: Path) -> Path | None:
    resolved_directory = directory.resolve()
    for candidate in [resolved_directory, *resolved_directory.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _tracked_yyp_paths(directory: Path) -> list[Path] | None:
    """Return safe, tracked, non-prefab projects, or ``None`` when Git fails."""
    if not (directory / ".git").exists():
        return []
    workspace_root = directory.resolve()
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), "ls-files", "-z", "--", "*.yyp"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    tracked: list[Path] = []
    for raw_path in completed.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if not raw_path:
            continue
        relative = Path(raw_path)
        if any(part.casefold() == "prefabs" for part in relative.parts):
            continue
        if relative.is_absolute():
            continue
        candidate = (workspace_root / relative).resolve()
        if not candidate.is_relative_to(workspace_root):
            continue
        if candidate.is_file():
            tracked.append(candidate)
    return tracked


def _single_tracked_nested_yyp_directory(directory: Path) -> Path | None:
    """Resolve one tracked nested project when the MCP starts at a Git workspace root."""
    tracked = _tracked_yyp_paths(directory)
    if tracked is None:
        return None
    if len(tracked) != 1:
        return None
    return tracked[0].parent.resolve()


def _resolve_candidate(
    candidate: Path,
    *,
    requested_yyp: Path | None = None,
    allow_untracked_direct: bool = False,
) -> Path | None:
    if not candidate.exists() or not candidate.is_dir():
        return None

    # A Git workspace is authoritative: only a single tracked, non-prefab
    # project may be selected. Do not fall back to arbitrary filesystem matches
    # or traverse beyond a nested workspace boundary.
    workspace_root = _git_workspace_root(candidate)
    if workspace_root is not None:
        tracked = _tracked_yyp_paths(workspace_root)
        if tracked is None:
            return None
        direct_yyp_files = _list_yyp_files(candidate)
        if requested_yyp is not None:
            requested_yyp = requested_yyp.resolve()
            if (
                len(direct_yyp_files) == 1
                and direct_yyp_files[0].resolve() == requested_yyp
                and not any(part.casefold() == "prefabs" for part in requested_yyp.parts)
                and (requested_yyp in tracked or allow_untracked_direct)
            ):
                return requested_yyp.parent
            return None
        direct_tracked = [path for path in direct_yyp_files if path.resolve() in tracked]
        if len(direct_yyp_files) == 1 and len(direct_tracked) == 1:
            return candidate.resolve()
        if (
            allow_untracked_direct
            and len(direct_yyp_files) == 1
            and not any(part.casefold() == "prefabs" for part in direct_yyp_files[0].parts)
        ):
            return candidate.resolve()
        if direct_yyp_files:
            return None

        project_directories = sorted({path.parent.resolve() for path in tracked})

        def _is_unambiguous_project(directory: Path) -> bool:
            project_files = _list_yyp_files(directory)
            return len(project_files) == 1 and project_files[0].resolve() in tracked

        containing_projects = [path for path in project_directories if candidate.resolve().is_relative_to(path)]
        if containing_projects:
            selected = max(containing_projects, key=lambda path: len(path.parts))
            return selected if _is_unambiguous_project(selected) else None
        nested_projects = [path for path in project_directories if path.is_relative_to(candidate.resolve())]
        if len(nested_projects) == 1 and _is_unambiguous_project(nested_projects[0]):
            return nested_projects[0]
        return None

    if _list_yyp_files(candidate):
        return candidate

    gamemaker_dir = candidate / "gamemaker"
    if gamemaker_dir.is_dir() and _list_yyp_files(gamemaker_dir):
        return gamemaker_dir

    tracked_project = _single_tracked_nested_yyp_directory(candidate)
    if tracked_project is not None:
        return tracked_project

    found = _search_upwards_for_yyp(candidate)
    if found is not None:
        return found

    return _search_upwards_for_gamemaker_yyp(candidate)


def resolve_project_directory(project_root: str | Path | None = None) -> Path:
    explicit_candidate: Path | None = None
    if project_root is not None:
        project_root_str = str(project_root).strip()
        if project_root_str and project_root_str != ".":
            raw_candidate = Path(project_root_str).expanduser()
            if not raw_candidate.is_absolute():
                raw_candidate = (Path.cwd() / raw_candidate).resolve()
            requested_yyp = (
                raw_candidate.resolve()
                if raw_candidate.is_file() and raw_candidate.suffix.casefold() == ".yyp"
                else None
            )
            explicit_candidate = _normalize_candidate(raw_candidate)
            resolved = _resolve_candidate(
                explicit_candidate,
                requested_yyp=requested_yyp,
                allow_untracked_direct=True,
            )
            if resolved is not None:
                return resolved
            raise FileNotFoundError(
                "No GameMaker project (.yyp) found.\n"
                f"Tried: {explicit_candidate}\n"
                "Fix: pass a directory that contains your .yyp, a .yyp file path, or a nested path inside the target project."
            )

    candidates: list[tuple[Path, bool]] = []
    for env_key in ("GM_PROJECT_ROOT", "PROJECT_ROOT"):
        env_value = os.environ.get(env_key)
        if env_value:
            candidates.append((Path(env_value), True))

    candidates.append((Path.cwd(), False))

    tried: list[str] = []
    seen: set[str] = set()
    for raw, allow_untracked_direct in candidates:
        candidate = _normalize_candidate(raw)
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        tried.append(candidate_key)

        resolved = _resolve_candidate(candidate, allow_untracked_direct=allow_untracked_direct)
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
