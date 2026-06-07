"""Room management command implementations."""

# Import from room helpers
from ..room_layer_helper import add_layer, remove_layer, list_layers
from ..room_helper import duplicate_room, rename_room, delete_room, list_rooms
from ..room_instance_helper import add_instance, remove_instance, list_instances
from ..results import OperationResult


def _room_result(result, operation: str, **data):
    if not isinstance(result, bool):
        return result
    if result:
        return OperationResult.ok(f"{operation} completed", data=data)
    return OperationResult.fail(
        f"{operation} failed",
        code="room_operation_failed",
        error_type="room_error",
        details={"operation": operation, **data},
        data=data,
    )


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

    return _room_result(
        add_layer(
            args.room_name,
            args.layer_name,
            layer_type,
            depth,
        ),
        "Room layer add",
        room_name=args.room_name,
        layer_name=args.layer_name,
        layer_type=layer_type,
        depth=depth,
    )


def handle_room_layer_remove(args):
    """Handle room layer removal."""
    return _room_result(
        remove_layer(args.room_name, args.layer_name),
        "Room layer remove",
        room_name=args.room_name,
        layer_name=args.layer_name,
    )


def handle_room_layer_list(args):
    """Handle room layer listing."""
    return list_layers(args.room_name)


# Standard room operation commands (replacing template commands)
def handle_room_duplicate(args):
    """Handle room duplication."""
    return _room_result(
        duplicate_room(args.source_room, args.new_name),
        "Room duplicate",
        source_room=args.source_room,
        new_name=args.new_name,
    )


def handle_room_rename(args):
    """Handle room renaming."""
    return _room_result(
        rename_room(args.room_name, args.new_name),
        "Room rename",
        room_name=args.room_name,
        new_name=args.new_name,
    )


def handle_room_delete(args):
    """Handle room deletion."""
    return _room_result(
        delete_room(args.room_name, getattr(args, "dry_run", False)),
        "Room delete",
        room_name=args.room_name,
        dry_run=getattr(args, "dry_run", False),
    )


def handle_room_list(args):
    """Handle room listing."""
    return list_rooms(getattr(args, "verbose", False))


# Instance commands
def handle_room_instance_add(args):
    """Handle room instance addition."""
    layer = getattr(args, "layer", "Instances") or "Instances"
    return _room_result(
        add_instance(
            args.room_name,
            args.object_name,
            args.x,
            args.y,
            layer,
        ),
        "Room instance add",
        room_name=args.room_name,
        object_name=args.object_name,
        x=args.x,
        y=args.y,
        layer=layer,
    )


def handle_room_instance_remove(args):
    """Handle room instance removal."""
    return _room_result(
        remove_instance(args.room_name, args.instance_id),
        "Room instance remove",
        room_name=args.room_name,
        instance_id=args.instance_id,
    )


def handle_room_instance_list(args):
    """Handle room instance listing."""
    return list_instances(args.room_name, getattr(args, "layer", None))
