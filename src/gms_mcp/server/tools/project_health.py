from __future__ import annotations

import argparse
from typing import Any, Dict, List

from ...update_notifier import check_for_updates
from ..direct import _run_gms_inprocess
from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..output import _apply_output_mode
from ..project import (
    _ensure_cli_on_sys_path,
    _find_yyp_file,
    _resolve_project_directory_no_deps,
    _resolve_repo_root,
)
from ..subprocess_runner import _run_cli_async


def register(mcp: Any, ContextType: Any) -> None:
    # FastMCP evaluates type annotations at runtime (inspect.signature(..., eval_str=True)).
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

        # Check for updates in a separate thread to avoid blocking (best-effort)
        # However, for a quick check, we can just call it.
        # We'll use a 2s timeout in the notifier to keep it snappy.
        update_info = check_for_updates()

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
        import argparse

        return await _run_with_fallback(
            direct_handler=lambda args: health_check(args.project_root),
            direct_args=argparse.Namespace(project_root=project_root),
            cli_args=["maintenance", "health"],
            project_root=project_root,
            prefer_cli=False,
            tool_name="gm-mcp-health",
            ctx=ctx
        )

    @mcp.tool()
    async def gm_cli(
        args: List[str],
        project_root: str = ".",
        prefer_cli: bool = True,
        timeout_seconds: int = 30,
        output_mode: str = "tail",
        tail_lines: int = 120,
        quiet: bool = True,
        fallback_to_subprocess: bool = True,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Run the existing `gms` CLI.

        - If `prefer_cli=true` (default): run in a subprocess with captured output + timeout.
        - If `prefer_cli=false`: try in-process first, and (optionally) fall back to subprocess.
        Example args: ["maintenance", "auto", "--fix", "--verbose"]
        """
        # If prefer_cli=True, run the subprocess path (streamed + cancellable).
        if prefer_cli:
            cli_dict = (
                await _run_cli_async(
                    args,
                    project_root,
                    timeout_seconds=timeout_seconds,
                    tool_name="gm_cli",
                    ctx=ctx,
                )
            ).as_dict()
            return _apply_output_mode(
                cli_dict,
                output_mode=output_mode,
                tail_lines=tail_lines,
                quiet=quiet,
            )

        # Otherwise, attempt in-process first (legacy behavior).
        inprocess_dict = _run_gms_inprocess(args, project_root).as_dict()
        shaped_inprocess = _apply_output_mode(
            inprocess_dict,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )
        if shaped_inprocess.get("ok"):
            return shaped_inprocess

        if not fallback_to_subprocess:
            shaped_inprocess["error"] = shaped_inprocess.get("error") or "In-process gms execution failed"
            return shaped_inprocess

        # Backup: subprocess with timeout (streamed + cancellable).
        cli_dict = (
            await _run_cli_async(
                args,
                project_root,
                timeout_seconds=timeout_seconds,
                tool_name="gm_cli",
                ctx=ctx,
            )
        ).as_dict()
        cli_dict["direct_error"] = shaped_inprocess.get("error") or "In-process gms execution failed"
        return _apply_output_mode(
            cli_dict,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Diagnostic tools
    # -----------------------------
    @mcp.tool()
    async def gm_diagnostics(
        depth: str = "quick",
        include_info: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
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
        return check_for_updates()
