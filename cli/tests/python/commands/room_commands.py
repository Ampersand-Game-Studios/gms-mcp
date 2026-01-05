"""Room management command implementations for tests."""

from gms_helpers.room_layer_helper import add_layer, remove_layer, list_layers
from gms_helpers.room_helper import duplicate_room, rename_room, delete_room, list_rooms
from gms_helpers.room_instance_helper import add_instance, remove_instance, list_instances

def handle_room_layer_add(args):
    return add_layer(args.room, args.name, args.layer_type, getattr(args, 'depth', 0))

def handle_room_layer_remove(args):
    return remove_layer(args.room, args.name)

def handle_room_layer_list(args):
    return list_layers(args.room)

def handle_room_duplicate(args):
    return duplicate_room(args.source_room, args.new_name)

def handle_room_rename(args):
    return rename_room(args.room_name, args.new_name)

def handle_room_delete(args):
    return delete_room(args.room_name, getattr(args, 'dry_run', False))

def handle_room_list(args):
    return list_rooms(getattr(args, 'verbose', False))

def handle_room_instance_add(args):
    return add_instance(args.room, args.object, args.x, args.y, getattr(args, 'layer', 'Instances'))

def handle_room_instance_remove(args):
    return remove_instance(args.room, args.instance_id)

def handle_room_instance_list(args):
    return list_instances(args.room, getattr(args, 'layer', None))
