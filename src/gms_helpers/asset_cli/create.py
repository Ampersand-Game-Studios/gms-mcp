from __future__ import annotations

from pathlib import Path

from ..asset_creation_flow import create_project_asset, run_post_creation_maintenance, run_pre_creation_maintenance
from ..asset_types import (
    AnimCurveAsset,
    FolderAsset,
    FontAsset,
    NoteAsset,
    ObjectAsset,
    PathAsset,
    RoomAsset,
    ScriptAsset,
    SequenceAsset,
    ShaderAsset,
    SoundAsset,
    SpriteAsset,
    TileSetAsset,
    TimelineAsset,
)
from .context import validate_asset_directory_structure


def create_script(args):
    """Create a new script asset."""
    try:
        gamemaker_root = validate_asset_directory_structure()
        print(f"[OK] GameMaker project validated: {gamemaker_root.name}")
        return create_project_asset(
            args,
            asset=ScriptAsset(),
            asset_type="script",
            label="Script",
            kwargs={"is_constructor": getattr(args, "constructor", False)},
            allow_constructor=getattr(args, "constructor", False),
        )
    except Exception as e:
        print(f"Error creating script: {e}")
        return False


def create_object(args):
    """Create a new object asset."""
    try:
        kwargs = {}
        if args.sprite_id:
            kwargs["sprite_id"] = args.sprite_id
        if args.parent_object:
            kwargs["parent_object"] = args.parent_object
        return create_project_asset(args, asset=ObjectAsset(), asset_type="object", label="Object", kwargs=kwargs)

    except Exception as e:
        print(f"Error creating object: {e}")
        return False


def create_sprite(args):
    """Create a new sprite asset."""
    try:
        frame_count = getattr(args, "frame_count", 1)
        return create_project_asset(
            args,
            asset=SpriteAsset(),
            asset_type="sprite",
            label="Sprite",
            kwargs={"frame_count": frame_count},
            success_message=(
                f"[OK] Sprite '{args.name}' created successfully with {frame_count} frames" if frame_count > 1 else None
            ),
        )

    except Exception as e:
        print(f"Error creating sprite: {e}")
        return False


def create_room(args):
    """Create a new room asset."""
    try:
        return create_project_asset(
            args,
            asset=RoomAsset(),
            asset_type="room",
            label="Room",
            kwargs={"width": args.width, "height": args.height},
        )

    except Exception as e:
        print(f"Error creating room: {e}")
        return False


def create_folder(args):
    """Create a new folder asset."""
    try:
        precheck = run_pre_creation_maintenance(args, f"Folder '{args.name}' creation")
        if precheck is not True:
            return precheck

        asset = FolderAsset()
        folder_path = asset.create_files(Path("."), args.name, args.path)

        print(f"[OK] Folder '{args.name}' created at logical path: {folder_path}")
        print(f'   [INFO] Use --parent-path "{folder_path}" when creating assets inside this folder.')
        return run_post_creation_maintenance(args, f"Folder '{args.name}' post-creation")

    except Exception as e:
        print(f"Error creating folder: {e}")
        return False


def create_font(args):
    """Create a new font asset."""
    try:
        kwargs = {
            "font_name": args.font_name,
            "size": args.size,
            "bold": args.bold,
            "italic": args.italic,
            "aa_level": args.aa_level,
            "uses_sdf": args.uses_sdf,
        }
        return create_project_asset(
            args,
            asset=FontAsset(),
            asset_type="font",
            label="Font",
            kwargs=kwargs,
            success_lines=(
                f"  Font family: {args.font_name}",
                f"  Size: {args.size}",
                f"  Bold: {args.bold}, Italic: {args.italic}",
            ),
        )

    except Exception as e:
        print(f"Error creating font: {e}")
        return False


def create_shader(args):
    """Create a new shader asset."""
    try:
        return create_project_asset(
            args,
            asset=ShaderAsset(),
            asset_type="shader",
            label="Shader",
            kwargs={"shader_type": args.shader_type},
            success_lines=(
                f"  Type: {['GLSL ES', 'GLSL', 'HLSL 9', 'HLSL 11'][args.shader_type - 1]}",
                f"  Created: {args.name}.vsh (vertex shader)",
                f"  Created: {args.name}.fsh (fragment shader)",
            ),
        )

    except Exception as e:
        print(f"Error creating shader: {e}")
        return False


