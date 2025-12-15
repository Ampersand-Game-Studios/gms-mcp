#!/usr/bin/env python3
"""
Event Synchronization Module
Fixes orphaned GML files and missing event references in GameMaker objects.

- Orphan GML files: File exists on disk but isn't referenced in object's .yy
  Action: Add matching event entry to the object's events array
  
- Missing GML files: Event entry exists in .yy but file is gone
  Action: Remove that event entry from the object's events array
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Set

def find_yyp_file(project_root):
    """Find the .yyp file in the project root"""
    for file in os.listdir(project_root):
        if file.endswith('.yyp'):
            return os.path.join(project_root, file)
    raise FileNotFoundError("No .yyp file found in project root.")

def find_gamemaker_project_root(start_path: str = '.') -> str:
    """
    Find the actual GameMaker project root directory containing the .yyp file.
    Handles both direct project directories and template projects with gamemaker/ subdirectory.
    """
    current_dir = Path(start_path).resolve()
    
    # First, try the current directory
    try:
        find_yyp_file(str(current_dir))
        return str(current_dir)
    except FileNotFoundError:
        pass
    
    # Walk up the directory tree looking for a GameMaker project
    while current_dir != current_dir.parent:
        # Check if this directory contains a .yyp file
        yyp_files = list(current_dir.glob("*.yyp"))
        if yyp_files:
            return str(current_dir)
        current_dir = current_dir.parent
    
    # Check if we're in root and need to look in gamemaker/ subdirectory
    start_path_obj = Path(start_path).resolve()
    gamemaker_subdir = start_path_obj / "gamemaker"
    if gamemaker_subdir.exists() and gamemaker_subdir.is_dir():
        try:
            find_yyp_file(str(gamemaker_subdir))
            return str(gamemaker_subdir)
        except FileNotFoundError:
            pass
    
    # Also check parent directories for gamemaker/ subdirectory
    current_dir = start_path_obj
    while current_dir != current_dir.parent:
        gamemaker_subdir = current_dir / "gamemaker"
        if gamemaker_subdir.exists() and gamemaker_subdir.is_dir():
            try:
                find_yyp_file(str(gamemaker_subdir))
                return str(gamemaker_subdir)
            except FileNotFoundError:
                pass
        current_dir = current_dir.parent
    
    raise FileNotFoundError(f"No GameMaker project (.yyp file) found starting from {start_path}")

def load_json_loose(path):
    """Load JSON with trailing commas support"""
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    # Remove trailing commas before closing braces/brackets
    content = re.sub(r',(\s*[}\]])', r'\1', content)
    return json.loads(content)

def save_json_loose(path, data):
    """Save JSON with GameMaker-style formatting (trailing commas allowed)"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, separators=(',', ':'))

def parse_gml_filename(filename: str) -> Tuple[str, int]:
    """
    Parse GML event filename to extract event type and number.
    Examples: 'Create_0.gml' -> ('Create', 0), 'Step_0.gml' -> ('Step', 0)
    """
    if not filename.endswith('.gml'):
        return None, None
    
    base = filename[:-4]  # Remove .gml
    if '_' not in base:
        return None, None
    
    parts = base.rsplit('_', 1)
    if len(parts) != 2:
        return None, None
    
    event_type, event_num_str = parts
    try:
        event_num = int(event_num_str)
        return event_type, event_num
    except ValueError:
        return None, None

def get_event_type_id(event_type: str) -> int:
    """Map GameMaker event type names to their numeric IDs"""
    event_map = {
        'Create': 0,
        'Destroy': 1,
        'Alarm': 2,
        'Step': 3,
        'Collision': 4,
        'Keyboard': 5,
        'Mouse': 6,
        'Other': 7,
        'Draw': 8,
        'KeyPress': 9,
        'KeyRelease': 10,
        'Trigger': 11,
        'CleanUp': 12,
        'Gesture': 13,
        'PreCreate': -1  # Special case
    }
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
            if file.is_file() and file.suffix == '.gml' and file.name != f"{object_name}.gml":
                gml_files.add(file.name)
    
    # Find events referenced in .yy file
    yy_events = set()
    if yy_file.exists():
        try:
            yy_data = load_json_loose(str(yy_file))
            if 'eventList' in yy_data:
                for event in yy_data['eventList']:
                    if 'resourceVersion' in event and 'resourceType' in event:
                        # Extract filename from event data
                        event_type = event.get('eventType', 0)
                        event_num = event.get('eventNum', 0)
                        # Map back to filename format
                        type_name = get_event_type_name(event_type)
                        if type_name:
                            filename = f"{type_name}_{event_num}.gml"
                            yy_events.add(filename)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not parse {yy_file}: {e}")
    
    return gml_files, yy_events

