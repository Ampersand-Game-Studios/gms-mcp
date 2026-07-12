"""Workflow command implementations."""

from pathlib import Path
from typing import Any, Callable, TypeVar

from ..results import OperationResult, normalize_result, result_dict_is_ok
from ..transactions import (
    GameMakerProjectTransaction,
    TransactionValidationError,
    should_compile_verify_after_mutation,
    transaction_is_active,
)
from ..workflow import duplicate_asset, rename_asset, safe_delete_asset, swap_sprite_png


_WorkflowResult = TypeVar("_WorkflowResult")


def _workflow_result_succeeded(result: Any) -> bool:
    if isinstance(result, OperationResult):
        return result.success
    if isinstance(result, dict):
        return result_dict_is_ok(result)
    return bool(result)


def _attach_transaction(result: _WorkflowResult, transaction: dict[str, Any]) -> _WorkflowResult:
    if isinstance(result, OperationResult):
        result.data["transaction"] = transaction
        if transaction.get("rollback_complete") is False:
            result.warnings.append(
                "Safe rollback could not restore every journaled path; inspect transaction conflicts."
            )
    elif isinstance(result, dict):
        result["transaction"] = transaction
        if transaction.get("rollback_complete") is False:
            warnings = result.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append("Safe rollback could not restore every journaled path; inspect transaction conflicts.")
    return result


def _run_transactional_workflow(
    project_root: Path,
    tool_name: str,
    operation: Callable[[], _WorkflowResult],
) -> _WorkflowResult:
    """Run one standalone CLI mutation transaction, reusing any active parent."""

    if transaction_is_active():
        return operation()

    transaction = GameMakerProjectTransaction(project_root, tool_name)
    transaction.begin()
    try:
        result = operation()
        transaction.capture_mutation_state()
        if not _workflow_result_succeeded(result):
            transaction.rollback()
            return _attach_transaction(result, transaction.to_dict())
        details = transaction.commit(verify_compile=should_compile_verify_after_mutation())
        return _attach_transaction(result, details)
    except BaseException as exc:
        if not transaction.committed:
            transaction.capture_mutation_state()
            rollback_complete = transaction.rollback()
            if not rollback_complete:
                raise TransactionValidationError(
                    "Workflow failed and safe rollback could not restore every journaled path.",
                    details={
                        "original_error": f"{type(exc).__name__}: {exc}",
                        "transaction": transaction.to_dict(),
                    },
                ) from exc
        raise
    finally:
        transaction.cleanup()


def handle_workflow_duplicate(args):
    """Handle asset duplication."""
    project_root = Path(args.project_root).resolve()
    result = _run_transactional_workflow(
        project_root,
        "workflow-duplicate",
        lambda: duplicate_asset(project_root, args.asset_path, args.new_name, yes=getattr(args, "yes", False)),
    )
    return normalize_result(result, operation="Workflow duplicate", data={"asset_path": args.asset_path})


def handle_workflow_rename(args):
    """Handle asset renaming."""
    project_root = Path(args.project_root).resolve()
    result = _run_transactional_workflow(
        project_root,
        "workflow-rename",
        lambda: rename_asset(project_root, args.asset_path, args.new_name),
    )
    return normalize_result(result, operation="Workflow rename", data={"asset_path": args.asset_path})


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
    apply = bool(getattr(args, "apply", False))
    operation = lambda: safe_delete_asset(
        project_root,
        args.asset_type,
        args.asset_name,
        force=getattr(args, "force", False),
        dry_run=not apply,
    )
    result = _run_transactional_workflow(project_root, "workflow-safe-delete", operation) if apply else operation()

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
