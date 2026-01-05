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
        self.json_issues: List[Tuple[str, bool, str]] = []
        self.lint_issues: List[LintIssue] = []
        self.path_issues: List[PathValidationIssue] = []
        self.orphaned_assets: List[str] = []
        self.missing_assets: List[str] = []
        self.event_sync_stats: Dict[str, int] = {}
        self.old_files_stats: Dict[str, int] = {}
        self.orphan_cleanup_stats: Dict[str, Any] = {}
        self.multi_asset_dirs: List[str] = []
        self.has_errors: bool = False
        self.degraded_mode: bool = False
        self.summary: str = ""

    def set_comma_fixes(self, issues: List[Tuple[str, bool, str]]):
        self.json_issues = issues
        if any(not success for _, success, _ in issues):
            self.has_errors = True

    def add_lint_issues(self, issues: List[LintIssue]):
        self.lint_issues.extend(issues)
        if any(issue.severity == 'error' for issue in issues):
            self.has_errors = True

    def add_path_issues(self, issues: List[PathValidationIssue]):
        self.path_issues.extend(issues)
        if any(issue.severity == 'error' for issue in issues):
            self.has_errors = True

    def set_orphan_data(self, orphaned: List[str], missing: List[str]):
        self.orphaned_assets = orphaned
        self.missing_assets = missing
        if missing:
            self.has_errors = True


def run_auto_maintenance(project_root: str, fix_issues: bool = None, verbose: bool = None) -> MaintenanceResult:
    """
    Run a set of standard maintenance operations.
    
    Args:
        project_root: Path to project root
        fix_issues: Whether to apply fixes (default from config)
        verbose: Whether to print detailed output (default from config)
        
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
    result.set_comma_fixes(json_validation)
    
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
            print(f"   [INFO] Found {len(orphaned)} orphaned asset(s)")
        if missing:
            print(f"   [ERROR] Found {len(missing)} missing asset(s)")
    
    # Step 5: Synchronize object events (fix orphaned/missing)
    if verbose:
        print("\n[5] Synchronizing object events...")
    
    from .maintenance.event_sync import sync_all_object_events
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
    
    result.event_sync_stats = event_stats
    
    # Step 6: Clean unused asset folders
    if verbose:
        print("\n[6] Cleaning unused asset folders...")
    from .maintenance.clean_unused_assets import clean_unused_folders
    asset_types = ['objects', 'sprites', 'scripts']
    total_found = 0
    total_deleted = 0
    for asset_type in asset_types:
        if verbose:
            print(f"  Scanning {asset_type}/ for unused folders...")
        found, deleted = clean_unused_folders(project_root, asset_type, do_delete=fix_issues)
        total_found += found
        total_deleted += deleted
    
    # Step 7: Clean up .old.yy files
    if verbose:
        print("\n[7] Cleaning up .old.yy files...")
    from .maintenance.clean_unused_assets import clean_old_yy_files
    old_files_found, old_files_deleted = clean_old_yy_files(project_root, do_delete=fix_issues)
    result.old_files_stats = {'found': old_files_found, 'deleted': old_files_deleted}
    
    # Step 8: Clean up orphaned asset files
    if verbose:
        print("\n[8] Cleaning up orphaned asset files...")
    orphan_cleanup_result = delete_orphan_files(project_root, fix_issues=fix_issues, skip_types={"folder"})
    result.orphan_cleanup_stats = orphan_cleanup_result
    
    # Step 9: Detect multi-asset directories
    if verbose:
        print("\n[9] Detecting multi-asset directories...")
    multi_asset_dirs = detect_multi_asset_directories(project_root)
    result.multi_asset_dirs = multi_asset_dirs
    
    if verbose:
        if result.has_errors:
            print("\n[ERROR] Auto-maintenance completed with ERRORS")
        elif result.lint_issues or result.path_issues:
            print("\n[WARN]  Auto-maintenance completed with warnings")
        else:
            print("\n[OK] Auto-maintenance completed successfully")
            
    return result


def validate_asset_creation_safe(result: MaintenanceResult) -> bool:
    """Check if it's safe to create an asset based on maintenance results."""
    # It's safe if there are no critical errors (missing assets, invalid JSON)
    return not result.has_errors


def handle_maintenance_failure(operation: str, result: MaintenanceResult) -> bool:
    """Handle maintenance failures with a detailed message."""
    print(f"[ERROR] {operation} aborted due to project issues:")
    if result.missing_assets:
        print(f"   - {len(result.missing_assets)} missing assets detected")
    if any(not success for _, success, _ in result.json_issues):
        print("   - Invalid JSON syntax detected in project files")
    print("   [INFO] Run 'gms maint fix-issues' to attempt automatic repair.")
    return False

def print_maintenance_summary(result: MaintenanceResult):
    """Print a summary of maintenance results."""
    print("\n[SUMMARY] Maintenance Summary:")
    print(f"  - JSON issues: {len(result.json_issues)}")
    print(f"  - Lint issues: {len(result.lint_issues)}")
    print(f"  - Path issues: {len(result.path_issues)}")
    print(f"  - Orphaned assets: {len(result.orphaned_assets)}")
    print(f"  - Missing assets: {len(result.missing_assets)}")
    if result.has_errors:
        print("[ERROR] Maintenance found issues that need attention.")
    else:
        print("[OK] Maintenance completed successfully.")

def print_event_sync_report(stats: Dict[str, int]):
    """Print a report of event synchronization results."""
    print(f"  - Objects processed: {stats.get('objects_processed', 0)}")
    print(f"  - Orphaned GML files: {stats.get('orphaned_found', 0)} found")
    print(f"  - Missing GML files: {stats.get('missing_found', 0)} found")

def print_orphan_cleanup_report(stats: Dict[str, Any]):
    """Print a report of orphan cleanup results."""
    print(f"  - Files deleted: {stats.get('total_deleted', 0)}")
    print(f"  - Directories deleted: {len(stats.get('deleted_directories', []))}")

def print_event_validation_report(event_issues: Dict[str, Any]):
    """Print a report of event validation issues."""
    print("\n[REPORT] Event Validation Issues:")
    for obj, report in event_issues.items():
        print(f"  - {obj}: {report}")
