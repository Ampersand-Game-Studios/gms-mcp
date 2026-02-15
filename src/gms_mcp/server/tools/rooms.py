from __future__ import annotations

import argparse
from typing import Any, Dict

from ..dispatch import _run_with_fallback
from ..dry_run_policy import _dry_run_policy_blocked_result, _requires_dry_run_for_tool
from ..mcp_types import Context
from ..project import _ensure_cli_on_sys_path, _resolve_repo_root


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Room tools
    # -----------------------------
    @mcp.tool()
    async def gm_room_ops_duplicate(
        source_room: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an existing room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_duplicate

        args = argparse.Namespace(source_room=source_room, new_name=new_name, project_root=project_root)
        cli_args = ["room", "ops", "duplicate", source_room, new_name]

        return await _run_with_fallback(
            direct_handler=handle_room_duplicate,
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
    async def gm_room_ops_rename(
        room_name: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Rename an existing room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_rename

        args = argparse.Namespace(room_name=room_name, new_name=new_name, project_root=project_root)
        cli_args = ["room", "ops", "rename", room_name, new_name]

        return await _run_with_fallback(
            direct_handler=handle_room_rename,
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
    async def gm_room_ops_delete(
        room_name: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Delete a room (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_delete

        args = argparse.Namespace(room_name=room_name, dry_run=dry_run, project_root=project_root)
        cli_args = ["room", "ops", "delete", room_name]
        if dry_run:
            cli_args.append("--dry-run")
        if not dry_run and _requires_dry_run_for_tool("gm_room_ops_delete"):
            return _dry_run_policy_blocked_result(
                "gm_room_ops_delete",
                "Use dry_run=true, add gm_room_ops_delete to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_room_delete,
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
    async def gm_room_ops_list(
        verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List rooms."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_list

        args = argparse.Namespace(verbose=verbose, project_root=project_root)
        cli_args = ["room", "ops", "list"]
        if verbose:
            cli_args.append("--verbose")

        return await _run_with_fallback(
            direct_handler=handle_room_list,
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
    async def gm_room_layer_add(
        room_name: str,
        layer_type: str,
        layer_name: str,
        depth: int = 0,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add a layer to a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_add

        args = argparse.Namespace(room_name=room_name, layer_type=layer_type, layer_name=layer_name, depth=depth, project_root=project_root)
        cli_args = ["room", "layer", "add", room_name, layer_type, layer_name]
        if depth:
            cli_args.extend(["--depth", str(depth)])

        return await _run_with_fallback(
            direct_handler=handle_room_layer_add,
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
    async def gm_room_layer_remove(
        room_name: str,
        layer_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove a layer from a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_remove

        args = argparse.Namespace(room_name=room_name, layer_name=layer_name, project_root=project_root)
        cli_args = ["room", "layer", "remove", room_name, layer_name]

        return await _run_with_fallback(
            direct_handler=handle_room_layer_remove,
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
    async def gm_room_layer_list(
        room_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List layers in a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_list

        args = argparse.Namespace(room_name=room_name, project_root=project_root)
        cli_args = ["room", "layer", "list", room_name]

        return await _run_with_fallback(
            direct_handler=handle_room_layer_list,
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
    async def gm_room_instance_add(
        room_name: str,
        object_name: str,
        x: float,
        y: float,
        layer: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add an object instance to a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_add

        args = argparse.Namespace(room_name=room_name, object_name=object_name, x=x, y=y, layer=layer if layer else None, project_root=project_root)
        cli_args = ["room", "instance", "add", room_name, object_name, str(x), str(y)]
        if layer:
            cli_args.extend(["--layer", layer])

        return await _run_with_fallback(
            direct_handler=handle_room_instance_add,
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
    async def gm_room_instance_remove(
        room_name: str,
        instance_id: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove an instance from a room by instance id."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_remove

        args = argparse.Namespace(room_name=room_name, instance_id=instance_id, project_root=project_root)
        cli_args = ["room", "instance", "remove", room_name, instance_id]

        return await _run_with_fallback(
            direct_handler=handle_room_instance_remove,
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
    async def gm_room_instance_list(
        room_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """List instances in a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_list

        args = argparse.Namespace(room_name=room_name, project_root=project_root)
        cli_args = ["room", "instance", "list", room_name]

        return await _run_with_fallback(
            direct_handler=handle_room_instance_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )
