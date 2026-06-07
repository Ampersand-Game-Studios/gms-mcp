"""Asset management command implementations."""

from typing import Any, Callable

# Import all the create_* functions from asset_helper.py
from ..asset_helper import (
    create_script,
    create_object,
    create_sprite,
    create_room,
    create_folder,
    create_font,
    create_shader,
    create_animcurve,
    create_sound,
    create_path,
    create_tileset,
    create_timeline,
    create_sequence,
    create_note,
    delete_asset,
)
from ..results import AssetResult, OperationResult


_ASSET_DIRS = {
    "script": "scripts",
    "object": "objects",
    "sprite": "sprites",
    "room": "rooms",
    "font": "fonts",
    "shader": "shaders",
    "animcurve": "animcurves",
    "sound": "sounds",
    "path": "paths",
    "tileset": "tilesets",
    "timeline": "timelines",
    "sequence": "sequences",
    "note": "notes",
}


def _asset_path(asset_type: str, args: Any) -> str | None:
    name = getattr(args, "name", None)
    if asset_type == "folder":
        return getattr(args, "path", None)
    folder = _ASSET_DIRS.get(asset_type)
    if not folder or not name:
        return None
    return f"{folder}/{str(name).lower()}/{name}.yy"


def _asset_result(asset_type: str, args: Any, result: Any, *, operation: str) -> AssetResult | Any:
    if isinstance(result, OperationResult):
        return result
    if not isinstance(result, bool):
        return result

    name = getattr(args, "name", None)
    if result:
        return AssetResult(
            success=True,
            message=f"{operation.title()} {asset_type} '{name}' completed successfully",
            asset_name=name,
            asset_type=asset_type,
            asset_path=_asset_path(asset_type, args),
        )
    return AssetResult(
        success=False,
        message=f"Failed to {operation} {asset_type} '{name}'",
        asset_name=name,
        asset_type=asset_type,
        asset_path=_asset_path(asset_type, args),
    )


def handle_asset_create(args):
    """Route asset creation to appropriate function."""
    asset_type = args.asset_type

    creators: dict[str, Callable[[Any], Any]] = {
        "script": create_script,
        "object": create_object,
        "sprite": create_sprite,
        "room": create_room,
        "folder": create_folder,
        "font": create_font,
        "shader": create_shader,
        "animcurve": create_animcurve,
        "sound": create_sound,
        "path": create_path,
        "tileset": create_tileset,
        "timeline": create_timeline,
        "sequence": create_sequence,
        "note": create_note,
    }

    if asset_type not in creators:
        print(f"[ERROR] Unknown asset type: {asset_type}")
        return AssetResult.fail(
            f"Unknown asset type: {asset_type}",
            code="unsupported_asset_type",
            error_type="validation_error",
            details={"asset_type": asset_type},
        )

    return _asset_result(asset_type, args, creators[asset_type](args), operation="create")


def handle_asset_delete(args):
    """Handle asset deletion."""
    asset_type = getattr(args, "asset_type", "asset")
    return _asset_result(asset_type, args, delete_asset(args), operation="delete")
