from __future__ import annotations

import argparse
from typing import Any, Dict

from ..debug import _dbg
from ..dispatch import _run_with_fallback
from ..dry_run_policy import _dry_run_policy_blocked_result, _requires_dry_run_for_tool
from ..mcp_types import Context
from ..project import _ensure_cli_on_sys_path, _resolve_repo_root


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Asset creation tools
    # -----------------------------
    @mcp.tool()
    async def gm_create_script(
        name: str,
        parent_path: str = "",
        is_constructor: bool = False,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker script asset."""
        # region agent log
        _dbg(
            "H2",
            "src/gms_mcp/gamemaker_mcp_server.py:gm_create_script:entry",
            "gm_create_script tool entry",
            {
                "name": name,
                "parent_path": parent_path,
                "project_root": project_root,
                "prefer_cli": prefer_cli,
                "skip_maintenance": skip_maintenance,
            },
        )
        # endregion
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="script",
            name=name,
            parent_path=parent_path,
            constructor=is_constructor,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "script",
            name,
            "--parent-path",
            parent_path,
        ]
        if is_constructor:
            cli_args.append("--constructor")
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_object(
        name: str,
        parent_path: str = "",
        sprite_id: str = "",
        parent_object: str = "",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker object asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="object",
            name=name,
            parent_path=parent_path,
            sprite_id=sprite_id or None,
            parent_object=parent_object or None,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "object",
            name,
            "--parent-path",
            parent_path,
        ]
        if sprite_id:
            cli_args.extend(["--sprite-id", sprite_id])
        if parent_object:
            cli_args.extend(["--parent-object", parent_object])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_sprite(
        name: str,
        parent_path: str = "",
        frame_count: int = 1,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker sprite asset with optional multi-frame support.
        
        Args:
            name: Sprite asset name (e.g., spr_player)
            parent_path: Parent folder path (e.g., "folders/Sprites.yy")
            frame_count: Number of animation frames (default: 1)
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sprite",
            name=name,
            parent_path=parent_path,
            frame_count=frame_count,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "sprite",
            name,
            "--parent-path",
            parent_path,
            "--frame-count",
            str(frame_count),
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_room(
        name: str,
        parent_path: str = "",
        width: int = 1024,
        height: int = 768,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker room asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="room",
            name=name,
            parent_path=parent_path,
            width=width,
            height=height,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "room",
            name,
            "--parent-path",
            parent_path,
            "--width",
            str(width),
            "--height",
            str(height),
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_folder(
        name: str,
        path: str,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker folder asset (`folders/My Folder.yy`)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="folder",
            name=name,
            path=path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "folder",
            name,
            "--path",
            path,
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_font(
        name: str,
        parent_path: str = "",
        font_name: str = "Arial",
        size: int = 12,
        bold: bool = False,
        italic: bool = False,
        aa_level: int = 1,
        uses_sdf: bool = True,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker font asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="font",
            name=name,
            parent_path=parent_path,
            font_name=font_name,
            size=size,
            bold=bold,
            italic=italic,
            aa_level=aa_level,
            uses_sdf=uses_sdf,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )

        cli_args = ["asset", "create", "font", name, "--parent-path", parent_path, "--font-name", font_name, "--size", str(size), "--aa-level", str(aa_level)]
        if bold:
            cli_args.append("--bold")
        if italic:
            cli_args.append("--italic")
        cli_args.extend(["--uses-sdf" if uses_sdf else "--no-uses-sdf"])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_shader(
        name: str,
        parent_path: str = "",
        shader_type: int = 1,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a GameMaker shader asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="shader",
            name=name,
            parent_path=parent_path,
            shader_type=shader_type,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "shader", name, "--parent-path", parent_path, "--shader-type", str(shader_type)]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_animcurve(
        name: str,
        parent_path: str = "",
        curve_type: str = "linear",
        channel_name: str = "curve",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create an animation curve asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="animcurve",
            name=name,
            parent_path=parent_path,
            curve_type=curve_type,
            channel_name=channel_name,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "animcurve", name, "--parent-path", parent_path, "--curve-type", curve_type, "--channel-name", channel_name]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_sound(
        name: str,
        parent_path: str = "",
        volume: float = 1.0,
        pitch: float = 1.0,
        sound_type: int = 0,
        bitrate: int = 128,
        sample_rate: int = 44100,
        format: int = 0,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a sound asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sound",
            name=name,
            parent_path=parent_path,
            volume=volume,
            pitch=pitch,
            sound_type=sound_type,
            bitrate=bitrate,
            sample_rate=sample_rate,
            format=format,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "sound",
            name,
            "--parent-path",
            parent_path,
            "--volume",
            str(volume),
            "--pitch",
            str(pitch),
            "--sound-type",
            str(sound_type),
            "--bitrate",
            str(bitrate),
            "--sample-rate",
            str(sample_rate),
            "--format",
            str(format),
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_path(
        name: str,
        parent_path: str = "",
        closed: bool = False,
        precision: int = 4,
        path_type: str = "straight",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a path asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="path",
            name=name,
            parent_path=parent_path,
            closed=closed,
            precision=precision,
            path_type=path_type,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "path", name, "--parent-path", parent_path, "--precision", str(precision), "--path-type", path_type]
        if closed:
            cli_args.append("--closed")
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_tileset(
        name: str,
        parent_path: str = "",
        sprite_id: str = "",
        tile_width: int = 32,
        tile_height: int = 32,
        tile_xsep: int = 0,
        tile_ysep: int = 0,
        tile_xoff: int = 0,
        tile_yoff: int = 0,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a tileset asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="tileset",
            name=name,
            parent_path=parent_path,
            sprite_id=sprite_id or None,
            tile_width=tile_width,
            tile_height=tile_height,
            tile_xsep=tile_xsep,
            tile_ysep=tile_ysep,
            tile_xoff=tile_xoff,
            tile_yoff=tile_yoff,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "tileset",
            name,
            "--parent-path",
            parent_path,
            "--tile-width",
            str(tile_width),
            "--tile-height",
            str(tile_height),
            "--tile-xsep",
            str(tile_xsep),
            "--tile-ysep",
            str(tile_ysep),
            "--tile-xoff",
            str(tile_xoff),
            "--tile-yoff",
            str(tile_yoff),
        ]
        if sprite_id:
            cli_args.extend(["--sprite-id", sprite_id])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_timeline(
        name: str,
        parent_path: str = "",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a timeline asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="timeline",
            name=name,
            parent_path=parent_path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "timeline", name]
        if parent_path:
            cli_args.extend(["--parent-path", parent_path])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_sequence(
        name: str,
        parent_path: str = "",
        length: float = 60.0,
        playback_speed: float = 30.0,
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a sequence asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sequence",
            name=name,
            parent_path=parent_path,
            length=length,
            playback_speed=playback_speed,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "sequence", name]
        if parent_path:
            cli_args.extend(["--parent-path", parent_path])
        cli_args.extend(["--length", str(length), "--playback-speed", str(playback_speed)])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_create_note(
        name: str,
        parent_path: str = "",
        content: str = "",
        skip_maintenance: bool = True,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Create a note asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="note",
            name=name,
            parent_path=parent_path,
            content=content if content else None,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "note", name]
        if parent_path:
            cli_args.extend(["--parent-path", parent_path])
        if content:
            cli_args.extend(["--content", content])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return await _run_with_fallback(
            direct_handler=handle_asset_create,
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
    async def gm_asset_delete(
        asset_type: str,
        name: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Delete an asset (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_delete

        args = argparse.Namespace(
            asset_type=asset_type,
            name=name,
            dry_run=dry_run,
            project_root=project_root,
        )
        cli_args = ["asset", "delete", asset_type, name]
        if dry_run:
            cli_args.append("--dry-run")
        if not dry_run and _requires_dry_run_for_tool("gm_asset_delete"):
            return _dry_run_policy_blocked_result(
                "gm_asset_delete",
                "Use dry_run=true, add gm_asset_delete to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_asset_delete,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )
