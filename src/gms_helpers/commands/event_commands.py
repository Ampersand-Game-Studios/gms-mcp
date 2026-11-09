"""Event management command implementations."""

from pathlib import Path

from ..event_helper import add_event, remove_event, list_events, duplicate_event
from ..exceptions import GMSError
from ..maintenance.event_sync import create_missing_gml_files, fix_orphaned_gml_files, sync_object_events
from ..path_safety import project_relative_path, validate_resource_name
from ..project_validation import resolve_asset_reference
from ..results import OperationResult, normalize_result


def _event_result(success: bool, operation: str, **data):
    if success:
        return OperationResult.ok(f"{operation} completed", data=data)
    return OperationResult.fail(
        f"{operation} failed",
        code="event_operation_failed",
        error_type="event_error",
        details={"operation": operation, **data},
        data=data,
    )


def _project_root(args):
    value = getattr(args, "project_root", None)
    return value if isinstance(value, (str, Path)) else None


def handle_event_add(args):
    """Handle event addition."""
    template = getattr(args, "template", None) or ""
    project_root = _project_root(args)
    success = (
        add_event(args.object, args.event, template, project_root)
        if project_root is not None
        else add_event(args.object, args.event, template)
    )
    return _event_result(
        success,
        "Event add",
        object=args.object,
        event=args.event,
    )


def handle_event_remove(args):
    """Handle event removal."""
    keep_file = getattr(args, "keep_file", False)
    project_root = _project_root(args)
    success = (
        remove_event(args.object, args.event, keep_file, project_root)
        if project_root is not None
        else remove_event(args.object, args.event, keep_file)
    )
    return _event_result(
        success,
        "Event remove",
        object=args.object,
        event=args.event,
    )


def handle_event_duplicate(args):
    """Handle event duplication."""
    project_root = _project_root(args)
    success = (
        duplicate_event(args.object, args.source_event, args.target_event, project_root)
        if project_root is not None
        else duplicate_event(args.object, args.source_event, args.target_event)
    )
    return _event_result(
        success,
        "Event duplicate",
        object=args.object,
        source_event=args.source_event,
        target_event=args.target_event,
    )


def handle_event_list(args):
    """Handle event listing."""
    project_root = _project_root(args)
    events = list_events(args.object, project_root) if project_root is not None else list_events(args.object)
    return normalize_result(
        events,
        operation="Event list",
        data_key="events",
        data={"object": args.object},
    )


def _registered_object_yy(args):
    """Resolve the object's registered .yy path, or return a failure result."""
    object_name = validate_resource_name(args.object, "object")
    project_root = Path(_project_root(args) or Path.cwd()).resolve()
    try:
        reference = resolve_asset_reference(project_root, object_name, "GMObject")
    except GMSError as exc:
        return (
            object_name,
            None,
            OperationResult.fail(
                f"Object '{object_name}' is not a registered object with a readable .yy: {exc}",
                code="object_not_found",
                error_type="event_error",
                details={"object": object_name},
                data={"object": object_name},
            ),
        )
    yy_path = project_relative_path(reference["path"], project_root=project_root, kind=f"object '{object_name}'")
    return object_name, yy_path, None


def handle_event_validate(args):
    """Handle event validation."""
    object_name, yy_path, failure = _registered_object_yy(args)
    if failure is not None:
        return failure
    results = sync_object_events(str(yy_path), dry_run=True)
    success = results["orphaned_found"] == 0 and results["missing_found"] == 0
    return _event_result(success, "Event validation", object=object_name, results=results)


def handle_event_fix(args):
    """Handle event fixing.

    Safe mode (the default) only creates empty files for events the .yy already
    declares. Registering orphaned .gml files as new events changes the object's
    behaviour, so it needs ``--no-safe-mode``.
    """
    object_name, yy_path, failure = _registered_object_yy(args)
    if failure is not None:
        return failure
    safe_mode = getattr(args, "safe_mode", True) is not False
    orphaned_found, orphaned_fixed = fix_orphaned_gml_files(str(yy_path), dry_run=safe_mode)
    missing_found, missing_created = create_missing_gml_files(str(yy_path), dry_run=False)
    results = {
        "orphaned_found": orphaned_found,
        "orphaned_fixed": orphaned_fixed,
        "missing_found": missing_found,
        "missing_created": missing_created,
        "safe_mode": safe_mode,
    }
    warnings = []
    if safe_mode and orphaned_found:
        warnings.append(
            f"{orphaned_found} orphaned event file(s) left unregistered in safe mode; use --no-safe-mode to add them."
        )
    return OperationResult.ok(
        "Event fix completed", warnings=warnings, data={"object": object_name, "results": results}
    )
