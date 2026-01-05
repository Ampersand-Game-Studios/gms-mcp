"""Asset management command implementations."""

import sys
from pathlib import Path

# Import existing functionality
# Ensure src is on Python path so gms_helpers can be imported
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import all the create_* functions from asset_helper.py
from gms_helpers.asset_helper import (
    create_script, create_object, create_sprite, create_room,
    create_folder, create_font, create_shader, create_animcurve,
    create_sound, create_path, create_tileset, create_timeline,
    create_sequence, create_note, delete_asset
)

def handle_asset_create(args):
    """Route asset creation to appropriate function."""
    asset_type = args.asset_type

    # Map asset types to functions
    creators = {
        'script': create_script,
        'object': create_object,
        'sprite': create_sprite,
        'room': create_room,
        'folder': create_folder,
        'font': create_font,
        'shader': create_shader,
        'animcurve': create_animcurve,
        'sound': create_sound,
        'path': create_path,
        'tileset': create_tileset,
        'timeline': create_timeline,
        'sequence': create_sequence,
        'note': create_note
    }

    if asset_type not in creators:
        print(f"[ERROR] Unknown asset type: {asset_type}")
        return False

    return creators[asset_type](args)

def handle_asset_delete(args):
    """Handle asset deletion."""
    return delete_asset(args)
