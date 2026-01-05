#!/usr/bin/env python3
"""
GameMaker Studio Asset Helper
Creates GameMaker assets with proper file structure and project integration.
"""

import argparse
import sys
import os
from pathlib import Path

# Direct imports - no complex fallbacks needed
from .utils import (
    validate_name,
    validate_parent_path,
    update_yyp_file,
    find_yyp_file,
    validate_working_directory,
    remove_folder_from_yyp,
    list_folders_in_yyp
)
from .assets import (
    ScriptAsset,
    ObjectAsset,
    SpriteAsset,
    RoomAsset,
    FolderAsset,
    FontAsset,
    ShaderAsset,
    AnimCurveAsset,
    SoundAsset,
    PathAsset,
    TileSetAsset,
    TimelineAsset,
    SequenceAsset,
    NoteAsset
)
from .maintenance.lint import lint_project, print_lint_report
from .maintenance.tidy_json import validate_project_json, print_json_validation_report
from .maintenance.orphans import find_orphaned_assets, find_missing_assets, print_orphan_report
from .maintenance.orphan_cleanup import delete_orphan_files, find_delete_candidates
from .maintenance.prune import prune_missing_assets, print_prune_report
from .maintenance.validate_paths import validate_folder_paths, print_path_validation_report
from .auto_maintenance import run_auto_maintenance, validate_asset_creation_safe, handle_maintenance_failure
from .maintenance.trash import move_to_trash, get_keep_patterns
from .utils import resolve_project_directory
from .exceptions import GMSError, ProjectNotFoundError, ValidationError


class GameMakerContextError(Exception):
    """Raised when commands are run outside proper GameMaker context"""
    pass


def validate_gamemaker_context():
    """
    Ensure commands run in proper GameMaker project context.
    Prevents asset creation in wrong directories.
    """
    cwd = Path.cwd()
    
    # Check if we're in a gamemaker directory or subdirectory
    current_dir = cwd
    gamemaker_root = None
    
    # Walk up the directory tree looking for a GameMaker project
    while current_dir != current_dir.parent:
        # Check if this directory contains a .yyp file
        yyp_files = list(current_dir.glob("*.yyp"))
        if yyp_files:
            gamemaker_root = current_dir
            break
        current_dir = current_dir.parent
    
    if not gamemaker_root:
        raise GameMakerContextError(
            "ERROR: Not in a GameMaker project directory.\n"
            "GameMaker asset operations must be run from within a directory containing a .yyp project file."
        )
    
    # Check if we're in the project root (contains .yyp) or should be
    if gamemaker_root != cwd:
        # We found a .yyp file in a parent directory
        rel_path = cwd.relative_to(gamemaker_root)
        
        # If we're not in the gamemaker root, suggest the correct directory
        if str(rel_path) != ".":
            print(f"[INFO] GameMaker project found at: {gamemaker_root}")
            print(f"   Current directory: {cwd}")
            print(f"   Consider running: cd {gamemaker_root}")
            # Don't raise error, just inform - allow operations from subdirectories
    
    # Additional validation: check for common GameMaker directory structure
    expected_dirs = ['objects', 'sprites', 'scripts', 'rooms']
    missing_dirs = [d for d in expected_dirs if not (gamemaker_root / d).exists()]
    
    if len(missing_dirs) == len(expected_dirs):
        raise GameMakerContextError(
            f"ERROR: Directory '{gamemaker_root}' contains a .yyp file but doesn't appear to be "
            f"a valid GameMaker project (missing standard asset directories: {', '.join(expected_dirs)})"
        )
    
    return gamemaker_root


def validate_asset_directory_structure():
    """
    Validate that asset operations won't create files outside the GameMaker project structure.
    This prevents the bug where assets were created in the wrong location.
    """
    try:
        gamemaker_root = validate_gamemaker_context()
        
        # Ensure we're not creating assets outside the project structure
        cwd = Path.cwd()
        if not str(cwd).startswith(str(gamemaker_root)):
            raise GameMakerContextError(
                f"ERROR: Current directory '{cwd}' is outside GameMaker project '{gamemaker_root}'"
            )
        
        return gamemaker_root
        
    except GameMakerContextError as e:
        message = (
            f"{e}\n\n"
            "[INFO] To fix this:\n"
            "   1. Navigate to your GameMaker project directory (contains .yyp file)\n"
            "   2. Run GameMaker asset commands from within the project\n"
            "   3. Use relative paths for --parent-path arguments"
        )
        raise ProjectNotFoundError(message)

def create_script(args):
    """Create a new script asset."""
    try:
        # DIRECTORY VALIDATION: Ensure we're in proper GameMaker context
        gamemaker_root = validate_asset_directory_structure()
        print(f"[OK] GameMaker project validated: {gamemaker_root.name}")
        
        # Run pre-creation maintenance check
        # Skip maintenance if explicitly requested
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Script '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'script', allow_constructor=getattr(args, 'constructor', False))
        validate_parent_path(args.parent_path)
        
        asset = ScriptAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        relative_path = asset.create_files(project_root, args.name, args.parent_path, 
                                          is_constructor=getattr(args, 'constructor', False))
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Script '{args.name}' created successfully")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Script '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for script '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating script: {e}")
        return False

def create_object(args):
    """Create a new object asset."""
    try:
        # Run pre-creation maintenance check
        # Skip maintenance if explicitly requested
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Object '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'object')
        validate_parent_path(args.parent_path)
        
        asset = ObjectAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {}
        if args.sprite_id:
            kwargs['sprite_id'] = args.sprite_id
        if args.parent_object:
            kwargs['parent_object'] = args.parent_object
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Object '{args.name}' created successfully")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Object '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for object '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating object: {e}")
        return False

def create_sprite(args):
    """Create a new sprite asset."""
    try:
        # Run pre-creation maintenance check
        # Skip maintenance if explicitly requested
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Sprite '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'sprite')
        validate_parent_path(args.parent_path)
        
        asset = SpriteAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        relative_path = asset.create_files(project_root, args.name, args.parent_path)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Sprite '{args.name}' created successfully")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Sprite '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for sprite '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating sprite: {e}")
        return False

