#!/usr/bin/env python3
"""
GameMaker Studio Room Instance Helper
Manages object instances within GameMaker room layers.
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

def find_layer_by_name(layers, layer_name):
    """Find a layer by name in the layers list."""
    for layer in layers:
        if layer.get("name") == layer_name:
            return layer
    return None

def create_instance_data(object_name, x, y, layer_name, **kwargs):
    """Create a new instance data structure."""
    instance_id = generate_uuid()
    
    instance_data = {
        "__type": "GMRInstance",
        "colour": 4294967295,
        "frozen": False,
        "hasCreationCode": False,
        "ignore": False,
        "imageIndex": 0,
        "imageSpeed": 1.0,
        "inheritCode": False,
        "inheritedItemId": None,
        "inheritItemSettings": False,
        "isDnd": False,
        "name": f"inst_{instance_id}",
        "objectId": {
            "name": object_name,
            "path": f"objects/{object_name}/{object_name}.yy"
        },
        "properties": [],
        "resourceType": "GMRInstance",
        "resourceVersion": "2.0",
        "rotation": kwargs.get('rotation', 0.0),
        "scaleX": kwargs.get('scale_x', 1.0),
        "scaleY": kwargs.get('scale_y', 1.0),
        "x": float(x),
        "y": float(y)
    }
    
    # Add creation code if provided
    if 'creation_code' in kwargs and kwargs['creation_code']:
        instance_data["hasCreationCode"] = True
        instance_data["creationCodeFile"] = f"rooms/{layer_name}/{instance_data['name']}.gml"
    
    return instance_data

def add_instance(args):
    """Add a new instance to a room layer."""
    try:
        room_data, room_path = load_room_data(args.room_name)
        
        # Find the target layer
        layers = room_data.get("layers", [])
        target_layer = find_layer_by_name(layers, args.layer_name)
        
        if not target_layer:
            print(f"[ERROR] Layer '{args.layer_name}' not found in room '{args.room_name}'")
            return False
        
        # Check if this is an instance layer
        if target_layer.get("__type") != "GMRInstanceLayer":
            print(f"[ERROR] Layer '{args.layer_name}' is not an instance layer (type: {target_layer.get('__type', 'Unknown')})")
            return False
        
        # Create instance kwargs
        kwargs = {}
        if args.rotation is not None:
            kwargs['rotation'] = args.rotation
        if args.scale_x is not None:
            kwargs['scale_x'] = args.scale_x
        if args.scale_y is not None:
            kwargs['scale_y'] = args.scale_y
        if args.creation_code:
            kwargs['creation_code'] = args.creation_code
        
        # Create new instance
        new_instance = create_instance_data(args.object_name, args.x, args.y, args.layer_name, **kwargs)
        
        # Add to layer
        if "instances" not in target_layer:
            target_layer["instances"] = []
        
        target_layer["instances"].append(new_instance)
        
        # Save room data
        save_room_data(room_data, room_path)
        
        # Create creation code file if needed
        if args.creation_code:
            creation_code_path = Path(f"rooms/{args.room_name}/{new_instance['name']}.gml")
            creation_code_path.parent.mkdir(parents=True, exist_ok=True)
            creation_code_path.write_text(args.creation_code, encoding='utf-8')
            print(f"[OK] Created creation code file: {creation_code_path}")
        
        print(f"[OK] Added instance of '{args.object_name}' to layer '{args.layer_name}' at ({args.x}, {args.y})")
        print(f"  Instance name: {new_instance['name']}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error adding instance: {e}")
        return False

def remove_instance(args):
    """Remove an instance from a room."""
    try:
        room_data, room_path = load_room_data(args.room_name)
        
        # Search all layers for the instance
        layers = room_data.get("layers", [])
        instance_found = False
        
        for layer in layers:
            if layer.get("__type") == "GMRInstanceLayer" and "instances" in layer:
                original_count = len(layer["instances"])
                layer["instances"] = [inst for inst in layer["instances"] 
                                    if inst.get("name") != args.instance_name]
                
                if len(layer["instances"]) < original_count:
                    instance_found = True
                    print(f"[OK] Removed instance '{args.instance_name}' from layer '{layer.get('name')}'")
                    break
        
        if not instance_found:
            print(f"[ERROR] Instance '{args.instance_name}' not found in room '{args.room_name}'")
            return False
        
        # Save room data
        save_room_data(room_data, room_path)
        
        # Remove creation code file if it exists
        creation_code_path = Path(f"rooms/{args.room_name}/{args.instance_name}.gml")
        if creation_code_path.exists():
            creation_code_path.unlink()
            print(f"[OK] Removed creation code file: {creation_code_path}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error removing instance: {e}")
        return False

def list_instances(args):
    """List instances in a room or specific layer."""
    try:
        room_data, _ = load_room_data(args.room_name)
        
        layers = room_data.get("layers", [])
        instance_count = 0
        
        print(f"[ROOM] Instances in room '{args.room_name}':")
        
        for layer in layers:
            if layer.get("__type") == "GMRInstanceLayer":
                layer_name = layer.get("name", "Unknown")
                instances = layer.get("instances", [])
                
                # Filter by layer if specified
                if args.layer_name and layer_name != args.layer_name:
                    continue
                
                if instances:
                    print(f"\n[FOLDER] Layer: {layer_name}")
                    print(f"{'Instance Name':<20} {'Object':<20} {'Position':<15} {'Scale':<10} {'Rotation':<8}")
                    print("-" * 80)
                    
                    for instance in instances:
                        name = instance.get("name", "Unknown")
                        obj_name = instance.get("objectId", {}).get("name", "Unknown")
                        x = instance.get("x", 0)
                        y = instance.get("y", 0)
                        scale_x = instance.get("scaleX", 1.0)
                        scale_y = instance.get("scaleY", 1.0)
                        rotation = instance.get("rotation", 0.0)
                        
                        position = f"({x:.0f}, {y:.0f})"
                        scale = f"({scale_x:.1f}, {scale_y:.1f})"
                        
                        print(f"{name:<20} {obj_name:<20} {position:<15} {scale:<10} {rotation:<8.1f}")
                        instance_count += 1
        
        if instance_count == 0:
            filter_text = f" in layer '{args.layer_name}'" if args.layer_name else ""
            print(f"No instances found{filter_text}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error listing instances: {e}")
        return False

def modify_instance(args):
    """Modify properties of an instance."""
    try:
        room_data, room_path = load_room_data(args.room_name)
        
        # Search all layers for the instance
        layers = room_data.get("layers", [])
        instance_found = False
        
        for layer in layers:
            if layer.get("__type") == "GMRInstanceLayer" and "instances" in layer:
                for instance in layer["instances"]:
                    if instance.get("name") == args.instance_name:
                        # Update properties
                        if args.x is not None:
                            instance["x"] = float(args.x)
                        if args.y is not None:
                            instance["y"] = float(args.y)
                        if args.rotation is not None:
                            instance["rotation"] = float(args.rotation)
                        if args.scale_x is not None:
                            instance["scaleX"] = float(args.scale_x)
                        if args.scale_y is not None:
                            instance["scaleY"] = float(args.scale_y)
                        
                        instance_found = True
                        print(f"[OK] Modified instance '{args.instance_name}' in layer '{layer.get('name')}'")
                        break
                
                if instance_found:
                    break
        
        if not instance_found:
            print(f"[ERROR] Instance '{args.instance_name}' not found in room '{args.room_name}'")
            return False
        
        # Save room data
        save_room_data(room_data, room_path)
        return True
        
    except Exception as e:
        print(f"[ERROR] Error modifying instance: {e}")
        return False

def set_creation_code(args):
    """Set creation code for an instance."""
    try:
        room_data, room_path = load_room_data(args.room_name)
        
        # Search all layers for the instance
        layers = room_data.get("layers", [])
        instance_found = False
        target_instance = None
        
        for layer in layers:
            if layer.get("__type") == "GMRInstanceLayer" and "instances" in layer:
                for instance in layer["instances"]:
                    if instance.get("name") == args.instance_name:
                        target_instance = instance
                        instance_found = True
                        break
                
                if instance_found:
                    break
        
        if not instance_found:
            print(f"[ERROR] Instance '{args.instance_name}' not found in room '{args.room_name}'")
            return False
        
        # Update instance to have creation code
        target_instance["hasCreationCode"] = True
        target_instance["creationCodeFile"] = f"rooms/{args.room_name}/{args.instance_name}.gml"
        
        # Save room data
        save_room_data(room_data, room_path)
        
        # Create creation code file
        creation_code_path = Path(f"rooms/{args.room_name}/{args.instance_name}.gml")
        creation_code_path.parent.mkdir(parents=True, exist_ok=True)
        creation_code_path.write_text(args.code, encoding='utf-8')
        
        print(f"[OK] Set creation code for instance '{args.instance_name}'")
        print(f"  Code file: {creation_code_path}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error setting creation code: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='GameMaker Studio Room Instance Helper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s add-instance r_game o_player --layer "lyr_player" --x 100 --y 200
  %(prog)s add-instance r_game o_enemy_zombie --layer "lyr_enemies" --x 300 --y 400 --scale-x 1.5
  %(prog)s remove-instance r_game inst_12345678
  %(prog)s list-instances r_game --layer "lyr_player"
  %(prog)s modify-instance r_game inst_12345678 --x 150 --y 250 --rotation 45
  %(prog)s set-creation-code r_game inst_12345678 --code "hp = 100; damage = 25;"
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Instance operation')
    subparsers.required = True
    
    # Add instance command
    add_parser = subparsers.add_parser('add-instance', help='Add an object instance to a room layer')
    add_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    add_parser.add_argument('object_name', help='Object name (e.g., o_player)')
    add_parser.add_argument('--layer', dest='layer_name', required=True, help='Target layer name')
    add_parser.add_argument('--x', type=float, required=True, help='X position')
    add_parser.add_argument('--y', type=float, required=True, help='Y position')
    add_parser.add_argument('--rotation', type=float, help='Rotation in degrees')
    add_parser.add_argument('--scale-x', dest='scale_x', type=float, help='X scale factor')
    add_parser.add_argument('--scale-y', dest='scale_y', type=float, help='Y scale factor')
    add_parser.add_argument('--creation-code', dest='creation_code', help='Creation code for the instance')
    add_parser.set_defaults(func=add_instance)
    
    # Remove instance command
    remove_parser = subparsers.add_parser('remove-instance', help='Remove an instance from a room')
    remove_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    remove_parser.add_argument('instance_name', help='Instance name (e.g., inst_12345678)')
    remove_parser.set_defaults(func=remove_instance)
    
    # List instances command
    list_parser = subparsers.add_parser('list-instances', help='List instances in a room')
    list_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    list_parser.add_argument('--layer', dest='layer_name', help='Filter by layer name')
    list_parser.set_defaults(func=list_instances)
    
    # Modify instance command
    modify_parser = subparsers.add_parser('modify-instance', help='Modify properties of an instance')
    modify_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    modify_parser.add_argument('instance_name', help='Instance name (e.g., inst_12345678)')
    modify_parser.add_argument('--x', type=float, help='New X position')
    modify_parser.add_argument('--y', type=float, help='New Y position')
    modify_parser.add_argument('--rotation', type=float, help='New rotation in degrees')
    modify_parser.add_argument('--scale-x', dest='scale_x', type=float, help='New X scale factor')
    modify_parser.add_argument('--scale-y', dest='scale_y', type=float, help='New Y scale factor')
    modify_parser.set_defaults(func=modify_instance)
    
    # Set creation code command
    code_parser = subparsers.add_parser('set-creation-code', help='Set creation code for an instance')
    code_parser.add_argument('room_name', help='Room name (e.g., r_game)')
    code_parser.add_argument('instance_name', help='Instance name (e.g., inst_12345678)')
    code_parser.add_argument('--code', required=True, help='Creation code to set')
    code_parser.set_defaults(func=set_creation_code)
    
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
