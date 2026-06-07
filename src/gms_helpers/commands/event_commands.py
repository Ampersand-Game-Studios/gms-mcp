"""Event management command implementations."""

from ..event_helper import add_event, remove_event, list_events, duplicate_event
from ..maintenance.event_sync import sync_object_events
from ..path_safety import project_child_path, validate_resource_name
from ..results import OperationResult


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


def handle_event_add(args):
    """Handle event addition."""
    template = getattr(args, "template", None) or ""
    return _event_result(
        add_event(args.object, args.event, template),
        "Event add",
        object=args.object,
        event=args.event,
    )


def handle_event_remove(args):
    """Handle event removal."""
    return _event_result(
        remove_event(args.object, args.event, getattr(args, "keep_file", False)),
        "Event remove",
        object=args.object,
        event=args.event,
    )


def handle_event_duplicate(args):
    """Handle event duplication."""
    return _event_result(
        duplicate_event(args.object, args.source_event, args.target_num),
        "Event duplicate",
        object=args.object,
        source_event=args.source_event,
        target_num=args.target_num,
    )


def handle_event_list(args):
    """Handle event listing."""
    return list_events(args.object)


def handle_event_validate(args):
    """Handle event validation."""
    object_name = validate_resource_name(args.object, "object")
    object_dir = project_child_path("objects", object_name, kind=f"object '{object_name}'")
    results = sync_object_events(str(object_dir), dry_run=True)
    success = results["orphaned_found"] == 0 and results["missing_found"] == 0
    return _event_result(success, "Event validation", object=object_name, results=results)


def handle_event_fix(args):
    """Handle event fixing."""
    object_name = validate_resource_name(args.object, "object")
    object_dir = project_child_path("objects", object_name, kind=f"object '{object_name}'")
    results = sync_object_events(str(object_dir), dry_run=False)
    return OperationResult.ok("Event fix completed", data={"object": object_name, "results": results})
