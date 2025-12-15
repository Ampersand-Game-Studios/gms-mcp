#!/usr/bin/env python3
"""
GameMaker Studio Room Layer Helper
Manages layers within GameMaker room assets.
"""

import argparse
import sys
import os
import json
from pathlib import Path

from .utils import (
    load_json_loose,
    save_pretty_json,
    generate_uuid,
    find_yyp_file,
)

# GameMaker layer types
LAYER_TYPES = {
    'background': 'background',
    'instance': 'instances',
    'asset': 'assets',
    'tile': 'tiles',
    'path': 'path',
    'effect': 'effect'
}

def find_room_file(room_name):
    """Find the room .yy file for the given room name."""
    room_path = Path(f"rooms/{room_name}/{room_name}.yy")
    if not room_path.exists():
        raise FileNotFoundError(f"Room file not found: {room_path}")
    return room_path

def load_room_data(room_name):
    """Load room data from .yy file."""
    room_path = find_room_file(room_name)
    return load_json_loose(room_path), room_path

def save_room_data(room_data, room_path):
    """Save room data to .yy file."""
    save_pretty_json(room_path, room_data)

def create_layer_data(layer_name, layer_type, depth):
    """Create a new layer data structure."""
    layer_id = generate_uuid()
    
    # Base layer structure
    layer_data = {
        "__type": "GMRLayer",
        "depth": depth,
        "effectEnabled": True,
        "effectType": None,
        "gridX": 32,
        "gridY": 32,
        "hierarchyFrozen": False,
        "inheritLayerDepth": False,
        "inheritLayerSettings": False,
        "inheritSubLayers": False,
        "inheritVisibility": False,
        "layers": [],
        "name": layer_name,
        "properties": [],
        "resourceType": "GMRLayer",
        "resourceVersion": "2.0",
        "userdefinedDepth": False,
        "visible": True
    }
    
    # Add layer-type specific properties
    if layer_type == 'background':
        layer_data.update({
            "__type": "GMRBackgroundLayer",
            "animationFPS": 15.0,
            "animationSpeedType": 0,
            "colour": 4278190080,
            "hspeed": 0.0,
            "htiled": False,
            "spriteId": None,
            "stretch": False,
            "userdefinedAnimFPS": False,
            "vspeed": 0.0,
            "vtiled": False,
            "x": 0,
            "y": 0,
            "resourceType": "GMRBackgroundLayer"
        })
    elif layer_type == 'instance':
        layer_data.update({
            "__type": "GMRInstanceLayer",
            "instances": [],
            "resourceType": "GMRInstanceLayer"
        })
    elif layer_type == 'asset':
        layer_data.update({
            "__type": "GMRAssetLayer",
            "assets": [],
            "resourceType": "GMRAssetLayer"
        })
    elif layer_type == 'tile':
        layer_data.update({
            "__type": "GMRTileLayer",
            "tiles": {
                "SerialiseHeight": 0,
                "SerialiseWidth": 0,
                "TileCompressedData": [],
                "TileDataFormat": 1
            },
            "tilesetId": None,
            "x": 0,
            "y": 0,
            "resourceType": "GMRTileLayer"
        })
    
    return layer_data

def add_layer(args):
    """Add a new layer to a room."""
    try:
        room_data, room_path = load_room_data(args.room_name)
        
        # Check if layer already exists
        existing_layers = room_data.get("layers", [])
        if any(layer.get("name") == args.layer_name for layer in existing_layers):
            print(f"[ERROR] Layer '{args.layer_name}' already exists in room '{args.room_name}'")
            return False
        
        # Validate layer type
        if args.layer_type not in LAYER_TYPES:
            print(f"[ERROR] Invalid layer type '{args.layer_type}'. Valid types: {', '.join(LAYER_TYPES.keys())}")
            return False
        
        # Create new layer
        new_layer = create_layer_data(args.layer_name, args.layer_type, args.depth)
        
        # Add to room
        existing_layers.append(new_layer)
        
        # Sort layers by depth (deeper layers first)
        existing_layers.sort(key=lambda l: l.get("depth", 0), reverse=True)
        
        room_data["layers"] = existing_layers
        
        # Save room data
        save_room_data(room_data, room_path)
        
        print(f"[OK] Added {args.layer_type} layer '{args.layer_name}' to room '{args.room_name}' at depth {args.depth}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error adding layer: {e}")
        return False

