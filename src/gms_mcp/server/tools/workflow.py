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
    # Workflow tools
    # -----------------------------
    @mcp.tool()
    async def gm_workflow_duplicate(
        asset_path: str,
        new_name: str,
        yes: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an asset (.yy path relative to project root)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_duplicate

        args = argparse.Namespace(asset_path=asset_path, new_name=new_name, yes=yes, project_root=project_root)
        cli_args = ["workflow", "duplicate", asset_path, new_name]
        if yes:
            cli_args.append("--yes")

        return await _run_with_fallback(
            direct_handler=handle_workflow_duplicate,
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
    async def gm_workflow_rename(
        asset_path: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Rename an asset (.yy path relative to project root)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_rename

        args = argparse.Namespace(asset_path=asset_path, new_name=new_name, project_root=project_root)
        cli_args = ["workflow", "rename", asset_path, new_name]

        return await _run_with_fallback(
            direct_handler=handle_workflow_rename,
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
    async def gm_workflow_delete(
        asset_path: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Delete an asset by .yy path (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_delete

        args = argparse.Namespace(asset_path=asset_path, dry_run=dry_run, project_root=project_root)
        cli_args = ["workflow", "delete", asset_path]
        if dry_run:
            cli_args.append("--dry-run")
        if not dry_run and _requires_dry_run_for_tool("gm_workflow_delete"):
            return _dry_run_policy_blocked_result(
                "gm_workflow_delete",
                "Use dry_run=true, add gm_workflow_delete to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_workflow_delete,
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
    async def gm_workflow_swap_sprite(
        asset_path: str,
        png: str,
        frame: int = 0,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Replace a sprite frame's PNG source.
        
        Args:
            asset_path: Sprite .yy path relative to project root
            png: Path to replacement PNG file
            frame: Frame index to replace (0-indexed, default: 0)
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_swap_sprite

        args = argparse.Namespace(asset_path=asset_path, png=png, frame=frame, project_root=project_root)
        cli_args = ["workflow", "swap-sprite", asset_path, png, "--frame", str(frame)]

        return await _run_with_fallback(
            direct_handler=handle_workflow_swap_sprite,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    # -----------------------------
    # Sprite frame tools
    # -----------------------------
    @mcp.tool()
    async def gm_sprite_add_frame(
        sprite_path: str,
        position: int = -1,
        source_png: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Add a frame to an existing sprite.
        
        Args:
            sprite_path: Sprite .yy path relative to project root
            position: Insert position (0-indexed, -1 = append at end)
            source_png: Optional path to source PNG (creates blank if empty)
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.sprite_commands import handle_sprite_add_frame

        args = argparse.Namespace(
            sprite_path=sprite_path,
            position=position,
            source=source_png if source_png else None,
            project_root=project_root
        )
        cli_args = ["sprite-frames", "add", sprite_path, "--position", str(position)]
        if source_png:
            cli_args.extend(["--source", source_png])

        return await _run_with_fallback(
            direct_handler=handle_sprite_add_frame,
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
    async def gm_sprite_remove_frame(
        sprite_path: str,
        position: int,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove a frame from an existing sprite.
        
        Args:
            sprite_path: Sprite .yy path relative to project root
            position: Frame index to remove (0-indexed)
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.sprite_commands import handle_sprite_remove_frame

        args = argparse.Namespace(
            sprite_path=sprite_path,
            position=position,
            project_root=project_root
        )
        cli_args = ["sprite-frames", "remove", sprite_path, str(position)]

        return await _run_with_fallback(
            direct_handler=handle_sprite_remove_frame,
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
    async def gm_sprite_duplicate_frame(
        sprite_path: str,
        source_position: int,
        target_position: int = -1,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Duplicate an existing frame within a sprite.
        
        Args:
            sprite_path: Sprite .yy path relative to project root
            source_position: Frame index to duplicate (0-indexed)
            target_position: Where to insert duplicate (-1 = after source)
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.sprite_commands import handle_sprite_duplicate_frame

        args = argparse.Namespace(
            sprite_path=sprite_path,
            source_position=source_position,
            target=target_position,
            project_root=project_root
        )
        cli_args = ["sprite-frames", "duplicate", sprite_path, str(source_position), "--target", str(target_position)]

        return await _run_with_fallback(
            direct_handler=handle_sprite_duplicate_frame,
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
    async def gm_sprite_import_strip(
        name: str,
        source: str,
        parent_path: str = "",
        layout: str = "horizontal",
        frame_width: int = 0,
        frame_height: int = 0,
        columns: int = 0,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Import a sprite strip or spritesheet as a new GameMaker sprite.
        
        Args:
            name: Sprite name to create
            source: Path to source PNG strip/sheet
            parent_path: Parent folder path (e.g., "folders/Sprites.yy")
            layout: Strip layout - "horizontal", "vertical", or "grid"
            frame_width: Frame width in pixels (0 = auto-detect)
            frame_height: Frame height in pixels (0 = auto-detect)
            columns: Number of columns for grid layout (0 = auto-detect)
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.sprite_commands import handle_sprite_import_strip

        args = argparse.Namespace(
            name=name,
            source=source,
            parent_path=parent_path,
            layout=layout,
            frame_width=frame_width if frame_width > 0 else None,
            frame_height=frame_height if frame_height > 0 else None,
            columns=columns if columns > 0 else None,
            project_root=project_root
        )
        cli_args = ["sprite-frames", "import-strip", name, source, "--parent-path", parent_path, "--layout", layout]
        if frame_width > 0:
            cli_args.extend(["--frame-width", str(frame_width)])
        if frame_height > 0:
            cli_args.extend(["--frame-height", str(frame_height)])
        if columns > 0:
            cli_args.extend(["--columns", str(columns)])

        return await _run_with_fallback(
            direct_handler=handle_sprite_import_strip,
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
    async def gm_sprite_frame_count(
        sprite_path: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Get the frame count for a sprite.
        
        Args:
            sprite_path: Sprite .yy path relative to project root
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.sprite_commands import handle_sprite_frame_count

        args = argparse.Namespace(
            sprite_path=sprite_path,
            project_root=project_root
        )
        cli_args = ["sprite-frames", "count", sprite_path]

        return await _run_with_fallback(
            direct_handler=handle_sprite_frame_count,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )
