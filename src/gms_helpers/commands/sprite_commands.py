"""Sprite frame manipulation command implementations."""

from pathlib import Path


def handle_sprite_add_frame(args):
    """Handle adding a frame to a sprite."""
    from ..sprite_frames import add_frame
    
    project_root = Path(args.project_root).resolve()
    source_png = Path(args.source) if getattr(args, 'source', None) else None
    
    result = add_frame(
        project_root,
        args.sprite_path,
        position=getattr(args, 'position', -1),
        source_png=source_png
    )
    
    print(f"[OK] Added frame at position {result['position']}")
    print(f"     Frame UUID: {result['frame_uuid']}")
    print(f"     New frame count: {result['new_frame_count']}")
    return result


def handle_sprite_remove_frame(args):
    """Handle removing a frame from a sprite."""
    from ..sprite_frames import remove_frame
    
    project_root = Path(args.project_root).resolve()
    
    result = remove_frame(
        project_root,
        args.sprite_path,
        args.position
    )
    
    print(f"[OK] Removed frame at position {result['removed_position']}")
    print(f"     Removed UUID: {result['removed_frame_uuid']}")
    print(f"     New frame count: {result['new_frame_count']}")
    return result


def handle_sprite_duplicate_frame(args):
    """Handle duplicating a frame within a sprite."""
    from ..sprite_frames import duplicate_frame
    
    project_root = Path(args.project_root).resolve()
    
    result = duplicate_frame(
        project_root,
        args.sprite_path,
        args.source_position,
        target_position=getattr(args, 'target', -1)
    )
    
    print(f"[OK] Duplicated frame to position {result['position']}")
    print(f"     New frame UUID: {result['frame_uuid']}")
    print(f"     New frame count: {result['new_frame_count']}")
    return result


def handle_sprite_import_strip(args):
    """Handle importing a sprite strip as a new sprite."""
    from ..sprite_import import import_strip_to_sprite
    
    project_root = Path(args.project_root).resolve()
    
    result = import_strip_to_sprite(
        project_root,
        args.name,
        Path(args.source),
        parent_path=getattr(args, 'parent_path', ''),
        frame_width=getattr(args, 'frame_width', None),
        frame_height=getattr(args, 'frame_height', None),
        layout=getattr(args, 'layout', 'horizontal'),
        columns=getattr(args, 'columns', None)
    )
    
    print(f"[OK] Imported sprite '{result['sprite_name']}'")
    print(f"     Frames: {result['frame_count']}")
    print(f"     Frame size: {result['frame_size'][0]}x{result['frame_size'][1]}")
    print(f"     Path: {result['path']}")
    return result


def handle_sprite_frame_count(args):
    """Handle getting frame count for a sprite."""
    from ..sprite_frames import get_frame_count
    
    project_root = Path(args.project_root).resolve()
    
    count = get_frame_count(project_root, args.sprite_path)
    
    print(f"Frame count: {count}")
    return {"success": True, "frame_count": count}
