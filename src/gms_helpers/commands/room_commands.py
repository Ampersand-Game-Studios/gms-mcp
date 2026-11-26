"""Room management command implementations."""

# Import from room helpers
from ..room_layer_helper import add_layer, remove_layer, list_layers
from ..room_helper import duplicate_room, rename_room, delete_room, list_rooms
from ..room_instance_helper import add_instance, remove_instance, list_instances
from ..results import OperationResult, normalize_result


def _room_result(result, operation: str, **data):
    if isinstance(result, OperationResult):
        return result
    return normalize_result(
        result,
        operation=operation,
        data=data,
        success_message=f"{operation} completed",
        failure_message=f"{operation} failed",
        code="room_operation_failed",
        error_type="room_error",
    )


# Layer commands
def handle_room_layer_add(args):
    """Handle room layer addition."""
    # CLI parser provides: room_name, layer_name, layer_type, (optional) depth and tileset
    layer_type = (getattr(args, "layer_type", "") or "").strip().lower()
    # Normalize common synonyms
    if layer_type == "instances":
        layer_type = "instance"

    depth = getattr(args, "depth", None)
    tileset = getattr(args, "tileset", None)

    return _room_result(
        add_layer(
            args.room_name,
            args.layer_name,
            layer_type,
            depth,
            tileset_name=tileset,
        ),
        "Room layer add",
        room_name=args.room_name,
        layer_name=args.layer_name,
        layer_type=layer_type,
        depth=depth,
        tileset=tileset,
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
    layers = list_layers(args.room_name)
    return normalize_result(
        layers,
        operation="Room layer list",
        data_key="layers",
        data={"room_name": args.room_name},
    )


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
        delete_room(args.room_name, getattr(args, "dry_run", False), force=getattr(args, "force", False)),
        "Room delete",
        room_name=args.room_name,
        dry_run=getattr(args, "dry_run", False),
    )


def handle_room_list(args):
    """Handle room listing."""
    rooms = list_rooms(getattr(args, "verbose", False))
    return normalize_result(rooms, operation="Room list", data_key="rooms")


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
    instances = list_instances(args.room_name, getattr(args, "layer", None))
    return normalize_result(
        instances,
        operation="Room instance list",
        data_key="instances",
        data={"room_name": args.room_name, "layer": getattr(args, "layer", None)},
    )


# Dense shapes for the MCP listing tools: the handlers' data, each shared part written once.
def _listing_data(value):
    """The handler's data, or None when it failed (its report is then returned as it is)."""
    if not isinstance(value, dict) or not value.get("success", value.get("ok", True)):
        return None
    data = value.get("data")
    return data if isinstance(data, dict) else {}


def _number(value):
    """A coordinate as GameMaker wrote it, without a float's trailing ".0"."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def dense_room_list(value, verbose=False):
    """``rooms`` maps each room to "<width>x<height>, <n> layers"; with verbose, ``layers`` lists
    each distinct layer stack once with the rooms that have it."""
    data = _listing_data(value)
    if data is None:
        return value
    from ..dense import name_ranges

    rooms = {}
    stacks = {}
    for room in data.get("rooms", []):
        name = str(room.get("name"))
        if room.get("error"):
            rooms[name] = f"error: {room['error']}"
            continue
        count = room.get("layer_count")
        rooms[name] = f"{room.get('width')}x{room.get('height')}, {count} layer{'' if count == 1 else 's'}"
        if verbose:
            stacks.setdefault(tuple(room.get("layers") or ()), []).append(name)
    result = {"ok": True, "count": len(rooms), "rooms": rooms}
    if verbose:
        result["layers"] = [{"rooms": name_ranges(names), "layers": list(stack)} for stack, names in stacks.items()]
    return result


def dense_layer_list(value):
    """``layers`` in the room's order, each "<name> <type> <depth>", ending " hidden" when it is."""
    data = _listing_data(value)
    if data is None:
        return value
    layers = [
        f"{layer.get('name')} {layer.get('type')} {layer.get('depth')}"
        + ("" if layer.get("visible", True) else " hidden")
        for layer in data.get("layers", [])
    ]
    return {"ok": True, "room": data.get("room_name"), "layers": layers}


def dense_instance_list(value):
    """``instances`` maps layer to object to "<name> <x>,<y>" entries, with " scale <x>,<y>" and
    " rotation <r>" only where they are not 1,1 and 0."""
    data = _listing_data(value)
    if data is None:
        return value
    layers = {}
    count = 0
    for item in data.get("instances", []):
        entry = f"{item.get('name')} {_number(item.get('x'))},{_number(item.get('y'))}"
        scale = tuple(_number(1.0 if item.get(key) is None else item[key]) for key in ("scale_x", "scale_y"))
        if scale != (1, 1):
            entry += f" scale {scale[0]},{scale[1]}"
        rotation = _number(item.get("rotation") or 0)
        if rotation != 0:
            entry += f" rotation {rotation}"
        layers.setdefault(str(item.get("layer")), {}).setdefault(str(item.get("object")), []).append(entry)
        count += 1
    return {"ok": True, "room": data.get("room_name"), "count": count, "instances": layers}