def remove_layer(args):
    """Remove a layer from a room."""
    try:
        room_data, room_path = load_room_data(args.room_name)
        
        # Find and remove layer
        layers = room_data.get("layers", [])
        original_count = len(layers)
        
        layers = [layer for layer in layers if layer.get("name") != args.layer_name]
        
        if len(layers) == original_count:
            print(f"[ERROR] Layer '{args.layer_name}' not found in room '{args.room_name}'")
            return False
        
        room_data["layers"] = layers
        
        # Save room data
        save_room_data(room_data, room_path)
        
        print(f"[OK] Removed layer '{args.layer_name}' from room '{args.room_name}'")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error removing layer: {e}")
        return False

def list_layers(args):
    """List all layers in a room."""
    try:
        room_data, _ = load_room_data(args.room_name)
        
        layers = room_data.get("layers", [])
        
        if not layers:
            print(f"Room '{args.room_name}' has no layers")
            return True
        
        print(f"[ROOM] Layers in room '{args.room_name}':")
        print(f"{'Name':<20} {'Type':<15} {'Depth':<10} {'Visible':<8}")
        print("-" * 55)
        
        # Sort by depth for display
        sorted_layers = sorted(layers, key=lambda l: l.get("depth", 0), reverse=True)
        
        for layer in sorted_layers:
            name = layer.get("name", "Unknown")
            layer_type = layer.get("__type", "Unknown").replace("GMR", "").replace("Layer", "")
            depth = layer.get("depth", 0)
            visible = "Yes" if layer.get("visible", True) else "No"
            
            print(f"{name:<20} {layer_type:<15} {depth:<10} {visible:<8}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error listing layers: {e}")
        return False

def reorder_layer(args):
    """Change the depth of a layer."""
    try:
        room_data, room_path = load_room_data(args.room_name)
        
        # Find and update layer
        layers = room_data.get("layers", [])
        layer_found = False
        
        for layer in layers:
            if layer.get("name") == args.layer_name:
                old_depth = layer.get("depth", 0)
                layer["depth"] = args.new_depth
                layer_found = True
                print(f"[OK] Changed layer '{args.layer_name}' depth from {old_depth} to {args.new_depth}")
                break
        
        if not layer_found:
            print(f"[ERROR] Layer '{args.layer_name}' not found in room '{args.room_name}'")
            return False
        
        # Sort layers by depth
        layers.sort(key=lambda l: l.get("depth", 0), reverse=True)
        room_data["layers"] = layers
        
        # Save room data
        save_room_data(room_data, room_path)
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error reordering layer: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='GameMaker Studio Room Layer Helper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s add-layer r_game "lyr_enemies" --type instance --depth 4150
  %(prog)s add-layer r_game "Background" --type background --depth 5000
  %(prog)s remove-layer r_game "lyr_old_layer"
  %(prog)s list-layers r_game
  %(prog)s reorder-layer r_game "lyr_player" --new-depth 3950

Layer Types:
  background  - Background layer (sprites, colors)
  instance    - Instance layer (objects)
  asset       - Asset layer (sprites, sounds)
  tile        - Tile layer (tilemap)
  path        - Path layer (movement paths)
  effect      - Effect layer (particles, shaders)
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Layer operation')
    subparsers.required = True
    
    # Add layer command
    add_parser = subparsers.add_parser('add-layer', help='Add a new layer to a room')
    add_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    add_parser.add_argument('layer_name', help='New layer name')
    add_parser.add_argument('--type', dest='layer_type', required=True, 
                           choices=list(LAYER_TYPES.keys()), 
                           help='Layer type')
    add_parser.add_argument('--depth', type=int, default=0, help='Layer depth (default: 0)')
    add_parser.set_defaults(func=add_layer)
    
    # Remove layer command
    remove_parser = subparsers.add_parser('remove-layer', help='Remove a layer from a room')
    remove_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    remove_parser.add_argument('layer_name', help='Layer name to remove')
    remove_parser.set_defaults(func=remove_layer)
    
    # List layers command
    list_parser = subparsers.add_parser('list-layers', help='List all layers in a room')
    list_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    list_parser.set_defaults(func=list_layers)
    
    # Reorder layer command
    reorder_parser = subparsers.add_parser('reorder-layer', help='Change the depth of a layer')
    reorder_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    reorder_parser.add_argument('layer_name', help='Layer name to reorder')
    reorder_parser.add_argument('--new-depth', type=int, required=True, help='New depth value')
    reorder_parser.set_defaults(func=reorder_layer)
    
    args = parser.parse_args()
    
    try:
        success = args.func(args)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
