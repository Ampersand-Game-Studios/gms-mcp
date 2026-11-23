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
    maint_list_orphans_command,
    maint_prune_missing_command,
    maint_sync_events_command,
    maint_validate_json_command,
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
    """Lint the project: print the report and return every issue as diagnostics data."""
    from pathlib import Path

    from ..maintenance.lint import lint_project, print_lint_report

    root = Path(getattr(args, "project_root", ".") or ".").resolve()
    print("[SCAN] Scanning project for issues...")
    issues = lint_project(str(root))
    print_lint_report(issues)
    summary = {"error": 0, "warning": 0, "info": 0, "hint": 0}
    for issue in issues:
        summary[issue.severity] = summary.get(issue.severity, 0) + 1
    return {
        "ok": summary["error"] == 0,
        "depth": "lint",
        "diagnostics": [issue.to_diagnostic().to_dict() for issue in issues],
        "summary": summary,
        "project_root": str(root),
    }


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
    """Validate folder paths: print the report and return every issue as data."""
    from ..maintenance.validate_paths import print_path_validation_report, validate_folder_paths

    strict = getattr(args, "strict_disk_check", False)
    issues = validate_folder_paths(
        getattr(args, "project_root", "."),
        strict_mode=strict,
        include_parent_folders=getattr(args, "include_parent_folders", False),
    )
    print_path_validation_report(issues, strict_mode=strict)
    return {
        "ok": not any(issue.severity == "error" for issue in issues),
        "issues": [
            {
                "severity": issue.severity,
                "type": issue.issue_type,
                "folder": issue.referenced_folder,
                "asset": issue.asset_path,
                "asset_name": issue.asset_name,
            }
            for issue in issues
        ],
    }


def handle_maintenance_dedupe_resources(args):
    """Handle resource deduplication."""
    return _maintenance_result(maint_dedupe_resources_command(args), "Resource deduplication")


def handle_maintenance_restore_trash(args):
    """Move a maintenance trash batch back to its original project paths."""
    from ..maintenance.trash import restore_from_trash

    return _maintenance_result(
        restore_from_trash(getattr(args, "project_root", None) or ".", args.trash_name), "Trash restore"
    )


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


def dense_path_issues(report: dict) -> dict:
    """Group path issues by severity and type: the folders each names, and the assets when they differ.

    ``folders`` maps a parent folder to the folder files under it.
    """
    from ..dense import by_folder

    groups: dict[tuple, dict] = {}
    for issue in report.get("issues", []):
        key = (issue.get("severity"), issue.get("type"))
        group = groups.setdefault(key, {"severity": key[0], "type": key[1], "_items": []})
        group["_items"].append(issue)
    out = []
    for group in groups.values():
        items = group.pop("_items")
        if all(item.get("asset") in ("", None, item.get("folder")) for item in items):
            # An orphaned folder is reported against itself: the folder is the whole story.
            group["folders"] = by_folder(str(item.get("folder")) for item in items)
        else:
            group["items"] = [
                {"asset": item.get("asset"), "folder": item.get("folder")}
                if not item.get("asset_name") or f"/{item.get('asset_name')}/" in str(item.get("asset"))
                else {key: value for key, value in item.items() if key not in ("severity", "type")}
                for item in items
            ]
        out.append(group)
    return {"ok": report.get("ok", True), "issue_count": len(report.get("issues", [])), "issues": out}


def dense_renames(report: dict) -> dict:
    """Write each planned or applied rename as "old -> new", grouped by the asset's folder.

    The asset's file is <folder>/<old>/<old>.yy; an asset whose file is named otherwise keeps its
    path after the arrow pair, in parentheses.
    """
    nested = report.get("data")
    data: dict = nested if isinstance(nested, dict) else report
    out: dict = {"ok": report.get("ok", report.get("success", True))}
    if report.get("message"):
        out["message"] = report["message"]
    out["dry_run"] = data.get("dry_run", True)

    def grouped(items: list) -> dict:
        folders: dict[str, list[str]] = {}
        for item in items:
            name, path = item.get("asset_name", ""), str(item.get("asset_path", ""))
            folder, _, tail = path.rpartition(f"/{name}/")
            entry = f"{name} -> {item.get('target_name')}"
            if tail != f"{name}.yy":
                folder, entry = "", f"{entry} ({path})"
            if item.get("reason"):
                entry += f": {item['reason']}"
            folders.setdefault(folder, []).append(entry)
        return folders

    for key in ("planned", "applied", "skipped", "failed"):
        if data.get(key):
            out[key] = grouped(data[key])
    if "changed_count" in data and not out["dry_run"]:
        out["changed_count"] = data["changed_count"]
    if data.get("error"):
        out["error"] = data["error"]
    return out
