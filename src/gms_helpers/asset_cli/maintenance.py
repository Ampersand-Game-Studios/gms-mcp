from __future__ import annotations

import os
from pathlib import Path

from ..auto_maintenance import run_auto_maintenance
from ..maintenance.lint import lint_project, print_lint_report
from ..maintenance.orphan_cleanup import delete_orphan_files
from ..maintenance.orphans import find_missing_assets, find_orphaned_assets, print_orphan_report
from ..maintenance.prune import print_prune_report, prune_missing_assets
from ..maintenance.tidy_json import print_json_validation_report, validate_project_json
from ..maintenance.trash import get_keep_patterns, move_to_trash
from ..maintenance.validate_paths import print_path_validation_report, validate_folder_paths
from ..utils import list_folders_in_yyp, remove_folder_from_yyp, resolve_project_directory


def maint_lint_command(args):
    """Lint the GameMaker project for issues."""
    print("[SCAN] Scanning project for issues...")

    try:
        issues = lint_project(".")
        print_lint_report(issues)

        # Return success/failure based on whether errors were found
        has_errors = any(issue.severity == "error" for issue in issues)
        return not has_errors

    except Exception as e:
        print(f"[ERROR] Error during project scan: {e}")
        return False


def maint_validate_json_command(args):
    """Validate JSON syntax in project files."""
    print("[VALIDATE] Validating JSON syntax in project files...")

    try:
        from ..maintenance.tidy_json import validate_project_json, print_json_validation_report

        results = validate_project_json(".")
        print_json_validation_report(results)

        # Return success if all files are valid
        invalid_files = [r for r in results if not r[1]]
        return len(invalid_files) == 0

    except Exception as e:
        print(f"[ERROR] Error during JSON validation: {e}")
        return False


def maint_list_orphans_command(args):
    """Find orphaned and missing assets."""
    print("[SCAN] Scanning project for orphaned and missing assets...")

    try:
        orphaned_assets = find_orphaned_assets(".")
        missing_assets = find_missing_assets(".")
        print_orphan_report(orphaned_assets, missing_assets)

        # Return success - this is informational
        return True

    except Exception as e:
        print(f"[ERROR] Error during asset scan: {e}")
        return False


def maint_prune_missing_command(args):
    """Remove missing asset references from project file."""
    action = "Scanning for" if args.dry_run else "Removing"
    print(f"[MAINT] {action} missing asset references from project file...")

    try:
        removed_entries = prune_missing_assets(".", args.dry_run)
        print_prune_report(removed_entries, args.dry_run)

        # Return success - this is a maintenance operation
        return True

    except Exception as e:
        print(f"[ERROR] Error during asset pruning: {e}")
        return False


def maint_validate_paths_command(args):
    """Validate that all folder paths referenced in assets exist."""
    strict_disk_check = getattr(args, "strict_disk_check", False)
    mode_text = "with disk check" if strict_disk_check else "standard mode"
    parent_mode = " (including parent folders)" if getattr(args, "include_parent_folders", False) else ""
    print(f"[VALIDATE] Validating folder paths referenced in assets ({mode_text}{parent_mode})...")

    try:
        include_parent_folders = getattr(args, "include_parent_folders", False)
        issues = validate_folder_paths(
            ".", strict_mode=strict_disk_check, include_parent_folders=include_parent_folders
        )
        print_path_validation_report(issues, strict_mode=strict_disk_check)

        # Return success/failure based on whether errors were found
        has_errors = any(issue.severity == "error" for issue in issues)
        return not has_errors

    except Exception as e:
        print(f"[ERROR] Error during path validation: {e}")
        return False


def maint_dedupe_resources_command(args):
    """Remove duplicate resource entries from project file."""
    try:
        from ..utils import load_json, save_json, find_yyp_file, dedupe_resources
    except ImportError:
        from ..utils import load_json, save_json, find_yyp_file, dedupe_resources

    action = "Scanning for" if args.dry_run else "Removing"
    mode = "automatic" if args.auto else "interactive"
    print(f"[MAINT] {action} duplicate resource entries ({mode} mode)...")

    try:
        yyp_file = find_yyp_file()
        project_data = load_json(yyp_file)

        # Run deduplication
        modified_data, removed_count, report = dedupe_resources(
            project_data, interactive=not args.auto and not args.dry_run
        )

        # Print report
        for line in report:
            print(line)

        if removed_count > 0:
            if args.dry_run:
                print(f"\n[DRY-RUN] Would remove {removed_count} duplicate resource entries")
            else:
                # Save the modified project file
                save_json(modified_data, yyp_file)
                print(f"\n[OK] Removed {removed_count} duplicate resource entries from {yyp_file}")
        else:
            print("\n[OK] No duplicate resources found - project is clean!")

        return True

    except Exception as e:
        print(f"[ERROR] Error during resource deduplication: {e}")
        return False


