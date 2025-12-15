#!/usr/bin/env python3
"""
Auto-maintenance module - Automatically runs maintenance operations after asset changes
"""

import sys
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from contextlib import contextmanager

from .config import config
from .maintenance.lint import lint_project, print_lint_report, LintIssue
from .maintenance.tidy_json import validate_project_json, print_json_validation_report
from .maintenance.validate_paths import validate_folder_paths, print_path_validation_report, PathValidationIssue
from .maintenance.orphans import find_orphaned_assets, find_missing_assets, print_orphan_report
from .maintenance.orphan_cleanup import delete_orphan_files
from .event_helper import validate_events, ValidationReport


class MaintenanceInterruptedError(Exception):
    """Raised when maintenance operations are interrupted"""
    pass


@contextmanager
def progress_tracker(operation_name: str = "Auto-Maintenance"):
    """Context manager to provide progress tracking for long operations"""
    start_time = time.time()
    print(f"[MAINT] Starting {operation_name}...")
    
    try:
        yield
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[ERROR] {operation_name} failed after {elapsed:.1f}s: {e}")
        raise
    else:
        elapsed = time.time() - start_time
        print(f"[OK] {operation_name} completed successfully in {elapsed:.1f}s")


def execute_maintenance_step(step_name: str, func, *args, **kwargs):
    """Execute a maintenance step with progress tracking"""
    print(f"   [SYNC] {step_name}...")
    start_time = time.time()
    
    try:
        result = func(*args, **kwargs)
        elapsed = time.time() - start_time
        print(f"   [OK] {step_name} completed in {elapsed:.1f}s")
        return result
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"   [ERROR] {step_name} failed after {elapsed:.1f}s: {e}")
        raise


def handle_graceful_degradation(error: Exception, operation_name: str = "maintenance") -> 'MaintenanceResult':
    """Handle errors gracefully by providing partial results"""
    print(f"[WARN]  {operation_name} operation encountered an error - providing partial results")
    result = MaintenanceResult()
    result.degraded_mode = True
    result.has_errors = True
    return result


def detect_multi_asset_directories(project_root: str) -> List[str]:
    """
    Detect directories that contain multiple different asset .yy files.
    This violates the one-asset-per-folder rule and can cause issues.
    
    Args:
        project_root: Path to the GameMaker project root
        
    Returns:
        List of directory descriptions with multiple assets
    """
    multi_asset_dirs = []
    
    for asset_type in ['objects', 'sprites', 'scripts']:
        asset_dir = Path(project_root) / asset_type
        if not asset_dir.exists():
            continue
            
        for subdir in asset_dir.iterdir():
            if subdir.is_dir():
                yy_files = list(subdir.glob("*.yy"))
                if len(yy_files) > 1:
                    yy_names = [f.name for f in yy_files]
                    multi_asset_dirs.append(f"{asset_type}/{subdir.name}: {yy_names}")
    
    return multi_asset_dirs


class MaintenanceResult:
    """Results from running auto-maintenance operations."""
    
    def __init__(self):
        self.lint_issues: List[LintIssue] = []
        self.path_issues: List[PathValidationIssue] = []
        self.comma_fixes: List[Tuple[str, bool, str]] = []
        self.orphaned_assets: List[Tuple[str, str]] = []
        self.missing_assets: List[Tuple[str, str]] = []
        self.event_issues: Dict[str, ValidationReport] = {}  # Deprecated - kept for compatibility
        self.event_sync_stats: Dict[str, int] = {}
        self.old_files_stats: Dict[str, int] = {}
        self.orphan_cleanup_stats: Dict[str, Any] = {}
        self.multi_asset_directories: List[str] = []
        self.has_errors = False
        self.has_warnings = False
        self.degraded_mode = False
    
    def add_lint_issues(self, issues: List[LintIssue]):
        self.lint_issues.extend(issues)
        self.has_errors = self.has_errors or any(issue.severity == 'error' for issue in issues)
        self.has_warnings = self.has_warnings or any(issue.severity == 'warning' for issue in issues)
    
    def add_path_issues(self, issues: List[PathValidationIssue]):
        self.path_issues.extend(issues)
        self.has_errors = self.has_errors or any(issue.severity == 'error' for issue in issues)
        self.has_warnings = self.has_warnings or any(issue.severity == 'warning' for issue in issues)
    
    def set_comma_fixes(self, fixes: List[Tuple[str, bool, str]]):
        self.comma_fixes = fixes
    
    def set_orphan_data(self, orphaned: List[Tuple[str, str]], missing: List[Tuple[str, str]]):
        self.orphaned_assets = orphaned
        self.missing_assets = missing
        # Missing assets are errors, orphaned are just info
        self.has_errors = self.has_errors or len(missing) > 0
    
    def add_event_issues(self, object_name: str, validation: ValidationReport):
        """Deprecated - kept for compatibility"""
        self.event_issues[object_name] = validation
        self.has_errors = self.has_errors or len(validation.errors) > 0
        self.has_warnings = self.has_warnings or len(validation.warnings) > 0


