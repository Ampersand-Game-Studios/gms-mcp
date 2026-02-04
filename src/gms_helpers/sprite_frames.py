"""Sprite frame manipulation utilities for multi-frame sprite support."""

import shutil
from pathlib import Path
from typing import Optional

from .utils import generate_uuid, ensure_directory, load_json_loose, save_pretty_json, create_dummy_png
from .exceptions import ValidationError


def add_frame(
    project_root: Path,
    sprite_path: str,
    position: int = -1,
    source_png: Optional[Path] = None,
) -> dict:
    """
    Add a frame to an existing sprite.
    
    Args:
        project_root: Project root directory
        sprite_path: Sprite asset path (e.g., "sprites/spr_player/spr_player.yy")
        position: Insert position (0-indexed, -1 = append at end)
        source_png: Optional source image path (creates blank if None)
    
    Returns: Operation result dict with success, sprite_name, frame_uuid, position, new_frame_count
    """
    project_root = Path(project_root)
    sprite_yy = project_root / sprite_path
    
    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")
    
    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")
    
    sprite_folder = sprite_yy.parent
    sprite_name = yy_data["name"]
    layer_uuid = yy_data["layers"][0]["name"]
    current_frame_count = len(yy_data["frames"])
    
    # Determine insert position
    if position < 0 or position > current_frame_count:
        position = current_frame_count
    
    # Generate new UUIDs
    new_frame_uuid = generate_uuid()
    new_keyframe_uuid = generate_uuid()
    
    # Create new frame entry
    new_frame = {
        "$GMSpriteFrame": "",
        "%Name": new_frame_uuid,
        "name": new_frame_uuid,
        "resourceType": "GMSpriteFrame",
        "resourceVersion": "2.0"
    }
    
    # Insert frame at position
    yy_data["frames"].insert(position, new_frame)
    
    # Update keyframes: shift all keyframes at >= position
    keyframes = yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
    
    for kf in keyframes:
        if kf["Key"] >= position:
            kf["Key"] += 1.0
    
    # Create new keyframe
    new_keyframe = {
        "$Keyframe<SpriteFrameKeyframe>": "",
        "Channels": {
            "0": {
                "$SpriteFrameKeyframe": "",
                "Id": {
                    "name": new_frame_uuid,
                    "path": f"sprites/{sprite_name.lower()}/{sprite_name}.yy"
                },
                "resourceType": "SpriteFrameKeyframe",
                "resourceVersion": "2.0"
            }
        },
        "Disabled": False,
        "id": new_keyframe_uuid,
        "IsCreationKey": False,
        "Key": float(position),
        "Length": 1.0,
        "resourceType": "Keyframe<SpriteFrameKeyframe>",
        "resourceVersion": "2.0",
        "Stretch": False
    }
    
    # Insert keyframe and re-sort by Key
    keyframes.append(new_keyframe)
    keyframes.sort(key=lambda kf: kf["Key"])
    
    # Update sequence length
    yy_data["sequence"]["length"] = float(len(yy_data["frames"]))
    
    # Create PNG files
    width = yy_data.get("width", 1)
    height = yy_data.get("height", 1)
    
    # Save main PNG
    main_png = sprite_folder / f"{new_frame_uuid}.png"
    if source_png and Path(source_png).exists():
        shutil.copy2(source_png, main_png)
    else:
        create_dummy_png(main_png, width=width, height=height)
    
    # Save layer PNG
    layer_dir = sprite_folder / "layers" / new_frame_uuid
    ensure_directory(layer_dir)
    layer_png = layer_dir / f"{layer_uuid}.png"
    if source_png and Path(source_png).exists():
        shutil.copy2(source_png, layer_png)
    else:
        create_dummy_png(layer_png, width=width, height=height)
    
    # Save updated .yy
    save_pretty_json(sprite_yy, yy_data)
    
    return {
        "success": True,
        "sprite_name": sprite_name,
        "frame_uuid": new_frame_uuid,
        "position": position,
        "new_frame_count": len(yy_data["frames"])
    }


def remove_frame(
    project_root: Path,
    sprite_path: str,
    position: int,
) -> dict:
    """
    Remove a frame from an existing sprite.
    
    Args:
        project_root: Project root directory
        sprite_path: Sprite asset path
        position: Frame index to remove (0-indexed)
    
    Returns: Operation result dict with success, sprite_name, removed_frame_uuid, removed_position, new_frame_count
    """
    project_root = Path(project_root)
    sprite_yy = project_root / sprite_path
    
    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")
    
    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")
    
    sprite_folder = sprite_yy.parent
    sprite_name = yy_data["name"]
    current_frame_count = len(yy_data["frames"])
    
    # Validation
    if current_frame_count <= 1:
        raise ValidationError("Cannot remove frame: sprite must have at least 1 frame")
    
    if position < 0 or position >= current_frame_count:
        raise ValidationError(
            f"Invalid position {position}: sprite has {current_frame_count} frames (valid: 0-{current_frame_count-1})"
        )
    
    # Get frame UUID before removal
    removed_frame_uuid = yy_data["frames"][position]["name"]
    
    # Remove frame entry
    yy_data["frames"].pop(position)
    
    # Remove and shift keyframes
    keyframes = yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
    
    # Find and remove the keyframe for this position
    keyframes[:] = [kf for kf in keyframes if kf["Key"] != float(position)]
    
    # Shift remaining keyframes
    for kf in keyframes:
        if kf["Key"] > position:
            kf["Key"] -= 1.0
    
    # Update sequence length
    yy_data["sequence"]["length"] = float(len(yy_data["frames"]))
    
    # Delete PNG files
    main_png = sprite_folder / f"{removed_frame_uuid}.png"
    if main_png.exists():
        main_png.unlink()
    
    layer_dir = sprite_folder / "layers" / removed_frame_uuid
    if layer_dir.exists():
        shutil.rmtree(layer_dir)
    
    # Save updated .yy
    save_pretty_json(sprite_yy, yy_data)
    
    return {
        "success": True,
        "sprite_name": sprite_name,
        "removed_frame_uuid": removed_frame_uuid,
        "removed_position": position,
        "new_frame_count": len(yy_data["frames"])
    }


def duplicate_frame(
    project_root: Path,
    sprite_path: str,
    source_position: int,
    target_position: int = -1,
) -> dict:
    """
    Duplicate an existing frame within a sprite.
    
    Args:
        project_root: Project root directory
        sprite_path: Sprite asset path
        source_position: Frame index to duplicate (0-indexed)
        target_position: Where to insert the duplicate (-1 = after source)
    
    Returns: Operation result dict
    """
    project_root = Path(project_root)
    sprite_yy = project_root / sprite_path
    
    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")
    
    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")
    
    sprite_folder = sprite_yy.parent
    frame_count = len(yy_data["frames"])
    
    if source_position < 0 or source_position >= frame_count:
        raise ValidationError(
            f"Invalid source position {source_position}: sprite has {frame_count} frames"
        )
    
    if target_position < 0:
        target_position = source_position + 1
    
    # Get source frame's PNG
    source_uuid = yy_data["frames"][source_position]["name"]
    source_png = sprite_folder / f"{source_uuid}.png"
    
    # Use add_frame with the source PNG
    return add_frame(project_root, sprite_path, target_position, source_png)


def get_frame_count(project_root: Path, sprite_path: str) -> int:
    """Get the number of frames in a sprite."""
    project_root = Path(project_root)
    sprite_yy = project_root / sprite_path
    
    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")
    
    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")
    
    return len(yy_data["frames"])
