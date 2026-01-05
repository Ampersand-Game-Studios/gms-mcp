"""Event management command implementations for tests."""

from gms_helpers.event_helper import (
    add_event, remove_event, list_events
)

def handle_event_add(args):
    """Handle event addition."""
    return add_event(args.object, args.event, getattr(args, "template", ""))

def handle_event_remove(args):
    """Handle event removal."""
    return remove_event(args.object, args.event, getattr(args, "keep_file", False))

def handle_event_list(args):
    """Handle event listing."""
    return list_events(args.object)
