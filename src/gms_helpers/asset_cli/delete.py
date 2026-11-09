from __future__ import annotations

from pathlib import Path

from ..auto_maintenance import handle_maintenance_failure, run_auto_maintenance, validate_asset_creation_safe

# Asset type -> top-level project directory of its registered .yy path.
ASSET_TYPE_FOLDERS = {
    "script": "scripts",
    "object": "objects",
    "sprite": "sprites",
    "room": "rooms",
    "font": "fonts",
    "shader": "shaders",
    "animcurve": "animcurves",
    "sound": "sounds",
    "path": "paths",
    "tileset": "tilesets",
    "timeline": "timelines",
    "sequence": "sequences",
    "note": "notes",
}


def _resource_path(resource) -> str:
    resource_id = resource.get("id") if isinstance(resource, dict) else None
    path = resource_id.get("path") if isinstance(resource_id, dict) else None
    return path.replace("\\", "/") if isinstance(path, str) else ""


def _resource_name(resource) -> str | None:
    resource_id = resource.get("id") if isinstance(resource, dict) else None
    return resource_id.get("name") if isinstance(resource_id, dict) else None


def delete_asset(args):
    """Delete a registered asset from the project.

    The asset is located by its registered .yyp ``id.path`` (never rebuilt from
    the name), must live under the directory of the requested type, and its
    resource-order and room-order entries are removed with it. Maintenance runs
    report-only before and after; it never deletes anything else.
    """
    try:
        from ..transactions import transactional_rmtree
        from ..utils import find_yyp, load_json, save_json
        from ..workflow import _remove_resource_order_entries

        project_root = Path.cwd().resolve()

        if not getattr(args, "skip_maintenance", False):
            print("[SCAN] Running pre-deletion validation...")
            pre_result = run_auto_maintenance(str(project_root), fix_issues=False, verbose=False)
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Asset '{args.name}' deletion", pre_result)

        asset_folder = ASSET_TYPE_FOLDERS.get(args.asset_type)
        if asset_folder is None:
            if args.asset_type == "folder":
                print("[ERROR] Logical folders are removed with 'maint remove-folder', not 'delete'")
            else:
                print(f"[ERROR] Unsupported asset type: {args.asset_type}")
            return False

        asset_name = str(args.name).strip()
        asset_name_path = Path(asset_name)
        if (
            not asset_name
            or asset_name_path.is_absolute()
            or len(asset_name_path.parts) != 1
            or asset_name in {".", ".."}
        ):
            print(f"[ERROR] Invalid asset name: {args.name}")
            return False

        yyp_file = find_yyp(project_root)
        project_data = load_json(yyp_file)
        resources = project_data.get("resources", [])

        named = [resource for resource in resources if _resource_name(resource) == asset_name]
        matches = [
            resource
            for resource in named
            if _resource_path(resource).split("/", 1)[0].casefold() == asset_folder.casefold()
        ]
        if not matches:
            if named:
                registered = ", ".join(_resource_path(resource) for resource in named)
                print(f"[ERROR] '{asset_name}' is not a {args.asset_type}; it is registered at {registered}")
            else:
                print(f"[ERROR] Asset '{asset_name}' not found in project")
            return False
        if len(matches) > 1:
            print(f"[ERROR] '{asset_name}' is registered more than once as a {args.asset_type}; dedupe first")
            return False

        resource_to_remove = matches[0]
        registered_path = _resource_path(resource_to_remove)
        path_parts = registered_path.split("/")
        if len(path_parts) != 3 or not path_parts[2].casefold().endswith(".yy"):
            print(f"[ERROR] Registered path is not '<folder>/<name>/<name>.yy': {registered_path}")
            return False
        type_root = (project_root / path_parts[0]).resolve()
        disk_path = (project_root / registered_path).parent.resolve()
        try:
            disk_path.relative_to(type_root)
        except ValueError:
            print(f"[ERROR] Refusing to delete outside the {asset_folder}/ directory: {disk_path}")
            return False
        if disk_path == type_root:
            print(f"[ERROR] Refusing to delete the whole {asset_folder}/ directory")
            return False

        files_to_delete = []
        if disk_path.is_dir():
            files_to_delete = [disk_path, *(item for item in disk_path.rglob("*") if item.is_file())]

        if args.dry_run:
            print(f"[DRY-RUN] Would delete asset '{asset_name}' ({args.asset_type}):")
            print(f"  [FILE] .yyp entry: {registered_path}")
            if registered_path.startswith("rooms/"):
                print("  [FILE] RoomOrderNodes entry")
            if files_to_delete:
                print(f"  [FILES] Files/folders ({len(files_to_delete)}):")
                for file_path in files_to_delete[:10]:  # Show first 10 files
                    print(f"    - {file_path}")
                if len(files_to_delete) > 10:
                    print(f"    ... and {len(files_to_delete) - 10} more files")
            else:
                print("  [FILES] No files found on disk")
            return True

        project_data["resources"] = [resource for resource in resources if resource is not resource_to_remove]
        _remove_resource_order_entries(project_root, project_data, registered_path)
        save_json(project_data, yyp_file)
        print(f"[OK] Removed '{asset_name}' from {yyp_file.name}")

        if files_to_delete:
            try:
                transactional_rmtree(disk_path)
                print(f"[OK] Deleted folder: {disk_path}")
            except Exception as e:
                print(f"[ERROR] Could not delete files on disk: {e}")
                return False

        print(f"[OK] Asset '{asset_name}' deleted successfully")

        if not getattr(args, "skip_maintenance", False):
            print("[MAINT] Running post-deletion validation...")
            post_result = run_auto_maintenance(
                str(project_root),
                fix_issues=False,
                verbose=getattr(args, "maintenance_verbose", True),
            )

            if post_result.has_errors:
                return handle_maintenance_failure(f"Asset '{args.name}' post-deletion", post_result)

            print("[OK] Asset deleted and validated successfully!")

        return True

    except Exception as e:
        print(f"[ERROR] Error deleting asset: {e}")
        return False
