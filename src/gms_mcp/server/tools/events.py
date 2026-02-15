from __future__ import annotations

import argparse
from typing import Any, Dict

from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..project import _ensure_cli_on_sys_path, _resolve_repo_root


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Event tools
    # -----------------------------
    @mcp.tool()
    async def gm_event_add(
        object: str,
        event: str,
        template: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add an event to an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_add

        args = argparse.Namespace(object=object, event=event, template=template if template else None, project_root=project_root)
        cli_args = ["event", "add", object, event]
        if template:
            cli_args.extend(["--template", template])

        return await _run_with_fallback(
            direct_handler=handle_event_add,
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
    async def gm_event_remove(
        object: str,
        event: str,
        keep_file: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove an event from an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_remove

        args = argparse.Namespace(object=object, event=event, keep_file=keep_file, project_root=project_root)
        cli_args = ["event", "remove", object, event]
        if keep_file:
            cli_args.append("--keep-file")

        return await _run_with_fallback(
            direct_handler=handle_event_remove,
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
    async def gm_event_duplicate(
        object: str,
        source_event: str,
        target_num: int,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an event within an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_duplicate

        args = argparse.Namespace(object=object, source_event=source_event, target_num=target_num, project_root=project_root)
        cli_args = ["event", "duplicate", object, source_event, str(target_num)]

        return await _run_with_fallback(
            direct_handler=handle_event_duplicate,
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
    async def gm_event_list(
        object: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List all events for an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_list

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "list", object]

        return await _run_with_fallback(
            direct_handler=handle_event_list,
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
    async def gm_event_validate(
        object: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Validate object events."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_validate

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "validate", object]

        return await _run_with_fallback(
            direct_handler=handle_event_validate,
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
    async def gm_event_fix(
        object: str,
        safe_mode: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Fix object event issues (safe_mode defaults true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_fix

        args = argparse.Namespace(object=object, safe_mode=safe_mode, project_root=project_root)
        cli_args = ["event", "fix", object]
        if not safe_mode:
            cli_args.append("--no-safe-mode")

        return await _run_with_fallback(
            direct_handler=handle_event_fix,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )
