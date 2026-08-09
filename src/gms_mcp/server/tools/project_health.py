from __future__ import annotations

import argparse
from typing import Any, Dict

from ...update_status import get_update_status
from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..project import (
    _ensure_cli_on_sys_path,
    _find_yyp_file,
    _resolve_project_directory_no_deps,
    _resolve_repo_root,
)
from ..tool_types import OutputMode


def register(mcp: Any, ContextType: Any) -> None:
    # MCPServer evaluates type annotations at runtime (inspect.signature(..., eval_str=True)).
    # Because we use `from __future__ import annotations`, annotations are strings and must be
    # resolvable from the function's *globals* dict. Ensure `Context` is available there.
    globals()["Context"] = ContextType

    @mcp.tool()
    async def gm_project_info(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Resolve GameMaker project directory (where the .yyp lives) and return basic info.
        """
        _ = ctx
        project_directory = _resolve_project_directory_no_deps(project_root)
        update_info = get_update_status().to_dict()

        return {
            "project_directory": str(project_directory),
            "yyp": _find_yyp_file(project_directory),
            "tools_mode": "installed",
            "updates": update_info,
        }

    @mcp.tool()
    async def gm_mcp_health(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
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
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Run project diagnostics and return structured issues.

        Args:
            depth: "quick" runs fast lint checks only; "deep" adds reference
                   analysis, orphan detection, and GML string search.
            include_info: Whether to include info-level diagnostics.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.diagnostics_commands import handle_diagnostics

        args = argparse.Namespace(
            depth=depth,
            include_info=include_info,
            project_root=project_root,
        )
        cli_args = ["diagnostics", "--depth", depth]
        if include_info:
            cli_args.append("--include-info")

        return await _run_with_fallback(
            direct_handler=handle_diagnostics,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_check_updates() -> Dict[str, Any]:
        """Check for newer versions of gms-mcp on PyPI."""
        return get_update_status().to_dict()
