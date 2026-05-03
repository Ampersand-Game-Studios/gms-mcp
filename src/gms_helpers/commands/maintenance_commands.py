"""Maintenance command implementations."""

from ..auto_maintenance import run_auto_maintenance
from ..health import gm_mcp_health
from ..maintenance.normalize_names import normalize_asset_names
from ..asset_helper import (
    maint_lint_command,
    maint_validate_json_command,
    maint_list_orphans_command,
    maint_prune_missing_command,
    maint_validate_paths_command,
    maint_dedupe_resources_command,
    maint_sync_events_command,
    maint_clean_old_files_command,
    maint_clean_orphans_command,
    maint_fix_issues_command,
)


def handle_maintenance_auto(args):
    """Handle automatic maintenance."""
    result = run_auto_maintenance(
        project_root=getattr(args, "project_root", "."),
        fix_issues=getattr(args, "fix", False),
        verbose=getattr(args, "verbose", True),
    )
    return not result.has_errors


def handle_maintenance_lint(args):
    """Handle project linting."""
    return maint_lint_command(args)


def handle_maintenance_validate_json(args):
    """Handle JSON validation."""
    return maint_validate_json_command(args)


def handle_maintenance_list_orphans(args):
    """Handle orphan listing."""
    return maint_list_orphans_command(args)


def handle_maintenance_prune_missing(args):
    """Handle missing asset pruning."""
    return maint_prune_missing_command(args)


def handle_maintenance_validate_paths(args):
    """Handle path validation."""
    return maint_validate_paths_command(args)


def handle_maintenance_dedupe_resources(args):
    """Handle resource deduplication."""
    return maint_dedupe_resources_command(args)


def handle_maintenance_normalize_names(args):
    """Handle opt-in asset naming normalization."""
    result = normalize_asset_names(
        project_root=getattr(args, "project_root", "."),
        fix=getattr(args, "fix", False),
        asset_type=getattr(args, "asset_type", None),
    )

    if not result.get("ok"):
        print(f"[ERROR] {result.get('error', 'Name normalization failed')}")
        for item in result.get("failed", []):
            print(f"  [FAIL] {item['asset_name']} -> {item.get('target_name', '?')}: {item.get('reason', '')}")
        return False

    planned = result.get("planned", [])
    skipped = result.get("skipped", [])
    if result.get("dry_run", True):
        print(f"[DRY-RUN] {len(planned)} asset rename(s) planned.")
        for item in planned:
            print(f"  {item['asset_type']}: {item['asset_name']} -> {item['target_name']} ({item['asset_path']})")
        if skipped:
            print(f"[WARN] {len(skipped)} asset(s) skipped.")
        return True

    print(f"[OK] Applied {result.get('changed_count', 0)} asset rename(s).")
    for item in result.get("applied", []):
        print(f"  {item['asset_type']}: {item['asset_name']} -> {item['target_name']}")
    if skipped:
        print(f"[WARN] {len(skipped)} asset(s) skipped.")
    return True


def handle_maintenance_sync_events(args):
    """Handle event synchronization."""
    return maint_sync_events_command(args)


def handle_maintenance_clean_old_files(args):
    """Handle old file cleaning."""
    return maint_clean_old_files_command(args)


def handle_maintenance_clean_orphans(args):
    """Handle orphan cleaning."""
    return maint_clean_orphans_command(args)


def handle_maintenance_fix_issues(args):
    """Handle comprehensive issue fixing."""
    return maint_fix_issues_command(args)


def handle_maintenance_health(args):
    """Handle environment health check."""
    result = gm_mcp_health(getattr(args, "project_root", "."))
    for detail in result.details:
        print(detail)
    return result.success