def create_room(args):
    """Create a new room asset."""
    try:
        # Run pre-creation maintenance check
        # Skip maintenance if explicitly requested
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Room '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'room')
        validate_parent_path(args.parent_path)
        
        asset = RoomAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'width': args.width,
            'height': args.height
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Room '{args.name}' created successfully")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Room '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for room '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating room: {e}")
        return False

def create_folder(args):
    """Create a new folder asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Folder '{args.name}' creation", pre_result)
        
        asset = FolderAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the folder entry in .yyp file
        folder_path = asset.create_files(project_root, args.name, args.path)
        
        print(f"[OK] Folder '{args.name}' created at logical path: {folder_path}")
        print(f"   [INFO] Use --parent-path \"{folder_path}\" when creating assets inside this folder.")
        
        # Run post-creation maintenance
        if not getattr(args, 'skip_maintenance', False):
            print("[MAINT] Running post-creation maintenance...")
            post_result = run_auto_maintenance(
                '.', 
                fix_issues=not getattr(args, 'no_auto_fix', False),
                verbose=getattr(args, 'maintenance_verbose', True)
            )
            
            if post_result.has_errors:
                return handle_maintenance_failure(f"Folder '{args.name}' post-creation", post_result)
            
            print("[OK] Asset created and validated successfully!")
        
        return True
            
    except Exception as e:
        print(f"Error creating folder: {e}")
        return False

def create_font(args):
    """Create a new font asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Font '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'font')
        validate_parent_path(args.parent_path)
        
        asset = FontAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'font_name': args.font_name,
            'size': args.size,
            'bold': args.bold,
            'italic': args.italic,
            'aa_level': args.aa_level,
            'uses_sdf': args.uses_sdf
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Font '{args.name}' created successfully")
            print(f"  Font family: {args.font_name}")
            print(f"  Size: {args.size}")
            print(f"  Bold: {args.bold}, Italic: {args.italic}")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Font '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for font '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating font: {e}")
        return False

def create_shader(args):
    """Create a new shader asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Shader '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'shader')
        validate_parent_path(args.parent_path)
        
        asset = ShaderAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'shader_type': args.shader_type
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Shader '{args.name}' created successfully")
            print(f"  Type: {['GLSL ES', 'GLSL', 'HLSL 9', 'HLSL 11'][args.shader_type - 1]}")
            print(f"  Created: {args.name}.vsh (vertex shader)")
            print(f"  Created: {args.name}.fsh (fragment shader)")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Shader '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for shader '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating shader: {e}")
        return False

def create_animcurve(args):
    """Create a new animation curve asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Animation curve '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'animcurve')
        validate_parent_path(args.parent_path)
        
        asset = AnimCurveAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'curve_type': args.curve_type,
            'channel_name': args.channel_name
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Animation curve '{args.name}' created successfully")
            print(f"  Type: {args.curve_type}")
            print(f"  Channel: {args.channel_name}")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Animation curve '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for animation curve '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating animation curve: {e}")
        return False

def create_sound(args):
    """Create a new sound asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Sound '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'sound')
        validate_parent_path(args.parent_path)
        
        asset = SoundAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'volume': args.volume,
            'pitch': args.pitch,
            'sound_type': args.sound_type,
            'bitrate': args.bitrate,
            'sample_rate': args.sample_rate,
            'format': args.format
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Sound '{args.name}' created successfully")
            print(f"  Type: {['Normal', 'Background', '3D'][args.sound_type]}")
            print(f"  Volume: {args.volume}, Pitch: {args.pitch}")
            print(f"  Bitrate: {args.bitrate}, Sample Rate: {args.sample_rate}")
            print(f"  [WARN] Replace placeholder audio file with actual audio!")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Sound '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for sound '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating sound: {e}")
        return False

def create_path(args):
    """Create a new path asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Path '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'path')
        validate_parent_path(args.parent_path)
        
        asset = PathAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'closed': args.closed,
            'precision': args.precision,
            'path_type': args.path_type
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Path '{args.name}' created successfully")
            print(f"  Type: {args.path_type}")
            print(f"  Closed: {args.closed}, Precision: {args.precision}")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Path '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for path '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating path: {e}")
        return False

def create_tileset(args):
    """Create a new tileset asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Tileset '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'tileset')
        validate_parent_path(args.parent_path)
        
        asset = TileSetAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'tile_width': args.tile_width,
            'tile_height': args.tile_height,
            'tile_xsep': args.tile_xsep,
            'tile_ysep': args.tile_ysep,
            'tile_xoff': args.tile_xoff,
            'tile_yoff': args.tile_yoff,
            'sprite_id': args.sprite_id
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Tileset '{args.name}' created successfully")
            print(f"  Tile size: {args.tile_width}x{args.tile_height}")
            print(f"  Separation: {args.tile_xsep}x{args.tile_ysep}")
            print(f"  Offset: {args.tile_xoff}x{args.tile_yoff}")
            if args.sprite_id:
                print(f"  Sprite: {args.sprite_id}")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Tileset '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for tileset '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating tileset: {e}")
        return False

def create_timeline(args):
    """Create a new timeline asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Timeline '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'timeline')
        validate_parent_path(args.parent_path)
        
        asset = TimelineAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {}
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Timeline '{args.name}' created successfully")
            print(f"  Created: moment_0.gml")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Timeline '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for timeline '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating timeline: {e}")
        return False

