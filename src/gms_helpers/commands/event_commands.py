"""Event management command implementations."""

from ..event_helper import (
    cmd_add, cmd_remove, cmd_duplicate, cmd_list, cmd_validate, cmd_fix
)

def handle_event_add(args):
    """Handle event addition."""
    return cmd_add(args)

def handle_event_remove(args):
    """Handle event removal."""
    return cmd_remove(args)

def handle_event_duplicate(args):
    """Handle event duplication."""
    return cmd_duplicate(args)

def handle_event_list(args):
    """Handle event listing."""
    return cmd_list(args)

def handle_event_validate(args):
    """Handle event validation."""
    return cmd_validate(args)

def handle_event_fix(args):
    """Handle event fixing."""
    return cmd_fix(args) 
