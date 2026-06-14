"""Workflow command implementations."""

from pathlib import Path

from ..results import OperationResult, normalize_result
from ..workflow import duplicate_asset, rename_asset, delete_asset, safe_delete_asset, swap_sprite_png


def handle_workflow_duplicate(args):
    """Handle asset duplication."""
    project_root = Path(args.project_root).resolve()
    result = duplicate_asset(project_root, args.asset_path, args.new_name, yes=getattr(args, "yes", False))
    return normalize_result(result, operation="Workflow duplicate", data={"asset_path": args.asset_path})


def handle_workflow_rename(args):
    """Handle asset renaming."""
    project_root = Path(args.project_root).resolve()
    result = rename_asset(project_root, args.asset_path, args.new_name)
    return normalize_result(result, operation="Workflow rename", data={"asset_path": args.asset_path})


def handle_workflow_delete(args):
    """Handle asset deletion."""
    project_root = Path(args.project_root).resolve()
    result = delete_asset(project_root, args.asset_path, dry_run=getattr(args, "dry_run", False))
    return normalize_result(
        result,
        operation="Workflow delete",
        data={"asset_path": args.asset_path, "dry_run": getattr(args, "dry_run", False)},
    )


def handle_workflow_swap_sprite(args):
    """Handle sprite PNG swapping."""
    project_root = Path(args.project_root).resolve()
    frame_index = getattr(args, "frame", 0)
    result = swap_sprite_png(project_root, args.asset_path, Path(args.png), frame_index=frame_index)
    return normalize_result(
        result,
        operation="Workflow swap sprite",
        data={"asset_path": args.asset_path, "png": args.png, "frame": frame_index},
    )


def handle_workflow_safe_delete(args):
    """Handle dependency-aware asset deletion."""
    project_root = Path(args.project_root).resolve()
    result = safe_delete_asset(
        project_root,
        args.asset_type,
        args.asset_name,
        force=getattr(args, "force", False),
        clean_refs=getattr(args, "clean_refs", False),
        dry_run=not getattr(args, "apply", False),
    )

    if result.get("ok") is False:
        message = str(result.get("error", "Safe delete failed"))
        print(f"[ERROR] {message}")
        return normalize_result(
            result,
            operation="Safe delete",
            failure_message=message,
            code="safe_delete_failed",
            error_type="workflow_error",
        )
    if result.get("blocked"):
        print("[WARN] Safe delete blocked by dependencies:")
        for dep in result.get("dependencies", []):
            print(
                f"  - {dep.get('asset_type', 'unknown')} {dep.get('asset_name', 'unknown')} "
                f"({dep.get('relation', 'unknown')})"
            )
        return normalize_result(
            {**result, "ok": False, "error": "Safe delete blocked by dependencies"},
            operation="Safe delete",
            failure_message="Safe delete blocked by dependencies",
            code="safe_delete_blocked",
            error_type="dependency_error",
        )
    if result.get("dry_run"):
        print("[OK] Safe delete dry-run completed.")
        return normalize_result(result, operation="Safe delete", success_message="Safe delete dry-run completed")
    if result.get("deleted", False):
        return normalize_result(result, operation="Safe delete", success_message="Safe delete completed")
    return normalize_result(
        {**result, "ok": False, "error": "Safe delete did not delete the asset"},
        operation="Safe delete",
        failure_message="Safe delete did not delete the asset",
        code="safe_delete_noop",
        error_type="workflow_error",
    )
