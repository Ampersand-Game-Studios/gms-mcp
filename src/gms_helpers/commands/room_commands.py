"""Room management command implementations."""

# Import from room helpers
from ..room_layer_helper import add_layer, remove_layer, list_layers
from ..room_helper import duplicate_room, rename_room, delete_room, list_rooms
from ..room_instance_helper import add_instance, remove_instance, list_instances

# Layer commands
def handle_room_layer_add(args):
    """Handle room layer addition."""
    # Convert CLI arguments to match what the room helper expects
    args.layer_type = args.layer_type
    args.depth = getattr(args, 'depth', 0)
    return add_layer(args)

def handle_room_layer_remove(args):
    """Handle room layer removal."""
    return remove_layer(args)

def handle_room_layer_list(args):
    """Handle room layer listing."""
    return list_layers(args)

# Standard room operation commands (replacing template commands)
def handle_room_duplicate(args):
    """Handle room duplication."""
    # Map CLI args to room function args
    room_args = type('Args', (), {
        'source_room': args.source_room,
        'new_name': args.new_name
    })()
    return duplicate_room(room_args)

def handle_room_rename(args):
    """Handle room renaming."""
    # Map CLI args to room function args
    room_args = type('Args', (), {
        'room_name': args.room_name,
        'new_name': args.new_name
    })()
    return rename_room(room_args)

def handle_room_delete(args):
    """Handle room deletion."""
    # Map CLI args to room function args
    room_args = type('Args', (), {
        'room_name': args.room_name,
        'dry_run': getattr(args, 'dry_run', False)
    })()
    return delete_room(room_args)

def handle_room_list(args):
    """Handle room listing."""
    # Map CLI args to room function args
    room_args = type('Args', (), {
        'verbose': getattr(args, 'verbose', False)
    })()
    return list_rooms(room_args)

# Instance commands
def handle_room_instance_add(args):
    """Handle room instance addition."""
    return add_instance(args)

def handle_room_instance_remove(args):
    """Handle room instance removal."""
    return remove_instance(args)

def handle_room_instance_list(args):
    """Handle room instance listing."""
    return list_instances(args) 
