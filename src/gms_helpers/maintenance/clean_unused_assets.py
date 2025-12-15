#!/usr/bin/env python3
"""
Clean Unused Asset Folders
Deletes asset folders (objects, sprites, scripts, etc.) not referenced in the .yyp file.
Default is dry-run (prints what would be deleted). Use --delete to actually remove folders.
"""

import argparse
import os
import shutil
from pathlib import Path
import sys

# Helper to find the .yyp file in the project root

def find_yyp_file(project_root):
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

# Helper to load JSON (loose) - handles trailing commas
def load_json(path):
    import json
    import re
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Try to parse as-is first, then clean up trailing commas if needed
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Remove trailing commas before closing braces and brackets
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        return json.loads(content)

def collect_referenced_folders(yyp_data, asset_type):
    referenced = set()
    for resource in yyp_data.get('resources', []):
        path = resource.get('id', {}).get('path', '')
        if path.startswith(f'{asset_type}/'):
            # e.g., objects/o_enemy_boss/o_enemy_boss.yy -> o_enemy_boss
            parts = Path(path).parts
            if len(parts) > 1:
                referenced.add(parts[1])
    return referenced

def clean_unused_folders(project_root, asset_type, do_delete=False):
    yyp_path = find_yyp_file(project_root)
    yyp_data = load_json(yyp_path)
    referenced = collect_referenced_folders(yyp_data, asset_type)
    asset_dir = Path(project_root) / asset_type
    if not asset_dir.exists():
        print(f"[SKIP] {asset_type}/ directory does not exist.")
        return 0, 0
    found = 0
    deleted = 0
    referenced_lower = {r.lower() for r in referenced}
    for folder in asset_dir.iterdir():
        if folder.is_dir():
            found += 1
            if folder.name.lower() not in referenced_lower:
                if do_delete:
                    shutil.rmtree(folder)
                    print(f"[DELETED] {folder}")
                    deleted += 1
                else:
                    print(f"[UNUSED]  {folder}")
    return found, deleted

def main():
    parser = argparse.ArgumentParser(description="Clean unused asset folders not referenced in the .yyp file.")
    parser.add_argument('--delete', action='store_true', help='Actually delete unused folders (default: dry-run)')
    parser.add_argument('--types', type=str, default='objects,sprites,scripts', help='Comma-separated asset types (default: objects,sprites,scripts)')
    parser.add_argument('--project-root', type=str, help='Project root directory (will auto-detect if not provided)')
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
        sys.exit(1)

    asset_types = [t.strip() for t in args.types.split(',') if t.strip()]
    total_found = 0
    total_deleted = 0
    for asset_type in asset_types:
        print(f"\nScanning {asset_type}/ for unused folders...")
        found, deleted = clean_unused_folders(project_root, asset_type, do_delete=args.delete)
        total_found += found
        total_deleted += deleted
    print(f"\nSummary: {total_found} folders scanned, {total_deleted} deleted.")
    if not args.delete:
        print("\nRun with --delete to actually remove unused folders.")

def clean_old_yy_files(project_root: str, do_delete: bool = False) -> tuple[int, int]:
    """
    Find and optionally delete .old.yy files throughout the project.
    
    Args:
        project_root: Root directory of the project
        do_delete: If True, actually delete the files. If False, just count them.
        
    Returns:
        Tuple of (files_found, files_deleted)
    """
    import os
    from pathlib import Path
    
    project_path = Path(project_root)
    found = 0
    deleted = 0
    
    # Search through all directories for .old.yy files
    for root, dirs, files in os.walk(project_path):
        for file in files:
            if file.endswith('.old.yy'):
                file_path = Path(root) / file
                found += 1
                
                if do_delete:
                    try:
                        file_path.unlink()
                        print(f"[DELETED] {file_path}")
                        deleted += 1
                    except Exception as e:
                        print(f"[ERROR] Could not delete {file_path}: {e}")
                else:
                    print(f"[OLD FILE] {file_path}")
    
    return found, deleted

if __name__ == "__main__":
    main() 