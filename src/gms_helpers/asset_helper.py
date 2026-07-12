#!/usr/bin/env python3
"""Public facade for GameMaker asset helper commands."""

from __future__ import annotations

import sys

from .asset_cli import (
    GameMakerContextError,
    create_animcurve,
    create_folder,
    create_font,
    create_note,
    create_object,
    create_path,
    create_room,
    create_script,
    create_sequence,
    create_shader,
    create_sound,
    create_sprite,
    create_tileset,
    create_timeline,
    delete_asset,
    list_folders_command,
    main,
    maint_audit_command,
    maint_clean_old_files_command,
    maint_clean_orphans_command,
    maint_dedupe_resources_command,
    maint_fix_issues_command,
    maint_lint_command,
    maint_list_orphans_command,
    maint_prune_missing_command,
    maint_purge_command,
    maint_sync_events_command,
    maint_test_command,
    maint_validate_json_command,
    maint_validate_paths_command,
    remove_folder_command,
    validate_asset_directory_structure,
    validate_gamemaker_context,
)
from .asset_types import (
    AnimCurveAsset,
    FolderAsset,
    FontAsset,
    NoteAsset,
    ObjectAsset,
    PathAsset,
    RoomAsset,
    ScriptAsset,
    SequenceAsset,
    ShaderAsset,
    SoundAsset,
    SpriteAsset,
    TileSetAsset,
    TimelineAsset,
)
from .exceptions import GMSError

__all__ = [
    "AnimCurveAsset",
    "FolderAsset",
    "FontAsset",
    "GMSError",
    "GameMakerContextError",
    "NoteAsset",
    "ObjectAsset",
    "PathAsset",
    "RoomAsset",
    "ScriptAsset",
    "SequenceAsset",
    "ShaderAsset",
    "SoundAsset",
    "SpriteAsset",
    "TileSetAsset",
    "TimelineAsset",
    "create_animcurve",
    "create_folder",
    "create_font",
    "create_note",
    "create_object",
    "create_path",
    "create_room",
    "create_script",
    "create_sequence",
    "create_shader",
    "create_sound",
    "create_sprite",
    "create_tileset",
    "create_timeline",
    "delete_asset",
    "list_folders_command",
    "main",
    "maint_audit_command",
    "maint_clean_old_files_command",
    "maint_clean_orphans_command",
    "maint_dedupe_resources_command",
    "maint_fix_issues_command",
    "maint_lint_command",
    "maint_list_orphans_command",
    "maint_prune_missing_command",
    "maint_purge_command",
    "maint_sync_events_command",
    "maint_test_command",
    "maint_validate_json_command",
    "maint_validate_paths_command",
    "remove_folder_command",
    "validate_asset_directory_structure",
    "validate_gamemaker_context",
]

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except GMSError as e:
        sys.exit(e.exit_code)
    except Exception:
        sys.exit(1)
