from __future__ import annotations

import argparse
from typing import Any, Dict

from ..dispatch import _run_for_data
from ..mcp_types import Context


def register(mcp: Any, ContextType: Any, *, read_only: bool = False) -> None:
    globals()["Context"] = ContextType
    mutating_tool = (lambda function: function) if read_only else mcp.tool()

    # -----------------------------
    # Code Intelligence Tools
    # -----------------------------
    @mutating_tool
    async def gm_build_index(
        project_root: str = ".",
        force: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Build or refresh the GML symbol index that the symbol lookups read.

        The lookups build it themselves when needed; this is for doing that ahead of time.

        Args:
            force: Rebuild from scratch instead of updating the files that changed.
        """
        _ = ctx
        from gms_helpers.commands.symbol_commands import handle_build_index

        return await _run_for_data(
            direct_handler=handle_build_index,
            direct_args=argparse.Namespace(project_root=project_root, force=force),
            project_root=project_root,
            tool_name="gm-build-index",
            cli_args=["symbol", "build"],
        )

    @mcp.tool()
    async def gm_find_definition(
        symbol_name: str,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Find where a GML symbol (function, script, enum, enum value, macro, globalvar, constructor) is defined.

        Each definition gives its kind, `at` (file:line), its parameters and its whole doc comment.
        """
        _ = ctx
        from gms_helpers.commands.symbol_commands import handle_find_definition

        return await _run_for_data(
            direct_handler=handle_find_definition,
            direct_args=argparse.Namespace(project_root=project_root, symbol_name=symbol_name),
            project_root=project_root,
            tool_name="gm-find-definition",
            cli_args=["symbol", "find-definition"],
        )

    @mcp.tool()
    async def gm_find_references(
        symbol_name: str,
        project_root: str = ".",
        max_results: int | None = None,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Find every reference to a GML symbol.

        `references` maps each file to its lines that name the symbol, as "<line> <code>";
        `defined_at` names the definition lines among them, and `count` is the number of
        references (a line naming the symbol twice is listed once).

        Args:
            max_results: Keep only the first this many references.
        """
        _ = ctx
        from gms_helpers.commands.symbol_commands import handle_find_references

        return await _run_for_data(
            direct_handler=handle_find_references,
            direct_args=argparse.Namespace(project_root=project_root, symbol_name=symbol_name, max_results=max_results),
            project_root=project_root,
            tool_name="gm-find-references",
            cli_args=["symbol", "find-references"],
        )

    @mcp.tool()
    async def gm_list_symbols(
        project_root: str = ".",
        kind: str | None = None,
        name_filter: str | None = None,
        file_filter: str | None = None,
        max_results: int | None = 100,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List the GML symbols defined in the project, in name order.

        `symbols` maps each kind to its files and each file to "name:line" entries (an enum value
        is written "Enum.value"). `count` is every match; `truncated` says max_results kept fewer.

        Args:
            kind: function, script, enum, enum_value, macro, globalvar or constructor.
            name_filter: Keep symbols whose name contains this text (case-insensitive).
            file_filter: Keep symbols whose file path contains this text (case-insensitive).
            max_results: Keep the first this many (null for every match).
        """
        _ = ctx
        from gms_helpers.commands.symbol_commands import handle_list_symbols

        args = argparse.Namespace(
            project_root=project_root,
            kind=kind,
            name_filter=name_filter,
            file_filter=file_filter,
            max_results=max_results,
        )
        return await _run_for_data(
            direct_handler=handle_list_symbols,
            direct_args=args,
            project_root=project_root,
            tool_name="gm-list-symbols",
            cli_args=["symbol", "list"],
        )
