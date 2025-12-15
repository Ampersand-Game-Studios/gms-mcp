#!/usr/bin/env python3
"""
GameMaker Studio Object Event Helper
Manages object events: add, remove, duplicate, validate, and fix.
"""

import argparse
import sys
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass

# Direct imports - no complex fallbacks needed
from .utils import (
    load_json_loose,
    save_pretty_json,
    ensure_directory,
    validate_working_directory
)

# GameMaker event type mappings
EVENT_TYPES = {
    "create": 0,
    "destroy": 1,
    "alarm": 2,
    "step": 3,
    "collision": 4,
    "keyboard": 5,
    "mouse": 6,
    "other": 7,
    "draw": 8,
    "keypress": 9,
    "keyrelease": 10,
    "trigger": 11,
    "cleanup": 12,
    "gesture": 13
}

# Event sub-type mappings for common events
STEP_SUBTYPES = {
    "begin": 0,
    "normal": 0,
    "step": 0,
    "end": 2
}

DRAW_SUBTYPES = {
    "draw": 0,
    "gui": 64,
    "gui_begin": 72,
    "gui_end": 73,
    "pre": 76,
    "post": 77
}

OTHER_SUBTYPES = {
    "outside": 0,
    "intersect": 1,
    "game_start": 2,
    "game_end": 3,
    "room_start": 4,
    "room_end": 5
}

@dataclass
class EventInfo:
    """Information about an object event."""
    event_type: int
    event_num: int
    collision_object_id: Optional[str]
    filename: str
    file_exists: bool
    gml_content: Optional[str] = None

@dataclass
class ValidationReport:
    """Report from event validation."""
    errors: List[str]
    warnings: List[str]
    missing_files: List[str]
    orphan_files: List[str]
    duplicates: List[str]

@dataclass
class FixReport:
    """Report from event fixing."""
    files_created: int
    files_deleted: int
    events_added: int
    events_removed: int
    issues_fixed: List[str]

def _event_to_filename(event_type: int, event_num: int, collision_object_id: Optional[str] = None) -> str:
    """Convert event type/num to filename."""
    event_names = {
        0: "Create",
        1: "Destroy", 
        2: "Alarm",
        3: "Step",
        4: "Collision",
        5: "Keyboard",
        6: "Mouse",
        7: "Other",
        8: "Draw",
        9: "KeyPress",
        10: "KeyRelease",
        11: "Trigger",
        12: "CleanUp",
        13: "Gesture"
    }
    
    base_name = event_names.get(event_type, f"Event{event_type}")
    
    if event_type == 4 and collision_object_id:  # Collision events
        return f"{base_name}_{collision_object_id}.gml"
    else:
        return f"{base_name}_{event_num}.gml"

def _filename_to_event(filename: str) -> Tuple[int, int, Optional[str]]:
    """Convert filename to event type/num/collision_object."""
    if not filename.endswith('.gml'):
        raise ValueError(f"Not a GML file: {filename}")
    
    base = filename[:-4]  # Remove .gml
    
    # Handle collision events
    if base.startswith('Collision_'):
        collision_obj = base[10:]  # Remove 'Collision_'
        return (4, 0, collision_obj)
    
    # Handle other events
    parts = base.split('_')
    if len(parts) != 2:
        raise ValueError(f"Invalid event filename format: {filename}")
    
    event_name, event_num_str = parts
    
    # Map event names back to types
    name_to_type = {
        "Create": 0,
        "Destroy": 1,
        "Alarm": 2,
        "Step": 3,
        "Collision": 4,
        "Keyboard": 5,
        "Mouse": 6,
        "Other": 7,
        "Draw": 8,
        "KeyPress": 9,
        "KeyRelease": 10,
        "Trigger": 11,
        "CleanUp": 12,
        "Gesture": 13
    }
    
    event_type = name_to_type.get(event_name)
    if event_type is None:
        raise ValueError(f"Unknown event type: {event_name}")
    
    try:
        event_num = int(event_num_str)
    except ValueError:
        raise ValueError(f"Invalid event number: {event_num_str}")
    
    return (event_type, event_num, None)

def _load_object_yy(obj_name: str) -> Tuple[Path, Dict[str, Any]]:
    """Load object .yy file and return path and data."""
    obj_path = Path(f"objects/{obj_name}")
    yy_path = obj_path / f"{obj_name}.yy"
    
    if not yy_path.exists():
        raise FileNotFoundError(f"Object not found: {yy_path}")
    
    data = load_json_loose(yy_path)
    return yy_path, data

