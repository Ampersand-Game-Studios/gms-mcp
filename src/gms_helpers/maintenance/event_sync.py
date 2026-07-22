#!/usr/bin/env python3
"""
Event Synchronization Module
Fixes orphaned GML files and missing event references in GameMaker objects.

- Orphan GML files: File exists on disk but isn't referenced in object's .yy
  Action: Add matching event entry to the object's events array

- Missing GML files: Event entry exists in .yy but file is gone
  Action: Remove that event entry from the object's events array
"""

import sys
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from ..event_model import (
    EVENT_TYPE_NAMES,
    build_event_entry,
    event_filename_from_entry,
    parse_event_filename,
    resolve_collision_object_reference,
)
from ..exceptions import GMSError, ValidationError
from ..path_safety import project_child_path, validate_resource_name
from ..utils import atomic_write_text, load_json_loose, resolve_project_directory, save_json_loose


def parse_gml_filename(filename: str) -> Tuple[Optional[str], Optional[int | str]]:
    """
    Parse GML event filename to extract event type and number.
    Examples: 'Create_0.gml' -> ('Create', 0), 'Step_0.gml' -> ('Step', 0)
    """
    try:
        spec = parse_event_filename(filename)
    except ValidationError:
        return None, None
    if spec.collision_object is not None:
        return EVENT_TYPE_NAMES[spec.event_type], spec.collision_object
    return EVENT_TYPE_NAMES[spec.event_type], spec.event_num


def get_event_type_id(event_type: str) -> int:
    """Map GameMaker event type names to their numeric IDs"""
    event_map = {name: event_id for event_id, name in EVENT_TYPE_NAMES.items()}
    return event_map.get(event_type, 7)  # Default to 'Other' if unknown


def scan_object_events(object_path: str) -> Tuple[Set[str], Set[str]]:
    """
    Scan an object folder for GML files and .yy event references.
    Returns: (gml_files_on_disk, events_in_yy)
    """
    object_dir = Path(object_path)
    object_name = object_dir.name
    yy_file = object_dir / f"{object_name}.yy"

    # Find GML files on disk
    gml_files = set()
    if object_dir.exists():
        for file in object_dir.iterdir():
            if file.is_file() and file.suffix == ".gml" and file.name != f"{object_name}.gml":
                gml_files.add(file.name)

    # Find events referenced in .yy file
    yy_events = set()
    if yy_file.exists():
        try:
            yy_data = load_json_loose(yy_file)
            if yy_data and "eventList" in yy_data:
                for event in yy_data["eventList"]:
                    if "resourceVersion" in event and "resourceType" in event:
                        try:
                            yy_events.add(event_filename_from_entry(event))
                        except ValidationError as exc:
                            print(f"Warning: Invalid event entry in {yy_file}: {exc}")
        except Exception as e:
            print(f"Warning: Could not parse {yy_file}: {e}")

    return gml_files, yy_events


def get_event_type_name(event_type_id: int) -> str:
    """Map GameMaker event type IDs back to names"""
    return EVENT_TYPE_NAMES.get(event_type_id, "Other")


