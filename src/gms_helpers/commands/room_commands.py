"""Room management command implementations."""

# Import from room helpers
from ..room_layer_helper import add_layer, remove_layer, list_layers
from ..room_helper import duplicate_room, rename_room, delete_room, list_rooms
from ..room_instance_helper import add_instance, remove_instance, list_instances

# Layer commands
def handle_room_layer_add(args):
    """Handle room layer addition."""
    # CLI parser provides: room_name, layer_name, layer_type, (optional) depth
    layer_type = (getattr(args, "layer_type", "") or "").strip().lower()
    # Normalize common synonyms
    if layer_type == "instances":
        layer_type = "instance"
    
    depth = getattr(args, "depth", 0)
    # Debug print to catch why depth might be 0
    # print(f"[DEBUG] handle_room_layer_add: room_name={args.room_name}, layer_name={args.layer_name}, layer_type={layer_type}, depth={depth}")
    
    return add_layer(
        args.room_name,
        args.layer_name,
        layer_type,
        depth,
    )

def handle_room_layer_remove(args):
    """Handle room layer removal."""
    return remove_layer(args.room_name, args.layer_name)

def handle_room_layer_list(args):
    """Handle room layer listing."""
    return list_layers(args.room_name)

# Standard room operation commands (replacing template commands)
def handle_room_duplicate(args):
    """Handle room duplication."""
    return duplicate_room(args.source_room, args.new_name)

def handle_room_rename(args):
    """Handle room renaming."""
    return rename_room(args.room_name, args.new_name)

def handle_room_delete(args):
    """Handle room deletion."""
    return delete_room(args.room_name, getattr(args, 'dry_run', False))

def handle_room_list(args):
    """Handle room listing."""
    return list_rooms(getattr(args, 'verbose', False))

# Instance commands
def handle_room_instance_add(args):
    """Handle room instance addition."""
    return add_instance(
        args.room_name,
        args.object_name,
        args.x,
        args.y,
        getattr(args, "layer", "Instances") or "Instances",
    )

def handle_room_instance_remove(args):
    """Handle room instance removal."""
    return remove_instance(args.room_name, args.instance_id)

def handle_room_instance_list(args):
    """Handle room instance listing."""
    return list_instances(args.room_name, getattr(args, "layer", None))