def create_animcurve(args):
    """Create a new animation curve asset."""
    try:
        return create_project_asset(
            args,
            asset=AnimCurveAsset(),
            asset_type="animcurve",
            label="Animation curve",
            kwargs={"curve_type": args.curve_type, "channel_name": args.channel_name},
            success_lines=(f"  Type: {args.curve_type}", f"  Channel: {args.channel_name}"),
        )

    except Exception as e:
        print(f"Error creating animation curve: {e}")
        return False


def create_sound(args):
    """Create a new sound asset."""
    try:
        kwargs = {
            "volume": args.volume,
            "pitch": args.pitch,
            "sound_type": args.sound_type,
            "bitrate": args.bitrate,
            "sample_rate": args.sample_rate,
            "format": args.format,
        }
        return create_project_asset(
            args,
            asset=SoundAsset(),
            asset_type="sound",
            label="Sound",
            kwargs=kwargs,
            success_lines=(
                f"  Type: {['Normal', 'Background', '3D'][args.sound_type]}",
                f"  Volume: {args.volume}, Pitch: {args.pitch}",
                f"  Bitrate: {args.bitrate}, Sample Rate: {args.sample_rate}",
                "  [WARN] Replace placeholder audio file with actual audio!",
            ),
        )

    except Exception as e:
        print(f"Error creating sound: {e}")
        return False


def create_path(args):
    """Create a new path asset."""
    try:
        return create_project_asset(
            args,
            asset=PathAsset(),
            asset_type="path",
            label="Path",
            kwargs={"closed": args.closed, "precision": args.precision, "path_type": args.path_type},
            success_lines=(f"  Type: {args.path_type}", f"  Closed: {args.closed}, Precision: {args.precision}"),
        )

    except Exception as e:
        print(f"Error creating path: {e}")
        return False


def create_tileset(args):
    """Create a new tileset asset."""
    try:
        kwargs = {
            "tile_width": args.tile_width,
            "tile_height": args.tile_height,
            "tile_xsep": args.tile_xsep,
            "tile_ysep": args.tile_ysep,
            "tile_xoff": args.tile_xoff,
            "tile_yoff": args.tile_yoff,
            "sprite_id": args.sprite_id,
        }
        lines = [
            f"  Tile size: {args.tile_width}x{args.tile_height}",
            f"  Separation: {args.tile_xsep}x{args.tile_ysep}",
            f"  Offset: {args.tile_xoff}x{args.tile_yoff}",
        ]
        if args.sprite_id:
            lines.append(f"  Sprite: {args.sprite_id}")
        return create_project_asset(
            args,
            asset=TileSetAsset(),
            asset_type="tileset",
            label="Tileset",
            kwargs=kwargs,
            success_lines=lines,
        )

    except Exception as e:
        print(f"Error creating tileset: {e}")
        return False


def create_timeline(args):
    """Create a new timeline asset."""
    try:
        return create_project_asset(
            args,
            asset=TimelineAsset(),
            asset_type="timeline",
            label="Timeline",
            success_lines=("  Created: moment_0.gml",),
        )

    except Exception as e:
        print(f"Error creating timeline: {e}")
        return False


def create_sequence(args):
    """Create a new sequence asset."""
    try:
        return create_project_asset(
            args,
            asset=SequenceAsset(),
            asset_type="sequence",
            label="Sequence",
            kwargs={"length": args.length, "playback_speed": args.playback_speed},
            success_lines=(f"  Length: {args.length} frames", f"  Playback speed: {args.playback_speed} FPS"),
        )

    except Exception as e:
        print(f"Error creating sequence: {e}")
        return False


def create_note(args):
    """Create a new note asset."""
    try:
        return create_project_asset(
            args,
            asset=NoteAsset(),
            asset_type="note",
            label="Note",
            kwargs={"content": args.content},
            success_lines=(f"  Created: {args.name}.txt",),
        )

    except Exception as e:
        print(f"Error creating note: {e}")
        return False