def create_sequence(args):
    """Create a new sequence asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Sequence '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'sequence')
        validate_parent_path(args.parent_path)
        
        asset = SequenceAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'length': args.length,
            'playback_speed': args.playback_speed
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Sequence '{args.name}' created successfully")
            print(f"  Length: {args.length} frames")
            print(f"  Playback speed: {args.playback_speed} FPS")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Sequence '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for sequence '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating sequence: {e}")
        return False

def create_note(args):
    """Create a new note asset."""
    try:
        # Run pre-creation maintenance check
        if not getattr(args, 'skip_maintenance', False):
            print("[VALIDATE] Running pre-creation validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Note '{args.name}' creation", pre_result)
        
        validate_name(args.name, 'note')
        validate_parent_path(args.parent_path)
        
        asset = NoteAsset()
        from pathlib import Path
        project_root = Path('.')
        
        # Create the asset files
        kwargs = {
            'content': args.content
        }
        
        relative_path = asset.create_files(project_root, args.name, args.parent_path, **kwargs)
        
        # Create resource entry for .yyp file
        resource_entry = {
            "id": {
                "name": args.name,
                "path": relative_path
            }
        }
        
        # Update .yyp file
        success = update_yyp_file(resource_entry)
        
        if success:
            print(f"[OK] Note '{args.name}' created successfully")
            print(f"  Created: {args.name}.txt")
            
            # Run post-creation maintenance
            if not getattr(args, 'skip_maintenance', False):
                print("[MAINT] Running post-creation maintenance...")
                post_result = run_auto_maintenance(
                    '.', 
                    fix_issues=not getattr(args, 'no_auto_fix', False),
                    verbose=getattr(args, 'maintenance_verbose', True)
                )
                
                if post_result.has_errors:
                    return handle_maintenance_failure(f"Note '{args.name}' post-creation", post_result)
                
                print("[OK] Asset created and validated successfully!")
            
            return True
        else:
            print(f"[ERROR] Failed to update .yyp file for note '{args.name}'")
            return False
            
    except Exception as e:
        print(f"Error creating note: {e}")
        return False

def delete_asset(args):
    """Delete an asset from the project."""
    try:
        import os
        import shutil
        from pathlib import Path
        
        # Import utilities with fallback
        try:
            from .utils import load_json, save_json, find_yyp_file
        except ImportError:
            from .utils import load_json, save_json, find_yyp_file
        
        # Skip maintenance if explicitly requested
        if not getattr(args, 'skip_maintenance', False):
            print("[SCAN] Running pre-deletion validation...")
            pre_result = run_auto_maintenance('.', fix_issues=not getattr(args, 'no_auto_fix', False), verbose=False)
            
            if not validate_asset_creation_safe(pre_result):
                return handle_maintenance_failure(f"Asset '{args.name}' deletion", pre_result)
        
        # Map asset types to their expected paths and prefixes
        asset_type_info = {
            'script': {'folder': 'scripts', 'prefix': '', 'extension': '.gml'},
            'object': {'folder': 'objects', 'prefix': 'o_', 'extension': ''},
            'sprite': {'folder': 'sprites', 'prefix': 'spr_', 'extension': ''},
            'room': {'folder': 'rooms', 'prefix': 'r_', 'extension': ''},
            'font': {'folder': 'fonts', 'prefix': 'fnt_', 'extension': ''},
            'shader': {'folder': 'shaders', 'prefix': 'sh_', 'extension': ''},
            'animcurve': {'folder': 'animcurves', 'prefix': 'curve_', 'extension': ''},
            'sound': {'folder': 'sounds', 'prefix': 'snd_', 'extension': ''},
            'path': {'folder': 'paths', 'prefix': 'pth_', 'extension': ''},
            'tileset': {'folder': 'tilesets', 'prefix': 'ts_', 'extension': ''},
            'timeline': {'folder': 'timelines', 'prefix': 'tl_', 'extension': ''},
            'sequence': {'folder': 'sequences', 'prefix': 'seq_', 'extension': ''},
            'note': {'folder': 'notes', 'prefix': '', 'extension': ''}
        }
        
        if args.asset_type not in asset_type_info:
            print(f"[ERROR] Unsupported asset type: {args.asset_type}")
            return False
        
        info = asset_type_info[args.asset_type]
        asset_folder = info['folder']
        asset_name = args.name
        
        # Determine asset path structure
        if args.asset_type == 'folder':
            # Special handling for folders
            asset_path = f"folders/{asset_name}.yy"
            disk_path = Path(asset_path)
        else:
            # Regular assets have folder structure
            asset_path = f"{asset_folder}/{asset_name}/{asset_name}.yy"
            disk_path = Path(asset_folder) / asset_name
        
        # Check if asset exists in .yyp file
        yyp_file = find_yyp_file()
        project_data = load_json(yyp_file)
        resources = project_data.get('resources', [])
        
        # Find the resource entry
        resource_to_remove = None
        for resource in resources:
            if resource.get('id', {}).get('name') == asset_name:
                resource_to_remove = resource
                break
        
        if not resource_to_remove:
            print(f"[ERROR] Asset '{asset_name}' not found in project")
            return False
        
        # Check if asset files exist on disk
        files_to_delete = []
        if disk_path.exists():
            if disk_path.is_file():
                files_to_delete.append(disk_path)
            else:
                files_to_delete.append(disk_path)
                # Add all files in the directory
                for item in disk_path.rglob('*'):
                    if item.is_file():
                        files_to_delete.append(item)
        
        if args.dry_run:
            print(f"[DRY-RUN] Would delete asset '{asset_name}' ({args.asset_type}):")
            print(f"  [FILE] .yyp entry: {resource_to_remove['id']['path']}")
            if files_to_delete:
                print(f"  [FILES] Files/folders ({len(files_to_delete)}):")
                for file_path in files_to_delete[:10]:  # Show first 10 files
                    print(f"    - {file_path}")
                if len(files_to_delete) > 10:
                    print(f"    ... and {len(files_to_delete) - 10} more files")
            else:
                print(f"  [FILES] No files found on disk")
            return True
        
        # Remove from .yyp file
        updated_resources = [r for r in resources if r.get('id', {}).get('name') != asset_name]
        project_data['resources'] = updated_resources
        
        try:
            save_json(project_data, yyp_file)
            print(f"[OK] Removed '{asset_name}' from {yyp_file}")
        except Exception as e:
            print(f"[ERROR] Failed to update .yyp file: {e}")
            return False
        
        # Delete files from disk
        if files_to_delete:
            try:
                if disk_path.is_file():
                    disk_path.unlink()
                    print(f"[OK] Deleted file: {disk_path}")
                else:
                    shutil.rmtree(disk_path)
                    print(f"[OK] Deleted folder: {disk_path}")
            except Exception as e:
                print(f"[WARN] Warning: Could not delete files on disk: {e}")
                print(f"   Asset removed from project but files may remain")
        
        print(f"[OK] Asset '{asset_name}' deleted successfully")
        
        # Run post-deletion maintenance
        if not getattr(args, 'skip_maintenance', False):
            print("[MAINT] Running post-deletion maintenance...")
            post_result = run_auto_maintenance(
                '.', 
                fix_issues=not getattr(args, 'no_auto_fix', False),
                verbose=getattr(args, 'maintenance_verbose', True)
            )
            
            if post_result.has_errors:
                return handle_maintenance_failure(f"Asset '{args.name}' post-deletion", post_result)
            
            print("[OK] Asset deleted and validated successfully!")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error deleting asset: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='GameMaker Studio Asset Helper',
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
        """
    )
    
    # Global options for auto-maintenance
    parser.add_argument(
        '--skip-maintenance',
        action='store_true',
        help='Skip automatic maintenance operations (not recommended)'
    )
    parser.add_argument(
        '--maintenance-verbose',
        action='store_true',
        default=True,
        help='Show verbose maintenance output (default: True)'
    )
    parser.add_argument(
        '--no-auto-fix',
        action='store_true',
        help='Do not automatically fix issues during maintenance'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Asset type to create or maintenance command')
    subparsers.required = True
    
    # Asset creation commands
    # Script command
    script_parser = subparsers.add_parser('script', help='Create a script asset')
    script_parser.add_argument('name', help='Script name (snake_case or PascalCase with --constructor)')
    script_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    script_parser.add_argument('--constructor', action='store_true', help='Create a constructor script (allows PascalCase naming)')
    script_parser.set_defaults(func=create_script)
    
    # Object command
    object_parser = subparsers.add_parser('object', help='Create an object asset')
    object_parser.add_argument('name', help='Object name (o_ prefix)')
    object_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    object_parser.add_argument('--sprite-id', help='Sprite resource ID')
    object_parser.add_argument('--parent-object', help='Parent object name (for inheritance)')
    object_parser.set_defaults(func=create_object)
    
    # Sprite command
    sprite_parser = subparsers.add_parser('sprite', help='Create a sprite asset')
    sprite_parser.add_argument('name', help='Sprite name (spr_ prefix)')
    sprite_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    sprite_parser.set_defaults(func=create_sprite)
    
    # Room command
    room_parser = subparsers.add_parser('room', help='Create a room asset')
    room_parser.add_argument('name', help='Room name (r_ prefix)')
    room_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    room_parser.add_argument('--width', type=int, default=1024, help='Room width (default: 1024)')
    room_parser.add_argument('--height', type=int, default=768, help='Room height (default: 768)')
    room_parser.set_defaults(func=create_room)
    
    # Folder command
    folder_parser = subparsers.add_parser('folder', help='Create a folder asset')
    folder_parser.add_argument('name', help='Folder name')
    folder_parser.add_argument('--path', required=True, help='Folder path (e.g., "folders/My Folder.yy")')
    folder_parser.set_defaults(func=create_folder)
    
    # Font command
    font_parser = subparsers.add_parser('font', help='Create a font asset')
    font_parser.add_argument('name', help='Font name (fnt_ prefix)')
    font_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    font_parser.add_argument('--font-name', default='Arial', help='Font family name (default: Arial)')
    font_parser.add_argument('--size', type=int, default=12, help='Font size (default: 12)')
    font_parser.add_argument('--bold', action='store_true', help='Make font bold')
    font_parser.add_argument('--italic', action='store_true', help='Make font italic')
    font_parser.add_argument('--aa-level', type=int, default=1, choices=[0, 1, 2, 3], help='Anti-aliasing level (0-3, default: 1)')
    font_parser.add_argument('--uses-sdf', action='store_true', default=True, help='Use SDF rendering (default: True)')
    font_parser.set_defaults(func=create_font)
    
    # Shader command
    shader_parser = subparsers.add_parser('shader', help='Create a shader asset')
    shader_parser.add_argument('name', help='Shader name (sh_ or shader_ prefix)')
    shader_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    shader_parser.add_argument('--shader-type', type=int, default=1, choices=[1, 2, 3, 4], 
                              help='Shader type: 1=GLSL ES, 2=GLSL, 3=HLSL 9, 4=HLSL 11 (default: 1)')
    shader_parser.set_defaults(func=create_shader)
    
    # Animation curve command
    animcurve_parser = subparsers.add_parser('animcurve', help='Create an animation curve asset')
    animcurve_parser.add_argument('name', help='Animation curve name (curve_ or ac_ prefix)')
    animcurve_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    animcurve_parser.add_argument('--curve-type', default='linear', 
                                  choices=['linear', 'smooth', 'ease_in', 'ease_out'],
                                  help='Curve type (default: linear)')
    animcurve_parser.add_argument('--channel-name', default='curve', help='Channel name (default: curve)')
    animcurve_parser.set_defaults(func=create_animcurve)
    
    # Sound command
    sound_parser = subparsers.add_parser('sound', help='Create a sound asset')
    sound_parser.add_argument('name', help='Sound name (snd_ or sfx_ prefix)')
    sound_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    sound_parser.add_argument('--volume', type=float, default=1.0, help='Volume (0.0-1.0, default: 1.0)')
    sound_parser.add_argument('--pitch', type=float, default=1.0, help='Pitch (default: 1.0)')
    sound_parser.add_argument('--sound-type', type=int, default=0, choices=[0, 1, 2], 
                              help='Sound type: 0=Normal, 1=Background, 2=3D (default: 0)')
    sound_parser.add_argument('--bitrate', type=int, default=128, help='Bitrate (default: 128)')
    sound_parser.add_argument('--sample-rate', type=int, default=44100, help='Sample rate (default: 44100)')
    sound_parser.add_argument('--format', type=int, default=0, choices=[0, 1, 2], 
                              help='Format: 0=OGG, 1=MP3, 2=WAV (default: 0)')
    sound_parser.set_defaults(func=create_sound)
    
    # Path command
    path_parser = subparsers.add_parser('path', help='Create a path asset')
    path_parser.add_argument('name', help='Path name (pth_ or path_ prefix)')
    path_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    path_parser.add_argument('--closed', action='store_true', help='Make path closed (loops back to start)')
    path_parser.add_argument('--precision', type=int, default=4, help='Path precision (default: 4)')
    path_parser.add_argument('--path-type', default='straight', 
                            choices=['straight', 'smooth', 'circle'],
                            help='Path type (default: straight)')
    path_parser.set_defaults(func=create_path)
    
    # Tileset command
    tileset_parser = subparsers.add_parser('tileset', help='Create a tileset asset')
    tileset_parser.add_argument('name', help='Tileset name (ts_ or tile_ prefix)')
    tileset_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    tileset_parser.add_argument('--sprite-id', help='Sprite resource ID to use for tiles')
    tileset_parser.add_argument('--tile-width', type=int, default=32, help='Tile width (default: 32)')
    tileset_parser.add_argument('--tile-height', type=int, default=32, help='Tile height (default: 32)')
    tileset_parser.add_argument('--tile-xsep', type=int, default=0, help='Horizontal separation (default: 0)')
    tileset_parser.add_argument('--tile-ysep', type=int, default=0, help='Vertical separation (default: 0)')
    tileset_parser.add_argument('--tile-xoff', type=int, default=0, help='Horizontal offset (default: 0)')
    tileset_parser.add_argument('--tile-yoff', type=int, default=0, help='Vertical offset (default: 0)')
    tileset_parser.set_defaults(func=create_tileset)
    
    # Timeline command
    timeline_parser = subparsers.add_parser('timeline', help='Create a timeline asset')
    timeline_parser.add_argument('name', help='Timeline name (tl_ or timeline_ prefix)')
    timeline_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    timeline_parser.set_defaults(func=create_timeline)
    
    # Sequence command
    sequence_parser = subparsers.add_parser('sequence', help='Create a sequence asset')
    sequence_parser.add_argument('name', help='Sequence name (seq_ or sequence_ prefix)')
    sequence_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    sequence_parser.add_argument('--length', type=float, default=60.0, help='Sequence length in frames (default: 60.0)')
    sequence_parser.add_argument('--playback-speed', type=float, default=30.0, help='Playback speed in FPS (default: 30.0)')
    sequence_parser.set_defaults(func=create_sequence)
    
    # Note command
    note_parser = subparsers.add_parser('note', help='Create a note asset')
    note_parser.add_argument('name', help='Note name (letters, numbers, underscores, hyphens, spaces)')
    note_parser.add_argument('--parent-path', required=True, help='Parent folder path')
    note_parser.add_argument('--content', help='Initial note content')
    note_parser.set_defaults(func=create_note)
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete an asset')
    delete_parser.add_argument('asset_type', choices=['script', 'object', 'sprite', 'room', 'folder', 'font', 'shader', 'animcurve', 'sound', 'path', 'tileset', 'timeline', 'sequence', 'note'], help='Asset type to delete')
    delete_parser.add_argument('name', help='Asset name to delete')
    delete_parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without making changes')
    delete_parser.set_defaults(func=delete_asset)
    
    # Maintenance commands
    maint_parser = subparsers.add_parser('maint', help='Asset maintenance commands')
    maint_subparsers = maint_parser.add_subparsers(dest='maint_command', help='Maintenance operation')
    maint_subparsers.required = True
    
    # Lint command
    lint_parser = maint_subparsers.add_parser('lint', help='Check project for JSON errors and naming issues')
    lint_parser.add_argument('--fix', action='store_true', help='Automatically fix issues where possible')
    lint_parser.set_defaults(func=maint_lint_command)
    
    # Validate-json command
    validate_json_parser = maint_subparsers.add_parser('validate-json', help='Validate JSON syntax in project files')
    validate_json_parser.set_defaults(func=maint_validate_json_command)
    
    # List-orphans command
    orphans_parser = maint_subparsers.add_parser('list-orphans', help='Find orphaned and missing assets')
    orphans_parser.set_defaults(func=maint_list_orphans_command)
    
    # Prune-missing command
    prune_parser = maint_subparsers.add_parser('prune-missing', help='Remove missing asset references from project file')
    prune_parser.add_argument('--dry-run', action='store_true', help='Show what would be removed without making changes')
    prune_parser.set_defaults(func=maint_prune_missing_command)
    
    # Validate-paths command
    validate_parser = maint_subparsers.add_parser('validate-paths', help='Check that all folder paths referenced in assets exist')
    validate_parser.add_argument('--strict-disk-check', action='store_true', help='Also check that folder .yy files exist on disk (legacy behavior)')
    validate_parser.add_argument('--include-parent-folders', action='store_true', help='Show parent folders as orphaned even if they have subfolders with assets')
    validate_parser.set_defaults(func=maint_validate_paths_command)
    
    # Dedupe-resources command
    dedupe_parser = maint_subparsers.add_parser('dedupe-resources', help='Remove duplicate resource entries from project file')
    dedupe_parser.add_argument('--auto', action='store_true', help='Automatically keep first occurrence of each duplicate (non-interactive)')
    dedupe_parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without making changes')
    dedupe_parser.set_defaults(func=maint_dedupe_resources_command)
    
    # Sync-events command
    sync_events_parser = maint_subparsers.add_parser('sync-events', help='Synchronize object events (fix orphaned/missing GML files)')
    sync_events_parser.add_argument('--fix', action='store_true', help='Actually fix issues (default is dry-run)')
    sync_events_parser.add_argument('--object', help='Sync specific object only (e.g., o_player)')
    sync_events_parser.set_defaults(func=maint_sync_events_command)
    
    # Clean-old-files command
    clean_old_parser = maint_subparsers.add_parser('clean-old-files', help='Remove .old.yy backup files from project')
    clean_old_parser.add_argument('--delete', action='store_true', help='Actually delete files (default is dry-run)')
    clean_old_parser.set_defaults(func=maint_clean_old_files_command)
    
    # Clean-orphans command  
    clean_orphans_parser = maint_subparsers.add_parser('clean-orphans', help='Remove orphaned asset files from project')
    clean_orphans_parser.add_argument('--delete', action='store_true', help='Actually delete files (default is dry-run)')
    clean_orphans_parser.add_argument('--skip-types', nargs='*', default=['folder'], 
                                    help='Asset types to skip during cleanup (default: folder)')
    clean_orphans_parser.set_defaults(func=maint_clean_orphans_command)
    
    # Fix-issues command (comprehensive auto-maintenance)
    fix_issues_parser = maint_subparsers.add_parser('fix-issues', help='Run comprehensive auto-maintenance with fixes enabled')
    fix_issues_parser.add_argument('--verbose', action='store_true', help='Show detailed progress and reports')
    fix_issues_parser.set_defaults(func=maint_fix_issues_command)
    
    # Audit command (new robust analysis)
    audit_parser = maint_subparsers.add_parser('audit', help='Run comprehensive asset analysis and generate report')
    audit_parser.add_argument('--output', default='maintenance_report.json', help='Output file for audit report (default: maintenance_report.json)')
    audit_parser.set_defaults(func=maint_audit_command)
    
    # Purge command (safe deletion with trash folder)
    purge_parser = maint_subparsers.add_parser('purge', help='Move or delete orphaned assets with safety checks')
    purge_parser.add_argument('--apply', action='store_true', help='Actually move/delete files (default is dry-run)')
    purge_parser.add_argument('--delete', action='store_true', help='Actually delete files after moving to trash (requires --apply)')
    purge_parser.add_argument('--keep', nargs='*', help='Additional patterns to keep (beyond maintenance_keep.txt)')
    purge_parser.set_defaults(func=maint_purge_command)
    
    # Placeholder for additional maintenance commands
    maint_test = maint_subparsers.add_parser('test', help='Test maintenance system')
    maint_test.set_defaults(func=maint_test_command)
    
    # Remove-folder command
    remove_folder_parser = maint_subparsers.add_parser('remove-folder', help='Remove a folder from the .yyp file')
    remove_folder_parser.add_argument('folder_path', help='Folder path to remove (e.g., "folders/Cursor Test.yy")')
    remove_folder_parser.add_argument('--force', action='store_true', help='Force removal even if folder contains assets')
    remove_folder_parser.add_argument('--dry-run', action='store_true', help='Show what would be removed without making changes')
    remove_folder_parser.set_defaults(func=remove_folder_command)
    
    # List-folders command
    list_folders_parser = maint_subparsers.add_parser('list-folders', help='List all folders in the .yyp file')
    list_folders_parser.add_argument('--show-paths', action='store_true', help='Show folder paths alongside names')
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

def maint_lint_command(args):
    """Lint the GameMaker project for issues."""
    print("[SCAN] Scanning project for issues...")
    
    try:
        issues = lint_project('.')
        print_lint_report(issues)
        
        # Return success/failure based on whether errors were found
        has_errors = any(issue.severity == 'error' for issue in issues)
        return not has_errors
        
    except Exception as e:
        print(f"[ERROR] Error during project scan: {e}")
        return False

def maint_validate_json_command(args):
    """Validate JSON syntax in project files."""
    print("[VALIDATE] Validating JSON syntax in project files...")
    
    try:
        try:
            from .maintenance.tidy_json import validate_project_json, print_json_validation_report
        except ImportError:
            from maintenance.tidy_json import validate_project_json, print_json_validation_report
        
        results = validate_project_json('.')
        print_json_validation_report(results)
        
        # Return success if all files are valid
        invalid_files = [r for r in results if not r[1]]
        return len(invalid_files) == 0
        
    except Exception as e:
        print(f"[ERROR] Error during JSON validation: {e}")
        return False

def maint_list_orphans_command(args):
    """Find orphaned and missing assets."""
    print("[SCAN] Scanning project for orphaned and missing assets...")
    
    try:
        orphaned_assets = find_orphaned_assets('.')
        missing_assets = find_missing_assets('.')
        print_orphan_report(orphaned_assets, missing_assets)
        
        # Return success - this is informational
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during asset scan: {e}")
        return False

def maint_prune_missing_command(args):
    """Remove missing asset references from project file."""
    action = "Scanning for" if args.dry_run else "Removing"
    print(f"[MAINT] {action} missing asset references from project file...")
    
    try:
        removed_entries = prune_missing_assets('.', args.dry_run)
        print_prune_report(removed_entries, args.dry_run)
        
        # Return success - this is a maintenance operation
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during asset pruning: {e}")
        return False

def maint_validate_paths_command(args):
    """Validate that all folder paths referenced in assets exist."""
    strict_disk_check = getattr(args, 'strict_disk_check', False)
    mode_text = "with disk check" if strict_disk_check else "standard mode"
    parent_mode = " (including parent folders)" if getattr(args, 'include_parent_folders', False) else ""
    print(f"[VALIDATE] Validating folder paths referenced in assets ({mode_text}{parent_mode})...")
    
    try:
        include_parent_folders = getattr(args, 'include_parent_folders', False)
        issues = validate_folder_paths('.', strict_mode=strict_disk_check, include_parent_folders=include_parent_folders)
        print_path_validation_report(issues, strict_mode=strict_disk_check)
        
        # Return success/failure based on whether errors were found
        has_errors = any(issue.severity == 'error' for issue in issues)
        return not has_errors
        
    except Exception as e:
        print(f"[ERROR] Error during path validation: {e}")
        return False

def maint_dedupe_resources_command(args):
    """Remove duplicate resource entries from project file."""
    try:
        from .utils import load_json, save_json, find_yyp_file, dedupe_resources
    except ImportError:
        from .utils import load_json, save_json, find_yyp_file, dedupe_resources
    
    action = "Scanning for" if args.dry_run else "Removing"
    mode = "automatic" if args.auto else "interactive"
    print(f"[MAINT] {action} duplicate resource entries ({mode} mode)...")
    
    try:
        yyp_file = find_yyp_file()
        project_data = load_json(yyp_file)
        
        # Run deduplication
        modified_data, removed_count, report = dedupe_resources(
            project_data, 
            interactive=not args.auto and not args.dry_run
        )
        
        # Print report
        for line in report:
            print(line)
        
        if removed_count > 0:
            if args.dry_run:
                print(f"\n[DRY-RUN] Would remove {removed_count} duplicate resource entries")
            else:
                # Save the modified project file
                save_json(modified_data, yyp_file)
                print(f"\n[OK] Removed {removed_count} duplicate resource entries from {yyp_file}")
        else:
            print("\n[OK] No duplicate resources found - project is clean!")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during resource deduplication: {e}")
        return False

def maint_sync_events_command(args):
    """Synchronize object events (fix orphaned/missing GML files)."""
    dry_run = not args.fix
    action = "Scanning" if dry_run else "Synchronizing"
    print(f"[SYNC] {action} object events...")
    
    if dry_run:
        print("(DRY RUN - use --fix to actually make changes)")
    
    try:
        try:
            from .maintenance.event_sync import sync_object_events, sync_all_object_events
        except ImportError:
            from maintenance.event_sync import sync_object_events, sync_all_object_events
        
        if args.object:
            # Sync specific object
            import os
            object_path = os.path.join('.', 'objects', args.object)
            if os.path.exists(object_path):
                stats = sync_object_events(object_path, dry_run)
                print(f"[OBJECT] {args.object}:")
                if stats['orphaned_found'] > 0:
                    action_text = "FIXED" if not dry_run and stats['orphaned_fixed'] > 0 else "FOUND"
                    print(f"  [ORPHAN] Orphaned GML files: {stats['orphaned_found']} {action_text}")
                if stats['missing_found'] > 0:
                    action_text = "CREATED" if not dry_run and stats.get('missing_created', 0) > 0 else "FOUND"
                    print(f"  [MISSING] Missing GML files: {stats['missing_found']} {action_text}")
                if stats['orphaned_found'] == 0 and stats['missing_found'] == 0:
                    print(f"  [OK] All events synchronized")
            else:
                print(f"[ERROR] Object {args.object} not found")
                return False
        else:
            # Sync all objects
            stats = sync_all_object_events('.', dry_run)
            
            print(f"\n[SUMMARY] Summary:")
            print(f"  Objects processed: {stats['objects_processed']}")
            print(f"  Orphaned GML files: {stats['orphaned_found']} found, {stats['orphaned_fixed']} fixed")
            print(f"  Missing GML files: {stats['missing_found']} found, {stats.get('missing_created', 0)} created")
            
            if stats['orphaned_found'] == 0 and stats['missing_found'] == 0:
                print("[OK] All object events are properly synchronized")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during event synchronization: {e}")
        return False

def maint_clean_old_files_command(args):
    """Remove .old.yy backup files from project."""
    delete = args.delete
    action = "Removing" if delete else "Scanning for"
    print(f"[MAINT] {action} .old.yy backup files from project...")
    
    try:
        try:
            from .maintenance.clean_unused_assets import clean_old_yy_files
        except ImportError:
            from maintenance.clean_unused_assets import clean_old_yy_files
        
        found, deleted = clean_old_yy_files('.', do_delete=delete)
        
        if found > 0:
            if delete:
                print(f"\n[OK] Found {found} .old.yy files, deleted {deleted}")
            else:
                print(f"\n[INFO] Found {found} .old.yy files (use --delete to remove them)")
        else:
            print("\n[OK] No .old.yy files found - project is clean!")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during old file cleaning: {e}")
        return False

def maint_clean_orphans_command(args):
    """Remove orphaned asset files from project."""
    delete = args.delete
    skip_types = set(args.skip_types) if args.skip_types else {"folder"}
    action = "Removing" if delete else "Scanning for"
    print(f"[MAINT] {action} orphaned asset files from project...")
    
    if not delete:
        print("(DRY RUN - use --delete to actually remove files)")
    
    try:
        cleanup_result = delete_orphan_files('.', fix_issues=delete, skip_types=skip_types)
        
        total_deleted = cleanup_result.get('total_deleted', 0)
        deleted_dirs = len(cleanup_result.get('deleted_directories', []))
        errors = cleanup_result.get('errors', [])
        
        if total_deleted > 0:
            if delete:
                print(f"\n[OK] Deleted {total_deleted} orphaned files")
                if deleted_dirs > 0:
                    print(f"[DIRS] Removed {deleted_dirs} empty directories")
            else:
                print(f"\n[INFO] Found {total_deleted} orphaned files to remove")
                print("   Use --delete to actually remove them")
                
        else:
            print("\n[OK] No orphaned files found - project is clean!")
        
        if errors:
            print(f"\n[WARN] {len(errors)} errors occurred during cleanup:")
            for error in errors[:5]:  # Show first 5 errors
                print(f"  - {error}")
            if len(errors) > 5:
                print(f"  ... and {len(errors) - 5} more errors")
        
        # Show detailed report for dry run
        if not delete and total_deleted > 0:
            deleted_files = cleanup_result.get('deleted_files', [])
            if deleted_files:
                print(f"\nFiles that would be deleted:")
                for file_path in deleted_files[:20]:  # Show first 20 files
                    print(f"  - {file_path}")
                if len(deleted_files) > 20:
                    print(f"  ... and {len(deleted_files) - 20} more files")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during orphan cleaning: {e}")
        return False

def maint_fix_issues_command(args):
    """Run comprehensive auto-maintenance with fixes enabled."""
    verbose = args.verbose
    print("[MAINT] Running comprehensive auto-maintenance with fixes enabled...")
    
    try:
        run_auto_maintenance('.', fix_issues=True, verbose=verbose)
        print("[OK] Auto-maintenance completed successfully!")
        return True
    except Exception as e:
        print(f"[ERROR] Error during auto-maintenance: {e}")
        return False

def maint_test_command(args):
    """Test command for maintenance system."""
    print("[MAINT] Maintenance system initialized!")
    print("Available maintenance commands will be added in subsequent steps.")
    return True

def maint_audit_command(args):
    """Run comprehensive asset analysis and generate report."""
    output_file = args.output
    print(f"[ANALYZE] Running comprehensive asset analysis...")
    print(f"[REPORT] Report will be saved to: {output_file}")
    
    try:
        # Import the comprehensive analysis function (Phase 1 + 2)
        from .maintenance.audit import comprehensive_analysis
        
        # Run comprehensive analysis (Phase 1 + 2)
        analysis_results = comprehensive_analysis('.')
        
        # Generate comprehensive report from analysis results
        import json
        from datetime import datetime
        
        # Extract data from comprehensive analysis
        phase_1 = analysis_results['phase_1_results']
        phase_2 = analysis_results['phase_2_results']
        final = analysis_results['final_analysis']
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "phase": "Phase 1 + 2 - Comprehensive Analysis Complete",
            "status": "comprehensive_analysis_implemented",
            "counts": {
                "total_files_on_disk": phase_2['filesystem_files_count'],
                "total_referenced_files": phase_1['referenced_files_count'],
                "missing_but_referenced": final['missing_but_referenced_count'],
                "truly_orphan": final['true_orphans_count'],
                "case_sensitivity_issues": final['case_sensitivity_issues_count'],
                "derivable_orphans": len(phase_2['derivable_orphans'])
            },
            "missing_but_referenced": final['missing_but_referenced'],
            "truly_orphan": final['true_orphans'],
            "case_sensitivity_issues": final['case_sensitivity_issues'],
            "derivable_orphans": phase_2['derivable_orphans'],
            "string_references_summary": {
                "by_type": {k: len(v) for k, v in phase_2['string_references']['by_type'].items()},
                "found_exact": len(phase_2['string_references']['cross_reference']['string_refs_found_exact']),
                "found_case_diff": len(phase_2['string_references']['cross_reference']['string_refs_found_case_diff']),
                "missing": len(phase_2['string_references']['cross_reference']['string_refs_missing'])
            },
            "full_analysis_results": analysis_results  # Include complete analysis for detailed inspection
        }
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"[OK] Comprehensive audit complete (Phase 1 + 2)!")
        print(f"[SUMMARY] Summary:")
        print(f"   - Total files on disk: {phase_2['filesystem_files_count']}")
        print(f"   - Referenced files: {phase_1['referenced_files_count']}")
        print(f"   - Missing files: {final['missing_but_referenced_count']}")
        print(f"   - True orphans: {final['true_orphans_count']}")
        print(f"   - Case sensitivity issues: {final['case_sensitivity_issues_count']}")
        print(f"   - Derivable orphans: {len(phase_2['derivable_orphans'])}")
        print(f"[REPORT] Detailed report saved to: {output_file}")
        
        if final['missing_but_referenced_count'] > 0:
            print(f"[WARN]  {final['missing_but_referenced_count']} files are referenced but missing!")
        if final['case_sensitivity_issues_count'] > 0:
            print(f"[CASE] {final['case_sensitivity_issues_count']} case sensitivity issues found!")
        if final['true_orphans_count'] > 0:
            print(f"[DELETE]  {final['true_orphans_count']} files appear to be true orphans")
        if len(phase_2['derivable_orphans']) > 0:
            print(f"[INFO] {len(phase_2['derivable_orphans'])} files are derivable orphans (may be used via naming conventions or strings)")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during audit: {e}")
        import traceback
        traceback.print_exc()
        return False