def _save_object_yy(yy_path: Path, data: Dict[str, Any]):
    """Save object .yy file."""
    save_pretty_json(yy_path, data)

def _create_event_stub(obj_path: Path, filename: str, obj_name: str, event_type: int, event_num: int, template: Optional[str] = None):
    """Create a stub GML file for an event."""
    gml_path = obj_path / filename
    
    if template:
        content = template
    else:
        # Determine event name for comment
        event_names = {
            0: "Create",
            1: "Destroy", 
            2: f"Alarm {event_num}",
            3: f"Step ({['Begin', 'Normal', 'End'][event_num] if event_num < 3 else f'Step {event_num}'})",
            8: f"Draw ({['Draw', 'GUI'][1 if event_num >= 64 else 0]})",
            12: "Clean Up"
        }
        
        event_desc = event_names.get(event_type, f"Event {event_type}_{event_num}")
        
        content = f"""/// {event_desc} event for {obj_name}
// Inherit the parent event
event_inherited();

"""
    
    gml_path.write_text(content, encoding="utf-8")

def add_event(obj_name: str, event_type: int, event_num: int = 0, collision_object_id: Optional[str] = None, template: Optional[str] = None) -> bool:
    """Add an event to an object."""
    try:
        yy_path, data = _load_object_yy(obj_name)
        obj_path = yy_path.parent
        
        # Check if event already exists
        event_list = data.get("eventList", [])
        for event in event_list:
            if (event["eventType"] == event_type and 
                event["eventNum"] == event_num and
                event.get("collisionObjectId") == collision_object_id):
                print(f"[WARN] Event {event_type}_{event_num} already exists for {obj_name}")
                return False
        
        # Create new event entry
        new_event = {
            "$GMEvent": "v1",
            "%Name": "",
            "collisionObjectId": collision_object_id,
            "eventNum": event_num,
            "eventType": event_type,
            "isDnD": False,
            "name": "",
            "resourceType": "GMEvent",
            "resourceVersion": "2.0"
        }
        
        # Add to event list
        event_list.append(new_event)
        data["eventList"] = event_list
        
        # Save .yy file
        _save_object_yy(yy_path, data)
        
        # Create GML file
        filename = _event_to_filename(event_type, event_num, collision_object_id)
        gml_path = obj_path / filename
        
        if not gml_path.exists():
            _create_event_stub(obj_path, filename, obj_name, event_type, event_num, template)
            print(f"[OK] Created event file: {filename}")
        
        print(f"[OK] Added event {event_type}_{event_num} to {obj_name}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error adding event: {e}")
        return False

def remove_event(obj_name: str, event_type: int, event_num: int = 0, collision_object_id: Optional[str] = None, delete_file: bool = True) -> bool:
    """Remove an event from an object."""
    try:
        yy_path, data = _load_object_yy(obj_name)
        obj_path = yy_path.parent
        
        # Find and remove event from list
        event_list = data.get("eventList", [])
        original_count = len(event_list)
        
        event_list = [
            event for event in event_list
            if not (event["eventType"] == event_type and 
                   event["eventNum"] == event_num and
                   event.get("collisionObjectId") == collision_object_id)
        ]
        
        if len(event_list) == original_count:
            print(f"[WARN] Event {event_type}_{event_num} not found in {obj_name}")
            return False
        
        data["eventList"] = event_list
        _save_object_yy(yy_path, data)
        
        # Optionally delete GML file
        if delete_file:
            filename = _event_to_filename(event_type, event_num, collision_object_id)
            gml_path = obj_path / filename
            if gml_path.exists():
                gml_path.unlink()
                print(f"[OK] Deleted event file: {filename}")
        
        print(f"[OK] Removed event {event_type}_{event_num} from {obj_name}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error removing event: {e}")
        return False

