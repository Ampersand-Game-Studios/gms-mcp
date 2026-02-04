"""Sprite import utilities for strip/sheet conversion."""

from pathlib import Path
from typing import Literal, Tuple, List, Optional, TYPE_CHECKING

from .utils import generate_uuid, ensure_directory, load_json_loose, save_pretty_json
from .exceptions import ValidationError

# Pillow is optional - import lazily
if TYPE_CHECKING:
    from PIL import Image


def _get_pillow():
    """Lazily import Pillow, raise helpful error if not installed."""
    try:
        from PIL import Image
        return Image
    except ImportError:
        raise ImportError(
            "Pillow is required for sprite import functionality.\n"
            "Install it with: pip install Pillow\n"
            "Or install gms-mcp with import extras: pip install gms-mcp[import]"
        )


def detect_strip_layout(
    image_path: Path,
    frame_width: Optional[int] = None,
    frame_height: Optional[int] = None,
) -> Tuple[int, int, int]:
    """
    Auto-detect strip layout from an image.
    
    Args:
        image_path: Path to the sprite strip/sheet image
        frame_width: Optional known frame width
        frame_height: Optional known frame height
    
    Returns: (frame_count, frame_width, frame_height)
    """
    Image = _get_pillow()
    image = Image.open(image_path)
    width, height = image.size
    
    if frame_width and frame_height:
        # Grid mode - both dimensions specified
        cols = width // frame_width
        rows = height // frame_height
        return cols * rows, frame_width, frame_height
    elif frame_width:
        # Horizontal strip with known frame width
        return width // frame_width, frame_width, height
    elif frame_height:
        # Vertical strip with known frame height
        return height // frame_height, width, frame_height
    else:
        # Auto-detect: assume horizontal strip with square frames
        if width > height:
            # Horizontal strip
            frame_size = height
            return width // frame_size, frame_size, frame_size
        else:
            # Vertical strip
            frame_size = width
            return height // frame_size, frame_size, frame_size


def split_strip(
    source_path: Path,
    frame_width: Optional[int] = None,
    frame_height: Optional[int] = None,
    layout: Literal["horizontal", "vertical", "grid"] = "horizontal",
    columns: Optional[int] = None,
) -> List["Image.Image"]:
    """
    Split a sprite strip/sheet into individual frames.
    
    Args:
        source_path: Path to source PNG strip/sheet
        frame_width: Frame width in pixels (auto-detected if None)
        frame_height: Frame height in pixels (auto-detected if None)
        layout: Strip layout - "horizontal", "vertical", or "grid"
        columns: Number of columns (required for grid layout)
    
    Returns: List of PIL Image objects
    """
    Image = _get_pillow()
    image = Image.open(source_path)
    width, height = image.size
    
    frames = []
    
    if layout == "grid":
        if not (frame_width and frame_height):
            raise ValidationError("Grid layout requires frame_width and frame_height")
        if not columns:
            # Auto-detect columns from image width
            columns = width // frame_width
        
        rows = height // frame_height
        for row in range(rows):
            for col in range(columns):
                if col * frame_width >= width:
                    break
                box = (
                    col * frame_width,
                    row * frame_height,
                    (col + 1) * frame_width,
                    (row + 1) * frame_height
                )
                frames.append(image.crop(box))
    
    elif layout == "vertical":
        if not frame_height:
            frame_height = width  # Assume square frames
        frame_count = height // frame_height
        for i in range(frame_count):
            box = (0, i * frame_height, width, (i + 1) * frame_height)
            frames.append(image.crop(box))
    
    else:  # horizontal (default)
        if not frame_width:
            frame_width = height  # Assume square frames
        frame_count = width // frame_width
        for i in range(frame_count):
            box = (i * frame_width, 0, (i + 1) * frame_width, height)
            frames.append(image.crop(box))
    
    if not frames:
        raise ValidationError("No frames detected in source image")
    
    return frames


