"""Maintenance command implementations."""

from typing import Any

from ..auto_maintenance import run_auto_maintenance
from ..health import gm_mcp_health
from ..maintenance.normalize_names import normalize_asset_names
from ..results import MaintenanceResult, OperationResult, normalize_result
from ..asset_cli.maintenance import (
    maint_clean_old_files_command,
    maint_clean_orphans_command,
    maint_dedupe_resources_command,
    maint_fix_issues_command,
    maint_lint_command,
    maint_list_orphans_command,
    maint_prune_missing_command,
    maint_sync_events_command,
    maint_validate_json_command,
    maint_validate_paths_command,
)


def _maintenance_result(result: Any, operation: str) -> Any:
    if isinstance(result, OperationResult):
        return result
    return normalize_result(
        result,
        operation=operation,
        result_cls=MaintenanceResult,
        success_message=f"{operation} completed",
        failure_message=f"{operation} failed",
        code="maintenance_failed",
        error_type="maintenance_error",
    )


def handle_maintenance_auto(args):
    """Handle automatic maintenance."""
    result = run_auto_maintenance(
        project_root=getattr(args, "project_root", "."),
        fix_issues=getattr(args, "fix", False),
        verbose=getattr(args, "verbose", True),
    )
    return MaintenanceResult(
        success=not result.has_errors,
        message="Automatic maintenance completed" if not result.has_errors else "Automatic maintenance failed",
        issues_found=len(getattr(result, "issues", []) or []),
        details=list(getattr(result, "details", []) or []),
    )


def handle_maintenance_lint(args):
    """Handle project linting."""
    return _maintenance_result(maint_lint_command(args), "Maintenance lint")


def handle_maintenance_validate_json(args):
    """Handle JSON validation."""
    return _maintenance_result(maint_validate_json_command(args), "JSON validation")


def handle_maintenance_list_orphans(args):
    """Handle orphan listing."""
    return _maintenance_result(maint_list_orphans_command(args), "Orphan listing")


def handle_maintenance_prune_missing(args):
    """Handle missing asset pruning."""
    return _maintenance_result(maint_prune_missing_command(args), "Missing asset pruning")


def handle_maintenance_validate_paths(args):
    """Handle path validation."""
    return _maintenance_result(maint_validate_paths_command(args), "Path validation")


def handle_maintenance_dedupe_resources(args):
    """Handle resource deduplication."""
    return _maintenance_result(maint_dedupe_resources_command(args), "Resource deduplication")


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
        return MaintenanceResult.fail(
            str(result.get("error", "Name normalization failed")),
            code="name_normalization_failed",
            error_type="maintenance_error",
            details=result,
            data=result,
        )

    planned = result.get("planned", [])
    skipped = result.get("skipped", [])
    if result.get("dry_run", True):
        print(f"[DRY-RUN] {len(planned)} asset rename(s) planned.")
        for item in planned:
            print(f"  {item['asset_type']}: {item['asset_name']} -> {item['target_name']} ({item['asset_path']})")
        if skipped:
            print(f"[WARN] {len(skipped)} asset(s) skipped.")
        return MaintenanceResult.ok("Name normalization dry-run completed", data=result)

    print(f"[OK] Applied {result.get('changed_count', 0)} asset rename(s).")
    for item in result.get("applied", []):
        print(f"  {item['asset_type']}: {item['asset_name']} -> {item['target_name']}")
    if skipped:
        print(f"[WARN] {len(skipped)} asset(s) skipped.")
    return MaintenanceResult.ok("Name normalization completed", data=result)


def handle_maintenance_sync_events(args):
    """Handle event synchronization."""
    return _maintenance_result(maint_sync_events_command(args), "Event synchronization")


def handle_maintenance_clean_old_files(args):
    """Handle old file cleaning."""
    return _maintenance_result(maint_clean_old_files_command(args), "Old file cleanup")


def handle_maintenance_clean_orphans(args):
    """Handle orphan cleaning."""
    return _maintenance_result(maint_clean_orphans_command(args), "Orphan cleanup")


def handle_maintenance_fix_issues(args):
    """Handle comprehensive issue fixing."""
    return _maintenance_result(maint_fix_issues_command(args), "Maintenance fix")


def handle_maintenance_health(args):
    """Handle environment health check."""
    result = gm_mcp_health(getattr(args, "project_root", "."))
    for detail in result.details:
        print(detail)
    return MaintenanceResult(
        success=result.success,
        message="Health check passed" if result.success else "Health check failed",
        details=list(result.details),
    )
