from __future__ import annotations

import argparse
from typing import Annotated, Any, Dict

from pydantic import Field

from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..project import _ensure_cli_on_sys_path, _resolve_repo_root
from ..tool_types import OutputMode


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Event tools
    # -----------------------------
    @mcp.tool()
    async def gm_event_add(
        object: str,
        event: Annotated[
            str,
            Field(
                description=(
                    'The event: "create", "step", "begin_step", "end_step", "draw", "draw_gui", "destroy", '
                    '"cleanup", "room_start", "alarm:0", "collision:o_wall", "user_event_0", or type:number.'
                )
            ),
        ],
        template: Annotated[str, Field(description="The event's GML code (the text itself, not a filename).")] = "",
        overwrite: Annotated[
            bool,
            Field(description="Replace the code of an event that already exists with `template`."),
        ] = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add an event to an object, or set an existing event's code.

        `template` is the event's GML. If the event already exists: a generated placeholder (such
        as the Create event a new object starts with) is filled in; real code is replaced only with
        `overwrite=true`, otherwise the call fails and nothing is written.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_add

        args = argparse.Namespace(
            object=object,
            event=event,
            template=template if template else None,
            overwrite=overwrite,
            project_root=project_root,
        )
        cli_args = ["event", "add"]
        if template:
            cli_args.append(f"--template={template}")
        if overwrite:
            cli_args.append("--overwrite")
        cli_args.extend(["--", object, event])

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
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove an event from an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_remove

        args = argparse.Namespace(object=object, event=event, keep_file=keep_file, project_root=project_root)
        cli_args = ["event", "remove"]
        if keep_file:
            cli_args.append("--keep-file")
        cli_args.extend(["--", object, event])

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
        target_event: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an event within an object using full source and target event specifications."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_duplicate

        args = argparse.Namespace(
            object=object, source_event=source_event, target_event=target_event, project_root=project_root
        )
        cli_args = ["event", "duplicate", "--", object, source_event, target_event]

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
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List all events for an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_list

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "list", "--", object]

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
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Check that an object's event files and its .yy event list agree, and report any mismatch."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_validate

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "validate", "--", object]

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
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Fix object event issues (safe_mode defaults true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_fix

        args = argparse.Namespace(object=object, safe_mode=safe_mode, project_root=project_root)
        cli_args = ["event", "fix"]
        if not safe_mode:
            cli_args.append("--no-safe-mode")
        cli_args.extend(["--", object])

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
