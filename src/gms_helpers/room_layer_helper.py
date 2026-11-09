#!/usr/bin/env python3
"""
GameMaker Studio Room Layer Helper
Provides CLI and library functions for managing layers in rooms.
"""

import argparse
import sys
import math
from pathlib import Path
from typing import Dict, List, Any, Optional

from .utils import load_json_loose, save_json_loose
from .exceptions import GMSError, AssetNotFoundError, ValidationError
from .path_safety import project_child_path, validate_resource_name
from .room_instance_helper import (
    _find_room_file,
    _iter_layers,
    creation_code_path,
    require_current_room_format,
    run_room_helper_cli,
)
from .tilemap_codec import TILE_EMPTY
from .transactions import transactional_unlink

# Layer type constants
LAYER_TYPES = {
    "background": "GMRBackgroundLayer",
    "instance": "GMRInstanceLayer",
    "asset": "GMRAssetLayer",
    "tile": "GMRTileLayer",
    "path": "GMRPathLayer",
    "effect": "GMREffectLayer",
}

# ------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------


def _load_room_data(room_path: Path) -> Dict[str, Any]:
    """Load room JSON data."""
    data = load_json_loose(room_path)
    if not isinstance(data, dict) or data.get("resourceType") != "GMRoom":
        raise GMSError(f"Failed to load room data from {room_path}")
    return data


def _save_room_data(room_path: Path, data: Dict[str, Any]):
    """Save room JSON data."""
    save_json_loose(room_path, data)


