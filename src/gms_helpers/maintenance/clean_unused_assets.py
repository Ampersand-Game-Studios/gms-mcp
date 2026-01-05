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

from ..utils import load_json_loose, find_yyp, resolve_project_directory
from ..exceptions import ProjectNotFoundError, GMSError

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
    project_root = Path(project_root)
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if not yyp_data:
        return 0, 0
        
    referenced = collect_referenced_folders(yyp_data, asset_type)
    asset_dir = project_root / asset_type
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
    project_root = resolve_project_directory(args.project_root)
    print(f"[FOLDER] Using GameMaker project: {project_root}")

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
    """
    project_path = Path(project_root)
    found = 0
    deleted = 0
    
    # Common asset directories to scan
    search_dirs = ['objects', 'sprites', 'scripts', 'rooms', 'sounds', 'paths', 'fonts', 'shaders', 'animcurves', 'tilesets', 'timelines', 'sequences']
    
    for d in search_dirs:
        dir_path = project_path / d
        if not dir_path.exists():
            continue
            
        for file_path in dir_path.rglob("*.old.yy"):
            found += 1
            if do_delete:
                file_path.unlink()
                print(f"[DELETED] {file_path}")
                deleted += 1
            else:
                print(f"[OLD FILE] {file_path}")
    
    return found, deleted

if __name__ == "__main__":
    try:
        main()
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        sys.exit(e.exit_code)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