def get_event_type_name(event_type_id: int) -> str:
    """Map GameMaker event type IDs back to names"""
    type_map = {
        0: 'Create',
        1: 'Destroy', 
        2: 'Alarm',
        3: 'Step',
        4: 'Collision',
        5: 'Keyboard',
        6: 'Mouse',
        7: 'Other',
        8: 'Draw',
        9: 'KeyPress',
        10: 'KeyRelease',
        11: 'Trigger',
        12: 'CleanUp',
        13: 'Gesture',
        -1: 'PreCreate'
    }
    return type_map.get(event_type_id, 'Other')

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
            yy_data = load_json_loose(str(yy_file))
            if 'eventList' not in yy_data:
                yy_data['eventList'] = []
            
            for gml_file in orphaned:
                event_type_name, event_num = parse_gml_filename(gml_file)
                if event_type_name and event_num is not None:
                    event_type_id = get_event_type_id(event_type_name)
                    
                    # Create new event entry
                    new_event = {
                        "$GMEvent": "v1",
                        "%Name": f"{event_type_name}_{event_num}",
                        "collisionObjectId": None,
                        "eventNum": event_num,
                        "eventType": event_type_id,
                        "isDnD": False,
                        "name": f"{event_type_name}_{event_num}",
                        "resourceType": "GMEvent",
                        "resourceVersion": "2.0"
                    }
                    
                    yy_data['eventList'].append(new_event)
                    fixed += 1
                    print(f"  [FIXED] Added event reference for {gml_file}")
            
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
                event_type_name, event_num = parse_gml_filename(missing_file)
                if event_type_name and event_num is not None:
                    
                    # Generate stub content based on event type
                    if event_type_name == 'Create':
                        content = "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add initialization code here\n"
                    elif event_type_name == 'Step':
                        content = "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add step logic here\n"
                    elif event_type_name == 'Draw':
                        content = "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add drawing code here\n"
                    elif event_type_name == 'Destroy':
                        content = "// Inherit the parent event\nevent_inherited();\n\n// TODO: Add cleanup code here\n"
                    else:
                        content = f"// {event_type_name} event\n// TODO: Add event logic here\n"
                    
                    gml_path.write_text(content, encoding='utf-8')
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
            yy_data = load_json_loose(str(yy_file))
            if 'eventList' in yy_data:
                original_count = len(yy_data['eventList'])
                
                # Filter out events for missing files
                new_event_list = []
                for event in yy_data['eventList']:
                    event_type_id = event.get('eventType', 0)
                    event_num = event.get('eventNum', 0)
                    type_name = get_event_type_name(event_type_id)
                    expected_filename = f"{type_name}_{event_num}.gml"
                    
                    if expected_filename not in missing:
                        new_event_list.append(event)
                    else:
                        print(f"  [REMOVED] Event reference for missing {expected_filename}")
                        fixed += 1
                
                yy_data['eventList'] = new_event_list
                
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
        'orphaned_found': orphaned_found,
        'orphaned_fixed': orphaned_fixed,
        'missing_found': missing_found,
        'missing_created': missing_created
    }

def sync_all_object_events(project_root: str = None, dry_run: bool = True) -> Dict[str, int]:
    """
    Synchronize events for all objects in the project.
    Returns: total stats dictionary
    """
    # Find the actual GameMaker project root if not provided
    if project_root is None:
        project_root = find_gamemaker_project_root()
    else:
        # Validate the provided project root contains a .yyp file
        try:
            find_yyp_file(project_root)
        except FileNotFoundError:
            # Try to find the correct project root starting from provided path
            project_root = find_gamemaker_project_root(project_root)
    
    objects_dir = Path(project_root) / 'objects'
    if not objects_dir.exists():
        return {'objects_processed': 0}
    
    total_stats = {
        'objects_processed': 0,
        'orphaned_found': 0,
        'orphaned_fixed': 0,
        'missing_found': 0,
        'missing_created': 0
    }
    
    for obj_dir in objects_dir.iterdir():
        if obj_dir.is_dir() and obj_dir.name.startswith('o_'):
            stats = sync_object_events(str(obj_dir), dry_run)
            total_stats['objects_processed'] += 1
            
            for key in ['orphaned_found', 'orphaned_fixed', 'missing_found', 'missing_created']:
                total_stats[key] += stats.get(key, 0)
            
            if stats['orphaned_found'] > 0 or stats['missing_found'] > 0:
                print(f"[PACKAGE] {obj_dir.name}:")
                if stats['orphaned_found'] > 0:
                    action = "FIXED" if not dry_run and stats['orphaned_fixed'] > 0 else "FOUND"
                    print(f"  [SCAN] Orphaned GML files: {stats['orphaned_found']} {action}")
                if stats['missing_found'] > 0:
                    action = "CREATED" if not dry_run and stats['missing_created'] > 0 else "FOUND"
                    print(f"  [ERROR] Missing GML files: {stats['missing_found']} {action}")
    
    return total_stats

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Synchronize GameMaker object events")
    parser.add_argument('--fix', action='store_true', help='Actually fix issues (default is dry-run)')
    parser.add_argument('--object', help='Sync specific object only')
    parser.add_argument('--project-root', help='Path to GameMaker project root (will auto-detect if not provided)')
    
    args = parser.parse_args()
    
    # Use proper project root detection
    try:
        if args.project_root:
            project_root = find_gamemaker_project_root(args.project_root)
        else:
            project_root = find_gamemaker_project_root()
        print(f"[FOLDER] Using GameMaker project: {project_root}")
    except FileNotFoundError as e:
        print(f"[ERROR] ERROR: {e}")
        print("[INFO] Make sure you're running from a GameMaker project directory or specify --project-root")
        exit(1)
    
    dry_run = not args.fix
    
    if args.object:
        object_path = os.path.join(project_root, 'objects', args.object)
        if os.path.exists(object_path):
            stats = sync_object_events(object_path, dry_run)
            print(f"Processed {args.object}: {stats}")
        else:
            print(f"Object {args.object} not found in {object_path}")
    else:
        print("[SYNC] Synchronizing all object events...")
        if dry_run:
            print("(DRY RUN - use --fix to actually make changes)")
        
        stats = sync_all_object_events(project_root, dry_run)
        
        print(f"\n[SUMMARY] Summary:")
        print(f"  Objects processed: {stats['objects_processed']}")
        print(f"  Orphaned GML files: {stats['orphaned_found']} found, {stats['orphaned_fixed']} fixed")
        print(f"  Missing GML files: {stats['missing_found']} found, {stats['missing_created']} created") 