def duplicate_event(obj_name: str, src_event_type: int, src_event_num: int, dst_event_num: int, src_collision_object_id: Optional[str] = None) -> bool:
    """Duplicate an event within an object."""
    try:
        yy_path, data = _load_object_yy(obj_name)
        obj_path = yy_path.parent
        
        # Find source event
        event_list = data.get("eventList", [])
        src_event = None
        for event in event_list:
            if (event["eventType"] == src_event_type and 
                event["eventNum"] == src_event_num and
                event.get("collisionObjectId") == src_collision_object_id):
                src_event = event
                break
        
        if not src_event:
            print(f"[ERROR] Source event {src_event_type}_{src_event_num} not found in {obj_name}")
            return False
        
        # Read source GML content
        src_filename = _event_to_filename(src_event_type, src_event_num, src_collision_object_id)
        src_gml_path = obj_path / src_filename
        
        template = None
        if src_gml_path.exists():
            template = src_gml_path.read_text(encoding="utf-8")
        
        # Add new event with copied content
        success = add_event(obj_name, src_event_type, dst_event_num, src_collision_object_id, template)
        
        if success:
            print(f"[OK] Duplicated event {src_event_type}_{src_event_num} to {src_event_type}_{dst_event_num} in {obj_name}")
        
        return success
        
    except Exception as e:
        print(f"[ERROR] Error duplicating event: {e}")
        return False

def list_events(obj_name: str) -> List[EventInfo]:
    """List all events for an object."""
    try:
        yy_path, data = _load_object_yy(obj_name)
        obj_path = yy_path.parent
        
        events = []
        event_list = data.get("eventList", [])
        
        for event in event_list:
            event_type = event["eventType"]
            event_num = event["eventNum"]
            collision_object_id = event.get("collisionObjectId")
            
            filename = _event_to_filename(event_type, event_num, collision_object_id)
            gml_path = obj_path / filename
            file_exists = gml_path.exists()
            
            gml_content = None
            if file_exists:
                try:
                    gml_content = gml_path.read_text(encoding="utf-8")
                except Exception:
                    pass
            
            events.append(EventInfo(
                event_type=event_type,
                event_num=event_num,
                collision_object_id=collision_object_id,
                filename=filename,
                file_exists=file_exists,
                gml_content=gml_content
            ))
        
        return events
        
    except Exception as e:
        print(f"[ERROR] Error listing events: {e}")
        return []

def validate_events(obj_name: str) -> ValidationReport:
    """Validate object events and return report."""
    errors = []
    warnings = []
    missing_files = []
    orphan_files = []
    duplicates = []
    
    try:
        yy_path, data = _load_object_yy(obj_name)
        obj_path = yy_path.parent
        
        # Check for missing .yy file
        if not yy_path.exists():
            errors.append(f"Object .yy file not found: {yy_path}")
            return ValidationReport(errors, warnings, missing_files, orphan_files, duplicates)
        
        event_list = data.get("eventList", [])
        expected_files = set()
        seen_events = set()
        
        # Check events in .yy file
        for event in event_list:
            event_type = event["eventType"]
            event_num = event["eventNum"]
            collision_object_id = event.get("collisionObjectId")
            
            # Check for duplicates
            event_key = (event_type, event_num, collision_object_id)
            if event_key in seen_events:
                duplicates.append(f"Duplicate event: {event_type}_{event_num}")
            else:
                seen_events.add(event_key)
            
            filename = _event_to_filename(event_type, event_num, collision_object_id)
            expected_files.add(filename)
            
            gml_path = obj_path / filename
            if not gml_path.exists():
                missing_files.append(filename)
        
        # Check for orphan GML files
        if obj_path.exists():
            for gml_file in obj_path.glob("*.gml"):
                if gml_file.name not in expected_files:
                    try:
                        # Try to parse the filename to see if it's a valid event
                        _filename_to_event(gml_file.name)
                        orphan_files.append(gml_file.name)
                    except ValueError:
                        warnings.append(f"Unknown GML file format: {gml_file.name}")
        
    except Exception as e:
        errors.append(f"Error validating {obj_name}: {e}")
    
    return ValidationReport(errors, warnings, missing_files, orphan_files, duplicates)