def maint_sync_events_command(args):
    """Synchronize object events (fix orphaned/missing GML files)."""
    dry_run = not args.fix
    action = "Scanning" if dry_run else "Synchronizing"
    print(f"[SYNC] {action} object events...")

    if dry_run:
        print("(DRY RUN - use --fix to actually make changes)")

    try:
        from ..maintenance.event_sync import sync_object_events, sync_all_object_events

        if args.object:
            # Sync specific object
            import os

            object_path = os.path.join(".", "objects", args.object)
            if os.path.exists(object_path):
                stats = sync_object_events(object_path, dry_run)
                print(f"[OBJECT] {args.object}:")
                if stats["orphaned_found"] > 0:
                    action_text = "FIXED" if not dry_run and stats["orphaned_fixed"] > 0 else "FOUND"
                    print(f"  [ORPHAN] Orphaned GML files: {stats['orphaned_found']} {action_text}")
                if stats["missing_found"] > 0:
                    action_text = "CREATED" if not dry_run and stats.get("missing_created", 0) > 0 else "FOUND"
                    print(f"  [MISSING] Missing GML files: {stats['missing_found']} {action_text}")
                if stats["orphaned_found"] == 0 and stats["missing_found"] == 0:
                    print(f"  [OK] All events synchronized")
            else:
                print(f"[ERROR] Object {args.object} not found")
                return False
        else:
            # Sync all objects
            stats = sync_all_object_events(".", dry_run)

            print(f"\n[SUMMARY] Summary:")
            print(f"  Objects processed: {stats['objects_processed']}")
            print(f"  Orphaned GML files: {stats['orphaned_found']} found, {stats['orphaned_fixed']} fixed")
            print(f"  Missing GML files: {stats['missing_found']} found, {stats.get('missing_created', 0)} created")

            if stats["orphaned_found"] == 0 and stats["missing_found"] == 0:
                print("[OK] All object events are properly synchronized")

        return True

    except Exception as e:
        print(f"[ERROR] Error during event synchronization: {e}")
        return False


def maint_clean_old_files_command(args):
    """Remove .old.yy backup files from project."""
    delete = args.delete
    action = "Removing" if delete else "Scanning for"
    print(f"[MAINT] {action} .old.yy backup files from project...")

    try:
        from ..maintenance.clean_unused_assets import clean_old_yy_files

        found, deleted = clean_old_yy_files(".", do_delete=delete)

        if found > 0:
            if delete:
                print(f"\n[OK] Found {found} .old.yy files, deleted {deleted}")
            else:
                print(f"\n[INFO] Found {found} .old.yy files (use --delete to remove them)")
        else:
            print("\n[OK] No .old.yy files found - project is clean!")

        return True

    except Exception as e:
        print(f"[ERROR] Error during old file cleaning: {e}")
        return False


def maint_clean_orphans_command(args):
    """Remove orphaned asset files from project."""
    delete = args.delete
    skip_types = set(args.skip_types) if args.skip_types else {"folder"}
    action = "Removing" if delete else "Scanning for"
    print(f"[MAINT] {action} orphaned asset files from project...")

    if not delete:
        print("(DRY RUN - use --delete to actually remove files)")

    try:
        cleanup_result = delete_orphan_files(".", fix_issues=delete, skip_types=skip_types)

        total_deleted = cleanup_result.get("total_deleted", 0)
        deleted_dirs = len(cleanup_result.get("deleted_directories", []))
        errors = cleanup_result.get("errors", [])

        if total_deleted > 0:
            if delete:
                print(f"\n[OK] Deleted {total_deleted} orphaned files")
                if deleted_dirs > 0:
                    print(f"[DIRS] Removed {deleted_dirs} empty directories")
            else:
                print(f"\n[INFO] Found {total_deleted} orphaned files to remove")
                print("   Use --delete to actually remove them")

        else:
            print("\n[OK] No orphaned files found - project is clean!")

        if errors:
            print(f"\n[WARN] {len(errors)} errors occurred during cleanup:")
            for error in errors[:5]:  # Show first 5 errors
                print(f"  - {error}")
            if len(errors) > 5:
                print(f"  ... and {len(errors) - 5} more errors")

        # Show detailed report for dry run
        if not delete and total_deleted > 0:
            deleted_files = cleanup_result.get("deleted_files", [])
            if deleted_files:
                print(f"\nFiles that would be deleted:")
                for file_path in deleted_files[:20]:  # Show first 20 files
                    print(f"  - {file_path}")
                if len(deleted_files) > 20:
                    print(f"  ... and {len(deleted_files) - 20} more files")

        return True

    except Exception as e:
        print(f"[ERROR] Error during orphan cleaning: {e}")
        return False