def import_strip_to_sprite(
    project_root: Path,
    sprite_name: str,
    source_path: Path,
    parent_path: str = "",
    frame_width: Optional[int] = None,
    frame_height: Optional[int] = None,
    layout: Literal["horizontal", "vertical", "grid"] = "horizontal",
    columns: Optional[int] = None,
) -> dict:
    """
    Import a sprite strip as a new GameMaker sprite.
    
    Args:
        project_root: Project root directory
        sprite_name: Name for the new sprite
        source_path: Path to source PNG strip/sheet
        parent_path: Parent folder path (e.g., "folders/Sprites.yy")
        frame_width: Frame width in pixels (auto-detected if None)
        frame_height: Frame height in pixels (auto-detected if None)
        layout: Strip layout - "horizontal", "vertical", or "grid"
        columns: Number of columns (for grid layout)
    
    Returns: Operation result dict with success, sprite_name, frame_count, frame_size, path
    """
    from .assets import SpriteAsset
    from .utils import update_yyp_file
    
    project_root = Path(project_root)
    source_path = Path(source_path)
    
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    
    # Split the source image
    frame_images = split_strip(source_path, frame_width, frame_height, layout, columns)
    frame_count = len(frame_images)
    
    # Get actual frame dimensions from first frame
    actual_width, actual_height = frame_images[0].size
    
    # Create the sprite asset with correct frame count
    asset = SpriteAsset()
    relative_path = asset.create_files(
        project_root, 
        sprite_name, 
        parent_path,
        frame_count=frame_count,
        width=actual_width,
        height=actual_height
    )
    
    # Load the created .yy to get UUIDs
    sprite_folder = project_root / "sprites" / sprite_name.lower()
    yy_path = sprite_folder / f"{sprite_name}.yy"
    yy_data = load_json_loose(yy_path)
    
    if yy_data is None:
        raise ValidationError(f"Failed to load created sprite: {yy_path}")
    
    layer_uuid = yy_data["layers"][0]["name"]
    
    # Replace dummy PNGs with actual frame images
    for i, frame_image in enumerate(frame_images):
        frame_uuid = yy_data["frames"][i]["name"]
        
        # Save main PNG
        main_png = sprite_folder / f"{frame_uuid}.png"
        frame_image.save(main_png, "PNG")
        
        # Save layer PNG
        layer_dir = sprite_folder / "layers" / frame_uuid
        ensure_directory(layer_dir)
        layer_png = layer_dir / f"{layer_uuid}.png"
        frame_image.save(layer_png, "PNG")
    
    # Update .yyp file
    resource_entry = {
        "id": {
            "name": sprite_name,
            "path": relative_path
        }
    }
    update_yyp_file(resource_entry)
    
    return {
        "success": True,
        "sprite_name": sprite_name,
        "frame_count": frame_count,
        "frame_size": (actual_width, actual_height),
        "path": str(relative_path)
    }


def import_frames_to_existing_sprite(
    project_root: Path,
    sprite_path: str,
    source_path: Path,
    start_position: int = -1,
    frame_width: Optional[int] = None,
    frame_height: Optional[int] = None,
    layout: Literal["horizontal", "vertical", "grid"] = "horizontal",
    columns: Optional[int] = None,
    replace: bool = False,
) -> dict:
    """
    Import frames from a strip into an existing sprite.
    
    Args:
        project_root: Project root directory
        sprite_path: Sprite asset path
        source_path: Path to source PNG strip/sheet
        start_position: Position to insert frames (-1 = append at end)
        frame_width: Frame width in pixels
        frame_height: Frame height in pixels
        layout: Strip layout
        columns: Number of columns (for grid layout)
        replace: If True, replace existing frames instead of inserting
    
    Returns: Operation result dict
    """
    from .sprite_frames import add_frame, remove_frame, get_frame_count
    
    Image = _get_pillow()
    project_root = Path(project_root)
    source_path = Path(source_path)
    
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    
    # Split the source image
    frame_images = split_strip(source_path, frame_width, frame_height, layout, columns)
    imported_count = len(frame_images)
    
    if replace:
        # Remove existing frames first
        existing_count = get_frame_count(project_root, sprite_path)
        for _ in range(existing_count - 1, -1, -1):  # Remove from end to start
            remove_frame(project_root, sprite_path, 0)
        start_position = 0
    
    # Create a temp directory for the frame images
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Save frames to temp files and add them
        for i, frame_image in enumerate(frame_images):
            temp_png = tmpdir / f"frame_{i}.png"
            frame_image.save(temp_png, "PNG")
            
            pos = start_position + i if start_position >= 0 else -1
            add_frame(project_root, sprite_path, position=pos, source_png=temp_png)
    
    return {
        "success": True,
        "imported_frames": imported_count,
        "sprite_path": sprite_path
    }
