"""Shared flow helpers for GameMaker asset creation commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .auto_maintenance import handle_maintenance_failure, run_auto_maintenance, validate_asset_creation_safe
from .utils import update_yyp_file, validate_name, validate_parent_path_for_project


def run_pre_creation_maintenance(args: Any, operation: str) -> Any:
    """Run the shared pre-creation maintenance gate."""
    if getattr(args, "skip_maintenance", False):
        return True
    print("[VALIDATE] Running pre-creation validation...")
    project_root = getattr(args, "project_root", ".")
    pre_result = run_auto_maintenance(project_root, fix_issues=not getattr(args, "no_auto_fix", False), verbose=False)
    if not validate_asset_creation_safe(pre_result):
        return handle_maintenance_failure(operation, pre_result)
    return True


def run_post_creation_maintenance(args: Any, operation: str) -> bool:
    """Run the shared post-creation maintenance gate."""
    if getattr(args, "skip_maintenance", False):
        return True
    print("[MAINT] Running post-creation maintenance...")
    post_result = run_auto_maintenance(
        getattr(args, "project_root", "."),
        fix_issues=not getattr(args, "no_auto_fix", False),
        verbose=getattr(args, "maintenance_verbose", True),
    )
    if not post_result.has_errors:
        print("[OK] Asset created and validated successfully!")
        return True
    return handle_maintenance_failure(operation, post_result)


def validate_named_asset(args: Any, asset_type: str, *, allow_constructor: bool = False) -> None:
    """Validate the standard asset name + parent path pair."""
    if allow_constructor:
        validate_name(args.name, asset_type, allow_constructor=True)
    else:
        validate_name(args.name, asset_type)
    validate_parent_path_for_project(getattr(args, "project_root", Path.cwd()), args.parent_path)


def create_project_asset(
    args: Any,
    *,
    asset: Any,
    asset_type: str,
    label: str,
    kwargs: dict[str, Any] | None = None,
    success_message: str | None = None,
    success_lines: Iterable[str] | Callable[[Any], Iterable[str]] = (),
    allow_constructor: bool = False,
) -> bool:
    """Create files for a standard project asset and register it in the .yyp file."""
    precheck = run_pre_creation_maintenance(args, f"{label} '{args.name}' creation")
    if precheck is not True:
        return precheck

    validate_named_asset(args, asset_type, allow_constructor=allow_constructor)
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    relative_path = asset.create_files(project_root, args.name, args.parent_path, **(kwargs or {}))
    resource_entry = {"id": {"name": args.name, "path": relative_path}}

    if not update_yyp_file(resource_entry, project_root=project_root):
        print(f"[ERROR] Failed to update .yyp file for {label.lower()} '{args.name}'")
        return False

    print(success_message or f"[OK] {label} '{args.name}' created successfully")
    lines = success_lines(args) if callable(success_lines) else success_lines
    for line in lines:
        print(line)

    return run_post_creation_maintenance(args, f"{label} '{args.name}' post-creation")
