"""Sprite frame manipulation utilities for multi-frame sprite support."""

import copy
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .exceptions import ValidationError
from .path_safety import assert_project_tree_contained, project_relative_path, validate_resource_name
from .transactions import transactional_copy2, transactional_rmtree, transactional_unlink
from .utils import create_dummy_png, ensure_directory, generate_uuid, load_json_loose, save_pretty_json

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_png_dimensions(path: Path) -> Tuple[int, int]:
    """Return ``(width, height)`` from a PNG's IHDR chunk."""
    with Path(path).open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValidationError(f"Not a PNG image: {path}")
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def require_png_matches_sprite(path: Path, yy_data: Dict[str, Any]) -> None:
    """Refuse a frame image whose size differs from the sprite canvas."""
    width, height = read_png_dimensions(path)
    expected = (yy_data.get("width"), yy_data.get("height"))
    if (width, height) != expected:
        raise ValidationError(
            f"Image {path} is {width}x{height}, but sprite '{yy_data.get('name')}' is "
            f"{expected[0]}x{expected[1]}. Resize the image or the sprite first."
        )


def sprite_layer_ids(yy_data: Dict[str, Any]) -> List[str]:
    """Return validated image-layer identifiers; a sprite must have at least one."""
    layers = yy_data.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ValidationError(f"Sprite '{yy_data.get('name')}' has no image layers")
    return [validate_resource_name(layer.get("name"), "sprite layer identifier") for layer in layers]


def require_modern_sprite_format(yy_data: Dict[str, Any], sprite_yy: Path) -> None:
    """Only the 2023+ ``$GMSprite`` format is edited; older files are refused."""
    if "$GMSprite" not in yy_data and str(yy_data.get("resourceVersion", "")).startswith("1."):
        raise ValidationError(
            f"{sprite_yy} uses the pre-2023 GameMaker sprite format (resourceVersion 1.x, no $GMSprite tag). "
            "Open and save the project in GameMaker 2023.2 or later before editing frames."
        )