def create_layer_data(
    name: str,
    layer_type: str,
    depth: int,
    *,
    userdefined_depth: bool = False,
    tileset: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new layer data dictionary.

    A tile layer needs ``tileset``: ``{"reference": {"name", "path"}, "tile_width", "tile_height",
    "columns", "rows"}``; GameMaker cannot paint on a tile layer without a tileset and grid.
    """
    if layer_type not in LAYER_TYPES:
        raise ValidationError(f"Invalid layer type '{layer_type}'")
    if layer_type == "tile" and tileset is None:
        raise ValidationError("A tile layer needs a tileset; pass the tileset asset name.")

    # GameMaker's asset compiler expects a type tag field (e.g. "$GMRInstanceLayer")
    # at the start of each layer object, and uses resourceVersion 2.0 for current formats.
    if layer_type == "instance":
        return {
            "$GMRInstanceLayer": "",
            "%Name": name,
            "depth": int(depth),
            "effectEnabled": True,
            "effectType": None,
            "gridX": 32,
            "gridY": 32,
            "hierarchyFrozen": False,
            "inheritLayerDepth": False,
            "inheritLayerSettings": False,
            "inheritSubLayers": True,
            "inheritVisibility": True,
            "instances": [],
            "layers": [],
            "name": name,
            "properties": [],
            "resourceType": "GMRInstanceLayer",
            "resourceVersion": "2.0",
            "userdefinedDepth": userdefined_depth,
            "visible": True,
        }

    if layer_type == "background":
        return {
            "$GMRBackgroundLayer": "",
            "%Name": name,
            "animationFPS": 15.0,
            "animationSpeedType": 0,
            "colour": 4278190080,
            "depth": int(depth),
            "effectEnabled": True,
            "effectType": None,
            "gridX": 32,
            "gridY": 32,
            "hierarchyFrozen": False,
            "hspeed": 0.0,
            "htiled": False,
            "inheritLayerDepth": False,
            "inheritLayerSettings": False,
            "inheritSubLayers": True,
            "inheritVisibility": True,
            "layers": [],
            "name": name,
            "properties": [],
            "resourceType": "GMRBackgroundLayer",
            "resourceVersion": "2.0",
            "spriteId": None,
            "stretch": False,
            "userdefinedAnimFPS": False,
            "userdefinedDepth": userdefined_depth,
            "visible": True,
            "vspeed": 0.0,
            "vtiled": False,
            "x": 0,
            "y": 0,
        }

    # Best-effort shapes for other layer types. These are sufficient for JSON tooling and
    # mirror the common "type tag first" pattern to avoid Igor parse errors.
    tag = f"${LAYER_TYPES[layer_type]}"
    base = {
        tag: "",
        "%Name": name,
        "depth": int(depth),
        "effectEnabled": True,
        "effectType": None,
        "gridX": 32,
        "gridY": 32,
        "hierarchyFrozen": False,
        "inheritLayerDepth": False,
        "inheritLayerSettings": False,
        "inheritSubLayers": True,
        "inheritVisibility": True,
        "layers": [],
        "name": name,
        "properties": [],
        "resourceType": LAYER_TYPES[layer_type],
        "resourceVersion": "2.0",
        "userdefinedDepth": userdefined_depth,
        "visible": True,
    }
    if layer_type == "asset":
        base["assets"] = []
    elif layer_type == "tile":
        columns, rows = int(tileset["columns"]), int(tileset["rows"])
        base["gridX"], base["gridY"] = int(tileset["tile_width"]), int(tileset["tile_height"])
        # GameMaker 2023+ writes tile layers as resourceVersion 2.1 with run-length tile data.
        base["resourceVersion"] = "2.1"
        base["tiles"] = {
            "SerialiseHeight": rows,
            "SerialiseWidth": columns,
            "TileCompressedData": [-(columns * rows), TILE_EMPTY],
            "TileDataFormat": 1,
        }
        base["tilesetId"] = dict(tileset["reference"])
        base["x"] = 0
        base["y"] = 0
    elif layer_type == "path":
        base["paths"] = []
    elif layer_type == "effect":
        base["effects"] = []
    return base


# ------------------------------------------------------------------
# Library Functions
# ------------------------------------------------------------------


def _tileset_grid(project_root: Path, room_data: Dict[str, Any], tileset_name: str) -> Dict[str, Any]:
    """Tileset reference plus the room-covering tile grid for a new tile layer."""
    from .project_validation import resolve_asset_reference

    tileset_name = validate_resource_name(tileset_name, "tileset")
    try:
        reference = resolve_asset_reference(project_root, tileset_name, "GMTileSet")
    except ValidationError as exc:
        raise AssetNotFoundError(f"Tileset '{tileset_name}' is not a registered valid tileset: {exc}") from exc
    tileset_path = project_child_path(reference["path"], project_root=project_root, kind=f"tileset '{tileset_name}'")
    tileset_data = load_json_loose(tileset_path)
    tile_width = tileset_data.get("tileWidth") if isinstance(tileset_data, dict) else None
    tile_height = tileset_data.get("tileHeight") if isinstance(tileset_data, dict) else None
    settings = room_data.get("roomSettings") or {}
    room_width, room_height = settings.get("Width"), settings.get("Height")
    for label, value in (
        (f"tileset '{tileset_name}' tileWidth", tile_width),
        (f"tileset '{tileset_name}' tileHeight", tile_height),
        ("room width", room_width),
        ("room height", room_height),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValidationError(f"Cannot size the tile layer: {label} is {value!r}, not a positive number.")
    return {
        "reference": reference,
        "tile_width": int(tile_width),
        "tile_height": int(tile_height),
        "columns": math.ceil(room_width / tile_width),
        "rows": math.ceil(room_height / tile_height),
    }


def _insert_by_depth(siblings: List[Any], layer: Dict[str, Any]) -> None:
    """GameMaker lists sibling layers by ascending depth; insert after any layer of equal depth."""
    depth = layer.get("depth", 0)
    for index, sibling in enumerate(siblings):
        if isinstance(sibling, dict) and sibling.get("depth", 0) > depth:
            siblings.insert(index, layer)
            return
    siblings.append(layer)


def _sibling_list(layers: Any, layer_name: str) -> Optional[List[Any]]:
    """The list (top level or a folder layer's children) that directly contains ``layer_name``."""
    if not isinstance(layers, list):
        return None
    for layer in layers:
        if isinstance(layer, dict) and layer.get("name") == layer_name:
            return layers
    for layer in layers:
        if isinstance(layer, dict):
            found = _sibling_list(layer.get("layers"), layer_name)
            if found is not None:
                return found
    return None


def add_layer(
    room_name: str,
    layer_name: str,
    layer_type: str = "instance",
    depth: Optional[int] = None,
    project_root: str | Path | None = None,
    tileset_name: Optional[str] = None,
) -> bool:
    """Add a new top-level layer to a room, in GameMaker's ascending-depth order.

    With ``depth`` the layer keeps that depth (``userdefinedDepth``); without it the layer goes on
    top, 100 above the shallowest layer, as the IDE places a new layer. A tile layer needs
    ``tileset_name``; it covers the room with that tileset's grid.
    """
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    room_path = _find_room_file(room_name, root)
    room_data = _load_room_data(room_path)
    require_current_room_format(room_data, room_name)

    # Check if layer already exists
    for layer in _iter_layers(room_data.get("layers", [])):
        if layer.get("name") == layer_name:
            raise ValidationError(f"Layer '{layer_name}' already exists in room '{room_name}'")

    if layer_type not in LAYER_TYPES:
        raise ValidationError(f"Invalid layer type '{layer_type}'. Valid types: {', '.join(LAYER_TYPES.keys())}")
    if layer_type != "tile" and tileset_name:
        raise ValidationError("tileset_name applies only to tile layers")
    if layer_type == "tile" and not tileset_name:
        raise ValidationError(
            "A tile layer needs a tileset: pass the tileset asset name so the layer gets its tile grid."
        )
    tileset = _tileset_grid(root, room_data, tileset_name) if layer_type == "tile" else None

    siblings = room_data.setdefault("layers", [])
    if depth is None:
        depths = [layer.get("depth", 0) for layer in siblings if isinstance(layer, dict)]
        layer_depth = min(depths) - 100 if depths else 0
    else:
        layer_depth = int(depth)

    # Create the layer entry (GameMaker-compatible, with type tag first)
    new_layer = create_layer_data(
        layer_name, layer_type, layer_depth, userdefined_depth=depth is not None, tileset=tileset
    )
    _insert_by_depth(siblings, new_layer)

    _save_room_data(room_path, room_data)
    print(f"[OK] Added {layer_type} layer '{layer_name}' to room '{room_name}' at depth {layer_depth}")
    return True


def remove_layer(room_name: str, layer_name: str) -> bool:
    """Remove a layer (and any layers nested in it) with its instances and their creation code."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)

    siblings = _sibling_list(room_data.get("layers", []), layer_name)
    if siblings is None:
        raise AssetNotFoundError(f"Layer '{layer_name}' not found in room '{room_name}'")
    removed = next(layer for layer in siblings if isinstance(layer, dict) and layer.get("name") == layer_name)
    siblings.remove(removed)
    removed_instances = {
        instance.get("name")
        for layer in _iter_layers([removed])
        for instance in layer.get("instances") or []
        if isinstance(instance, dict) and instance.get("name")
    }
    room_data["instanceCreationOrder"] = [
        entry
        for entry in room_data.get("instanceCreationOrder", [])
        if (entry if isinstance(entry, str) else entry.get("name") if isinstance(entry, dict) else None)
        not in removed_instances
    ]
    for instance_name in sorted(removed_instances):
        code_path = creation_code_path(room_path, instance_name)
        if code_path.exists():
            transactional_unlink(code_path)
            print(f"[OK] Removed creation code file: {code_path}")
    _save_room_data(room_path, room_data)
    print(f"[OK] Removed layer '{layer_name}' from room '{room_name}'")
    return True


def list_layers(room_name: str) -> List[Dict[str, Any]]:
    """List all layers in a room."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)

    results = []
    print(f"[ROOM] Layers in room '{room_name}':")
    print(f"{'Name':<20} {'Type':<15} {'Depth':<10} {'Visible'}")
    print("-" * 55)

    for layer in _iter_layers(room_data.get("layers", [])):
        name = layer.get("name")
        res_type = layer.get("resourceType", "Unknown")
        # Map back to simple type
        layer_type = "Unknown"
        for k, v in LAYER_TYPES.items():
            if v == res_type:
                layer_type = k.capitalize()
                break

        depth = layer.get("depth", 0)
        visible = "Yes" if layer.get("visible", True) else "No"

        print(f"{name:<20} {layer_type:<15} {depth:<10} {visible}")
        results.append({"name": name, "type": layer_type, "depth": depth, "visible": layer.get("visible", True)})

    return results


def reorder_layer(room_name: str, layer_name: str, new_depth: int) -> bool:
    """Give a layer a user-defined depth and re-sort its siblings into GameMaker's ascending order."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)

    siblings = _sibling_list(room_data.get("layers", []), layer_name)
    if siblings is None:
        raise AssetNotFoundError(f"Layer '{layer_name}' not found in room '{room_name}'")
    layer = next(item for item in siblings if isinstance(item, dict) and item.get("name") == layer_name)
    old_depth = layer.get("depth", 0)
    layer["depth"] = int(new_depth)
    layer["userdefinedDepth"] = True
    siblings.remove(layer)
    _insert_by_depth(siblings, layer)
    print(f"[OK] Changed layer '{layer_name}' depth from {old_depth} to {new_depth}")

    _save_room_data(room_path, room_data)
    return True


# ------------------------------------------------------------------
# CLI Handlers
# ------------------------------------------------------------------


def handle_add_layer(args):
    return add_layer(args.room, args.name, args.type, args.depth, tileset_name=args.tileset)


def handle_remove_layer(args):
    return remove_layer(args.room, args.name)


def handle_list_layers(args):
    return list_layers(args.room)


def handle_reorder_layer(args):
    return reorder_layer(args.room, args.name, args.new_depth)


def main():
    parser = argparse.ArgumentParser(description="GameMaker Studio Room Layer Helper")
    subparsers = parser.add_subparsers(dest="command", help="Layer operation")

    # Add Layer
    add_parser = subparsers.add_parser("add-layer", help="Add a new layer to a room")
    add_parser.add_argument("room", help="Room name")
    add_parser.add_argument("name", help="Layer name")
    add_parser.add_argument("--type", default="instance", choices=LAYER_TYPES.keys(), help="Layer type")
    add_parser.add_argument("--depth", type=int, help="Layer depth (default: on top of the existing layers)")
    add_parser.add_argument("--tileset", help="Tileset asset name (required for tile layers)")
    add_parser.set_defaults(func=handle_add_layer)

    # Remove Layer
    remove_parser = subparsers.add_parser("remove-layer", help="Remove a layer from a room")
    remove_parser.add_argument("room", help="Room name")
    remove_parser.add_argument("name", help="Layer name")
    remove_parser.set_defaults(func=handle_remove_layer)

    # List Layers
    list_parser = subparsers.add_parser("list-layers", help="List all layers in a room")
    list_parser.add_argument("room", help="Room name")
    list_parser.set_defaults(func=handle_list_layers)

    # Reorder Layer
    reorder_parser = subparsers.add_parser("reorder-layer", help="Change the depth of a layer")
    reorder_parser.add_argument("room", help="Room name")
    reorder_parser.add_argument("name", help="Layer name")
    reorder_parser.add_argument("--new-depth", type=int, required=True, help="New depth")
    reorder_parser.set_defaults(func=handle_reorder_layer)

    return run_room_helper_cli(
        parser,
        "layer",
        {"add-layer": "add", "remove-layer": "remove", "list-layers": "list", "reorder-layer": "reorder"},
    )


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except GMSError as e:
        sys.exit(e.exit_code)
    except Exception:
        sys.exit(1)
