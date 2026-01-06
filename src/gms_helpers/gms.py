#!/usr/bin/env python3
"""
GameMaker Studio Master CLI
Unified interface for all GameMaker development tools.
"""

import argparse
import sys
import os

# Import utilities for directory validation
from .utils import validate_working_directory, resolve_project_directory
from .exceptions import GMSError

def create_parser():
    """Create the master argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog='gms',
        description='GameMaker Studio Development Tools',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gms asset create script my_function --parent-path "folders/Scripts.yy"
  gms event add o_player create
  gms workflow duplicate scripts/old.yy new_script
  gms room layer add r_level background my_bg
  gms maintenance auto --fix --verbose
  gms run start --output-location temp     # Use IDE-style temp directory (default)
  gms run start --output-location project  # Use classic output folder in project
        """
    )
    
    # Global options
    parser.add_argument('--version', action='version', version='GMS Tools 2.0')
    parser.add_argument('--project-root', default='.', help='Project root directory (directory containing .yyp, or repo root containing gamemaker/)')
    
    # Create subcommand parsers
    subparsers = parser.add_subparsers(dest='category', help='Tool categories')
    subparsers.required = True
    
    # Add subcommand groups
    setup_asset_commands(subparsers)
    setup_event_commands(subparsers)
    setup_workflow_commands(subparsers)
    setup_room_commands(subparsers)
    setup_maintenance_commands(subparsers)
    setup_runner_commands(subparsers)
    setup_diagnostics_commands(subparsers)
    setup_symbol_commands(subparsers)
    
    return parser

def setup_diagnostics_commands(subparsers):
    """Set up diagnostics commands."""
    parser = subparsers.add_parser('diagnostics', help='Run project diagnostics')
    parser.add_argument('--depth', default='quick', choices=['quick', 'deep'], 
                              help='Search depth (default: quick)')
    parser.add_argument('--include-info', action='store_true', help='Include info-level diagnostics')
    parser.set_defaults(func=handle_diagnostics)

def setup_asset_commands(subparsers):
    """Set up asset management commands."""
    asset_parser = subparsers.add_parser('asset', help='Create and manage assets')
    asset_subparsers = asset_parser.add_subparsers(dest='asset_action', help='Asset actions')
    asset_subparsers.required = True
    
    # Asset creation
    create_parser = asset_subparsers.add_parser('create', help='Create new assets')
    create_subparsers = create_parser.add_subparsers(dest='asset_type', help='Asset type to create')
    create_subparsers.required = True
    
    # Add all asset type parsers
    setup_script_parser(create_subparsers)
    setup_object_parser(create_subparsers)
    setup_sprite_parser(create_subparsers)
    setup_room_parser(create_subparsers)
    setup_folder_parser(create_subparsers)
    setup_font_parser(create_subparsers)
    setup_shader_parser(create_subparsers)
    setup_animcurve_parser(create_subparsers)
    setup_sound_parser(create_subparsers)
    setup_path_parser(create_subparsers)
    setup_tileset_parser(create_subparsers)
    setup_timeline_parser(create_subparsers)
    setup_sequence_parser(create_subparsers)
    setup_note_parser(create_subparsers)
    
    # Asset deletion
    delete_parser = asset_subparsers.add_parser('delete', help='Delete assets')
    delete_parser.add_argument('asset_type', choices=['script', 'object', 'sprite', 'room', 'folder', 'font', 'shader', 'animcurve', 'sound', 'path', 'tileset', 'timeline', 'sequence', 'note'], help='Type of asset to delete')
    delete_parser.add_argument('name', help='Name of asset to delete')
    delete_parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without making changes')
    delete_parser.set_defaults(func=handle_asset_delete)

def setup_script_parser(subparsers):
    """Set up script creation parser."""
    parser = subparsers.add_parser('script', help='Create a script asset')
    parser.add_argument('name', help='Script name (snake_case or PascalCase with --constructor)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path (e.g. "folders/Scripts.yy"). If omitted, asset is created at project root.',
    )
    parser.add_argument('--constructor', action='store_true', help='Create a constructor script (allows PascalCase naming)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='script')

def setup_object_parser(subparsers):
    """Set up object creation parser."""
    parser = subparsers.add_parser('object', help='Create an object asset')
    parser.add_argument('name', help='Object name (o_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path (e.g. "folders/Objects.yy"). If omitted, asset is created at project root.',
    )
    parser.add_argument('--sprite-id', help='Sprite resource ID')
    parser.add_argument('--parent-object', help='Parent object name (for inheritance)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='object')

def setup_sprite_parser(subparsers):
    """Set up sprite creation parser."""
    parser = subparsers.add_parser('sprite', help='Create a sprite asset')
    parser.add_argument('name', help='Sprite name (spr_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path (e.g. "folders/Sprites.yy"). If omitted, asset is created at project root.',
    )
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='sprite')

def setup_room_parser(subparsers):
    """Set up room creation parser."""
    parser = subparsers.add_parser('room', help='Create a room asset')
    parser.add_argument('name', help='Room name (r_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path (e.g. "folders/Rooms.yy"). If omitted, asset is created at project root.',
    )
    parser.add_argument('--width', type=int, default=1024, help='Room width (default: 1024)')
    parser.add_argument('--height', type=int, default=768, help='Room height (default: 768)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='room')

def setup_folder_parser(subparsers):
    """Set up folder creation parser."""
    parser = subparsers.add_parser('folder', help='Create a folder asset')
    parser.add_argument('name', help='Folder name')
    parser.add_argument('--path', required=True, help='Folder path (e.g., "folders/My Folder.yy")')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='folder')

def setup_font_parser(subparsers):
    """Set up font creation parser."""
    parser = subparsers.add_parser('font', help='Create a font asset')
    parser.add_argument('name', help='Font name (fnt_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path (e.g. "folders/Fonts.yy"). If omitted, asset is created at project root.',
    )
    parser.add_argument('--font-name', default='Arial', help='Font family name (default: Arial)')
    parser.add_argument('--size', type=int, default=12, help='Font size (default: 12)')
    parser.add_argument('--bold', action='store_true', help='Make font bold')
    parser.add_argument('--italic', action='store_true', help='Make font italic')
    parser.add_argument('--aa-level', type=int, default=1, choices=[0, 1, 2, 3], help='Anti-aliasing level (0-3, default: 1)')
    parser.add_argument('--uses-sdf', action=argparse.BooleanOptionalAction, default=True, help='Use SDF rendering (default: True)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='font')

def setup_shader_parser(subparsers):
    """Set up shader creation parser."""
    parser = subparsers.add_parser('shader', help='Create a shader asset')
    parser.add_argument('name', help='Shader name (sh_ or shader_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path (e.g. "folders/Shaders.yy"). If omitted, asset is created at project root.',
    )
    parser.add_argument('--shader-type', type=int, default=1, choices=[1, 2, 3, 4], 
                              help='Shader type: 1=GLSL ES, 2=GLSL, 3=HLSL 9, 4=HLSL 11 (default: 1)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='shader')

def setup_animcurve_parser(subparsers):
    """Set up animation curve creation parser."""
    parser = subparsers.add_parser('animcurve', help='Create an animation curve asset')
    parser.add_argument('name', help='Animation curve name (curve_ or ac_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path. If omitted, asset is created at project root.',
    )
    parser.add_argument('--curve-type', default='linear', 
                                  choices=['linear', 'smooth', 'ease_in', 'ease_out'],
                                  help='Curve type (default: linear)')
    parser.add_argument('--channel-name', default='curve', help='Channel name (default: curve)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='animcurve')

def setup_sound_parser(subparsers):
    """Set up sound creation parser."""
    parser = subparsers.add_parser('sound', help='Create a sound asset')
    parser.add_argument('name', help='Sound name (snd_ or sfx_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path. If omitted, asset is created at project root.',
    )
    parser.add_argument('--volume', type=float, default=1.0, help='Volume (0.0-1.0, default: 1.0)')
    parser.add_argument('--pitch', type=float, default=1.0, help='Pitch (default: 1.0)')
    parser.add_argument('--sound-type', type=int, default=0, choices=[0, 1, 2], 
                              help='Sound type: 0=Normal, 1=Background, 2=3D (default: 0)')
    parser.add_argument('--bitrate', type=int, default=128, help='Bitrate (default: 128)')
    parser.add_argument('--sample-rate', type=int, default=44100, help='Sample rate (default: 44100)')
    parser.add_argument('--format', type=int, default=0, choices=[0, 1, 2], 
                              help='Format: 0=OGG, 1=MP3, 2=WAV (default: 0)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='sound')

def setup_path_parser(subparsers):
    """Set up path creation parser."""
    parser = subparsers.add_parser('path', help='Create a path asset')
    parser.add_argument('name', help='Path name (pth_ or path_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path. If omitted, asset is created at project root.',
    )
    parser.add_argument('--closed', action='store_true', help='Make path closed (loops back to start)')
    parser.add_argument('--precision', type=int, default=4, help='Path precision (default: 4)')
    parser.add_argument('--path-type', default='straight', 
                            choices=['straight', 'smooth', 'circle'],
                            help='Path type (default: straight)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='path')

def setup_tileset_parser(subparsers):
    """Set up tileset creation parser."""
    parser = subparsers.add_parser('tileset', help='Create a tileset asset')
    parser.add_argument('name', help='Tileset name (ts_ or tile_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path. If omitted, asset is created at project root.',
    )
    parser.add_argument('--sprite-id', help='Sprite resource ID to use for tiles')
    parser.add_argument('--tile-width', type=int, default=32, help='Tile width (default: 32)')
    parser.add_argument('--tile-height', type=int, default=32, help='Tile height (default: 32)')
    parser.add_argument('--tile-xsep', type=int, default=0, help='Horizontal separation (default: 0)')
    parser.add_argument('--tile-ysep', type=int, default=0, help='Vertical separation (default: 0)')
    parser.add_argument('--tile-xoff', type=int, default=0, help='Horizontal offset (default: 0)')
    parser.add_argument('--tile-yoff', type=int, default=0, help='Vertical offset (default: 0)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='tileset')

def setup_timeline_parser(subparsers):
    """Set up timeline creation parser."""
    parser = subparsers.add_parser('timeline', help='Create a timeline asset')
    parser.add_argument('name', help='Timeline name (tl_ or timeline_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path. If omitted, asset is created at project root.',
    )
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='timeline')

def setup_sequence_parser(subparsers):
    """Set up sequence creation parser."""
    parser = subparsers.add_parser('sequence', help='Create a sequence asset')
    parser.add_argument('name', help='Sequence name (seq_ or sequence_ prefix)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path. If omitted, asset is created at project root.',
    )
    parser.add_argument('--length', type=float, default=60.0, help='Sequence length in frames (default: 60.0)')
    parser.add_argument('--playback-speed', type=float, default=30.0, help='Playback speed in FPS (default: 30.0)')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='sequence')

def setup_note_parser(subparsers):
    """Set up note creation parser."""
    parser = subparsers.add_parser('note', help='Create a note asset')
    parser.add_argument('name', help='Note name (letters, numbers, underscores, hyphens, spaces)')
    parser.add_argument(
        '--parent-path',
        default="",
        help='Optional parent folder path. If omitted, asset is created at project root.',
    )
    parser.add_argument('--content', help='Initial note content')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip pre/post validation')
    parser.add_argument('--no-auto-fix', action='store_true', help='Do not automatically fix issues')
    parser.add_argument('--maintenance-verbose', action=argparse.BooleanOptionalAction, default=True, help='Show verbose maintenance output')
    parser.set_defaults(func=handle_asset_create, asset_type='note')

def setup_event_commands(subparsers):
    """Set up event management commands."""
    event_parser = subparsers.add_parser('event', help='Manage object events')
    event_subparsers = event_parser.add_subparsers(dest='event_action', help='Event actions')
    event_subparsers.required = True
    
    # Add command
    add_parser = event_subparsers.add_parser('add', help='Add an event to an object')
    add_parser.add_argument('object', help='Object name (e.g., o_player)')
    add_parser.add_argument('event', help='Event specification (e.g., create, step:1)')
    add_parser.add_argument('--template', help='Template file to use for event content')
    add_parser.set_defaults(func=handle_event_add)
    
    # Remove command
    remove_parser = event_subparsers.add_parser('remove', help='Remove an event from an object')
    remove_parser.add_argument('object', help='Object name (e.g., o_player)')
    remove_parser.add_argument('event', help='Event specification (e.g., create, step:1)')
    remove_parser.add_argument('--keep-file', action='store_true', help='Keep the GML file (do not delete .gml)')
    remove_parser.set_defaults(func=handle_event_remove)
    
    # Duplicate command
    dup_parser = event_subparsers.add_parser('duplicate', help='Duplicate an event within an object')
    dup_parser.add_argument('object', help='Object name (e.g., o_player)')
    dup_parser.add_argument('source_event', help='Source event specification (e.g., step:0)')
    dup_parser.add_argument('target_num', type=int, help='Target event number')
    dup_parser.set_defaults(func=handle_event_duplicate)
    
    # List command
    list_parser = event_subparsers.add_parser('list', help='List all events for an object')
    list_parser.add_argument('object', help='Object name (e.g., o_player)')
    list_parser.set_defaults(func=handle_event_list)
    
    # Validate command
    validate_parser = event_subparsers.add_parser('validate', help='Validate object events')
    validate_parser.add_argument('object', help='Object name (e.g., o_player)')
    validate_parser.set_defaults(func=handle_event_validate)
    
    # Fix command
    fix_parser = event_subparsers.add_parser('fix', help='Fix object event issues')
    fix_parser.add_argument('object', help='Object name (e.g., o_player)')
    fix_parser.add_argument('--no-safe-mode', dest='safe_mode', action='store_false', 
                           help='Allow potentially destructive fixes (add orphan events)')
    fix_parser.set_defaults(func=handle_event_fix)

def setup_workflow_commands(subparsers):
    """Set up workflow commands."""
    workflow_parser = subparsers.add_parser('workflow', help='Asset workflow operations')
    workflow_subparsers = workflow_parser.add_subparsers(dest='workflow_action', help='Workflow actions')
    workflow_subparsers.required = True
    
    # Duplicate command
    dup_parser = workflow_subparsers.add_parser('duplicate', help='Duplicate an asset with new name')
    dup_parser.add_argument('asset_path', help='Asset .yy path relative to project root')
    dup_parser.add_argument('new_name', help='New asset name')
    dup_parser.add_argument('--yes', action='store_true', help='Skip confirmation prompts')
    dup_parser.set_defaults(func=handle_workflow_duplicate)
    
    # Rename command
    rename_parser = workflow_subparsers.add_parser('rename', help='Rename an asset')
    rename_parser.add_argument('asset_path', help='Asset .yy path relative to project root')
    rename_parser.add_argument('new_name', help='New asset name')
    rename_parser.set_defaults(func=handle_workflow_rename)
    
    # Delete command
    delete_parser = workflow_subparsers.add_parser('delete', help='Delete an asset')
    delete_parser.add_argument('asset_path', help='Asset .yy path relative to project root')
    delete_parser.add_argument('--dry-run', action='store_true', help='Preview without deleting')
    delete_parser.set_defaults(func=handle_workflow_delete)
    
    # Swap sprite command
    swap_parser = workflow_subparsers.add_parser('swap-sprite', help="Replace sprite's PNG source")
    swap_parser.add_argument('asset_path', help='Sprite .yy path relative to project root')
    swap_parser.add_argument('png', help='Path to replacement PNG file')
    swap_parser.set_defaults(func=handle_workflow_swap_sprite)

def setup_room_commands(subparsers):
    """Set up room management commands."""
    room_parser = subparsers.add_parser('room', help='Manage rooms, layers, and instances')
    room_subparsers = room_parser.add_subparsers(dest='room_category', help='Room management categories')
    room_subparsers.required = True
    
    # Standard room operations (duplicate, rename, delete, list)
    ops_parser = room_subparsers.add_parser('ops', help='Standard room operations')
    ops_subparsers = ops_parser.add_subparsers(dest='ops_action', help='Room operations')
    ops_subparsers.required = True
    
    # Duplicate room
    duplicate_parser = ops_subparsers.add_parser('duplicate', help='Duplicate an existing room')
    duplicate_parser.add_argument('source_room', help='Source room name (e.g., r_level_01)')
    duplicate_parser.add_argument('new_name', help='New room name (e.g., r_level_02)')
    duplicate_parser.set_defaults(func=handle_room_duplicate)
    
    # Rename room
    rename_parser = ops_subparsers.add_parser('rename', help='Rename an existing room')
    rename_parser.add_argument('room_name', help='Current room name (e.g., r_old_name)')
    rename_parser.add_argument('new_name', help='New room name (e.g., r_new_name)')
    rename_parser.set_defaults(func=handle_room_rename)
    
    # Delete room
    delete_parser = ops_subparsers.add_parser('delete', help='Delete a room')
    delete_parser.add_argument('room_name', help='Room name to delete (e.g., r_unused)')
    delete_parser.add_argument('--dry-run', action='store_true', help='Preview deletion without actually deleting')
    delete_parser.set_defaults(func=handle_room_delete)
    
    # List rooms
    list_parser = ops_subparsers.add_parser('list', help='List all rooms in the project')
    list_parser.add_argument('--verbose', action='store_true', help='Show detailed room information')
    list_parser.set_defaults(func=handle_room_list)
    
    # Layer management
    layer_parser = room_subparsers.add_parser('layer', help='Manage room layers')
    layer_subparsers = layer_parser.add_subparsers(dest='layer_action', help='Layer actions')
    layer_subparsers.required = True
    
    # Add layer
    layer_add_parser = layer_subparsers.add_parser('add', help='Add a layer to a room')
    layer_add_parser.add_argument('room_name', help='Room name (e.g., r_level)')
    # Accept some common synonyms/casing to reduce foot-guns in MCP usage.
    layer_add_parser.add_argument(
        'layer_type',
        type=lambda s: (s or "").strip().lower(),
        choices=['background', 'instance', 'instances', 'asset', 'tile', 'path', 'effect'],
        help='Layer type',
    )
    layer_add_parser.add_argument('layer_name', help='Layer name')
    layer_add_parser.add_argument('--depth', type=int, default=0, help='Layer depth (default: 0)')
    layer_add_parser.set_defaults(func=handle_room_layer_add)
    
    # Remove layer
    layer_remove_parser = layer_subparsers.add_parser('remove', help='Remove a layer from a room')
    layer_remove_parser.add_argument('room_name', help='Room name')
    layer_remove_parser.add_argument('layer_name', help='Layer name to remove')
    layer_remove_parser.set_defaults(func=handle_room_layer_remove)
    
    # List layers
    layer_list_parser = layer_subparsers.add_parser('list', help='List all layers in a room')
    layer_list_parser.add_argument('room_name', help='Room name')
    layer_list_parser.set_defaults(func=handle_room_layer_list)
    
    # Instance management
    instance_parser = room_subparsers.add_parser('instance', help='Manage object instances in rooms')
    instance_subparsers = instance_parser.add_subparsers(dest='instance_action', help='Instance actions')
    instance_subparsers.required = True
    
    # Add instance
    instance_add_parser = instance_subparsers.add_parser('add', help='Add object instance to room')
    instance_add_parser.add_argument('room_name', help='Room name')
    instance_add_parser.add_argument('object_name', help='Object name (e.g., o_player)')
    instance_add_parser.add_argument('x', type=float, help='X position')
    instance_add_parser.add_argument('y', type=float, help='Y position')
    instance_add_parser.add_argument('--layer', help='Layer name to place instance on')
    instance_add_parser.set_defaults(func=handle_room_instance_add)
    
    # Remove instance
    instance_remove_parser = instance_subparsers.add_parser('remove', help='Remove object instance from room')
    instance_remove_parser.add_argument('room_name', help='Room name')
    instance_remove_parser.add_argument('instance_id', help='Instance ID to remove')
    instance_remove_parser.set_defaults(func=handle_room_instance_remove)
    
    # List instances
    instance_list_parser = instance_subparsers.add_parser('list', help='List all instances in room')
    instance_list_parser.add_argument('room_name', help='Room name')
    instance_list_parser.set_defaults(func=handle_room_instance_list)

def setup_maintenance_commands(subparsers):
    """Set up maintenance commands."""
    maint_parser = subparsers.add_parser('maintenance', help='Project maintenance and validation')
    maint_subparsers = maint_parser.add_subparsers(dest='maintenance_action', help='Maintenance actions')
    maint_subparsers.required = True
    
    # Auto maintenance
    auto_parser = maint_subparsers.add_parser('auto', help='Run comprehensive auto-maintenance')
    auto_parser.add_argument('--fix', action='store_true', help='Automatically fix issues')
    auto_parser.add_argument('--verbose', action=argparse.BooleanOptionalAction, default=True, help='Show detailed output')
    auto_parser.set_defaults(func=handle_maintenance_auto)
    
    # Lint
    lint_parser = maint_subparsers.add_parser('lint', help='Check project for JSON errors and naming issues')
    lint_parser.add_argument('--fix', action='store_true', help='Automatically fix issues where possible')
    lint_parser.set_defaults(func=handle_maintenance_lint)
    
    # Validate JSON
    validate_json_parser = maint_subparsers.add_parser('validate-json', help='Validate JSON syntax in project files')
    validate_json_parser.set_defaults(func=handle_maintenance_validate_json)
    
    # List orphans
    orphans_parser = maint_subparsers.add_parser('list-orphans', help='Find orphaned and missing assets')
    orphans_parser.set_defaults(func=handle_maintenance_list_orphans)
    
    # Prune missing
    prune_parser = maint_subparsers.add_parser('prune-missing', help='Remove missing asset references from project file')
    prune_parser.add_argument('--dry-run', action='store_true', help='Show what would be removed without making changes')
    prune_parser.set_defaults(func=handle_maintenance_prune_missing)
    
    # Validate paths
    validate_parser = maint_subparsers.add_parser('validate-paths', help='Check that all folder paths referenced in assets exist')
    validate_parser.add_argument('--strict-disk-check', action='store_true', help='Also check that folder .yy files exist on disk')
    validate_parser.add_argument('--include-parent-folders', action='store_true', help='Show parent folders as orphaned even if they have subfolders with assets')
    validate_parser.set_defaults(func=handle_maintenance_validate_paths)
    
    # Dedupe resources
    dedupe_parser = maint_subparsers.add_parser('dedupe-resources', help='Remove duplicate resource entries from project file')
    dedupe_parser.add_argument('--auto', action='store_true', help='Automatically keep first occurrence of each duplicate')
    dedupe_parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without making changes')
    dedupe_parser.set_defaults(func=handle_maintenance_dedupe_resources)
    
    # Sync events
    sync_events_parser = maint_subparsers.add_parser('sync-events', help='Synchronize object events')
    sync_events_parser.add_argument('--fix', action='store_true', help='Actually fix issues (default is dry-run)')
    sync_events_parser.add_argument('--object', help='Sync specific object only')
    sync_events_parser.set_defaults(func=handle_maintenance_sync_events)
    
    # Clean old files
    clean_old_parser = maint_subparsers.add_parser('clean-old-files', help='Remove .old.yy backup files from project')
    clean_old_parser.add_argument('--delete', action='store_true', help='Actually delete files (default is dry-run)')
    clean_old_parser.set_defaults(func=handle_maintenance_clean_old_files)
    
    # Clean orphans
    clean_orphans_parser = maint_subparsers.add_parser('clean-orphans', help='Remove orphaned asset files from project')
    clean_orphans_parser.add_argument('--delete', action='store_true', help='Actually delete files (default is dry-run)')
    clean_orphans_parser.add_argument('--skip-types', nargs='*', default=['folder'], help='Asset types to skip during cleanup')
    clean_orphans_parser.set_defaults(func=handle_maintenance_clean_orphans)
    
    # Health check
    health_parser = maint_subparsers.add_parser('health', help='Perform environment health check')
    health_parser.set_defaults(func=handle_maintenance_health)
    
    # Fix issues
    fix_issues_parser = maint_subparsers.add_parser('fix-issues', help='Run comprehensive auto-maintenance with fixes enabled')
    fix_issues_parser.add_argument('--verbose', action='store_true', help='Show detailed progress and reports')
    fix_issues_parser.set_defaults(func=handle_maintenance_fix_issues)

def setup_runner_commands(subparsers):
    """Set up runner commands."""
    runner_parser = subparsers.add_parser('run', help='Compile and run GameMaker projects')
    runner_subparsers = runner_parser.add_subparsers(dest='runner_action', help='Runner actions')
    runner_subparsers.required = True
    
    # Compile command
    compile_parser = runner_subparsers.add_parser('compile', help='Compile the GameMaker project')
    compile_parser.add_argument('--platform', default='Windows', 
                               choices=['Windows', 'HTML5', 'macOS', 'Linux', 'Android', 'iOS'],
                               help='Target platform (default: Windows)')
    compile_parser.add_argument('--runtime', default='VM', choices=['VM', 'YYC'],
                               help='Runtime type (default: VM)')
    compile_parser.add_argument('--runtime-version', help='Specific runtime version to use (e.g. 2024.1100.0.625)')
    compile_parser.set_defaults(func=handle_runner_compile)
    
    # Run command 
    run_parser = runner_subparsers.add_parser('start', help='Compile and run the GameMaker project')
    run_parser.add_argument('--platform', default='Windows',
                           choices=['Windows', 'HTML5', 'macOS', 'Linux', 'Android', 'iOS'], 
                           help='Target platform (default: Windows)')
    run_parser.add_argument('--runtime', default='VM', choices=['VM', 'YYC'],
                           help='Runtime type (default: VM)')
    run_parser.add_argument('--runtime-version', help='Specific runtime version to use')
    run_parser.add_argument('--background', action='store_true', 
                           help='Run in background (don\'t capture output)')
    run_parser.add_argument('--output-location', default='temp', choices=['temp', 'project'],
                           help='Output location: temp (IDE-style, AppData) or project (classic output folder) (default: temp)')
    run_parser.set_defaults(func=handle_runner_run)
    
    # Stop command
    stop_parser = runner_subparsers.add_parser('stop', help='Stop the running game')
    stop_parser.set_defaults(func=handle_runner_stop)
    
    # Status command
    status_parser = runner_subparsers.add_parser('status', help='Check if game is running')
    status_parser.set_defaults(func=handle_runner_status)


def setup_symbol_commands(subparsers):
    """Set up symbol/code intelligence commands."""
    symbol_parser = subparsers.add_parser('symbol', help='GML symbol indexing and code intelligence')
    symbol_subparsers = symbol_parser.add_subparsers(dest='symbol_action', help='Symbol actions')
    symbol_subparsers.required = True
    
    # Build index command
    build_parser = symbol_subparsers.add_parser('build', help='Build or rebuild the GML symbol index')
    build_parser.add_argument('--force', action='store_true', help='Force rebuild (ignore cache)')
    build_parser.set_defaults(func=handle_build_index)
    
    # Find definition command
    def_parser = symbol_subparsers.add_parser('find-definition', help='Find definition(s) of a symbol')
    def_parser.add_argument('symbol_name', help='Name of symbol to find')
    def_parser.set_defaults(func=handle_find_definition)
    
    # Find references command
    ref_parser = symbol_subparsers.add_parser('find-references', help='Find all references to a symbol')
    ref_parser.add_argument('symbol_name', help='Name of symbol to find references for')
    ref_parser.add_argument('--max-results', type=int, default=50, help='Maximum number of results (default: 50)')
    ref_parser.set_defaults(func=handle_find_references)
    
    # List symbols command
    list_parser = symbol_subparsers.add_parser('list', help='List all symbols in the project')
    list_parser.add_argument('--kind', choices=['function', 'enum', 'macro', 'globalvar', 'constructor'],
                            help='Filter by symbol kind')
    list_parser.add_argument('--name-filter', help='Filter symbols by name (case-insensitive substring)')
    list_parser.add_argument('--file-filter', help='Filter symbols by file path (case-insensitive substring)')
    list_parser.add_argument('--max-results', type=int, default=100, help='Maximum number of results (default: 100)')
    list_parser.set_defaults(func=handle_list_symbols)

# Import command handlers
from .commands.asset_commands import handle_asset_create, handle_asset_delete
from .commands.diagnostics_commands import handle_diagnostics
from .commands.event_commands import (
    handle_event_add, handle_event_remove, handle_event_duplicate,
    handle_event_list, handle_event_validate, handle_event_fix
)
from .commands.workflow_commands import (
    handle_workflow_duplicate, handle_workflow_rename,
    handle_workflow_delete, handle_workflow_swap_sprite
)
from .commands.room_commands import (
    handle_room_layer_add, handle_room_layer_remove, handle_room_layer_list,
    handle_room_duplicate, handle_room_rename, handle_room_delete, handle_room_list,
    handle_room_instance_add, handle_room_instance_remove, handle_room_instance_list
)
from .commands.maintenance_commands import (
    handle_maintenance_auto, handle_maintenance_lint, handle_maintenance_validate_json,
    handle_maintenance_list_orphans, handle_maintenance_prune_missing, handle_maintenance_validate_paths,
    handle_maintenance_dedupe_resources, handle_maintenance_sync_events, handle_maintenance_clean_old_files,
    handle_maintenance_clean_orphans, handle_maintenance_fix_issues, handle_maintenance_health
)
from .commands.runner_commands import (
    handle_runner_compile, handle_runner_run, handle_runner_stop, handle_runner_status
)
from .commands.symbol_commands import (
    handle_build_index, handle_find_definition, handle_find_references, handle_list_symbols
)



def main():
    """Main entry point for the master CLI."""
    parser = create_parser()

    # Allow help/version from any directory without requiring project discovery.
    if any(a in ("-h", "--help", "--version") for a in sys.argv[1:]):
        try:
            parser.parse_args()
            return True
        except SystemExit as e:
            return int(getattr(e, "code", 1) or 0) == 0

    # Resolve project directory before parsing full args (subparsers are required).
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--project-root", default=None)
    pre_args, _ = pre_parser.parse_known_args(sys.argv[1:])

    try:
        project_dir = resolve_project_directory(pre_args.project_root)
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

    # Run the CLI from the resolved directory so all helper modules can keep using relative paths.
    os.chdir(project_dir)

    # Now validate and parse full args.
    try:
        validate_working_directory()
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        raise
        
    args = parser.parse_args()

    # Normalize project_root after chdir so downstream handlers resolve correctly.
    # (If the user passed --project-root gamemaker from repo root, leaving it as-is would resolve to gamemaker/gamemaker)
    args.project_root = '.'
    
    # Route to appropriate handler
    try:
        result = args.func(args)
        if hasattr(result, "success"):
            return result.success
        return result
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        raise
    except KeyboardInterrupt:
        print("\n[WARN]  Operation cancelled by user")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except GMSError as e:
        sys.exit(e.exit_code)
    except Exception:
        sys.exit(1)