def fix_events(obj_name: str, safe_mode: bool = True) -> FixReport:
    """Fix object event issues."""
    files_created = 0
    files_deleted = 0
    events_added = 0
    events_removed = 0
    issues_fixed = []
    
    try:
        validation = validate_events(obj_name)
        yy_path, data = _load_object_yy(obj_name)
        obj_path = yy_path.parent
        
        # Create missing files
        for filename in validation.missing_files:
            try:
                # Parse filename to get event info
                event_type, event_num, collision_object_id = _filename_to_event(filename)
                _create_event_stub(obj_path, filename, obj_name, event_type, event_num)
                files_created += 1
                issues_fixed.append(f"Created missing file: {filename}")
            except Exception as e:
                issues_fixed.append(f"Failed to create {filename}: {e}")
        
        # Handle orphan files
        if not safe_mode:
            for filename in validation.orphan_files:
                try:
                    # Try to add the event to the .yy file
                    event_type, event_num, collision_object_id = _filename_to_event(filename)
                    
                    # Check if this event already exists in .yy
                    event_list = data.get("eventList", [])
                    event_exists = any(
                        event["eventType"] == event_type and 
                        event["eventNum"] == event_num and
                        event.get("collisionObjectId") == collision_object_id
                        for event in event_list
                    )
                    
                    if not event_exists:
                        new_event = {
                            "$GMEvent": "v1",
                            "%Name": "",
                            "collisionObjectId": collision_object_id,
                            "eventNum": event_num,
                            "eventType": event_type,
                            "isDnD": False,
                            "name": "",
                            "resourceType": "GMEvent",
                            "resourceVersion": "2.0"
                        }
                        event_list.append(new_event)
                        events_added += 1
                        issues_fixed.append(f"Added orphan event to .yy: {filename}")
                
                except Exception as e:
                    issues_fixed.append(f"Failed to process orphan {filename}: {e}")
            
            # Save updated .yy file if we added events
            if events_added > 0:
                data["eventList"] = event_list
                _save_object_yy(yy_path, data)
        
    except Exception as e:
        issues_fixed.append(f"Error fixing {obj_name}: {e}")
    
    return FixReport(files_created, files_deleted, events_added, events_removed, issues_fixed)

def _parse_event_spec(event_spec: str) -> Tuple[int, int, Optional[str]]:
    """Parse event specification like 'create', 'step:1', 'collision:o_wall'."""
    parts = event_spec.lower().split(':')
    event_name = parts[0]
    
    if event_name not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_name}")
    
    event_type = EVENT_TYPES[event_name]
    event_num = 0
    collision_object_id = None
    
    if len(parts) > 1:
        if event_type == 4:  # Collision
            collision_object_id = parts[1]
        else:
            try:
                event_num = int(parts[1])
            except ValueError:
                # Try named subtypes
                if event_type == 3 and parts[1] in STEP_SUBTYPES:
                    event_num = STEP_SUBTYPES[parts[1]]
                elif event_type == 8 and parts[1] in DRAW_SUBTYPES:
                    event_num = DRAW_SUBTYPES[parts[1]]
                elif event_type == 7 and parts[1] in OTHER_SUBTYPES:
                    event_num = OTHER_SUBTYPES[parts[1]]
                else:
                    raise ValueError(f"Unknown event subtype: {parts[1]}")
    
    return event_type, event_num, collision_object_id