def maint_purge_command(args):
    """Move or delete orphaned assets with safety checks."""
    apply_changes = args.apply
    delete_after_move = args.delete
    additional_keep_patterns = args.keep or []
    
    project_root = resolve_project_directory(getattr(args, 'project_root', None))
    
    if not apply_changes:
        print("[SCAN] DRY RUN: Analyzing what would be purged...")
    elif delete_after_move:
        print("[DELETE]  PURGE MODE: Moving files to trash then deleting...")
    else:
        print("[PACKAGE] MOVE MODE: Moving files to trash folder...")
    
    try:
        # 1. Find orphans
        print("[SCAN] Searching for orphaned assets...")
        orphans = find_orphaned_assets(str(project_root))
        if not orphans:
            print("[OK] No orphaned assets found to purge.")
            return True
            
        # 2. Load keep patterns
        keep_patterns = get_keep_patterns(str(project_root))
        keep_patterns.extend(additional_keep_patterns)
        
        # 3. Filter orphans
        to_purge = []
        for path, asset_type in orphans:
            should_keep = False
            for pattern in keep_patterns:
                if pattern in path:
                    should_keep = True
                    break
            
            if not should_keep:
                to_purge.append(path)
                # Also include companion files (.gml, etc.) if safe
                # Note: find_orphaned_assets returns .yy paths
                # We should use the more comprehensive deletion logic or move logic
        
        if not to_purge:
            print("[OK] All orphaned assets are protected by keep patterns.")
            return True
            
        print(f"[INFO] Found {len(to_purge)} assets to purge.")
        
        if not apply_changes:
            for path in sorted(to_purge):
                print(f"  [DRY RUN] Would move to trash: {path}")
            print(f"[OK] DRY RUN complete. Use --apply to actually move files.")
            return True
            
        # 4. Move to trash
        print(f"[PACKAGE] Moving {len(to_purge)} assets to trash...")
        result = move_to_trash(str(project_root), to_purge)
        
        if result["errors"]:
            for err in result["errors"]:
                print(f"[ERROR] {err}")
                
        print(f"[OK] Moved {result['moved_count']} files to {result['trash_folder']}")
        
        if delete_after_move:
            # Note: For now, we don't actually delete from trash for extra safety
            # unless we implement the full "run tests before delete" logic.
            print("[WARN]  Final deletion from trash folder not yet implemented for safety.")
            print(f"[INFO] Files are safe in {result['trash_folder']}")
            
        return True
        
    except Exception as e:
        print(f"[ERROR] Error during purge: {e}")
        import traceback
        traceback.print_exc()
        return False

