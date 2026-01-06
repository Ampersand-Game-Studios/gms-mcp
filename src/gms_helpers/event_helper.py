#!/usr/bin/env python3
"""
GameMaker Studio Event Helper
Provides CLI and library functions for managing object events.
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from .utils import load_json_loose, save_json_loose, validate_working_directory
from .exceptions import GMSError, ProjectNotFoundError, AssetNotFoundError, ValidationError
from .maintenance.event_sync import sync_object_events

# ------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------

def _filename_to_event(filename: str) -> Tuple[int, int]:
    """Convert GML event filename to event type and number."""
    if not filename.endswith(".gml"):
        return None, None
    
    parts = filename[:-4].split("_")
    if len(parts) != 2:
        return None, None
        
    type_map = {
        "Create": 0, "Destroy": 1, "Alarm": 2, "Step": 3, "Collision": 4,
        "Keyboard": 5, "Mouse": 6, "Other": 7, "Draw": 8, "KeyPress": 9,
        "KeyRelease": 10, "Trigger": 11, "CleanUp": 12, "Gesture": 13, "PreCreate": -1
    }
    
    event_type = type_map.get(parts[0])
    try:
        event_num = int(parts[1])
        return event_type, event_num
    except ValueError:
        return None, None

def _event_to_filename(event_type: int, event_num: int) -> str:
    """Convert event type and number to GML filename."""
    type_map = {
        0: "Create", 1: "Destroy", 2: "Alarm", 3: "Step", 4: "Collision",
        5: "Keyboard", 6: "Mouse", 7: "Other", 8: "Draw", 9: "KeyPress",
        10: "KeyRelease", 11: "Trigger", 12: "CleanUp", 13: "Gesture", -1: "PreCreate"
    }
    type_name = type_map.get(event_type, "Other")
    return f"{type_name}_{event_num}.gml"

# ------------------------------------------------------------------
# Library Functions
# ------------------------------------------------------------------

def list_events(object_name: str) -> List[Dict[str, str]]:
    """List all events for an object."""
    obj_path = Path("objects") / object_name / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")
        
    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")
        
    events = []
    event_list = data.get("eventList", [])
    
    if not event_list:
        print(f"No events found for {object_name}")
        return []
        
    print(f"Events for {object_name}:")
    for event in event_list:
        e_type = event.get("eventType")
        e_num = event.get("eventNum")
        filename = _event_to_filename(e_type, e_num)
        print(f"  - {filename}")
        events.append({"type": e_type, "num": e_num, "filename": filename})
        
    return events

def add_event(object_name: str, event_spec: str, template: str = "") -> bool:
    """Add a new event to an object."""
    # Parse event spec (e.g. "create", "step:0", "alarm:0")
    parts = event_spec.lower().split(":")
    e_type_name = parts[0]
    e_num = 0
    if len(parts) > 1:
        try:
            e_num = int(parts[1])
        except ValueError:
            raise ValidationError(f"Invalid event number in spec: {event_spec}")
            
    type_map = {
        "create": 0, "destroy": 1, "alarm": 2, "step": 3, "collision": 4,
        "keyboard": 5, "mouse": 6, "other": 7, "draw": 8, "keypress": 9,
        "keyrelease": 10, "trigger": 11, "cleanup": 12, "gesture": 13
    }
    
    if e_type_name not in type_map:
        raise ValidationError(f"Unknown event type: {e_type_name}")
        
    e_type = type_map[e_type_name]
    
    obj_dir = Path("objects") / object_name
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")
        
    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")
        
    # Check if event already exists
    event_list = data.get("eventList", [])
    for event in event_list:
        if event.get("eventType") == e_type and event.get("eventNum") == e_num:
            print(f"[WARN] Event {event_spec} already exists for {object_name}")
            return True
            
    # Create the GML file
    filename = _event_to_filename(e_type, e_num)
    gml_path = obj_dir / filename
    if not gml_path.exists():
        content = template if template else f"// {filename} event\n"
        gml_path.write_text(content, encoding="utf-8")
        print(f"[OK] Created event file: {gml_path}")
        
    # Add to .yy file
    event_name = filename.replace(".gml", "")
    new_event = {
        "$GMEvent": "v1",
        "%Name": event_name,
        "collisionObjectId": None,
        "eventNum": e_num,
        "eventType": e_type,
        "isDnD": False,
        "name": event_name,
        "resourceType": "GMEvent",
        "resourceVersion": "2.0"
    }
    
    if "eventList" not in data:
        data["eventList"] = []
    data["eventList"].append(new_event)
    
    save_json_loose(obj_path, data)
    print(f"[OK] Added event {event_spec} to {object_name}")
    return True

def remove_event(object_name: str, event_spec: str, keep_file: bool = False) -> bool:
    """Remove an event from an object."""
    # Similar parsing to add_event
    parts = event_spec.lower().split(":")
    e_type_name = parts[0]
    e_num = 0
    if len(parts) > 1:
        e_num = int(parts[1])
        
    type_map = {
        "create": 0, "destroy": 1, "alarm": 2, "step": 3, "collision": 4,
        "keyboard": 5, "mouse": 6, "other": 7, "draw": 8, "keypress": 9,
        "keyrelease": 10, "trigger": 11, "cleanup": 12, "gesture": 13
    }
    
    if e_type_name not in type_map:
        raise ValidationError(f"Unknown event type: {e_type_name}")
        
    e_type = type_map[e_type_name]
    
    obj_dir = Path("objects") / object_name
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")
        
    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")
        
    event_list = data.get("eventList", [])
    new_event_list = [e for e in event_list if not (e.get("eventType") == e_type and e.get("eventNum") == e_num)]
    
    if len(new_event_list) == len(event_list):
        print(f"[WARN] Event {event_spec} not found for {object_name}")
        return False
        
    data["eventList"] = new_event_list
    save_json_loose(obj_path, data)
    
    if not keep_file:
        filename = _event_to_filename(e_type, e_num)
        gml_path = obj_dir / filename
        if gml_path.exists():
            gml_path.unlink()
            print(f"[OK] Deleted event file: {gml_path}")
            
    print(f"[OK] Removed event {event_spec} from {object_name}")
    return True


def duplicate_event(object_name: str, source_event_spec: str, target_num: int) -> bool:
    """
    Duplicate an event within an object.

    Example:
      duplicate_event("o_player", "step:0", 1) -> copies Step_0.gml -> Step_1.gml and adds event entry.
    """
    # Parse source spec (e.g. "step", "step:0", "alarm:2")
    parts = (source_event_spec or "").lower().split(":")
    e_type_name = parts[0]
    source_num = 0
    if len(parts) > 1 and parts[1] != "":
        try:
            source_num = int(parts[1])
        except ValueError:
            raise ValidationError(f"Invalid source event number in spec: {source_event_spec}")

    type_map = {
        "create": 0, "destroy": 1, "alarm": 2, "step": 3, "collision": 4,
        "keyboard": 5, "mouse": 6, "other": 7, "draw": 8, "keypress": 9,
        "keyrelease": 10, "trigger": 11, "cleanup": 12, "gesture": 13
    }

    if e_type_name not in type_map:
        raise ValidationError(f"Unknown event type: {e_type_name}")

    e_type = type_map[e_type_name]

    obj_dir = Path("objects") / object_name
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    # Ensure source exists in eventList (or at least on disk)
    source_filename = _event_to_filename(e_type, source_num)
    target_filename = _event_to_filename(e_type, int(target_num))

    event_list = data.get("eventList", []) or []
    has_source_entry = any(
        e.get("eventType") == e_type and e.get("eventNum") == source_num
        for e in event_list
    )
    if not has_source_entry and not (obj_dir / source_filename).exists():
        raise ValidationError(f"Source event '{source_event_spec}' not found for {object_name}")

    # If target already exists, treat as success
    if any(e.get("eventType") == e_type and e.get("eventNum") == int(target_num) for e in event_list):
        print(f"[WARN] Event {e_type_name}:{target_num} already exists for {object_name}")
        return True

    # Copy or create the target GML file
    src_gml = obj_dir / source_filename
    dst_gml = obj_dir / target_filename
    if not dst_gml.exists():
        if src_gml.exists():
            dst_gml.write_text(src_gml.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            dst_gml.write_text(f"// {target_filename} event\n", encoding="utf-8")
        print(f"[OK] Created event file: {dst_gml}")

    # Add event entry to .yy (use modern GMEvent shape)
    type_name_map = {
        0: "Create", 1: "Destroy", 2: "Alarm", 3: "Step", 4: "Collision",
        5: "Keyboard", 6: "Mouse", 7: "Other", 8: "Draw", 9: "KeyPress",
        10: "KeyRelease", 11: "Trigger", 12: "CleanUp", 13: "Gesture", -1: "PreCreate"
    }
    type_name = type_name_map.get(e_type, "Other")
    new_event_name = f"{type_name}_{int(target_num)}"
    new_event = {
        "$GMEvent": "v1",
        "%Name": new_event_name,
        "collisionObjectId": None,
        "eventNum": int(target_num),
        "eventType": e_type,
        "isDnD": False,
        "name": new_event_name,
        "resourceType": "GMEvent",
        "resourceVersion": "2.0",
    }

    if "eventList" not in data or data["eventList"] is None:
        data["eventList"] = []
    data["eventList"].append(new_event)
    save_json_loose(obj_path, data)

    print(f"[OK] Duplicated event {source_event_spec} -> {e_type_name}:{target_num} for {object_name}")
    return True

# ------------------------------------------------------------------
# CLI Handlers
# ------------------------------------------------------------------

def handle_list(args):
    events = list_events(args.object)
    # Return True to indicate success (even if no events found)
    return True

def handle_add(args):
    return add_event(args.object, args.event, args.template)

def handle_remove(args):
    return remove_event(args.object, args.event, args.keep_file)

def handle_validate(args):
    results = sync_object_events(str(Path("objects") / args.object), dry_run=True)
    print(f"\nValidation Report for {args.object}")
    print("-" * 60)
    if results['orphaned_found'] == 0 and results['missing_found'] == 0:
        print("[OK] All events are valid!")
    else:
        if results['orphaned_found'] > 0:
            print(f"[ERROR] Found {results['orphaned_found']} orphaned GML files")
        if results['missing_found'] > 0:
            print(f"[ERROR] Found {results['missing_found']} missing GML files")
    return True

def handle_fix(args):
    results = sync_object_events(str(Path("objects") / args.object), dry_run=False)
    print(f"\nFix Report for {args.object}")
    print("-" * 60)
    print(f"Files created: {results['missing_created']}")
    print(f"Events added: {results['orphaned_fixed']}")
    if results['missing_created'] == 0 and results['orphaned_fixed'] == 0:
        print("[OK] No issues found to fix!")
    else:
        print("[OK] Object events fixed successfully!")
    return True

def main():
    parser = argparse.ArgumentParser(description="GameMaker Studio Event Helper")
    subparsers = parser.add_subparsers(dest="command", help="Event operation")
    
    # List
    list_parser = subparsers.add_parser("list", help="List all events for an object")
    list_parser.add_argument("object", help="Object name")
    list_parser.set_defaults(func=handle_list)
    
    # Add
    add_parser = subparsers.add_parser("add", help="Add a new event")
    add_parser.add_argument("object", help="Object name")
    add_parser.add_argument("event", help="Event spec (e.g. create, step, alarm:0)")
    add_parser.add_argument("--template", help="Optional GML code template")
    add_parser.set_defaults(func=handle_add)
    
    # Remove
    remove_parser = subparsers.add_parser("remove", help="Remove an event")
    remove_parser.add_argument("object", help="Object name")
    remove_parser.add_argument("event", help="Event spec")
    remove_parser.add_argument("--keep-file", action="store_true", help="Don't delete the GML file")
    remove_parser.set_defaults(func=handle_remove)
    
    # Validate
    val_parser = subparsers.add_parser("validate", help="Check for orphaned or missing event files")
    val_parser.add_argument("object", help="Object name")
    val_parser.set_defaults(func=handle_validate)
    
    # Fix
    fix_parser = subparsers.add_parser("fix", help="Fix orphaned or missing event files")
    fix_parser.add_argument("object", help="Object name")
    fix_parser.set_defaults(func=handle_fix)
    
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
