#!/usr/bin/env python3
"""
GameMaker Studio Room Instance Helper
Provides CLI and library functions for managing object instances in rooms.
"""

import os
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from .utils import load_json_loose, save_json_loose, find_yyp, validate_working_directory
from .exceptions import GMSError, ProjectNotFoundError, AssetNotFoundError, ValidationError

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

def _find_layer_by_name(room_data: Dict[str, Any], layer_name: str) -> Dict[str, Any]:
    """Find a layer by name in room data."""
    layers = room_data.get("layers", [])
    for layer in layers:
        if layer.get("name") == layer_name:
            return layer
    raise ValidationError(f"Layer '{layer_name}' not found in room")

# ------------------------------------------------------------------
# Library Functions
# ------------------------------------------------------------------

def add_instance(room_name: str, object_name: str, x: float, y: float, layer_name: str = "Instances") -> str:
    """
    Add an object instance to a room layer.
    Returns the new instance name (UUID).
    """
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    layer = _find_layer_by_name(room_data, layer_name)
    if layer.get("resourceType") != "GMRInstanceLayer":
        raise ValidationError(f"Layer '{layer_name}' is not an instance layer (type: {layer.get('resourceType')})")
    
    # Generate a unique name/ID for the instance
    import uuid
    instance_id = f"inst_{uuid.uuid4().hex}"
    
    # Create the instance entry (GameMaker-compatible, with type tag first)
    new_instance = {
        "$GMRInstance": "",
        "%Name": instance_id,
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
        "name": instance_id,
        "objectId": {"name": object_name, "path": f"objects/{object_name}/{object_name}.yy"},
        "properties": [],
        "resourceType": "GMRInstance",
        "resourceVersion": "2.0",
        "rotation": 0.0,
        "scaleX": 1.0,
        "scaleY": 1.0,
        "x": float(x),
        "y": float(y),
    }
    
    if "instances" not in layer:
        layer["instances"] = []
    layer["instances"].append(new_instance)
    
    _save_room_data(room_path, room_data)
    print(f"[OK] Added instance of '{object_name}' to layer '{layer_name}' at ({x}, {y})")
    print(f"  Instance name: {instance_id}")
    return instance_id

def remove_instance(room_name: str, instance_id: str):
    """Remove an instance from a room."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    found = False
    for layer in room_data.get("layers", []):
        if layer.get("resourceType") == "GMRInstanceLayer":
            instances = layer.get("instances", [])
            new_instances = [inst for inst in instances if inst.get("name") != instance_id]
            if len(new_instances) < len(instances):
                layer["instances"] = new_instances
                found = True
                break
    
    if not found:
        raise AssetNotFoundError(f"Instance '{instance_id}' not found in room '{room_name}'")
    
    # Check for and remove creation code file if it exists
    creation_code_path = Path("rooms") / room_name / f"{instance_id}.gml"
    if creation_code_path.exists():
        creation_code_path.unlink()
        print(f"[OK] Removed creation code file: {creation_code_path}")
        
    _save_room_data(room_path, room_data)
    print(f"[OK] Removed instance '{instance_id}' from room '{room_name}'")
    return True

def list_instances(room_name: str, layer_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """List instances in a room, optionally filtered by layer."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    results = []
    print(f"[ROOM] Instances in room '{room_name}':")
    
    layers = room_data.get("layers", [])
    if layer_name:
        layers = [l for l in layers if l.get("name") == layer_name]
        if not layers:
            raise ValidationError(f"Layer '{layer_name}' not found in room")
            
    for layer in layers:
        if layer.get("resourceType") == "GMRInstanceLayer":
            instances = layer.get("instances", [])
            if not instances and not layer_name:
                continue
                
            print(f"\n[FOLDER] Layer: {layer.get('name')}")
            print(f"{'Instance Name':<35} {'Object':<20} {'Position':<15} {'Scale':<10} {'Rotation'}")
            print("-" * 90)
            
            for inst in instances:
                obj_name = inst.get("objectId", {}).get("name", "Unknown")
                pos = f"({inst.get('x')}, {inst.get('y')})"
                scale = f"({inst.get('scaleX')}, {inst.get('scaleY')})"
                rot = inst.get("rotation")
                name = inst.get("name")
                
                print(f"{name:<35} {obj_name:<20} {pos:<15} {scale:<10} {rot}")
                results.append({
                    "name": name,
                    "object": obj_name,
                    "layer": layer.get("name"),
                    "x": inst.get("x"),
                    "y": inst.get("y")
                })
                
    if not results:
        print("No instances found")
        
    return results

