from __future__ import annotations

import argparse

from ..exceptions import GMSError
from ..utils import validate_working_directory
from .create import (
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
)
from .delete import delete_asset
from .maintenance import (
    list_folders_command,
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
)


def main():
    parser = argparse.ArgumentParser(
        description="GameMaker Studio Asset Helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s script my_function --parent-path "folders/Scripts.yy"
  %(prog)s object o_player --parent-path "folders/Objects.yy" --sprite-id "spr_player"
  %(prog)s sprite spr_enemy --parent-path "folders/Sprites.yy"
  %(prog)s room r_level_1 --parent-path "folders/Rooms.yy" --width 1920 --height 1080
  %(prog)s folder "My Scripts" --path "folders/My Scripts.yy"
  %(prog)s font fnt_ui_title --parent-path "folders/Fonts.yy" --font-name "Arial" --size 24 --bold
  %(prog)s shader sh_blur --parent-path "folders/Shaders.yy" --shader-type 1
  %(prog)s animcurve curve_ease_bounce --parent-path "folders/Curves.yy" --curve-type ease_in
  %(prog)s sound snd_explosion --parent-path "folders/Audio.yy" --volume 0.8 --sound-type 0
  %(prog)s path pth_enemy_patrol --parent-path "folders/Paths.yy" --path-type circle --closed
  %(prog)s tileset ts_grass --parent-path "folders/Tilesets.yy" --sprite-id "spr_grass_tiles" --tile-width 32 --tile-height 32
  %(prog)s timeline tl_cutscene --parent-path "folders/Timelines.yy"
  %(prog)s sequence seq_intro --parent-path "folders/Sequences.yy" --length 120 --playback-speed 60
  %(prog)s note "Game Design Notes" --parent-path "folders/Documentation.yy" --content "Initial game design notes"
  
Auto-Maintenance:
  All asset creation/modification operations now automatically run maintenance checks.
  Use --skip-maintenance to disable (not recommended).
  Use --no-auto-fix to prevent automatic issue fixing.
  
Maintenance Commands:
  %(prog)s maint lint                    # Check project for issues
  %(prog)s maint validate-json           # Validate JSON syntax in project files
  %(prog)s maint list-orphans            # Find orphaned assets
  %(prog)s maint prune-missing           # Remove missing asset references
  %(prog)s maint validate-paths                    # Check folder path references (.yyp-based)
  %(prog)s maint validate-paths --strict-disk-check # Also check folder .yy files exist on disk
  %(prog)s maint validate-paths --include-parent-folders # Include parent folders in orphan detection
  %(prog)s maint dedupe-resources        # Remove duplicate resource entries (interactive)
  %(prog)s maint dedupe-resources --auto # Remove duplicate resource entries (automatic)
  %(prog)s maint list-folders            # List all folders in project
  %(prog)s maint remove-folder "folders/Test.yy" # Remove folder from project
  %(prog)s maint remove-folder "folders/Test.yy" --force # Force remove even with assets
        """,
    )

    # Global options for auto-maintenance
    parser.add_argument(
        "--skip-maintenance", action="store_true", help="Skip automatic maintenance operations (not recommended)"
    )
    parser.add_argument(
        "--maintenance-verbose",
        action="store_true",
        default=True,
        help="Show verbose maintenance output (default: True)",
    )
    parser.add_argument("--no-auto-fix", action="store_true", help="Do not automatically fix issues during maintenance")

    subparsers = parser.add_subparsers(dest="command", help="Asset type to create or maintenance command")
    subparsers.required = True

    # Asset creation commands
    # Script command
    script_parser = subparsers.add_parser("script", help="Create a script asset")
    script_parser.add_argument("name", help="Script name (snake_case or PascalCase with --constructor)")
    script_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    script_parser.add_argument(
        "--constructor", action="store_true", help="Create a constructor script (allows PascalCase naming)"
    )
    script_parser.set_defaults(func=create_script)

    # Object command
    object_parser = subparsers.add_parser("object", help="Create an object asset")
    object_parser.add_argument("name", help="Object name (o_ prefix)")
    object_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    object_parser.add_argument("--sprite-id", help="Sprite resource ID")
    object_parser.add_argument("--parent-object", help="Parent object name (for inheritance)")
    object_parser.set_defaults(func=create_object)

    # Sprite command
    sprite_parser = subparsers.add_parser("sprite", help="Create a sprite asset")
    sprite_parser.add_argument("name", help="Sprite name (spr_ prefix)")
    sprite_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    sprite_parser.set_defaults(func=create_sprite)

    # Room command
    room_parser = subparsers.add_parser("room", help="Create a room asset")
    room_parser.add_argument("name", help="Room name (r_ prefix)")
    room_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    room_parser.add_argument("--width", type=int, default=1024, help="Room width (default: 1024)")
    room_parser.add_argument("--height", type=int, default=768, help="Room height (default: 768)")
    room_parser.set_defaults(func=create_room)

    # Folder command
    folder_parser = subparsers.add_parser("folder", help="Create a folder asset")
    folder_parser.add_argument("name", help="Folder name")
    folder_parser.add_argument("--path", required=True, help='Folder path (e.g., "folders/My Folder.yy")')
    folder_parser.set_defaults(func=create_folder)

    # Font command
    font_parser = subparsers.add_parser("font", help="Create a font asset")
    font_parser.add_argument("name", help="Font name (fnt_ prefix)")
    font_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    font_parser.add_argument("--font-name", default="Arial", help="Font family name (default: Arial)")
    font_parser.add_argument("--size", type=int, default=12, help="Font size (default: 12)")
    font_parser.add_argument("--bold", action="store_true", help="Make font bold")
    font_parser.add_argument("--italic", action="store_true", help="Make font italic")
    font_parser.add_argument(
        "--aa-level", type=int, default=1, choices=[0, 1, 2, 3], help="Anti-aliasing level (0-3, default: 1)"
    )
    font_parser.add_argument("--uses-sdf", action="store_true", default=True, help="Use SDF rendering (default: True)")
    font_parser.set_defaults(func=create_font)

    # Shader command
    shader_parser = subparsers.add_parser("shader", help="Create a shader asset")
    shader_parser.add_argument("name", help="Shader name (sh_ or shader_ prefix)")
    shader_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    shader_parser.add_argument(
        "--shader-type",
        type=int,
        default=1,
        choices=[1, 2, 3, 4],
        help="Shader type: 1=GLSL ES, 2=GLSL, 3=HLSL 9, 4=HLSL 11 (default: 1)",
    )
    shader_parser.set_defaults(func=create_shader)

    # Animation curve command
    animcurve_parser = subparsers.add_parser("animcurve", help="Create an animation curve asset")
    animcurve_parser.add_argument("name", help="Animation curve name (curve_ or ac_ prefix)")
    animcurve_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    animcurve_parser.add_argument(
        "--curve-type",
        default="linear",
        choices=["linear", "smooth", "ease_in", "ease_out"],
        help="Curve type (default: linear)",
    )
    animcurve_parser.add_argument("--channel-name", default="curve", help="Channel name (default: curve)")
    animcurve_parser.set_defaults(func=create_animcurve)

    # Sound command
    sound_parser = subparsers.add_parser("sound", help="Create a sound asset")
    sound_parser.add_argument("name", help="Sound name (snd_ or sfx_ prefix)")
    sound_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    sound_parser.add_argument("--volume", type=float, default=1.0, help="Volume (0.0-1.0, default: 1.0)")
    sound_parser.add_argument("--pitch", type=float, default=1.0, help="Pitch (default: 1.0)")
    sound_parser.add_argument(
        "--sound-type",
        type=int,
        default=0,
        choices=[0, 1, 2],
        help="Sound type: 0=Normal, 1=Background, 2=3D (default: 0)",
    )
    sound_parser.add_argument("--bitrate", type=int, default=128, help="Bitrate (default: 128)")
    sound_parser.add_argument("--sample-rate", type=int, default=44100, help="Sample rate (default: 44100)")
    sound_parser.add_argument(
        "--format", type=int, default=2, choices=[0, 1, 2], help="Preferred format: 0=OGG, 1=MP3, 2=WAV (default: 2)"
    )
    sound_parser.set_defaults(func=create_sound)

    # Path command
    path_parser = subparsers.add_parser("path", help="Create a path asset")
    path_parser.add_argument("name", help="Path name (pth_ or path_ prefix)")
    path_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    path_parser.add_argument("--closed", action="store_true", help="Make path closed (loops back to start)")
    path_parser.add_argument("--precision", type=int, default=4, help="Path precision (default: 4)")
    path_parser.add_argument(
        "--path-type",
        default="straight",
        choices=["straight", "smooth", "circle"],
        help="Path type (default: straight)",
    )
    path_parser.set_defaults(func=create_path)

    # Tileset command
    tileset_parser = subparsers.add_parser("tileset", help="Create a tileset asset")
    tileset_parser.add_argument("name", help="Tileset name (ts_ or tile_ prefix)")
    tileset_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    tileset_parser.add_argument("--sprite-id", help="Sprite resource ID to use for tiles")
    tileset_parser.add_argument("--tile-width", type=int, default=32, help="Tile width (default: 32)")
    tileset_parser.add_argument("--tile-height", type=int, default=32, help="Tile height (default: 32)")
    tileset_parser.add_argument("--tile-xsep", type=int, default=0, help="Horizontal separation (default: 0)")
    tileset_parser.add_argument("--tile-ysep", type=int, default=0, help="Vertical separation (default: 0)")
    tileset_parser.add_argument("--tile-xoff", type=int, default=0, help="Horizontal offset (default: 0)")
    tileset_parser.add_argument("--tile-yoff", type=int, default=0, help="Vertical offset (default: 0)")
    tileset_parser.set_defaults(func=create_tileset)

    # Timeline command
    timeline_parser = subparsers.add_parser("timeline", help="Create a timeline asset")
    timeline_parser.add_argument("name", help="Timeline name (tl_ or timeline_ prefix)")
    timeline_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    timeline_parser.set_defaults(func=create_timeline)

    # Sequence command
    sequence_parser = subparsers.add_parser("sequence", help="Create a sequence asset")
    sequence_parser.add_argument("name", help="Sequence name (seq_ or sequence_ prefix)")
    sequence_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    sequence_parser.add_argument("--length", type=float, default=60.0, help="Sequence length in frames (default: 60.0)")
    sequence_parser.add_argument(
        "--playback-speed", type=float, default=30.0, help="Playback speed in FPS (default: 30.0)"
    )
    sequence_parser.set_defaults(func=create_sequence)

    # Note command
    note_parser = subparsers.add_parser("note", help="Create a note asset")
    note_parser.add_argument("name", help="Note name (letters, numbers, underscores, hyphens, spaces)")
    note_parser.add_argument("--parent-path", default="", help="Optional parent folder path")
    note_parser.add_argument("--content", help="Initial note content")
    note_parser.set_defaults(func=create_note)

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete an asset")
    delete_parser.add_argument(
        "asset_type",
        choices=[
            "script",
            "object",
            "sprite",
            "room",
            "folder",
            "font",
            "shader",
            "animcurve",
            "sound",
            "path",
            "tileset",
            "timeline",
            "sequence",
            "note",
        ],
        help="Asset type to delete",
    )
    delete_parser.add_argument("name", help="Asset name to delete")
    delete_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be deleted without making changes"
    )
    delete_parser.set_defaults(func=delete_asset)

    # Maintenance commands
    maint_parser = subparsers.add_parser("maint", help="Asset maintenance commands")
    maint_subparsers = maint_parser.add_subparsers(dest="maint_command", help="Maintenance operation")
    maint_subparsers.required = True

    # Lint command
    lint_parser = maint_subparsers.add_parser("lint", help="Check project for JSON errors and naming issues")
    lint_parser.add_argument("--fix", action="store_true", help="Automatically fix issues where possible")
    lint_parser.set_defaults(func=maint_lint_command)

    # Validate-json command
    validate_json_parser = maint_subparsers.add_parser("validate-json", help="Validate JSON syntax in project files")
    validate_json_parser.set_defaults(func=maint_validate_json_command)

    # List-orphans command
    orphans_parser = maint_subparsers.add_parser("list-orphans", help="Find orphaned and missing assets")
    orphans_parser.set_defaults(func=maint_list_orphans_command)

    # Prune-missing command
    prune_parser = maint_subparsers.add_parser(
        "prune-missing", help="Remove missing asset references from project file"
    )
    prune_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be removed without making changes"
    )
    prune_parser.set_defaults(func=maint_prune_missing_command)

    # Validate-paths command
    validate_parser = maint_subparsers.add_parser(
        "validate-paths", help="Check that all folder paths referenced in assets exist"
    )
    validate_parser.add_argument(
        "--strict-disk-check",
        action="store_true",
        help="Also check that folder .yy files exist on disk (legacy behavior)",
    )
    validate_parser.add_argument(
        "--include-parent-folders",
        action="store_true",
        help="Show parent folders as orphaned even if they have subfolders with assets",
    )
    validate_parser.set_defaults(func=maint_validate_paths_command)

    # Dedupe-resources command
    dedupe_parser = maint_subparsers.add_parser(
        "dedupe-resources", help="Remove duplicate resource entries from project file"
    )
    dedupe_parser.add_argument(
        "--auto", action="store_true", help="Automatically keep first occurrence of each duplicate (non-interactive)"
    )
    dedupe_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be changed without making changes"
    )
    dedupe_parser.set_defaults(func=maint_dedupe_resources_command)

    # Sync-events command
    sync_events_parser = maint_subparsers.add_parser(
        "sync-events", help="Synchronize object events (fix orphaned/missing GML files)"
    )
    sync_events_parser.add_argument("--fix", action="store_true", help="Actually fix issues (default is dry-run)")
    sync_events_parser.add_argument("--object", help="Sync specific object only (e.g., o_player)")
    sync_events_parser.set_defaults(func=maint_sync_events_command)

    # Clean-old-files command
    clean_old_parser = maint_subparsers.add_parser("clean-old-files", help="Remove .old.yy backup files from project")
    clean_old_parser.add_argument("--delete", action="store_true", help="Actually delete files (default is dry-run)")
    clean_old_parser.set_defaults(func=maint_clean_old_files_command)

    # Clean-orphans command
    clean_orphans_parser = maint_subparsers.add_parser("clean-orphans", help="Remove orphaned asset files from project")
    clean_orphans_parser.add_argument(
        "--delete", action="store_true", help="Actually delete files (default is dry-run)"
    )
    clean_orphans_parser.add_argument(
        "--skip-types", nargs="*", default=["folder"], help="Asset types to skip during cleanup (default: folder)"
    )
    clean_orphans_parser.set_defaults(func=maint_clean_orphans_command)

    # Fix-issues command (comprehensive auto-maintenance)
    fix_issues_parser = maint_subparsers.add_parser(
        "fix-issues", help="Run comprehensive auto-maintenance with fixes enabled"
    )
    fix_issues_parser.add_argument("--verbose", action="store_true", help="Show detailed progress and reports")
    fix_issues_parser.set_defaults(func=maint_fix_issues_command)

    # Audit command (new robust analysis)
    audit_parser = maint_subparsers.add_parser("audit", help="Run comprehensive asset analysis and generate report")
    audit_parser.add_argument(
        "--output",
        default="maintenance_report.json",
        help="Output file for audit report (default: maintenance_report.json)",
    )
    audit_parser.set_defaults(func=maint_audit_command)

    # Purge command (safe deletion with trash folder)
    purge_parser = maint_subparsers.add_parser("purge", help="Move or delete orphaned assets with safety checks")
    purge_parser.add_argument("--apply", action="store_true", help="Actually move/delete files (default is dry-run)")
    purge_parser.add_argument(
        "--delete", action="store_true", help="Actually delete files after moving to trash (requires --apply)"
    )
    purge_parser.add_argument("--keep", nargs="*", help="Additional patterns to keep (beyond maintenance_keep.txt)")
    purge_parser.set_defaults(func=maint_purge_command)

    # Placeholder for additional maintenance commands
    maint_test = maint_subparsers.add_parser("test", help="Test maintenance system")
    maint_test.set_defaults(func=maint_test_command)

    # Remove-folder command
    remove_folder_parser = maint_subparsers.add_parser("remove-folder", help="Remove a folder from the .yyp file")
    remove_folder_parser.add_argument("folder_path", help='Folder path to remove (e.g., "folders/Cursor Test.yy")')
    remove_folder_parser.add_argument(
        "--force", action="store_true", help="Force removal even if folder contains assets"
    )
    remove_folder_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be removed without making changes"
    )
    remove_folder_parser.set_defaults(func=remove_folder_command)

    # List-folders command
    list_folders_parser = maint_subparsers.add_parser("list-folders", help="List all folders in the .yyp file")
    list_folders_parser.add_argument("--show-paths", action="store_true", help="Show folder paths alongside names")
    list_folders_parser.set_defaults(func=list_folders_command)

    # CRITICAL: Validate we're in the correct directory BEFORE parsing arguments
    # This ensures users get helpful directory guidance instead of confusing argparse errors
    validate_working_directory()

    args = parser.parse_args()

    try:
        return args.func(args)
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        raise
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False
