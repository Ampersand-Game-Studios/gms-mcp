from __future__ import annotations

import argparse
from typing import Any, Dict

from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..project import _ensure_cli_on_sys_path, _resolve_project_directory, _resolve_repo_root


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Code Intelligence Tools
    # -----------------------------
    @mcp.tool()
    async def gm_build_index(
        project_root: str = ".",
        force: bool = False,
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Build or rebuild the GML symbol index for code intelligence features.
        
        Args:
            force: If True, rebuild from scratch. If False, use cache if valid.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_build_index

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            force=force,
        )
        
        cli_args = ["symbol", "build"]
        if force:
            cli_args.append("--force")
        
        return await _run_with_fallback(
            direct_handler=handle_build_index,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-build-index",
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_find_definition(
        symbol_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Find definition(s) of a GML symbol (function, enum, macro, globalvar).
        
        Args:
            symbol_name: Name of the symbol to find.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_find_definition

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            symbol_name=symbol_name,
        )
        
        cli_args = ["symbol", "find-definition", symbol_name]
        
        return await _run_with_fallback(
            direct_handler=handle_find_definition,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-find-definition",
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_find_references(
        symbol_name: str,
        project_root: str = ".",
        max_results: int = 50,
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Find all references to a GML symbol.
        
        Args:
            symbol_name: Name of the symbol to find references for.
            max_results: Maximum number of references to return.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_find_references

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            symbol_name=symbol_name,
            max_results=max_results,
        )
        
        cli_args = ["symbol", "find-references", symbol_name, "--max", str(max_results)]
        
        return await _run_with_fallback(
            direct_handler=handle_find_references,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-find-references",
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_list_symbols(
        project_root: str = ".",
        kind: str | None = None,
        name_filter: str | None = None,
        file_filter: str | None = None,
        max_results: int = 100,
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List all GML symbols in the project, optionally filtered.
        
        Args:
            kind: Filter by symbol kind (function, enum, macro, globalvar, constructor).
            name_filter: Filter symbols by name (case-insensitive substring match).
            file_filter: Filter symbols by file path (case-insensitive substring match).
            max_results: Maximum number of symbols to return.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.symbol_commands import handle_list_symbols

        args = argparse.Namespace(
            project_root=_resolve_project_directory(project_root),
            kind=kind,
            name_filter=name_filter,
            file_filter=file_filter,
            max_results=max_results,
        )
        
        cli_args = ["symbol", "list"]
        if kind:
            cli_args.extend(["--kind", kind])
        if name_filter:
            cli_args.extend(["--name", name_filter])
        if file_filter:
            cli_args.extend(["--file", file_filter])
        cli_args.extend(["--max", str(max_results)])
        
        return await _run_with_fallback(
            direct_handler=handle_list_symbols,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            tool_name="gm-list-symbols",
            ctx=ctx,
        )
