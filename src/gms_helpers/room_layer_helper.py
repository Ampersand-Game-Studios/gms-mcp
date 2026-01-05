#!/usr/bin/env python3
"""
GameMaker Studio Room Layer Helper
Provides CLI and library functions for managing layers in rooms.
"""

import os
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from .utils import load_json_loose, save_json_loose, find_yyp, validate_working_directory
from .exceptions import GMSError, ProjectNotFoundError, AssetNotFoundError, ValidationError

# Layer type constants
LAYER_TYPES = {
    "background": "GMRBackgroundLayer",
    "instance": "GMRInstanceLayer",
    "asset": "GMRAssetLayer",
    "tile": "GMRTileLayer",
    "path": "GMRPathLayer",
    "effect": "GMREffectLayer"
}

# ------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------

def _find_room_file(room_name: str) -> Path:
    """Find the .yy file for a room."""
    room_path = Path("rooms") / room_name / f"{room_name}.yy"
    if not room_path.exists():
        raise AssetNotFoundError(f"Room file not found: {room_path}")
    return room_path

def _load_room_data(room_path: Path) -> Dict[str, Any]:
    """Load room JSON data."""
    data = load_json_loose(room_path)
    if data is None:
        raise GMSError(f"Failed to load room data from {room_path}")
    return data

def _save_room_data(room_path: Path, data: Dict[str, Any]):
    """Save room JSON data."""
    save_json_loose(room_path, data)

def create_layer_data(name: str, layer_type: str, depth: int) -> Dict[str, Any]:
    """Create a new layer data dictionary."""
    if layer_type not in LAYER_TYPES:
        raise ValidationError(f"Invalid layer type '{layer_type}'")

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
            "userdefinedDepth": False,
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
            "userdefinedDepth": False,
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
        "userdefinedDepth": False,
        "visible": True,
    }
    if layer_type == "asset":
        base["assets"] = []
    elif layer_type == "tile":
        base["tiles"] = {"SerialiseHeight": 0, "SerialiseWidth": 0, "TileSerialiseData": []}
    elif layer_type == "path":
        base["paths"] = []
    elif layer_type == "effect":
        base["effects"] = []
    return base

# ------------------------------------------------------------------
# Library Functions
# ------------------------------------------------------------------

def add_layer(room_name: str, layer_name: str, layer_type: str = "instance", depth: int = 0) -> bool:
    """Add a new layer to a room."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    # Check if layer already exists
    for layer in room_data.get("layers", []):
        if layer.get("name") == layer_name:
            raise ValidationError(f"Layer '{layer_name}' already exists in room '{room_name}'")
            
    if layer_type not in LAYER_TYPES:
        raise ValidationError(f"Invalid layer type '{layer_type}'. Valid types: {', '.join(LAYER_TYPES.keys())}")
        
    # Create the layer entry (GameMaker-compatible, with type tag first)
    new_layer = create_layer_data(layer_name, layer_type, depth)
        
    if "layers" not in room_data:
        room_data["layers"] = []
    room_data["layers"].append(new_layer)
    
    _save_room_data(room_path, room_data)
    print(f"[OK] Added {layer_type} layer '{layer_name}' to room '{room_name}' at depth {depth}")
    return True

def remove_layer(room_name: str, layer_name: str) -> bool:
    """Remove a layer from a room."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    layers = room_data.get("layers", [])
    new_layers = [l for l in layers if l.get("name") != layer_name]
    
    if len(new_layers) == len(layers):
        raise AssetNotFoundError(f"Layer '{layer_name}' not found in room '{room_name}'")
        
    room_data["layers"] = new_layers
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
    
    for layer in room_data.get("layers", []):
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
        results.append({
            "name": name,
            "type": layer_type,
            "depth": depth,
            "visible": layer.get("visible", True)
        })
        
    return results

def reorder_layer(room_name: str, layer_name: str, new_depth: int) -> bool:
    """Change the depth of a layer."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    found = False
    for layer in room_data.get("layers", []):
        if layer.get("name") == layer_name:
            old_depth = layer.get("depth", 0)
            layer["depth"] = int(new_depth)
            found = True
            print(f"[OK] Changed layer '{layer_name}' depth from {old_depth} to {new_depth}")
            break
            
    if not found:
        raise AssetNotFoundError(f"Layer '{layer_name}' not found in room '{room_name}'")
        
    room_data["layers"].sort(key=lambda l: l.get("depth", 0), reverse=True)
    _save_room_data(room_path, room_data)
    return True

# ------------------------------------------------------------------
# CLI Handlers
# ------------------------------------------------------------------

def handle_add_layer(args):
    return add_layer(args.room, args.name, args.type, args.depth)

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
    add_parser.add_argument("--depth", type=int, default=0, help="Layer depth")
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
    
    if len(sys.argv) == 1:
        parser.print_help()
        return False
        
    validate_working_directory()
    args = parser.parse_args()
    
    if hasattr(args, "func"):
        try:
            return args.func(args)
        except GMSError as e:
            print(f"[ERROR] {e.message}")
            raise
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
            return False
    else:
        parser.print_help()
        return False

if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except GMSError as e:
        sys.exit(e.exit_code)
    except Exception:
        sys.exit(1)