def run_auto_maintenance(project_root: str = '.', fix_issues: Optional[bool] = None, verbose: Optional[bool] = None) -> MaintenanceResult:
    """
    Run comprehensive maintenance operations automatically.
    
    Args:
        project_root: Root directory of the project
        fix_issues: If True, automatically fix JSON formatting issues (uses config default if None)
        verbose: If True, print detailed reports (uses config default if None)
        
    Returns:
        MaintenanceResult with all findings
    """
    if fix_issues is None:
        fix_issues = config.AUTO_FIX_ISSUES
    if verbose is None:
        verbose = config.VERBOSE_MAINTENANCE
    result = MaintenanceResult()
    
    if verbose:
        print("\n[MAINT] Running Auto-Maintenance...")
        print("=" * 50)
    
    # Step 1: Validate JSON syntax (non-destructive)
    if verbose:
        print("\n[1] Validating JSON syntax...")
    json_validation = validate_project_json(project_root)
    result.set_comma_fixes(json_validation)  # Reuse field for validation results
    
    if verbose and json_validation:
        invalid_files = [r for r in json_validation if not r[1]]
        if invalid_files:
            print(f"   [ERROR] Found {len(invalid_files)} invalid JSON file(s)")
        else:
            print(f"   [OK] All JSON files are valid")
    
    # Step 2: Run comprehensive linting
    if verbose:
        print("\n[2] Running project linting...")
    lint_issues = lint_project(project_root)
    result.add_lint_issues(lint_issues)
    
    if verbose and lint_issues:
        error_count = sum(1 for issue in lint_issues if issue.severity == 'error')
        warning_count = sum(1 for issue in lint_issues if issue.severity == 'warning')
        if error_count > 0:
            print(f"   [ERROR] Found {error_count} error(s)")
        if warning_count > 0:
            print(f"   [WARN]  Found {warning_count} warning(s)")
    
    # Step 3: Validate folder paths
    if verbose:
        print("\n[3] Validating folder paths...")
    path_issues = validate_folder_paths(project_root, strict_mode=False, include_parent_folders=False)
    result.add_path_issues(path_issues)
    
    if verbose and path_issues:
        error_count = sum(1 for issue in path_issues if issue.severity == 'error')
        warning_count = sum(1 for issue in path_issues if issue.severity == 'warning')
        if error_count > 0:
            print(f"   [ERROR] Found {error_count} path error(s)")
        if warning_count > 0:
            print(f"   [WARN]  Found {warning_count} path warning(s)")
    
    # Step 4: Check for orphaned/missing assets
    if verbose:
        print("\n[4] Checking for orphaned/missing assets...")
    orphaned = find_orphaned_assets(project_root)
    missing = find_missing_assets(project_root)
    result.set_orphan_data(orphaned, missing)
    
    if verbose:
        if orphaned:
            print(f"   📂 Found {len(orphaned)} orphaned asset(s)")
        if missing:
            print(f"   [ERROR] Found {len(missing)} missing asset(s)")
    
    # Step 5: Synchronize object events (fix orphaned/missing)
    if verbose:
        print("\n[5] Synchronizing object events...")
    
    try:
        from .maintenance.event_sync import sync_all_object_events
    except ImportError:
        from maintenance.event_sync import sync_all_object_events
    
    event_stats = sync_all_object_events(project_root, dry_run=not fix_issues)
    
    if verbose:
        if event_stats['orphaned_found'] > 0:
            action = "FIXED" if fix_issues else "FOUND"
            print(f"   [SCAN] Orphaned GML files: {event_stats['orphaned_found']} {action}")
        if event_stats['missing_found'] > 0:
            action = "REMOVED" if fix_issues else "FOUND"
            print(f"   [ERROR] Missing GML files: {event_stats['missing_found']} {action}")
        if event_stats['orphaned_found'] == 0 and event_stats['missing_found'] == 0:
            print("   [OK] All object events are synchronized")
        if not fix_issues and (event_stats['orphaned_found'] > 0 or event_stats['missing_found'] > 0):
            print("   (Dry-run mode: no changes made. Run with fix_issues=True to fix.)")
    
    # Store event sync results in maintenance result
    result.event_sync_stats = event_stats
    
    # Step 6: Clean unused asset folders
    if verbose:
        print("\n6️⃣ Cleaning unused asset folders...")
    try:
        from .maintenance.clean_unused_assets import clean_unused_folders
    except ImportError:
        from maintenance.clean_unused_assets import clean_unused_folders
    asset_types = ['objects', 'sprites', 'scripts']
    total_found = 0
    total_deleted = 0
    for asset_type in asset_types:
        if verbose:
            print(f"  Scanning {asset_type}/ for unused folders...")
        found, deleted = clean_unused_folders(project_root, asset_type, do_delete=fix_issues)
        total_found += found
        total_deleted += deleted
    if verbose:
        print(f"\n  Unused asset folders found: {total_found - (total_found - total_deleted)}")
        print(f"  Unused asset folders deleted: {total_deleted if fix_issues else 0}")
        if not fix_issues:
            print("  (Dry-run mode: no folders deleted. Run with fix_issues=True to delete.)")
    
    # Step 7: Clean up .old.yy files
    if verbose:
        print("\n7️⃣ Cleaning up .old.yy files...")
    try:
        from .maintenance.clean_unused_assets import clean_old_yy_files
    except ImportError:
        from maintenance.clean_unused_assets import clean_old_yy_files
    
    old_files_found, old_files_deleted = clean_old_yy_files(project_root, do_delete=fix_issues)
    
    if verbose:
        if old_files_found > 0:
            action = "DELETED" if fix_issues else "FOUND"
            print(f"   [REPORT] Old .yy files: {old_files_found} {action}")
            if old_files_deleted > 0:
                print(f"   [DELETE]  Files deleted: {old_files_deleted}")
        else:
            print("   [OK] No .old.yy files found")
        if not fix_issues and old_files_found > 0:
            print("   (Dry-run mode: no files deleted. Run with fix_issues=True to delete.)")
    
    # Store old file cleanup results in maintenance result
    result.old_files_stats = {'found': old_files_found, 'deleted': old_files_deleted}
    
    # Step 8: Clean up orphaned asset files
    if verbose:
        print("\n8️⃣ Cleaning up orphaned asset files...")
    
    orphan_cleanup_result = delete_orphan_files(project_root, fix_issues=fix_issues, skip_types={"folder"})
    result.orphan_cleanup_stats = orphan_cleanup_result
    
    if verbose:
        orphan_deleted = orphan_cleanup_result.get('total_deleted', 0)
        orphan_dirs_deleted = len(orphan_cleanup_result.get('deleted_directories', []))
        orphan_errors = len(orphan_cleanup_result.get('errors', []))
        safety_warnings = len(orphan_cleanup_result.get('safety_warnings', []))
        
        if orphan_deleted > 0:
            action = "DELETED" if fix_issues else "WOULD DELETE"
            print(f"   [DELETE]  Orphaned files: {orphan_deleted} {action}")
            if orphan_dirs_deleted > 0:
                print(f"   [FOLDER] Empty directories: {orphan_dirs_deleted} removed")
        else:
            print("   [OK] No orphaned files to clean up")
        
        if safety_warnings > 0:
            print(f"   [WARN]  Safety warnings: {safety_warnings} (companion files protected)")
            
        if orphan_errors > 0:
            print(f"   [ERROR] Errors during cleanup: {orphan_errors}")
            
        if not fix_issues and orphan_deleted > 0:
            print("   (Dry-run mode: no files deleted. Run with fix_issues=True to delete.)")
    
    # Step 9: Detect multi-asset directories (violates one-asset-per-folder rule)
    if verbose:
        print("\n9️⃣ Detecting multi-asset directories...")
    
    multi_asset_dirs = detect_multi_asset_directories(project_root)
    result.multi_asset_directories = multi_asset_dirs
    
    if verbose:
        if multi_asset_dirs:
            print(f"   [WARN]  Found {len(multi_asset_dirs)} directories with multiple assets:")
            for dir_info in multi_asset_dirs[:5]:  # Show first 5
                print(f"      • {dir_info}")
            if len(multi_asset_dirs) > 5:
                print(f"      ... and {len(multi_asset_dirs) - 5} more")
            print("   [INFO] These directories may cause issues with asset management")
        else:
            print("   [OK] All directories follow one-asset-per-folder rule")

    # Summary
    if verbose:
        print("\n" + "=" * 50)
        if result.has_errors:
            print("[ERROR] Auto-maintenance completed with ERRORS")
        elif result.has_warnings:
            print("[WARN]  Auto-maintenance completed with warnings")
        else:
            print("[OK] Auto-maintenance completed successfully")
    
    return result


def print_maintenance_summary(result: MaintenanceResult, detailed: bool = False):
    """Print a summary of maintenance results."""
    # Use new event sync stats if available, fallback to old event issues for compatibility
    if hasattr(result, 'event_sync_stats') and result.event_sync_stats:
        event_orphaned = result.event_sync_stats.get('orphaned_found', 0)
        event_missing = result.event_sync_stats.get('missing_found', 0)
        event_total = event_orphaned + event_missing
    else:
        # Fallback to old event validation format
        event_errors = sum(len(v.errors) + len(v.missing_files) for v in result.event_issues.values())
        event_warnings = sum(len(v.warnings) + len(v.orphan_files) for v in result.event_issues.values())
        event_total = len(result.event_issues)
    
    print(f"\n[INFO] Maintenance Summary:")
    print(f"   Errors: {sum(1 for i in result.lint_issues + result.path_issues if i.severity == 'error') + len(result.missing_assets)}")
    print(f"   Warnings: {sum(1 for i in result.lint_issues + result.path_issues if i.severity == 'warning')}")
    print(f"   JSON fixes: {sum(1 for r in result.comma_fixes if r[1])}")
    print(f"   Orphaned assets: {len(result.orphaned_assets)}")
    
    if hasattr(result, 'event_sync_stats') and result.event_sync_stats:
        print(f"   Event sync: {event_orphaned} orphaned, {event_missing} missing")
    else:
        print(f"   Event issues: {event_total} object(s)")
    
    if hasattr(result, 'old_files_stats') and result.old_files_stats:
        old_found = result.old_files_stats.get('found', 0)
        old_deleted = result.old_files_stats.get('deleted', 0)
        print(f"   Old .yy files: {old_found} found, {old_deleted} deleted")
    
    if hasattr(result, 'orphan_cleanup_stats') and result.orphan_cleanup_stats:
        orphan_deleted = result.orphan_cleanup_stats.get('total_deleted', 0)
        orphan_dirs_deleted = len(result.orphan_cleanup_stats.get('deleted_directories', []))
        orphan_errors = len(result.orphan_cleanup_stats.get('errors', []))
        print(f"   Orphaned files: {orphan_deleted} deleted, {orphan_dirs_deleted} dirs removed")
        if orphan_errors > 0:
            print(f"   Orphan cleanup errors: {orphan_errors}")
    
    if detailed:
        if result.lint_issues:
            print_lint_report(result.lint_issues)
        
        if result.path_issues:
            print_path_validation_report(result.path_issues)
        
        if result.comma_fixes:
            print_json_validation_report(result.comma_fixes)
        
        if result.orphaned_assets or result.missing_assets:
            print_orphan_report(result.orphaned_assets, result.missing_assets)
        
        # Show event sync details if available
        if hasattr(result, 'event_sync_stats') and result.event_sync_stats:
            print_event_sync_report(result.event_sync_stats)
        elif result.event_issues:
            print_event_validation_report(result.event_issues)
        
        # Show orphan cleanup details if available
        if hasattr(result, 'orphan_cleanup_stats') and result.orphan_cleanup_stats:
            print_orphan_cleanup_report(result.orphan_cleanup_stats)


def print_event_validation_report(event_issues: Dict[str, ValidationReport]):
    """Print a detailed report of event validation issues."""
    print("\n🎯 Event Validation Report:")
    print("=" * 50)
    
    for obj_name, validation in event_issues.items():
        print(f"\n[PACKAGE] {obj_name}:")
        
        if validation.errors:
            print("  [ERROR] Errors:")
            for error in validation.errors:
                print(f"    • {error}")
        
        if validation.missing_files:
            print("  [REPORT] Missing GML files:")
            for file in validation.missing_files:
                print(f"    • {file}")
        
        if validation.warnings:
            print("  [WARN]  Warnings:")
            for warning in validation.warnings:
                print(f"    • {warning}")
        
        if validation.orphan_files:
            print("  [SCAN] Orphan GML files:")
            for file in validation.orphan_files:
                print(f"    • {file}")
        
        if validation.duplicates:
            print("  [SYNC] Duplicate events:")
            for dup in validation.duplicates:
                print(f"    • {dup}")


def print_event_sync_report(event_stats: Dict[str, int]):
    """Print a detailed report of event synchronization results."""
    print("\n[SYNC] Event Synchronization Report:")
    print("=" * 50)
    
    objects_processed = event_stats.get('objects_processed', 0)
    orphaned_found = event_stats.get('orphaned_found', 0)
    orphaned_fixed = event_stats.get('orphaned_fixed', 0)
    missing_found = event_stats.get('missing_found', 0)
    missing_fixed = event_stats.get('missing_fixed', 0)
    
    print(f"[PACKAGE] Objects processed: {objects_processed}")
    
    if orphaned_found > 0:
        print(f"[SCAN] Orphaned GML files: {orphaned_found} found, {orphaned_fixed} fixed")
    
    if missing_found > 0:
        print(f"[ERROR] Missing GML files: {missing_found} found, {missing_fixed} references removed")
    
    if orphaned_found == 0 and missing_found == 0:
        print("[OK] All object events are properly synchronized")


def print_orphan_cleanup_report(cleanup_stats: Dict[str, Any]):
    """Print a detailed report of orphan cleanup results."""
    print("\n[DELETE] Orphan Cleanup Report:")
    print("=" * 50)
    
    deleted_files = cleanup_stats.get('deleted_files', [])
    deleted_dirs = cleanup_stats.get('deleted_directories', [])
    skipped_files = cleanup_stats.get('skipped_files', [])
    safety_warnings = cleanup_stats.get('safety_warnings', [])
    errors = cleanup_stats.get('errors', [])
    total_deleted = cleanup_stats.get('total_deleted', 0)
    total_skipped = cleanup_stats.get('total_skipped', 0)
    
    print(f"[SUMMARY] Summary: {total_deleted} files processed, {total_skipped} skipped")
    
    if deleted_files:
        print(f"\n[DELETE] Deleted Files ({len(deleted_files)}):")
        for file_path in deleted_files:
            print(f"   • {file_path}")
    
    if deleted_dirs:
        print(f"\n[FOLDER] Deleted Empty Directories ({len(deleted_dirs)}):")
        for dir_path in deleted_dirs:
            print(f"   • {dir_path}")
    
    if safety_warnings:
        print(f"\n[WARN] Safety Warnings ({len(safety_warnings)}):")
        for warning in safety_warnings:
            print(f"   • {warning}")
        print("   [INFO] These orphaned .yy files were deleted, but companion files were preserved")
        print("      to protect legitimate assets in the same directories.")
    
    if skipped_files:
        print(f"\n⏭️ Skipped Files ({len(skipped_files)}):")
        for skip_reason in skipped_files:
            print(f"   • {skip_reason}")
    
    if errors:
        print(f"\n[ERROR] Errors ({len(errors)}):")
        for error in errors:
            print(f"   • {error}")
    
    if not deleted_files and not deleted_dirs and not skipped_files and not errors:
        print("[OK] No orphaned files found to clean up")


