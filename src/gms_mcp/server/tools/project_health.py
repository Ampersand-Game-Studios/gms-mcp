from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Annotated, Any, Dict

from pydantic import Field

from ...update_status import get_update_status
from ..dispatch import _run_for_data
from ..mcp_types import Context
from ...project_detection import safe_git_command
from ..project import (
    _SERVER_START_DIRECTORY,
    _find_yyp_file,
    _resolve_project_directory_no_deps,
    configured_project_root,
)


ProjectRootHeader = Annotated[
    str,
    Field(json_schema_extra={"x-mcp-header": "project-root"}),
]


def _git_lines(directory: Path, *args: str) -> list[str]:
    try:
        completed = subprocess.run(
            safe_git_command(directory, *args),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return completed.stdout.splitlines() if completed.returncode == 0 else []


def _workspace_identity(project_directory: Path) -> Dict[str, Any]:
    """Identify the pinned checkout by names an agent can compare with its own, never a host path."""
    try:
        project_folder = project_directory.resolve().relative_to(_SERVER_START_DIRECTORY).as_posix()
    except ValueError:
        project_folder = None
    # "project_folder" is the project's place inside the workspace ("." when they are the same).
    identity: Dict[str, Any] = {"folder": _SERVER_START_DIRECTORY.name, "project_folder": project_folder}
    branch = _git_lines(project_directory, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git_lines(project_directory, "rev-parse", "--short", "HEAD")
    git_dirs = _git_lines(project_directory, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    if branch and commit and len(git_dirs) == 2:
        identity["git_branch"] = branch[0].strip()
        identity["git_commit"] = commit[0].strip()
        # A linked worktree keeps its own git directory beside the repository's shared one.
        identity["git_linked_worktree"] = Path(git_dirs[0]) != Path(git_dirs[1])
    return identity


def register(mcp: Any, ContextType: Any) -> None:
    # MCPServer evaluates type annotations at runtime (inspect.signature(..., eval_str=True)).
    # Because we use `from __future__ import annotations`, annotations are strings and must be
    # resolvable from the function's *globals* dict. Ensure `Context` is available there.
    globals()["Context"] = ContextType

    @mcp.tool()
    def gm_project_info(project_root: ProjectRootHeader = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Start here: say which GameMaker project and checkout this server is pinned to.

        Returns the project name, where it sits inside the workspace the server was started in, the
        git branch and commit of that checkout (so a session in a worktree can confirm the tools act
        on its own copy), asset counts by type, the room the game starts in, the enabled and
        disabled toolsets, a guide to the tools by task, and any notice about how the project was
        chosen.
        """
        _ = ctx
        project_directory = _resolve_project_directory_no_deps(project_root)
        yyp = _find_yyp_file(project_directory)
        updates = get_update_status(persist=False).to_dict()
        update_keys = ["status", "message", "current_version", "latest_version", "update_available"]
        if updates.get("update_available"):
            update_keys.append("upgrade_command")
        from gms_helpers.introspection import get_project_stats, room_order

        from gms_helpers.operation_policy import read_only_mode_enabled

        from ..register_all import enabled_toolsets, optional_toolsets
        from .capabilities import tool_guide

        stats = get_project_stats(project_directory)
        rooms = room_order(project_directory)
        enabled = enabled_toolsets()
        notice = configured_project_root()[1]
        return {
            "ok": True,
            "project": Path(yyp).stem if yyp else None,
            "yyp": yyp,
            "project_directory": str(project_directory),
            "workspace": _workspace_identity(project_directory),
            "assets": {
                "total": stats.get("total_resources"),
                "by_type": stats.get("counts_by_type"),
                "folders": stats.get("total_folders"),
            },
            "rooms": {"first": rooms[0] if rooms else None, "order": rooms},
            "toolsets": {
                "enabled": list(enabled),
                "disabled": [name for name in optional_toolsets() if name not in enabled],
            },
            "notices": [notice] if notice else [],
            "guide": tool_guide(enabled=enabled, read_only=read_only_mode_enabled()),
            "version": updates.get("current_version"),
            **(
                {"updates": {key: updates[key] for key in update_keys if key in updates}}
                if updates.get("update_available") or "current_version" not in updates
                else {}
            ),
        }

    @mcp.tool()
    def gm_mcp_health(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Perform a comprehensive health check of the GameMaker development environment.
        Verifies project validity, GameMaker runtimes/Igor, licenses, and Python dependencies.
        """
        from gms_helpers.health import gm_mcp_health as health_check

        _ = ctx
        result = health_check(project_root)
        payload = result.to_dict()
        payload["ok"] = payload.pop("success")
        return payload

    # -----------------------------
    # Diagnostic tools
    # -----------------------------
    @mcp.tool()
    async def gm_diagnostics(
        depth: str = "quick",
        include_info: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Check the project for problems and return every one found.

        `issues` groups them: each problem's message once, with everything it applies to. In a
        message, {name} is the affected file's own name. `assets` maps a folder to asset names
        whose files are <folder>/<name>/<name>.yy; `files` maps a folder to other file names in it
        (name:line when the problem has a line). `summary` counts them by severity.

        Args:
            depth: "quick" runs fast lint checks only; "deep" adds reference
                   analysis, orphan detection, and GML string search.
            include_info: Whether to include info-level diagnostics.
        """
        _ = ctx
        from gms_helpers.commands.diagnostics_commands import dense_diagnostics, handle_diagnostics

        args = argparse.Namespace(depth=depth, include_info=include_info, project_root=project_root)
        return await _run_for_data(
            direct_handler=handle_diagnostics,
            direct_args=args,
            project_root=project_root,
            tool_name="diagnostics",
            cli_args=["diagnostics", "--depth", depth],
            shape=dense_diagnostics,
        )

    @mcp.tool()
    def gm_check_updates() -> Dict[str, Any]:
        """Check for newer versions of gms-mcp on PyPI."""
        return get_update_status(persist=False).to_dict()
