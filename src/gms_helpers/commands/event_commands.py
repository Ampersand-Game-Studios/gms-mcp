"""Event management command implementations."""

from ..event_helper import (
    add_event, remove_event, list_events, duplicate_event
)
from ..maintenance.event_sync import sync_object_events

def handle_event_add(args):
    """Handle event addition."""
    template = getattr(args, "template", None) or ""
    return add_event(args.object, args.event, template)

def handle_event_remove(args):
    """Handle event removal."""
    return remove_event(args.object, args.event, getattr(args, "keep_file", False))

def handle_event_duplicate(args):
    """Handle event duplication."""
    return duplicate_event(args.object, args.source_event, args.target_num)

def handle_event_list(args):
    """Handle event listing."""
    return list_events(args.object)

def handle_event_validate(args):
    """Handle event validation."""
    from pathlib import Path
    results = sync_object_events(str(Path("objects") / args.object), dry_run=True)
    return results['orphaned_found'] == 0 and results['missing_found'] == 0

def handle_event_fix(args):
    """Handle event fixing."""
    from pathlib import Path
    results = sync_object_events(str(Path("objects") / args.object), dry_run=False)
    return True
