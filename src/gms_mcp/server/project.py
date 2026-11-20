from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
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


class ProjectAccessError(ValueError):
    """Raised when an MCP request tries to leave the server's pinned project."""


_NOTICE_NO_ACTION = (
    "This session is working normally. To remove this notice, give the client config a root that "
    'exists, such as "${CLAUDE_PROJECT_DIR:-.}/<folder>".'
)
_UNEXPANDED_VARIABLE = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*")


def configured_project_root() -> tuple[Path, str | None]:
    """Return the folder the client pointed this server at, and a notice if its setting was unusable.

    Clients build GM_PROJECT_ROOT from their own variables, for example "${CLAUDE_PROJECT_DIR}/game".
    A client that does not define the variable passes "/game" or the text unexpanded, and the server
    would refuse to start with nothing but "connection closed" for the agent to go on. The part after
    the variable still says where the project is inside the workspace the server was started in, so it
    is tried there before the workspace itself.
    """
    raw = str(os.environ.get("GM_PROJECT_ROOT") or "").strip()
    if not raw:
        return _SERVER_START_DIRECTORY, None
    unexpanded = _UNEXPANDED_VARIABLE.search(raw) is not None
    if not unexpanded:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = _SERVER_START_DIRECTORY / candidate
        if candidate.exists():
            return candidate, None
    remainder = _UNEXPANDED_VARIABLE.sub("", raw).replace("\\", "/").strip("/")
    inside_workspace = _SERVER_START_DIRECTORY / remainder if remainder and ".." not in Path(remainder).parts else None
    reason = (
        "GM_PROJECT_ROOT contains a variable the client did not expand"
        if unexpanded
        else "GM_PROJECT_ROOT names a folder that does not exist"
    )
    if inside_workspace is not None and inside_workspace.is_dir():
        return inside_workspace, (
            f"{reason}; using `{Path(remainder).as_posix()}` inside the folder the server was started in. "
            f"{_NOTICE_NO_ACTION}"
        )
    return _SERVER_START_DIRECTORY, (
        f"{reason}; using the project found from the folder the server was started in. {_NOTICE_NO_ACTION}"
    )


def _server_default_candidate() -> Path:
    """Resolve the one project candidate captured when the server starts."""
    return configured_project_root()[0]


def _lexical_server_path(raw: str | Path) -> Path:
    """Anchor and normalize a caller path without following symlinks."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = _SERVER_START_DIRECTORY / candidate
    return Path(os.path.abspath(candidate))


@dataclass(frozen=True)
class ProjectAccessPolicy:
    """One immutable GameMaker project boundary for an MCP server process."""

    project_root: Path
    lexical_root: Path

    @classmethod
    def from_server_environment(cls) -> "ProjectAccessPolicy":
        from gms_helpers.path_safety import assert_project_tree_contained

        default_candidate = _server_default_candidate()
        project_root = resolve_project_directory(default_candidate).resolve(strict=True)
        assert_project_tree_contained(project_root)
        return cls(project_root=project_root, lexical_root=_lexical_server_path(default_candidate))

    def authorize(self, project_root: str | None) -> Path:
        """Resolve a request to the pinned project or reject it without echoing paths."""
        from gms_helpers.exceptions import ValidationError
        from gms_helpers.path_safety import assert_project_tree_contained

        raw = str(project_root or "").strip()
        if not raw or raw == ".":
            candidate = self.project_root
        else:
            lexical_candidate = _lexical_server_path(raw)
            try:
                if not (
                    lexical_candidate.is_relative_to(self.lexical_root)
                    or lexical_candidate.is_relative_to(self.project_root)
                ):
                    raise ValueError
            except ValueError:
                raise ProjectAccessError(
                    "Project access denied: the requested path is outside this server's approved project."
                ) from None
            candidate = lexical_candidate

        try:
            resolved_project = resolve_project_directory(candidate).resolve(strict=True)
        except (FileNotFoundError, OSError, ValueError):
            raise ProjectAccessError(
                "Project access denied: the requested project is unavailable or invalid."
            ) from None

        if resolved_project != self.project_root:
            raise ProjectAccessError(
                "Project access denied: the requested path resolves to a different GameMaker project."
            )
        try:
            assert_project_tree_contained(self.project_root)
        except (OSError, ValueError, ValidationError):
            raise ProjectAccessError(
                "Project access denied: the approved project contains an unsafe filesystem link."
            ) from None
        return self.project_root


def _stable_project_candidate(project_root: str | None) -> Path:
    raw = str(project_root or "").strip()
    if not raw or raw == ".":
        return configured_project_root()[0].resolve()
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