def maint_fix_issues_command(args):
    """Run comprehensive auto-maintenance with fixes enabled."""
    verbose = args.verbose
    print("[MAINT] Running comprehensive auto-maintenance with fixes enabled...")

    try:
        run_auto_maintenance(".", fix_issues=True, verbose=verbose)
        print("[OK] Auto-maintenance completed successfully!")
        return True
    except Exception as e:
        print(f"[ERROR] Error during auto-maintenance: {e}")
        return False


def maint_test_command(args):
    """Test command for maintenance system."""
    print("[MAINT] Maintenance system initialized!")
    print("Available maintenance commands will be added in subsequent steps.")
    return True


def maint_audit_command(args):
    """Run comprehensive asset analysis and generate report."""
    output_file = args.output
    print(f"[ANALYZE] Running comprehensive asset analysis...")
    print(f"[REPORT] Report will be saved to: {output_file}")

    try:
        # Import the comprehensive analysis function (Phase 1 + 2)
        from ..maintenance.audit import comprehensive_analysis

        # Run comprehensive analysis (Phase 1 + 2)
        analysis_results = comprehensive_analysis(".")

        # Generate comprehensive report from analysis results
        import json
        from datetime import datetime

        # Extract data from comprehensive analysis
        phase_1 = analysis_results["phase_1_results"]
        phase_2 = analysis_results["phase_2_results"]
        final = analysis_results["final_analysis"]

        report = {
            "timestamp": datetime.now().isoformat(),
            "phase": "Phase 1 + 2 - Comprehensive Analysis Complete",
            "status": "comprehensive_analysis_implemented",
            "counts": {
                "total_files_on_disk": phase_2["filesystem_files_count"],
                "total_referenced_files": phase_1["referenced_files_count"],
                "missing_but_referenced": final["missing_but_referenced_count"],
                "truly_orphan": final["true_orphans_count"],
                "case_sensitivity_issues": final["case_sensitivity_issues_count"],
                "derivable_orphans": len(phase_2["derivable_orphans"]),
            },
            "missing_but_referenced": final["missing_but_referenced"],
            "truly_orphan": final["true_orphans"],
            "case_sensitivity_issues": final["case_sensitivity_issues"],
            "derivable_orphans": phase_2["derivable_orphans"],
            "string_references_summary": {
                "by_type": {k: len(v) for k, v in phase_2["string_references"]["by_type"].items()},
                "found_exact": len(phase_2["string_references"]["cross_reference"]["string_refs_found_exact"]),
                "found_case_diff": len(phase_2["string_references"]["cross_reference"]["string_refs_found_case_diff"]),
                "missing": len(phase_2["string_references"]["cross_reference"]["string_refs_missing"]),
            },
            "full_analysis_results": analysis_results,  # Include complete analysis for detailed inspection
        }

        with open(output_file, "w") as f:
            json.dump(report, f, indent=2)

        print(f"[OK] Comprehensive audit complete (Phase 1 + 2)!")
        print(f"[SUMMARY] Summary:")
        print(f"   - Total files on disk: {phase_2['filesystem_files_count']}")
        print(f"   - Referenced files: {phase_1['referenced_files_count']}")
        print(f"   - Missing files: {final['missing_but_referenced_count']}")
        print(f"   - True orphans: {final['true_orphans_count']}")
        print(f"   - Case sensitivity issues: {final['case_sensitivity_issues_count']}")
        print(f"   - Derivable orphans: {len(phase_2['derivable_orphans'])}")
        print(f"[REPORT] Detailed report saved to: {output_file}")

        if final["missing_but_referenced_count"] > 0:
            print(f"[WARN]  {final['missing_but_referenced_count']} files are referenced but missing!")
        if final["case_sensitivity_issues_count"] > 0:
            print(f"[CASE] {final['case_sensitivity_issues_count']} case sensitivity issues found!")
        if final["true_orphans_count"] > 0:
            print(f"[DELETE]  {final['true_orphans_count']} files appear to be true orphans")
        if len(phase_2["derivable_orphans"]) > 0:
            print(
                f"[INFO] {len(phase_2['derivable_orphans'])} files are derivable orphans (may be used via naming conventions or strings)"
            )

        return True

    except Exception as e:
        print(f"[ERROR] Error during audit: {e}")
        import traceback

        traceback.print_exc()
        return False