def fix_orphaned_gml_files(object_path: str, dry_run: bool = True) -> Tuple[int, int]:
    """
    Fix orphaned GML files by adding them to the object's .yy file.
    Returns: (orphaned_files_found, files_fixed)
    """
    object_dir = Path(object_path)
    object_name = object_dir.name
    yy_file = object_dir / f"{object_name}.yy"

    if not yy_file.exists():
        return 0, 0

    gml_files, yy_events = scan_object_events(object_path)
    orphaned = gml_files - yy_events

    if not orphaned:
        return 0, 0

    fixed = 0
    if not dry_run:
        try:
            yy_data = load_json_loose(yy_file)
            if not yy_data:
                return 0, 0

            if "eventList" not in yy_data:
                yy_data["eventList"] = []

            for gml_file in orphaned:
                try:
                    spec = parse_event_filename(gml_file)
                    collision_reference = None
                    if spec.collision_object is not None:
                        collision_reference = resolve_collision_object_reference(
                            object_dir.parent.parent, spec.collision_object
                        )
                    yy_data["eventList"].append(build_event_entry(spec, collision_reference))
                    fixed += 1
                    print(f"  [FIXED] Added event reference for {gml_file}")
                except GMSError as exc:
                    print(f"  [SKIPPED] Cannot add event reference for {gml_file}: {exc}")

            if fixed > 0:
                save_json_loose(str(yy_file), yy_data)

        except Exception as e:
            print(f"Error fixing {object_name}: {e}")
    else:
        for gml_file in orphaned:
            print(f"  [ORPHAN] {gml_file} exists but not referenced in .yy")

    return len(orphaned), fixed


def create_missing_gml_files(object_path: str, dry_run: bool = True) -> Tuple[int, int]:
    """
    Create missing GML files that are referenced in the object's .yy file.
    Returns: (missing_files_found, files_created)
    """
    object_dir = Path(object_path)
    object_name = object_dir.name
    yy_file = object_dir / f"{object_name}.yy"

    if not yy_file.exists():
        return 0, 0

    gml_files, yy_events = scan_object_events(object_path)
    missing = yy_events - gml_files

    if not missing:
        return 0, 0

    created = 0
    if not dry_run:
        try:
            for missing_file in missing:
                gml_path = object_dir / missing_file

                # Generate appropriate stub content based on event type
                try:
                    spec = parse_event_filename(missing_file)
                except ValidationError:
                    continue
                event_type_name = EVENT_TYPE_NAMES[spec.event_type]
                if event_type_name:
                    # Generate stub content based on event type
                    if event_type_name == "Create":
                        content = (
                            "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add initialization code here\n"
                        )
                    elif event_type_name == "Step":
                        content = "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add step logic here\n"
                    elif event_type_name == "Draw":
                        content = "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add drawing code here\n"
                    elif event_type_name == "Destroy":
                        content = "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add cleanup code here\n"
                    else:
                        content = f"// {event_type_name} event\n// TODO: Add event logic here\n"

                    atomic_write_text(gml_path, content)
                    created += 1
                    print(f"  [CREATED] Generated missing {missing_file}")

        except Exception as e:
            print(f"Error creating missing files for {object_name}: {e}")
    else:
        for missing_file in missing:
            print(f"  [MISSING] {missing_file} referenced in .yy but file not found")

    return len(missing), created


def fix_missing_gml_files(object_path: str, dry_run: bool = True) -> Tuple[int, int]:
    """
    Fix missing GML files by removing their references from the object's .yy file.
    Returns: (missing_files_found, references_removed)
    """
    object_dir = Path(object_path)
    object_name = object_dir.name
    yy_file = object_dir / f"{object_name}.yy"

    if not yy_file.exists():
        return 0, 0

    gml_files, yy_events = scan_object_events(object_path)
    missing = yy_events - gml_files

    if not missing:
        return 0, 0

    fixed = 0
    if not dry_run:
        try:
            yy_data = load_json_loose(yy_file)
            if yy_data and "eventList" in yy_data:
                # Filter out events for missing files
                new_event_list = []
                for event in yy_data["eventList"]:
                    try:
                        expected_filename = event_filename_from_entry(event)
                    except ValidationError:
                        new_event_list.append(event)
                        continue

                    if expected_filename not in missing:
                        new_event_list.append(event)
                    else:
                        print(f"  [REMOVED] Event reference for missing {expected_filename}")
                        fixed += 1

                yy_data["eventList"] = new_event_list

                if fixed > 0:
                    save_json_loose(str(yy_file), yy_data)

        except Exception as e:
            print(f"Error fixing {object_name}: {e}")
    else:
        for missing_file in missing:
            print(f"  [MISSING] {missing_file} referenced in .yy but file not found")

    return len(missing), fixed


