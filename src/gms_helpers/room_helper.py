#!/usr/bin/env python3
"""
GameMaker Studio Room Helper
Provides CLI and library functions for duplicating, renaming, and deleting rooms.
"""

import os
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from .utils import load_json_loose, save_json_loose, find_yyp, validate_working_directory, validate_name
from .exceptions import GMSError, ProjectNotFoundError, AssetNotFoundError, ValidationError
from .results import OperationResult
from .workflow import duplicate_asset, rename_asset, delete_asset
from .path_safety import validate_resource_name
from .room_instance_helper import _find_room_file, _iter_layers

# ------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------


def _find_rooms_directory() -> Optional[Path]:
    """Find the rooms directory in the project."""
    rooms_dir = Path("rooms")
    if not rooms_dir.exists():
        print("No rooms directory found in project.")
        return None
    return rooms_dir


# ------------------------------------------------------------------
# Library Functions
# ------------------------------------------------------------------


def duplicate_room(source_room: str, new_name: str) -> bool:
    """Duplicate an existing room."""
    # Validate name
    try:
        source_room = validate_resource_name(source_room, "room")
        validate_name(new_name, "room")
    except (ValueError, ValidationError) as e:
        print(f"[ERROR] Error duplicating room: {e}")
        return False

    project_root = Path.cwd()
    try:
        source_path = _find_room_file(source_room).relative_to(project_root).as_posix()
    except GMSError as exc:
        print(f"[ERROR] Room '{source_room}' not found or invalid: {exc}")
        return False

    result = duplicate_asset(project_root, source_path, new_name)
    if result.success:
        print(f"[OK] Duplicated room '{source_room}' to '{new_name}'")
        return True
    else:
        print(f"[ERROR] Failed to duplicate room: {result.message}")
        return False


def rename_room(room_name: str, new_name: str) -> bool:
    """Rename an existing room."""
    # Validate name
    try:
        room_name = validate_resource_name(room_name, "room")
        validate_name(new_name, "room")
    except (ValueError, ValidationError) as e:
        print(f"[ERROR] Error renaming room: {e}")
        return False

    project_root = Path.cwd()
    try:
        asset_path = _find_room_file(room_name).relative_to(project_root).as_posix()
    except GMSError as exc:
        print(f"[ERROR] Room '{room_name}' not found or invalid: {exc}")
        return False

    result = rename_asset(project_root, asset_path, new_name)
    if result.success:
        print(f"[OK] Renamed room '{room_name}' to '{new_name}'")
        return True
    else:
        print(f"[ERROR] Failed to rename room: {result.message}")
        return False


def delete_room(room_name: str, dry_run: bool = False, *, force: bool = False) -> OperationResult:
    """Delete a room while preserving dependency evidence for callers."""
    try:
        room_name = validate_resource_name(room_name, "room")
    except ValidationError as e:
        print(f"[ERROR] Error deleting room: {e}")
        return OperationResult.fail(
            f"Error deleting room: {e}",
            code="invalid_room_name",
            error_type="validation_error",
            data={"room_name": room_name, "dry_run": dry_run, "force": force},
        )

    project_root = Path.cwd()
    try:
        asset_path = _find_room_file(room_name).relative_to(project_root).as_posix()
    except GMSError as exc:
        print(f"[ERROR] Room '{room_name}' not found or invalid: {exc}")
        return OperationResult.fail(
            f"Room '{room_name}' not found",
            code="room_not_found",
            error_type="not_found",
            data={"room_name": room_name, "dry_run": dry_run, "force": force},
        )

    result = delete_asset(project_root, asset_path, dry_run=dry_run, force=force)
    if result.success:
        print(f"[OK] {'Would delete' if dry_run else 'Deleted'} room '{room_name}'")
    else:
        print(f"[ERROR] Failed to delete room: {result.message}")
    return result


def list_rooms(verbose: bool = False) -> List[Dict[str, Any]]:
    """List all rooms in the project."""
    rooms_dir = _find_rooms_directory()
    if not rooms_dir:
        return []

    results = []
    print("[INFO] Project Rooms:")
    print(f"{'Room Name':<30} {'Size':<12} {'Layers'}")
    print("-" * 55)

    project = load_json_loose(find_yyp(Path.cwd()))
    if not isinstance(project, dict) or not isinstance(project.get("resources", []), list):
        raise ValidationError("Malformed project resources")
    room_refs = [
        entry["id"]
        for entry in project.get("resources", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), dict)
        and str(entry["id"].get("path", "")).replace("\\", "/").startswith("rooms/")
    ]
    if not room_refs:
        print("No rooms found in project.")
        return []

    for ref in sorted(room_refs, key=lambda ref: str(ref.get("name", ""))):
        name = ref.get("name")
        try:
            yy_file = _find_room_file(name)
            data = load_json_loose(yy_file)
            if not data:
                print(f"{name:<30} {'ERROR':<12} {'N/A'}")
                results.append({"name": name, "error": "Invalid JSON"})
                continue

            width = data.get("roomSettings", {}).get("Width", "?")
            height = data.get("roomSettings", {}).get("Height", "?")
            size = f"{width}x{height}"

            layers = list(_iter_layers(data.get("layers", [])))
            layer_count = len(layers)

            print(f"{name:<30} {size:<12} {layer_count}")

            if verbose:
                layer_names = [l.get("name", "Unknown") for l in layers]
                if layer_names:
                    print(f"  Layers: {', '.join(layer_names)}")

            results.append(
                {
                    "name": name,
                    "width": width,
                    "height": height,
                    "layer_count": layer_count,
                    "layers": [l.get("name") for l in layers],
                }
            )

        except Exception as e:
            print(f"{name:<30} {'ERROR':<12} {'N/A'}")
            if verbose:
                print(f"  Error: {e}")
            results.append({"name": name, "error": str(e)})

    return results


# ------------------------------------------------------------------
# CLI Handlers
# ------------------------------------------------------------------


def handle_duplicate(args):
    return duplicate_room(args.source, args.new_name)


def handle_rename(args):
    return rename_room(args.old_name, args.new_name)


def handle_delete(args):
    return delete_room(args.room_name, args.dry_run, force=getattr(args, "force", False))


def handle_list(args):
    return list_rooms(args.verbose)


def main():
    parser = argparse.ArgumentParser(description="GameMaker Studio Room Helper")
    subparsers = parser.add_subparsers(dest="command", help="Room operation")

    # Duplicate
    dup_parser = subparsers.add_parser("duplicate", help="Duplicate an existing room")
    dup_parser.add_argument("source", help="Source room name")
    dup_parser.add_argument("new_name", help="New room name")
    dup_parser.set_defaults(func=handle_duplicate)

    # Rename
    ren_parser = subparsers.add_parser("rename", help="Rename an existing room")
    ren_parser.add_argument("old_name", help="Current room name")
    ren_parser.add_argument("new_name", help="New room name")
    ren_parser.set_defaults(func=handle_rename)

    # Delete
    del_parser = subparsers.add_parser("delete", help="Delete a room")
    del_parser.add_argument("room_name", help="Room name to delete")
    del_parser.add_argument("--dry-run", action="store_true", help="Don't actually delete")
    del_parser.add_argument("--force", action="store_true", help="Delete despite current incoming references")
    del_parser.set_defaults(func=handle_delete)

    # List
    list_parser = subparsers.add_parser("list", help="List all rooms in the project")
    list_parser.add_argument("--verbose", action="store_true", help="Show layer details")
    list_parser.set_defaults(func=handle_list)

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
