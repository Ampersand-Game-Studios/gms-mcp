"""Event management command implementations."""

from pathlib import Path

from ..event_helper import add_event, remove_event, list_events, duplicate_event
from ..maintenance.event_sync import sync_object_events
from ..path_safety import project_child_path, validate_resource_name
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


def handle_event_validate(args):
    """Handle event validation."""
    object_name = validate_resource_name(args.object, "object")
    object_dir = project_child_path(
        "objects",
        object_name,
        project_root=getattr(args, "project_root", None),
        kind=f"object '{object_name}'",
    )
    results = sync_object_events(str(object_dir), dry_run=True)
    success = results["orphaned_found"] == 0 and results["missing_found"] == 0
    return _event_result(success, "Event validation", object=object_name, results=results)


def handle_event_fix(args):
    """Handle event fixing."""
    object_name = validate_resource_name(args.object, "object")
    object_dir = project_child_path(
        "objects",
        object_name,
        project_root=getattr(args, "project_root", None),
        kind=f"object '{object_name}'",
    )
    results = sync_object_events(str(object_dir), dry_run=False)
    return OperationResult.ok("Event fix completed", data={"object": object_name, "results": results})
