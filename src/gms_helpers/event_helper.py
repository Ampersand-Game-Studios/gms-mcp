#!/usr/bin/env python3
"""
GameMaker Studio Event Helper
Provides CLI and library functions for managing object events.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .event_model import (
    build_event_entry,
    event_filename,
    event_filename_from_entry,
    event_matches,
    parse_event_filename,
    parse_event_spec,
    resolve_collision_object_reference,
)
from .exceptions import AssetNotFoundError, GMSError, ValidationError
from .maintenance.event_sync import sync_object_events
from .path_safety import project_child_path, validate_resource_name
from .transactions import transactional_unlink
from .utils import atomic_write_text, load_json_loose, save_json_loose, validate_working_directory

# ------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------


def _filename_to_event(filename: str) -> Tuple[Optional[int], Optional[int]]:
    """Convert GML event filename to event type and number."""
    try:
        spec = parse_event_filename(filename)
    except ValidationError:
        return None, None
    return spec.event_type, spec.event_num


def _event_to_filename(event_type: int, event_num: int, collision_object_id: Any = None) -> str:
    """Convert event type and number to GML filename."""
    return event_filename(event_type, event_num, collision_object_id)


def _object_dir(object_name: str, project_root: str | Path | None = None) -> tuple[str, Path]:
    """Return a validated object name and project-local object directory."""
    object_name = validate_resource_name(object_name, "object")
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    return object_name, project_child_path("objects", object_name, project_root=root, kind=f"object '{object_name}'")


# ------------------------------------------------------------------
# Library Functions
# ------------------------------------------------------------------


def list_events(object_name: str, project_root: str | Path | None = None) -> List[Dict[str, Any]]:
    """List all events for an object."""
    object_name, obj_dir = _object_dir(object_name, project_root)
    obj_path = obj_dir / f"{object_name}.yy"
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
        filename = event_filename_from_entry(event)
        print(f"  - {filename}")
        item: Dict[str, Any] = {"type": e_type, "num": e_num, "filename": filename}
        collision_reference = event.get("collisionObjectId")
        if isinstance(collision_reference, dict):
            item["collision_object"] = collision_reference.get("name")
        events.append(item)

    return events


def add_event(object_name: str, event_spec: str, template: str = "", project_root: str | Path | None = None) -> bool:
    """Add a new event to an object."""
    spec = parse_event_spec(event_spec)

    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    object_name, obj_dir = _object_dir(object_name, root)
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    collision_reference = None
    if spec.collision_object is not None:
        collision_reference = resolve_collision_object_reference(root, spec.collision_object)

    # Check if event already exists
    event_list = data.get("eventList", [])
    for event in event_list:
        if event_matches(event, spec):
            print(f"[WARN] Event {event_spec} already exists for {object_name}")
            return True

    # Create the GML file
    new_event = build_event_entry(spec, collision_reference)
    filename = event_filename_from_entry(new_event)
    gml_path = obj_dir / filename
    if not gml_path.exists():
        content = template if template else f"// {filename} event\n"
        atomic_write_text(gml_path, content)
        print(f"[OK] Created event file: {gml_path}")

    if "eventList" not in data:
        data["eventList"] = []
    data["eventList"].append(new_event)

    save_json_loose(obj_path, data)
    print(f"[OK] Added event {event_spec} to {object_name}")
    return True


def remove_event(
    object_name: str,
    event_spec: str,
    keep_file: bool = False,
    project_root: str | Path | None = None,
) -> bool:
    """Remove an event from an object."""
    spec = parse_event_spec(event_spec)

    object_name, obj_dir = _object_dir(object_name, project_root)
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    event_list = data.get("eventList", [])
    matching_events = [event for event in event_list if event_matches(event, spec)]
    new_event_list = [event for event in event_list if not event_matches(event, spec)]

    if len(new_event_list) == len(event_list):
        print(f"[WARN] Event {event_spec} not found for {object_name}")
        return False

    data["eventList"] = new_event_list
    save_json_loose(obj_path, data)

    if not keep_file:
        filename = event_filename_from_entry(matching_events[0])
        gml_path = obj_dir / filename
        if gml_path.exists():
            transactional_unlink(gml_path)
            print(f"[OK] Deleted event file: {gml_path}")

    print(f"[OK] Removed event {event_spec} from {object_name}")
    return True


def duplicate_event(
    object_name: str,
    source_event_spec: str,
    target_event_spec: str,
    project_root: str | Path | None = None,
) -> bool:
    """
    Duplicate an event within an object.

    Example:
      duplicate_event("o_player", "step:0", "step:1") copies Step_0.gml to Step_1.gml.
      duplicate_event("o_player", "collision:o_enemy", "collision:o_wall") copies a collision event.
    """
    source_spec = parse_event_spec(source_event_spec)
    target_spec = parse_event_spec(target_event_spec)
    if target_spec.event_type != source_spec.event_type:
        raise ValidationError("Source and target events must have the same event type")

    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    object_name, obj_dir = _object_dir(object_name, root)
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    # Ensure source exists in eventList (or at least on disk)
    source_collision_reference = None
    if source_spec.collision_object is not None:
        source_collision_reference = resolve_collision_object_reference(root, source_spec.collision_object)
    target_collision_reference = None
    if target_spec.collision_object is not None:
        target_collision_reference = resolve_collision_object_reference(root, target_spec.collision_object)

    source_entry = build_event_entry(source_spec, source_collision_reference)
    target_entry = build_event_entry(target_spec, target_collision_reference)
    source_filename = event_filename_from_entry(source_entry)
    target_filename = event_filename_from_entry(target_entry)

    event_list = data.get("eventList", []) or []
    has_source_entry = any(event_matches(event, source_spec) for event in event_list)
    if not has_source_entry and not (obj_dir / source_filename).exists():
        raise ValidationError(f"Source event '{source_event_spec}' not found for {object_name}")

    # If target already exists, treat as success
    if any(event_matches(event, target_spec) for event in event_list):
        print(f"[WARN] Event {target_spec.canonical} already exists for {object_name}")
        return True

    # Copy or create the target GML file
    src_gml = obj_dir / source_filename
    dst_gml = obj_dir / target_filename
    if not dst_gml.exists():
        if src_gml.exists():
            atomic_write_text(dst_gml, src_gml.read_text(encoding="utf-8"))
        else:
            atomic_write_text(dst_gml, f"// {target_filename} event\n")
        print(f"[OK] Created event file: {dst_gml}")

    if "eventList" not in data or data["eventList"] is None:
        data["eventList"] = []
    data["eventList"].append(target_entry)
    save_json_loose(obj_path, data)

    print(f"[OK] Duplicated event {source_event_spec} -> {target_event_spec} for {object_name}")
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
    object_name, obj_dir = _object_dir(args.object)
    results = sync_object_events(str(obj_dir), dry_run=True)
    print(f"\nValidation Report for {object_name}")
    print("-" * 60)
    if results["orphaned_found"] == 0 and results["missing_found"] == 0:
        print("[OK] All events are valid!")
    else:
        if results["orphaned_found"] > 0:
            print(f"[ERROR] Found {results['orphaned_found']} orphaned GML files")
        if results["missing_found"] > 0:
            print(f"[ERROR] Found {results['missing_found']} missing GML files")
    return True


def handle_fix(args):
    object_name, obj_dir = _object_dir(args.object)
    results = sync_object_events(str(obj_dir), dry_run=False)
    print(f"\nFix Report for {object_name}")
    print("-" * 60)
    print(f"Files created: {results['missing_created']}")
    print(f"Events added: {results['orphaned_fixed']}")
    if results["missing_created"] == 0 and results["orphaned_fixed"] == 0:
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