# CLI Commands
def cmd_add(args):
    """Add event command."""
    try:
        event_type, event_num, collision_object_id = _parse_event_spec(args.event)
        template = None
        if args.template:
            template = Path(args.template).read_text(encoding="utf-8")
        
        success = add_event(args.object, event_type, event_num, collision_object_id, template)
        return success
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def cmd_remove(args):
    """Remove event command."""
    try:
        event_type, event_num, collision_object_id = _parse_event_spec(args.event)
        success = remove_event(args.object, event_type, event_num, collision_object_id, args.delete_file)
        return success
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def cmd_duplicate(args):
    """Duplicate event command."""
    try:
        src_event_type, src_event_num, src_collision_object_id = _parse_event_spec(args.source_event)
        success = duplicate_event(args.object, src_event_type, src_event_num, args.target_num, src_collision_object_id)
        return success
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def cmd_list(args):
    """List events command."""
    try:
        events = list_events(args.object)
        if not events:
            print(f"No events found for {args.object}")
            return True
        
        print(f"\nEvents for {args.object}:")
        print("─" * 60)
        
        for event in events:
            status = "[OK]" if event.file_exists else "[MISSING]"
            collision_info = f" (collision: {event.collision_object_id})" if event.collision_object_id else ""
            print(f"{status} {event.event_type}_{event.event_num}{collision_info} → {event.filename}")
        
        return True
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def cmd_validate(args):
    """Validate events command."""
    try:
        validation = validate_events(args.object)
        
        print(f"\nValidation Report for {args.object}")
        print("─" * 60)
        
        if validation.errors:
            print("[ERROR] Errors:")
            for error in validation.errors:
                print(f"  • {error}")
        
        if validation.warnings:
            print("[WARN] Warnings:")
            for warning in validation.warnings:
                print(f"  • {warning}")
        
        if validation.missing_files:
            print("[MISSING] Missing GML files:")
            for file in validation.missing_files:
                print(f"  • {file}")
        
        if validation.orphan_files:
            print("[ORPHAN] Orphan GML files:")
            for file in validation.orphan_files:
                print(f"  • {file}")
        
        if validation.duplicates:
            print("[DUPLICATE] Duplicate events:")
            for dup in validation.duplicates:
                print(f"  • {dup}")
        
        if not any([validation.errors, validation.warnings, validation.missing_files, validation.orphan_files, validation.duplicates]):
            print("[OK] All events are valid!")
        
        return len(validation.errors) == 0
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def cmd_fix(args):
    """Fix events command."""
    try:
        fix_report = fix_events(args.object, args.safe_mode)
        
        print(f"\nFix Report for {args.object}")
        print("─" * 60)
        
        print(f"Files created: {fix_report.files_created}")
        print(f"Files deleted: {fix_report.files_deleted}")
        print(f"Events added: {fix_report.events_added}")
        print(f"Events removed: {fix_report.events_removed}")
        
        if fix_report.issues_fixed:
            print("\nIssues fixed:")
            for issue in fix_report.issues_fixed:
                print(f"  • {issue}")
        
        if fix_report.files_created == 0 and fix_report.events_added == 0 and not fix_report.issues_fixed:
            print("[OK] No issues found to fix!")
        
        return True
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="GameMaker Object Event Helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Event Specifications:
  create              - Create event (0_0)
  destroy             - Destroy event (1_0)
  step                - Step event (3_0)
  step:begin          - Begin Step event (3_0)
  step:end            - End Step event (3_2)
  step:1              - Step event with number (3_1)
  draw                - Draw event (8_0)
  draw:gui            - Draw GUI event (8_64)
  collision:o_wall    - Collision with o_wall (4_0)
  alarm:0             - Alarm 0 event (2_0)

Examples:
  python -m gms_helpers.event_helper add o_player create
  python -m gms_helpers.event_helper remove o_enemy step:end
  python -m gms_helpers.event_helper duplicate o_boss step:0 1
  python -m gms_helpers.event_helper list o_character
  python -m gms_helpers.event_helper validate o_player
  python -m gms_helpers.event_helper fix o_enemy --no-safe-mode
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add an event to an object')
    add_parser.add_argument('object', help='Object name (e.g., o_player)')
    add_parser.add_argument('event', help='Event specification (e.g., create, step:1)')
    add_parser.add_argument('--template', help='Template file to use for event content')
    add_parser.set_defaults(func=cmd_add)
    
    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove an event from an object')
    remove_parser.add_argument('object', help='Object name (e.g., o_player)')
    remove_parser.add_argument('event', help='Event specification (e.g., create, step:1)')
    remove_parser.add_argument('--keep-file', dest='delete_file', action='store_false', help='Keep the GML file')
    remove_parser.set_defaults(func=cmd_remove)
    
    # Duplicate command
    dup_parser = subparsers.add_parser('duplicate', help='Duplicate an event within an object')
    dup_parser.add_argument('object', help='Object name (e.g., o_player)')
    dup_parser.add_argument('source_event', help='Source event specification (e.g., step:0)')
    dup_parser.add_argument('target_num', type=int, help='Target event number')
    dup_parser.set_defaults(func=cmd_duplicate)
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all events for an object')
    list_parser.add_argument('object', help='Object name (e.g., o_player)')
    list_parser.set_defaults(func=cmd_list)
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate object events')
    validate_parser.add_argument('object', help='Object name (e.g., o_player)')
    validate_parser.set_defaults(func=cmd_validate)
    
    # Fix command
    fix_parser = subparsers.add_parser('fix', help='Fix object event issues')
    fix_parser.add_argument('object', help='Object name (e.g., o_player)')
    fix_parser.add_argument('--no-safe-mode', dest='safe_mode', action='store_false', 
                           help='Allow potentially destructive fixes (add orphan events)')
    fix_parser.set_defaults(func=cmd_fix)
    
    # CRITICAL: Validate we're in the correct directory BEFORE parsing arguments
    # This ensures users get helpful directory guidance instead of confusing argparse errors
    validate_working_directory()
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return False
    
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[WARN] Operation cancelled by user")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
