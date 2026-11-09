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
from typing import Dict, List, Optional, Set, Tuple

from ..event_model import (
    EVENT_TYPE_NAMES,
    build_event_entry,
    event_filename_from_entry,
    parse_event_filename,
    resolve_collision_object_reference,
)
from ..exceptions import GMSError, ValidationError
from ..path_safety import project_relative_path, validate_resource_name
from ..project_validation import resolve_asset_reference
from ..utils import atomic_write_text, find_yyp, load_json_loose, resolve_project_directory, save_json_loose


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


def _object_files(object_path: str) -> Tuple[Path, Optional[Path]]:
    """Return (object_dir, object .yy file) for an object folder or its .yy path.

    The .yy is located by its own name, so folders whose spelling differs from
    the asset name (lowercase folders, IDE exact-case folders) are handled.
    """
    target = Path(object_path)
    if target.suffix.casefold() == ".yy":
        return target.parent, target if target.is_file() else None
    yy_file = target / f"{target.name}.yy"
    if yy_file.is_file():
        return target, yy_file
    if target.is_dir():
        expected = f"{target.name}.yy".casefold()
        matches = [child for child in target.iterdir() if child.is_file() and child.name.casefold() == expected]
        if len(matches) == 1:
            return target, matches[0]
    return target, None


def _event_gml_files(object_dir: Path, object_name: str) -> Set[str]:
    if not object_dir.is_dir():
        return set()
    return {
        file.name
        for file in object_dir.iterdir()
        if file.is_file()
        and file.suffix.casefold() == ".gml"
        and file.name.casefold() != f"{object_name}.gml".casefold()
    }


def scan_object_events(object_path: str) -> Tuple[Set[str], Set[str]]:
    """
    Scan an object folder (or its .yy file) for GML files and .yy event references.
    Returns: (gml_files_on_disk, events_in_yy)
    """
    object_dir, yy_file = _object_files(object_path)
    object_name = yy_file.stem if yy_file is not None else object_dir.name

    gml_files = _event_gml_files(object_dir, object_name)

    yy_events = set()
    if yy_file is not None:
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


def _casefold_difference(left: Set[str], right: Set[str]) -> Set[str]:
    """Items of ``left`` with no case-insensitive counterpart in ``right``.

    GameMaker projects live on case-insensitive filesystems as often as not, so
    ``create_0.gml`` on disk *is* the ``Create_0.gml`` the .yy expects there.
    """
    folded = {item.casefold() for item in right}
    return {item for item in left if item.casefold() not in folded}


def get_event_type_name(event_type_id: int) -> str:
    """Map GameMaker event type IDs back to names"""
    return EVENT_TYPE_NAMES.get(event_type_id, "Other")


def fix_orphaned_gml_files(object_path: str, dry_run: bool = True) -> Tuple[int, int]:
    """
    Fix orphaned GML files by adding them to the object's .yy file.
    Returns: (orphaned_files_found, files_fixed)
    """
    object_dir, yy_file = _object_files(object_path)
    if yy_file is None:
        return 0, 0
    object_name = yy_file.stem

    gml_files, yy_events = scan_object_events(str(yy_file))
    orphaned = _casefold_difference(gml_files, yy_events)

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

            for gml_file in sorted(orphaned):
                try:
                    spec = parse_event_filename(gml_file)
                    collision_reference = None
                    if spec.collision_object is not None:
                        collision_reference = resolve_collision_object_reference(
                            object_dir.parent.parent, spec.collision_object
                        )
                    entry = build_event_entry(spec, collision_reference, object_data=yy_data)
                    canonical = event_filename_from_entry(entry)
                    if canonical != gml_file:
                        # GameMaker looks the file up by its canonical name; registering a
                        # differently-cased file would break on case-sensitive filesystems.
                        print(f"  [SKIPPED] {gml_file}: rename it to {canonical} before registering the event")
                        continue
                    yy_data["eventList"].append(entry)
                    fixed += 1
                    print(f"  [FIXED] Added event reference for {gml_file}")
                except GMSError as exc:
                    print(f"  [SKIPPED] Cannot add event reference for {gml_file}: {exc}")

            if fixed > 0:
                save_json_loose(str(yy_file), yy_data)

        except Exception as e:
            print(f"Error fixing {object_name}: {e}")
    else:
        for gml_file in sorted(orphaned):
            print(f"  [ORPHAN] {gml_file} exists but not referenced in .yy")

    return len(orphaned), fixed