def validate_asset_creation_safe(result: MaintenanceResult) -> bool:
    """
    Check if the maintenance results indicate it's safe to proceed with asset operations.
    Returns False if there are critical errors that should block asset creation.
    """
    # Critical errors that should block asset creation:
    critical_errors = [
        'missing_folder_definition',
        'asset_load_error',
        'json'  # JSON errors in category
    ]
    
    for issue in result.lint_issues + result.path_issues:
        if issue.severity == 'error':
            # Check if this is a critical error type
            # Handle different issue types (LintIssue has category, PathValidationIssue has issue_type)
            issue_category = getattr(issue, 'category', getattr(issue, 'issue_type', ''))
            issue_message = getattr(issue, 'message', str(issue))
            
            if (issue_category in critical_errors or 
                any(critical in issue_message.lower() for critical in ['json', 'folder', 'missing'])):
                return False
    
    # Missing assets are also critical
    if result.missing_assets:
        return False
    
    # Event validation errors are also critical (old system)
    for validation in result.event_issues.values():
        if validation.errors:
            return False
    
    # Event sync issues are also critical (new system)
    if hasattr(result, 'event_sync_stats') and result.event_sync_stats:
        # Missing GML files that couldn't be synchronized are critical
        missing_found = result.event_sync_stats.get('missing_found', 0)
        missing_fixed = result.event_sync_stats.get('missing_fixed', 0)
        if missing_found > missing_fixed:
            return False
    
    return True


def handle_maintenance_failure(operation_name: str, result: MaintenanceResult) -> bool:
    """
    Handle maintenance failure consistently across all operations.
    Returns True if operation should continue, False if it should abort.
    
    Note: Event validation errors are considered critical and will block asset creation.
    """
    print(f"\n[ERROR] {operation_name} failed maintenance validation!")
    print("Critical issues found:")
    
    # Show critical errors
    critical_count = 0
    for issue in result.lint_issues + result.path_issues:
        if issue.severity == 'error':
            # Enhanced display for different issue types
            if hasattr(issue, 'issue_type') and hasattr(issue, 'referenced_folder'):
                # PathValidationIssue
                print(f"  • {issue.issue_type}: {issue.referenced_folder}")
            elif hasattr(issue, 'category') and hasattr(issue, 'message'):
                # LintIssue
                print(f"  • [ERROR] [{issue.category}] {getattr(issue, 'file_path', '')}: {issue.message}")
            elif hasattr(issue, 'message'):
                # Generic issue with message
                print(f"  • {issue.message}")
            else:
                # Fallback
                print(f"  • {issue}")
            critical_count += 1
    
    for missing_path, asset_type in result.missing_assets:
        print(f"  • Missing {asset_type}: {missing_path}")
        critical_count += 1
    
    # Show event validation errors (these are critical and block asset creation)
    for obj_name, validation in result.event_issues.items():
        for error in validation.errors:
            print(f"  • {obj_name}: {error}")
            critical_count += 1
        for missing_file in validation.missing_files:
            print(f"  • {obj_name}: Missing GML file: {missing_file}")
            critical_count += 1
    
    # Show event sync issues (new system)
    if hasattr(result, 'event_sync_stats') and result.event_sync_stats:
        missing_found = result.event_sync_stats.get('missing_found', 0)
        missing_fixed = result.event_sync_stats.get('missing_fixed', 0)
        unfixed_missing = missing_found - missing_fixed
        if unfixed_missing > 0:
            print(f"  • Event sync: {unfixed_missing} missing GML file(s) could not be synchronized")
            critical_count += unfixed_missing
    
    print(f"\nTotal critical issues: {critical_count}")
    print("Please fix these issues manually before proceeding.")
    print("Run maintenance commands individually for detailed reports:")
    print("  python asset_helper.py maint lint")
    print("  python asset_helper.py maint validate-paths")
    print("  python asset_helper.py maint list-orphans")
    
    return False
