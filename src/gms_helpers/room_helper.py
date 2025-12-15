#!/usr/bin/env python3
"""
GameMaker Studio Room Helper
Provides room management operations aligned with standard asset workflow.

This module provides all high-level room operations (duplicate, rename,
delete, list) used by the CLI and tests.
"""

import argparse
import sys
import os
import shutil
from pathlib import Path

from .utils import (
    load_json_loose,
    save_pretty_json,
    find_yyp_file,
    validate_name,
    validate_parent_path,
)
from .workflow import duplicate_asset, rename_asset, delete_asset

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Core operations – thin wrappers around workflow helpers
# ---------------------------------------------------------------------------

def duplicate_room(args):
    """Duplicate an existing room with a new name."""
    try:
        # Validate the new room name
        validate_name(args.new_name, 'room')

        # Construct the source room path
        source_path = f"rooms/{args.source_room}/{args.source_room}.yy"

        # Check if source room exists
        if not Path(source_path).exists():
            print(f"[ERROR] Source room '{args.source_room}' not found")
            return False

        # Use the workflow duplicate function
        project_root = Path('.')
        result = duplicate_asset(project_root, source_path, args.new_name)

        if result:
            print(f"[OK] Duplicated room '{args.source_room}' to '{args.new_name}'")
            return True
        return False

    except Exception as e:
        print(f"[ERROR] Error duplicating room: {e}")
        return False

def rename_room(args):
    """Rename an existing room."""
    try:
        validate_name(args.new_name, 'room')
        room_path = f"rooms/{args.room_name}/{args.room_name}.yy"
        if not Path(room_path).exists():
            print(f"[ERROR] Room '{args.room_name}' not found")
            return False
        project_root = Path('.')
        result = rename_asset(project_root, room_path, args.new_name)
        if result:
            print(f"[OK] Renamed room '{args.room_name}' to '{args.new_name}'")
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Error renaming room: {e}")
        return False

def delete_room(args):
    """Delete a room from the project."""
    try:
        room_path = f"rooms/{args.room_name}/{args.room_name}.yy"
        if not Path(room_path).exists():
            print(f"[ERROR] Room '{args.room_name}' not found")
            return False
        project_root = Path('.')
        result = delete_asset(project_root, room_path, dry_run=args.dry_run)
        if result:
            if args.dry_run:
                print(f"[OK] Would delete room '{args.room_name}'")
            else:
                print(f"[OK] Deleted room '{args.room_name}'")
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Error deleting room: {e}")
        return False

def list_rooms(args):
    """List all rooms in the project."""
    try:
        rooms_dir = Path("rooms")
        if not rooms_dir.exists():
            print("No rooms directory found in project.")
            return True
        room_folders = [d for d in rooms_dir.iterdir() if d.is_dir()]
        if not room_folders:
            print("No rooms found in project.")
            return True
        print("[INFO] Project Rooms:")
        print(f"{'Room Name':<30} {'Size':<12} {'Layers':<8}")
        print("-" * 55)
        for room_folder in sorted(room_folders):
            room_name = room_folder.name
            yy_file = room_folder / f"{room_name}.yy"
            if yy_file.exists():
                try:
                    room_data = load_json_loose(yy_file)
                    room_settings = room_data.get("roomSettings") or {}
                    width = room_settings.get("Width", 0)
                    height = room_settings.get("Height", 0)
                    size = f"{width}x{height}"
                    layers = len(room_data.get("layers", []))
                    print(f"{room_name:<30} {size:<12} {layers:<8}")
                    if args.verbose:
                        layer_names = [layer.get("name", "Unknown") for layer in room_data.get("layers", [])]
                        print(f"  Layers: {', '.join(layer_names)}")
                except Exception as e:
                    print(f"{room_name:<30} {'ERROR':<12} {'N/A':<8}")
                    if args.verbose:
                        print(f"  Error: {e}")
            else:
                print(f"{room_name:<30} {'NO .YY':<12} {'N/A':<8}")
        return True
    except Exception as e:
        print(f"[ERROR] Error listing rooms: {e}")
        return False

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser():
    parser = argparse.ArgumentParser(
        description='GameMaker Studio Room Helper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s duplicate r_level_01 r_level_02
  %(prog)s rename r_old_name r_new_name
  %(prog)s delete r_unused_room
  %(prog)s delete r_unused_room --dry-run
  %(prog)s list
  %(prog)s list --verbose
        """
    )
    subparsers = parser.add_subparsers(dest='command', help='Room operation')
    subparsers.required = True
    # Duplicate room command
    duplicate_parser = subparsers.add_parser('duplicate', help='Duplicate an existing room')
    duplicate_parser.add_argument('source_room', help='Source room name (e.g., r_level_01)')
    duplicate_parser.add_argument('new_name', help='New room name (e.g., r_level_02)')
    duplicate_parser.set_defaults(func=duplicate_room)
    # Rename room command
    rename_parser = subparsers.add_parser('rename', help='Rename an existing room')
    rename_parser.add_argument('room_name', help='Current room name (e.g., r_old_name)')
    rename_parser.add_argument('new_name', help='New room name (e.g., r_new_name)')
    rename_parser.set_defaults(func=rename_room)
    # Delete room command
    delete_parser = subparsers.add_parser('delete', help='Delete a room')
    delete_parser.add_argument('room_name', help='Room name to delete (e.g., r_unused)')
    delete_parser.add_argument('--dry-run', action='store_true', help='Preview deletion without actually deleting')
    delete_parser.set_defaults(func=delete_room)
    # List rooms command
    list_parser = subparsers.add_parser('list', help='List all rooms in the project')
    list_parser.add_argument('--verbose', action='store_true', help='Show detailed room information')
    list_parser.set_defaults(func=list_rooms)
    return parser

def main():
    parser = _build_parser()
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

if __name__ == "__main__":
    main()