def remove_folder_command(args):
    """Remove a folder from the .yyp file."""
    folder_path = args.folder_path
    force = getattr(args, 'force', False)
    dry_run = getattr(args, 'dry_run', False)
    
    if dry_run:
        print(f"[SCAN] DRY RUN: Would remove folder '{folder_path}' from project...")
    else:
        action = "Forcefully removing" if force else "Removing"
        print(f"[DELETE] {action} folder '{folder_path}' from project...")
    
    try:
        success, message, assets_in_folder = remove_folder_from_yyp(folder_path, force=force, dry_run=dry_run)
        
        if success:
            if dry_run:
                print(f"[OK] DRY RUN: {message}")
            else:
                print(f"[OK] {message}")
            return True
        else:
            print(f"[ERROR] {message}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error removing folder: {e}")
        return False

def list_folders_command(args):
    """List all folders in the .yyp file."""
    show_paths = getattr(args, 'show_paths', False)
    print("[FOLDER] Listing all folders in project...")
    
    try:
        success, folders, message = list_folders_in_yyp()
        
        if success:
            print(f"[OK] {message}")
            
            if folders:
                print("\nFolders:")
                for folder in folders:
                    if show_paths:
                        print(f"  [FOLDER] {folder['name']} -> {folder['path']}")
                    else:
                        print(f"  [FOLDER] {folder['name']}")
                        
                if not show_paths:
                    print("\n[INFO] Use --show-paths to see folder paths")
            else:
                print("  (No folders found)")
            
            return True
        else:
            print(f"[ERROR] {message}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error listing folders: {e}")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except GMSError as e:
        sys.exit(e.exit_code)
    except Exception:
        sys.exit(1)