def maint_purge_command(args):
    """Move or delete orphaned assets with safety checks."""
    apply_changes = args.apply
    delete_after_move = args.delete
    additional_keep_patterns = args.keep or []

    project_root = resolve_project_directory(getattr(args, "project_root", None))

    if not apply_changes:
        print("[SCAN] DRY RUN: Analyzing what would be purged...")
    elif delete_after_move:
        print("[DELETE]  PURGE MODE: Moving files to trash then deleting...")
    else:
        print("[PACKAGE] MOVE MODE: Moving files to trash folder...")

    try:
        # 1. Find orphans
        print("[SCAN] Searching for orphaned assets...")
        orphans = find_orphaned_assets(str(project_root))
        if not orphans:
            print("[OK] No orphaned assets found to purge.")
            return True

        # 2. Load keep patterns
        keep_patterns = get_keep_patterns(str(project_root))
        keep_patterns.extend(additional_keep_patterns)

        # 3. Filter orphans
        to_purge = []
        for path, asset_type in orphans:
            should_keep = False
            for pattern in keep_patterns:
                if pattern in path:
                    should_keep = True
                    break

            if not should_keep:
                to_purge.append(path)
                # Also include companion files (.gml, etc.) if safe
                # Note: find_orphaned_assets returns .yy paths
                # We should use the more comprehensive deletion logic or move logic

        if not to_purge:
            print("[OK] All orphaned assets are protected by keep patterns.")
            return True

        print(f"[INFO] Found {len(to_purge)} assets to purge.")

        if not apply_changes:
            for path in sorted(to_purge):
                print(f"  [DRY RUN] Would move to trash: {path}")
            print(f"[OK] DRY RUN complete. Use --apply to actually move files.")
            return True

        # 4. Move to trash
        print(f"[PACKAGE] Moving {len(to_purge)} assets to trash...")
        result = move_to_trash(str(project_root), to_purge)

        if result["errors"]:
            for err in result["errors"]:
                print(f"[ERROR] {err}")

        print(f"[OK] Moved {result['moved_count']} files to {result['trash_folder']}")

        if delete_after_move:
            # Note: For now, we don't actually delete from trash for extra safety
            # unless we implement the full "run tests before delete" logic.
            print("[WARN]  Final deletion from trash folder not yet implemented for safety.")
            print(f"[INFO] Files are safe in {result['trash_folder']}")

        return True

    except Exception as e:
        print(f"[ERROR] Error during purge: {e}")
        import traceback

        traceback.print_exc()
        return False


def remove_folder_command(args):
    """Remove a folder from the .yyp file."""
    folder_path = args.folder_path
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        print(f"[SCAN] DRY RUN: Would remove folder '{folder_path}' from project...")
    else:
        action = "Forcefully removing" if force else "Removing"
        print(f"[DELETE] {action} folder '{folder_path}' from project...")

    try:
        success, message, assets_in_folder = remove_folder_from_yyp(folder_path, force=force, dry_run=dry_run)

        if success:
            if dry_run:
                print(f"[OK] DRY RUN: {message}")
            else:
                print(f"[OK] {message}")
            return True
        else:
            print(f"[ERROR] {message}")
            return False

    except Exception as e:
        print(f"[ERROR] Error removing folder: {e}")
        return False


def list_folders_command(args):
    """List all folders in the .yyp file."""
    show_paths = getattr(args, "show_paths", False)
    print("[FOLDER] Listing all folders in project...")

    try:
        success, folders, message = list_folders_in_yyp()

        if success:
            print(f"[OK] {message}")

            if folders:
                print("\nFolders:")
                for folder in folders:
                    if show_paths:
                        print(f"  [FOLDER] {folder['name']} -> {folder['path']}")
                    else:
                        print(f"  [FOLDER] {folder['name']}")

                if not show_paths:
                    print("\n[INFO] Use --show-paths to see folder paths")
            else:
                print("  (No folders found)")

            return True
        else:
            print(f"[ERROR] {message}")
            return False

    except Exception as e:
        print(f"[ERROR] Error listing folders: {e}")
        return False