def sync_object_events(object_path: str, dry_run: bool = True) -> Dict[str, int]:
    """
    Synchronize an object's events - fix both orphaned and missing files.
    Returns: stats dictionary
    """
    orphaned_found, orphaned_fixed = fix_orphaned_gml_files(object_path, dry_run)
    missing_found, missing_created = create_missing_gml_files(object_path, dry_run)

    return {
        "orphaned_found": orphaned_found,
        "orphaned_fixed": orphaned_fixed,
        "missing_found": missing_found,
        "missing_created": missing_created,
    }


def sync_all_object_events(project_root: Optional[str] = None, dry_run: bool = True) -> Dict[str, int]:
    """
    Synchronize events for all objects in the project.
    Returns: total stats dictionary
    """
    # Use standard resolution
    project_path = resolve_project_directory(project_root)

    objects_dir = project_path / "objects"
    if not objects_dir.exists():
        return {
            "objects_processed": 0,
            "orphaned_found": 0,
            "orphaned_fixed": 0,
            "missing_found": 0,
            "missing_created": 0,
        }

    total_stats = {
        "objects_processed": 0,
        "orphaned_found": 0,
        "orphaned_fixed": 0,
        "missing_found": 0,
        "missing_created": 0,
    }

    for obj_dir in objects_dir.iterdir():
        if obj_dir.is_dir() and obj_dir.name.startswith("o_"):
            stats = sync_object_events(str(obj_dir), dry_run)
            total_stats["objects_processed"] += 1

            for key in ["orphaned_found", "orphaned_fixed", "missing_found", "missing_created"]:
                total_stats[key] += stats.get(key, 0)

            if stats["orphaned_found"] > 0 or stats["missing_found"] > 0:
                print(f"[PACKAGE] {obj_dir.name}:")
                if stats["orphaned_found"] > 0:
                    action = "FIXED" if not dry_run and stats["orphaned_fixed"] > 0 else "FOUND"
                    print(f"  [SCAN] Orphaned GML files: {stats['orphaned_found']} {action}")
                if stats["missing_found"] > 0:
                    action = "CREATED" if not dry_run and stats["missing_created"] > 0 else "FOUND"
                    print(f"  [ERROR] Missing GML files: {stats['missing_found']} {action}")

    return total_stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Synchronize GameMaker object events")
    parser.add_argument("--fix", action="store_true", help="Actually fix issues (default is dry-run)")
    parser.add_argument("--object", help="Sync specific object only")
    parser.add_argument("--project-root", help="Path to GameMaker project root (will auto-detect if not provided)")

    args = parser.parse_args()

    # Use proper project root detection
    project_root = resolve_project_directory(args.project_root)
    print(f"[FOLDER] Using GameMaker project: {project_root}")

    dry_run = not args.fix

    if args.object:
        object_name = validate_resource_name(args.object, "object")
        object_path = project_child_path(
            "objects", object_name, project_root=project_root, kind=f"object '{object_name}'"
        )
        if object_path.exists():
            stats = sync_object_events(str(object_path), dry_run)
            print(f"Processed {object_name}: {stats}")
        else:
            print(f"Object {object_name} not found in {object_path}")
    else:
        print("[SYNC] Synchronizing all object events...")
        if dry_run:
            print("(DRY RUN - use --fix to actually make changes)")

        stats = sync_all_object_events(str(project_root), dry_run)

        print(f"\n[SUMMARY] Summary:")
        print(f"  Objects processed: {stats['objects_processed']}")
        print(f"  Orphaned GML files: {stats['orphaned_found']} found, {stats['orphaned_fixed']} fixed")
        print(f"  Missing GML files: {stats['missing_found']} found, {stats['missing_created']} created")


if __name__ == "__main__":
    try:
        main()
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        sys.exit(e.exit_code)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