def _frame_keyframes(yy_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValidationError(f"Sprite '{yy_data.get('name')}' has no frames track") from exc


def _add_frame(
    project_root: Path,
    sprite_path: str,
    position: int,
    *,
    composite_png: Optional[Path],
    layer_pngs: Optional[Dict[str, Path]],
    imported: bool,
) -> dict:
    project_root = assert_project_tree_contained(Path(project_root))
    sprite_yy = project_relative_path(sprite_path, project_root=project_root, kind="sprite path")

    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")

    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")
    require_modern_sprite_format(yy_data, sprite_yy)

    sprite_folder = sprite_yy.parent
    sprite_name = yy_data["name"]
    layer_uuids = sprite_layer_ids(yy_data)
    current_frame_count = len(yy_data["frames"])
    for image in [composite_png, *(layer_pngs or {}).values()]:
        if image is not None:
            if not Path(image).is_file():
                raise FileNotFoundError(f"Frame image not found: {image}")
            if imported:
                require_png_matches_sprite(Path(image), yy_data)

    # Determine insert position
    if position < 0 or position > current_frame_count:
        position = current_frame_count

    # Generate new UUIDs
    new_frame_uuid = generate_uuid()
    new_keyframe_uuid = generate_uuid()

    # Mirror the sprite's own serialization of frames and keyframes.
    template_frame = yy_data["frames"][0] if yy_data["frames"] else {}
    new_frame = {
        "$GMSpriteFrame": template_frame.get("$GMSpriteFrame", ""),
        "%Name": new_frame_uuid,
        "name": new_frame_uuid,
        "resourceType": "GMSpriteFrame",
        "resourceVersion": template_frame.get("resourceVersion", "2.0"),
    }

    # Insert frame at position
    yy_data["frames"].insert(position, new_frame)

    # Update keyframes: shift all keyframes at >= position
    keyframes = _frame_keyframes(yy_data)

    for kf in keyframes:
        if kf["Key"] >= position:
            kf["Key"] += 1.0

    sprite_reference_path = sprite_yy.relative_to(project_root).as_posix()
    if keyframes:
        new_keyframe = copy.deepcopy(keyframes[0])
        channel = next(iter(new_keyframe["Channels"].values()))
        new_keyframe["Channels"] = {"0": channel}
        channel["Id"] = {"name": new_frame_uuid, "path": sprite_reference_path}
        new_keyframe.update({"id": new_keyframe_uuid, "IsCreationKey": False, "Key": float(position), "Length": 1.0})
    else:
        new_keyframe = {
            "$Keyframe<SpriteFrameKeyframe>": "",
            "Channels": {
                "0": {
                    "$SpriteFrameKeyframe": "",
                    "Id": {"name": new_frame_uuid, "path": sprite_reference_path},
                    "resourceType": "SpriteFrameKeyframe",
                    "resourceVersion": "2.0",
                }
            },
            "Disabled": False,
            "id": new_keyframe_uuid,
            "IsCreationKey": False,
            "Key": float(position),
            "Length": 1.0,
            "resourceType": "Keyframe<SpriteFrameKeyframe>",
            "resourceVersion": "2.0",
            "Stretch": False,
        }

    # Insert keyframe and re-sort by Key
    keyframes.append(new_keyframe)
    keyframes.sort(key=lambda kf: kf["Key"])

    # Update sequence length
    yy_data["sequence"]["length"] = float(len(yy_data["frames"]))

    width = yy_data.get("width", 1)
    height = yy_data.get("height", 1)

    def write_image(destination: Path, source: Optional[Path]) -> None:
        if source is not None:
            transactional_copy2(source, destination)
        else:
            create_dummy_png(destination, width=width, height=height)

    # Composite frame image, then one image per layer.
    write_image(sprite_folder / f"{new_frame_uuid}.png", composite_png)
    layer_dir = sprite_folder / "layers" / new_frame_uuid
    ensure_directory(layer_dir)
    for layer_uuid in layer_uuids:
        write_image(layer_dir / f"{layer_uuid}.png", (layer_pngs or {}).get(layer_uuid))

    # Save updated .yy
    save_pretty_json(sprite_yy, yy_data)

    return {
        "success": True,
        "sprite_name": sprite_name,
        "frame_uuid": new_frame_uuid,
        "position": position,
        "new_frame_count": len(yy_data["frames"]),
    }


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
        source_png: Optional source image path (creates a blank frame if None).
            It must exist and match the sprite size. A single image cannot
            describe several layers, so multi-layer sprites only take blank frames.

    Returns: Operation result dict with success, sprite_name, frame_uuid, position, new_frame_count
    """
    layer_pngs = None
    if source_png is not None:
        root = assert_project_tree_contained(Path(project_root))
        sprite_yy = project_relative_path(sprite_path, project_root=root, kind="sprite path")
        yy_data = load_json_loose(sprite_yy) if sprite_yy.exists() else None
        if isinstance(yy_data, dict):
            layer_uuids = sprite_layer_ids(yy_data)
            if len(layer_uuids) > 1:
                raise ValidationError(
                    f"Sprite '{yy_data.get('name')}' has {len(layer_uuids)} image layers; one source image "
                    "cannot fill them. Add a blank frame or edit the layers in GameMaker."
                )
            layer_pngs = {layer_uuids[0]: Path(source_png)}
    return _add_frame(
        project_root,
        sprite_path,
        position,
        composite_png=Path(source_png) if source_png is not None else None,
        layer_pngs=layer_pngs,
        imported=True,
    )


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
    project_root = assert_project_tree_contained(Path(project_root))
    sprite_yy = project_relative_path(sprite_path, project_root=project_root, kind="sprite path")

    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")

    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")

    require_modern_sprite_format(yy_data, sprite_yy)
    sprite_folder = sprite_yy.parent
    sprite_name = yy_data["name"]
    current_frame_count = len(yy_data["frames"])

    # Validation
    if current_frame_count <= 1:
        raise ValidationError("Cannot remove frame: sprite must have at least 1 frame")

    if position < 0 or position >= current_frame_count:
        raise ValidationError(
            f"Invalid position {position}: sprite has {current_frame_count} frames (valid: 0-{current_frame_count - 1})"
        )

    # Get frame UUID before removal
    removed_frame_uuid = validate_resource_name(yy_data["frames"][position]["name"], "sprite frame identifier")

    # Remove frame entry
    yy_data["frames"].pop(position)

    # Remove and shift keyframes
    keyframes = _frame_keyframes(yy_data)

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
        transactional_unlink(main_png)

    layer_dir = sprite_folder / "layers" / removed_frame_uuid
    if layer_dir.exists():
        transactional_rmtree(layer_dir)

    # Save updated .yy
    save_pretty_json(sprite_yy, yy_data)

    return {
        "success": True,
        "sprite_name": sprite_name,
        "removed_frame_uuid": removed_frame_uuid,
        "removed_position": position,
        "new_frame_count": len(yy_data["frames"]),
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
    project_root = assert_project_tree_contained(Path(project_root))
    sprite_yy = project_relative_path(sprite_path, project_root=project_root, kind="sprite path")

    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")

    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")

    sprite_folder = sprite_yy.parent
    frame_count = len(yy_data["frames"])

    if source_position < 0 or source_position >= frame_count:
        raise ValidationError(f"Invalid source position {source_position}: sprite has {frame_count} frames")

    if target_position < 0:
        target_position = source_position + 1

    # Copy the source frame's composite image and every layer image.
    source_uuid = validate_resource_name(yy_data["frames"][source_position]["name"], "sprite frame identifier")
    layer_pngs = {
        layer_uuid: sprite_folder / "layers" / source_uuid / f"{layer_uuid}.png"
        for layer_uuid in sprite_layer_ids(yy_data)
    }
    return _add_frame(
        project_root,
        sprite_path,
        target_position,
        composite_png=sprite_folder / f"{source_uuid}.png",
        layer_pngs=layer_pngs,
        imported=False,
    )


def get_frame_count(project_root: Path, sprite_path: str) -> int:
    """Get the number of frames in a sprite."""
    project_root = Path(project_root).resolve()
    sprite_yy = project_relative_path(sprite_path, project_root=project_root, kind="sprite path")

    if not sprite_yy.exists():
        raise FileNotFoundError(f"Sprite file not found: {sprite_yy}")

    yy_data = load_json_loose(sprite_yy)
    if yy_data is None:
        raise ValidationError(f"Could not load sprite file: {sprite_yy}")

    return len(yy_data["frames"])