def modify_instance(room_name: str, instance_id: str, **kwargs):
    """
    Modify properties of an instance.
    Supported kwargs: x, y, scaleX, scaleY, rotation, object_name
    """
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    found_inst = None
    target_layer = None
    
    for layer in room_data.get("layers", []):
        if layer.get("resourceType") == "GMRInstanceLayer":
            for inst in layer.get("instances", []):
                if inst.get("name") == instance_id:
                    found_inst = inst
                    target_layer = layer
                    break
        if found_inst:
            break
            
    if not found_inst:
        raise AssetNotFoundError(f"Instance '{instance_id}' not found in room '{room_name}'")
        
    # Update properties
    if 'x' in kwargs: found_inst['x'] = float(kwargs['x'])
    if 'y' in kwargs: found_inst['y'] = float(kwargs['y'])
    if 'scaleX' in kwargs: found_inst['scaleX'] = float(kwargs['scaleX'])
    if 'scaleY' in kwargs: found_inst['scaleY'] = float(kwargs['scaleY'])
    if 'rotation' in kwargs: found_inst['rotation'] = float(kwargs['rotation'])
    if 'object_name' in kwargs:
        obj_name = kwargs['object_name']
        found_inst['objectId'] = {"name": obj_name, "path": f"objects/{obj_name}/{obj_name}.yy"}
        
    _save_room_data(room_path, room_data)
    print(f"[OK] Modified instance '{instance_id}' in room '{room_name}'")
    return True

def set_creation_code(room_name: str, instance_id: str, code: str):
    """Set creation code for an instance."""
    room_path = _find_room_file(room_name)
    room_data = _load_room_data(room_path)
    
    found_inst = None
    for layer in room_data.get("layers", []):
        if layer.get("resourceType") == "GMRInstanceLayer":
            for inst in layer.get("instances", []):
                if inst.get("name") == instance_id:
                    found_inst = inst
                    break
        if found_inst:
            break
            
    if not found_inst:
        raise AssetNotFoundError(f"Instance '{instance_id}' not found in room '{room_name}'")
        
    # Create the code file
    code_path = Path("rooms") / room_name / f"{instance_id}.gml"
    code_path.write_text(code, encoding="utf-8")
    
    # Update instance to indicate it has code
    found_inst["hasCreationCode"] = True
    
    _save_room_data(room_path, room_data)
    print(f"[OK] Set creation code for instance '{instance_id}'")
    print(f"  Code file: {code_path}")
    return True

# ------------------------------------------------------------------
# CLI Handlers
# ------------------------------------------------------------------

def handle_add_instance(args):
    return add_instance(args.room, args.object, args.x, args.y, args.layer)

def handle_remove_instance(args):
    return remove_instance(args.room, args.instance_id)

def handle_list_instances(args):
    return list_instances(args.room, args.layer)

def handle_modify_instance(args):
    props = {}
    if args.x is not None: props['x'] = args.x
    if args.y is not None: props['y'] = args.y
    if args.scale_x is not None: props['scaleX'] = args.scale_x
    if args.scale_y is not None: props['scaleY'] = args.scale_y
    if args.rotation is not None: props['rotation'] = args.rotation
    if args.object is not None: props['object_name'] = args.object
    return modify_instance(args.room, args.instance_id, **props)

def handle_set_creation_code(args):
    return set_creation_code(args.room, args.instance_id, args.code)

def main():
    parser = argparse.ArgumentParser(description="GameMaker Studio Room Instance Helper")
    subparsers = parser.add_subparsers(dest="command", help="Instance operation")
    
    # Add Instance
    add_parser = subparsers.add_parser("add-instance", help="Add an object instance to a room layer")
    add_parser.add_argument("room", help="Room name")
    add_parser.add_argument("object", help="Object name")
    add_parser.add_argument("--x", type=float, default=0.0, help="X position")
    add_parser.add_argument("--y", type=float, default=0.0, help="Y position")
    add_parser.add_argument("--layer", default="Instances", help="Layer name (default: Instances)")
    add_parser.set_defaults(func=handle_add_instance)
    
    # Remove Instance
    remove_parser = subparsers.add_parser("remove-instance", help="Remove an instance from a room")
    remove_parser.add_argument("room", help="Room name")
    remove_parser.add_argument("instance_id", help="Instance ID (e.g. inst_12345678)")
    remove_parser.set_defaults(func=handle_remove_instance)
    
    # List Instances
    list_parser = subparsers.add_parser("list-instances", help="List instances in a room")
    list_parser.add_argument("room", help="Room name")
    list_parser.add_argument("--layer", help="Filter by layer name")
    list_parser.set_defaults(func=handle_list_instances)
    
    # Modify Instance
    modify_parser = subparsers.add_parser("modify-instance", help="Modify properties of an instance")
    modify_parser.add_argument("room", help="Room name")
    modify_parser.add_argument("instance_id", help="Instance ID")
    modify_parser.add_argument("--x", type=float, help="New X position")
    modify_parser.add_argument("--y", type=float, help="New Y position")
    modify_parser.add_argument("--scale-x", type=float, help="New X scale")
    modify_parser.add_argument("--scale-y", type=float, help="New Y scale")
    modify_parser.add_argument("--rotation", type=float, help="New rotation")
    modify_parser.add_argument("--object", help="New object type")
    modify_parser.set_defaults(func=handle_modify_instance)
    
    # Set Creation Code
    code_parser = subparsers.add_parser("set-creation-code", help="Set creation code for an instance")
    code_parser.add_argument("room", help="Room name")
    code_parser.add_argument("instance_id", help="Instance ID")
    code_parser.add_argument("--code", required=True, help="GML code")
    code_parser.set_defaults(func=handle_set_creation_code)
    
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

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except GMSError as e:
        sys.exit(e.exit_code)
    except Exception:
        sys.exit(1)