def create_missing_gml_files(object_path: str, dry_run: bool = True) -> Tuple[int, int]:
    """
    Create empty GML files for events referenced in the object's .yy file.

    Stubs are empty: an empty event file behaves exactly like the (deliberately)
    empty override the .yy describes, whereas inserted code would change it.
    Returns: (missing_files_found, files_created)
    """
    object_dir, yy_file = _object_files(object_path)
    if yy_file is None:
        return 0, 0
    object_name = yy_file.stem

    gml_files, yy_events = scan_object_events(str(yy_file))
    missing = _casefold_difference(yy_events, gml_files)

    if not missing:
        return 0, 0

    created = 0
    if not dry_run:
        try:
            for missing_file in sorted(missing):
                try:
                    parse_event_filename(missing_file)
                except ValidationError:
                    continue
                folded = missing_file.casefold()
                if any(child.name.casefold() == folded for child in object_dir.iterdir()):
                    # Never write over a case variant of the user's file.
                    print(f"  [SKIPPED] {missing_file}: a differently-cased file already exists")
                    continue
                atomic_write_text(object_dir / missing_file, "")
                created += 1
                print(f"  [CREATED] Generated missing {missing_file}")

        except Exception as e:
            print(f"Error creating missing files for {object_name}: {e}")
    else:
        for missing_file in sorted(missing):
            print(f"  [MISSING] {missing_file} referenced in .yy but file not found")

    return len(missing), created


def fix_missing_gml_files(object_path: str, dry_run: bool = True) -> Tuple[int, int]:
    """
    Fix missing GML files by removing their references from the object's .yy file.
    Returns: (missing_files_found, references_removed)
    """
    _object_dir, yy_file = _object_files(object_path)
    if yy_file is None:
        return 0, 0
    object_name = yy_file.stem

    gml_files, yy_events = scan_object_events(str(yy_file))
    missing = _casefold_difference(yy_events, gml_files)

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
        for missing_file in sorted(missing):
            print(f"  [MISSING] {missing_file} referenced in .yy but file not found")

    return len(missing), fixed


def sync_object_events(object_path: str, dry_run: bool = True) -> Dict[str, int]:
    """
    Synchronize an object's events - fix both orphaned and missing files.
    ``object_path`` is the object's folder or its registered .yy path.
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


def registered_object_yy_paths(project_root: Path) -> List[Path]:
    """Return the .yy files of every object registered in the project's .yyp."""
    project_data = load_json_loose(find_yyp(project_root))
    if not isinstance(project_data, dict):
        raise ValidationError(f"Could not load the .yyp in {project_root}")
    paths: List[Path] = []
    for resource in project_data.get("resources", []):
        resource_id = resource.get("id") if isinstance(resource, dict) else None
        path = resource_id.get("path") if isinstance(resource_id, dict) else None
        if not isinstance(path, str):
            continue
        normalized = path.replace("\\", "/")
        if normalized.split("/", 1)[0].casefold() != "objects":
            continue
        paths.append(project_relative_path(normalized, project_root=project_root, kind="object path"))
    return paths


def sync_all_object_events(project_root: Optional[str] = None, dry_run: bool = True) -> Dict[str, int]:
    """
    Synchronize events for every object registered in the project's .yyp.

    ``None`` or "." means the current working directory (never an environment
    override). Objects are located by their registered path, not by folder name.
    Returns: total stats dictionary
    """
    project_path = Path.cwd() if project_root in (None, "", ".") else Path(project_root)
    project_path = project_path.resolve()

    total_stats = {
        "objects_processed": 0,
        "orphaned_found": 0,
        "orphaned_fixed": 0,
        "missing_found": 0,
        "missing_created": 0,
    }

    for yy_path in registered_object_yy_paths(project_path):
        if not yy_path.is_file():
            # Missing registered assets are reported by the orphan/missing scan.
            continue
        stats = sync_object_events(str(yy_path), dry_run)
        total_stats["objects_processed"] += 1

        for key in ["orphaned_found", "orphaned_fixed", "missing_found", "missing_created"]:
            total_stats[key] += stats.get(key, 0)

        if stats["orphaned_found"] > 0 or stats["missing_found"] > 0:
            print(f"[PACKAGE] {yy_path.stem}:")
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
        try:
            reference = resolve_asset_reference(project_root, object_name, "GMObject")
        except GMSError as exc:
            print(f"Object {object_name} not found: {exc}")
        else:
            object_path = project_relative_path(reference["path"], project_root=project_root, kind="object path")
            stats = sync_object_events(str(object_path), dry_run)
            print(f"Processed {object_name}: {stats}")
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
