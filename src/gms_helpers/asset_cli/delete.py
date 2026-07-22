from __future__ import annotations

from ..auto_maintenance import handle_maintenance_failure, run_auto_maintenance, validate_asset_creation_safe


def delete_asset(args):
    """Delete an asset from the project."""
    try:
        import os
        from pathlib import Path

        from ..transactions import transactional_rmtree, transactional_unlink

        # Import utilities with fallback
        try:
            from ..utils import load_json, save_json, find_yyp_file
        except ImportError:
            from ..utils import load_json, save_json, find_yyp_file

        # Skip maintenance if explicitly requested
        if not getattr(args, "skip_maintenance", False):
            print("[SCAN] Running pre-deletion validation...")
            pre_result = run_auto_maintenance(".", fix_issues=not getattr(args, "no_auto_fix", False), verbose=False)

            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Asset '{args.name}' deletion", pre_result)

        # Map asset types to their expected paths and prefixes
        asset_type_info = {
            "script": {"folder": "scripts", "prefix": "", "extension": ".gml"},
            "object": {"folder": "objects", "prefix": "o_", "extension": ""},
            "sprite": {"folder": "sprites", "prefix": "spr_", "extension": ""},
            "room": {"folder": "rooms", "prefix": "r_", "extension": ""},
            "font": {"folder": "fonts", "prefix": "fnt_", "extension": ""},
            "shader": {"folder": "shaders", "prefix": "sh_", "extension": ""},
            "animcurve": {"folder": "animcurves", "prefix": "curve_", "extension": ""},
            "sound": {"folder": "sounds", "prefix": "snd_", "extension": ""},
            "path": {"folder": "paths", "prefix": "pth_", "extension": ""},
            "tileset": {"folder": "tilesets", "prefix": "ts_", "extension": ""},
            "timeline": {"folder": "timelines", "prefix": "tl_", "extension": ""},
            "sequence": {"folder": "sequences", "prefix": "seq_", "extension": ""},
            "note": {"folder": "notes", "prefix": "", "extension": ""},
        }

        if args.asset_type not in asset_type_info:
            print(f"[ERROR] Unsupported asset type: {args.asset_type}")
            return False

        info = asset_type_info[args.asset_type]
        asset_folder = info["folder"]
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

        project_root = Path.cwd().resolve()

        # Determine asset path structure
        if args.asset_type == "folder":
            # Special handling for folders
            asset_path = f"folders/{asset_name}.yy"
            disk_path = (project_root / asset_path).resolve()
        else:
            # Regular assets have folder structure
            asset_path = f"{asset_folder}/{asset_name}/{asset_name}.yy"
            disk_path = (project_root / asset_folder / asset_name).resolve()
        try:
            disk_path.relative_to(project_root)
        except ValueError:
            print(f"[ERROR] Refusing to delete outside project root: {disk_path}")
            return False

        # Check if asset exists in .yyp file
        yyp_file = find_yyp_file()
        project_data = load_json(yyp_file)
        resources = project_data.get("resources", [])

        # Find the resource entry
        resource_to_remove = None
        for resource in resources:
            if resource.get("id", {}).get("name") == asset_name:
                resource_to_remove = resource
                break

        if not resource_to_remove:
            print(f"[ERROR] Asset '{asset_name}' not found in project")
            return False

        # Check if asset files exist on disk
        files_to_delete = []
        if disk_path.exists():
            if disk_path.is_file():
                files_to_delete.append(disk_path)
            else:
                files_to_delete.append(disk_path)
                # Add all files in the directory
                for item in disk_path.rglob("*"):
                    if item.is_file():
                        files_to_delete.append(item)

        if args.dry_run:
            print(f"[DRY-RUN] Would delete asset '{asset_name}' ({args.asset_type}):")
            print(f"  [FILE] .yyp entry: {resource_to_remove['id']['path']}")
            if files_to_delete:
                print(f"  [FILES] Files/folders ({len(files_to_delete)}):")
                for file_path in files_to_delete[:10]:  # Show first 10 files
                    print(f"    - {file_path}")
                if len(files_to_delete) > 10:
                    print(f"    ... and {len(files_to_delete) - 10} more files")
            else:
                print(f"  [FILES] No files found on disk")
            return True

        # Remove from .yyp file
        updated_resources = [r for r in resources if r.get("id", {}).get("name") != asset_name]
        project_data["resources"] = updated_resources

        try:
            save_json(project_data, yyp_file)
            print(f"[OK] Removed '{asset_name}' from {yyp_file}")
        except Exception as e:
            print(f"[ERROR] Failed to update .yyp file: {e}")
            return False

        # Delete files from disk
        if files_to_delete:
            try:
                if disk_path.is_file():
                    transactional_unlink(disk_path)
                    print(f"[OK] Deleted file: {disk_path}")
                else:
                    transactional_rmtree(disk_path)
                    print(f"[OK] Deleted folder: {disk_path}")
            except Exception as e:
                print(f"[WARN] Warning: Could not delete files on disk: {e}")
                print(f"   Asset removed from project but files may remain")

        print(f"[OK] Asset '{asset_name}' deleted successfully")

        # Run post-deletion maintenance
        if not getattr(args, "skip_maintenance", False):
            print("[MAINT] Running post-deletion maintenance...")
            post_result = run_auto_maintenance(
                ".",
                fix_issues=not getattr(args, "no_auto_fix", False),
                verbose=getattr(args, "maintenance_verbose", True),
            )

            if post_result.has_errors:
                return handle_maintenance_failure(f"Asset '{args.name}' post-deletion", post_result)

            print("[OK] Asset deleted and validated successfully!")

        return True

    except Exception as e:
        print(f"[ERROR] Error deleting asset: {e}")
        return False
