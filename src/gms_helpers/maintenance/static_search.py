"""
Static search utilities for finding asset references in GML code.

This module provides functions to search through GML files for string references
to assets, using configurable naming conventions.
"""

import os
import re
from typing import Set, Dict, List, Optional
from pathlib import Path

# Import naming config for dynamic pattern building
try:
    from ..naming_config import get_config, NamingConfig
except ImportError:
    # Fallback for standalone usage
    get_config = None
    NamingConfig = None


def _build_prefix_pattern(prefixes: List[str]) -> str:
    """Build a regex pattern from a list of prefixes.
    
    Args:
        prefixes: List of prefix strings (e.g., ['spr_', 'sprite_'])
        
    Returns:
        Regex pattern that matches any of the prefixes followed by word chars
    """
    if not prefixes:
        return None
    
    # Escape special regex characters in prefixes
    escaped = [re.escape(p) for p in prefixes]
    
    # Build alternation pattern
    if len(escaped) == 1:
        return rf'\b{escaped[0]}\w+\b'
    else:
        return rf'\b({"|".join(escaped)})\w+\b'


def _get_asset_patterns_from_config(config: Optional["NamingConfig"] = None) -> Dict[str, List[str]]:
    """Build asset search patterns from config.
    
    Args:
        config: NamingConfig instance, or None to use defaults
        
    Returns:
        Dict mapping asset types to list of regex patterns
    """
    # Asset type to folder name mapping
    asset_type_map = {
        'sprites': 'sprite',
        'sounds': 'sound',
        'objects': 'object',
        'scripts': 'script',
        'rooms': 'room',
        'fonts': 'font',
        'shaders': 'shader',
    }
    
    patterns = {}
    
    for plural_name, asset_type in asset_type_map.items():
        type_patterns = []
        
        # Try to get prefixes from config
        if config:
            prefixes = config.get_prefixes(asset_type)
            if prefixes:
                prefix_pattern = _build_prefix_pattern(prefixes)
                if prefix_pattern:
                    type_patterns.append(prefix_pattern)
        
        # Add fallback patterns if no config prefixes
        if not type_patterns:
            # Use default patterns
            default_patterns = _get_default_patterns()
            if plural_name in default_patterns:
                type_patterns.extend(default_patterns[plural_name])
        else:
            # Add function-based patterns that are always useful
            func_patterns = _get_function_patterns().get(plural_name, [])
            type_patterns.extend(func_patterns)
        
        patterns[plural_name] = type_patterns
    
    return patterns


def _get_default_patterns() -> Dict[str, List[str]]:
    """Get default hardcoded patterns as fallback."""
    return {
        'sprites': [r'\bspr_\w+\b', r'sprite_get_name\(["\']([^"\']+)["\']', r'asset_get_index\(["\']([^"\']+)["\']'],
        'sounds': [r'\bsnd_\w+\b', r'\bmus_\w+\b', r'audio_play_sound\(["\']([^"\']+)["\']'],
        'objects': [r'\bo_\w+\b', r'instance_create\w*\([^,]+,\s*[^,]+,\s*([^,\)]+)', r'object_get_name\(["\']([^"\']+)["\']'],
        'scripts': [r'\b[a-z_][a-z0-9_]*\s*\(', r'script_execute\(["\']([^"\']+)["\']'],
        'rooms': [r'\br_\w+\b', r'room_goto\(([^)]+)\)', r'room_get_name\(["\']([^"\']+)["\']'],
        'fonts': [r'\bfnt_\w+\b', r'font_get_name\(["\']([^"\']+)["\']'],
        'shaders': [r'\bshd_\w+\b', r'shader_get_name\(["\']([^"\']+)["\']']
    }


def _get_function_patterns() -> Dict[str, List[str]]:
    """Get patterns based on GameMaker function calls (these don't change with naming config)."""
    return {
        'sprites': [r'sprite_get_name\(["\']([^"\']+)["\']', r'asset_get_index\(["\']([^"\']+)["\']'],
        'sounds': [r'audio_play_sound\(["\']([^"\']+)["\']'],
        'objects': [r'instance_create\w*\([^,]+,\s*[^,]+,\s*([^,\)]+)', r'object_get_name\(["\']([^"\']+)["\']'],
        'scripts': [r'script_execute\(["\']([^"\']+)["\']'],
        'rooms': [r'room_goto\(([^)]+)\)', r'room_get_name\(["\']([^"\']+)["\']'],
        'fonts': [r'font_get_name\(["\']([^"\']+)["\']'],
        'shaders': [r'shader_get_name\(["\']([^"\']+)["\']']
    }


def find_string_references_in_gml(
    root_dir: str, 
    config: Optional["NamingConfig"] = None
) -> Dict[str, Set[str]]:
    """
    Search through all .gml files for string references to assets.
    
    Args:
        root_dir: Root directory to search for .gml files
        config: Optional NamingConfig to use for pattern building.
                If None, attempts to load from root_dir or uses defaults.
    
    Returns:
        Dict mapping reference types to sets of found references.
    """
    references = {
        'sprites': set(),
        'sounds': set(),
        'objects': set(),
        'scripts': set(),
        'rooms': set(),
        'fonts': set(),
        'shaders': set()
    }
    
    # Get config if not provided
    if config is None and get_config is not None:
        try:
            config = get_config(root_dir)
        except Exception:
            config = None
    
    # Build asset patterns from config
    asset_patterns = _get_asset_patterns_from_config(config)
    
    # Find all .gml files
    gml_files = []
    for root, dirs, files in os.walk(root_dir):
        # Skip non-GameMaker directories
        skip_dirs = {'tools', 'docs', '__pycache__', '.git', 'node_modules', '.vscode'}
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            if file.endswith('.gml'):
                gml_files.append(os.path.join(root, file))
    
    # Process each .gml file
    for gml_file in gml_files:
        try:
            with open(gml_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Search for each asset type
            for asset_type, patterns in asset_patterns.items():
                for pattern in patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        # Clean up the match
                        if isinstance(match, tuple):
                            match = match[0] if match else ""
                        
                        match = match.strip().strip('"\'')
                        if match and not match.startswith('//') and not match.startswith('/*'):
                            references[asset_type].add(match)
                            
        except Exception as e:
            print(f"Warning: Could not read {gml_file}: {e}")
    
    return references


def find_asset_name_patterns(filesystem_files: Set[str]) -> Dict[str, Set[str]]:
    """
    Extract asset names from filesystem paths using naming conventions.
    Returns dict mapping asset types to sets of asset names found.
    """
    asset_names = {
        'sprites': set(),
        'sounds': set(),
        'objects': set(),
        'scripts': set(),
        'rooms': set(),
        'fonts': set(),
        'shaders': set()
    }
    
    for file_path in filesystem_files:
        path_parts = file_path.split('/')
        
        if len(path_parts) >= 2:
            # Get the asset folder and name
            folder = path_parts[0]
            asset_name = path_parts[1]
            
            # Map folder names to asset types
            folder_mapping = {
                'sprites': 'sprites',
                'sounds': 'sounds', 
                'objects': 'objects',
                'scripts': 'scripts',
                'rooms': 'rooms',
                'fonts': 'fonts',
                'shaders': 'shaders'
            }
            
            if folder in folder_mapping:
                asset_type = folder_mapping[folder]
                asset_names[asset_type].add(asset_name)
    
    return asset_names


def cross_reference_strings_to_files(string_refs: Dict[str, Set[str]], 
                                   filesystem_files: Set[str],
                                   filesystem_map: Dict[str, str]) -> Dict[str, List[str]]:
    """
    Cross-reference string references found in .gml files with actual filesystem files.
    Returns dict with categories of matches.
    """
    try:
        from .path_utils import find_file_case_insensitive
    except ImportError:
        from path_utils import find_file_case_insensitive
    
    results = {
        'string_refs_found_exact': [],
        'string_refs_found_case_diff': [],
        'string_refs_missing': [],
        'extra_but_derivable': []
    }
    
    # Check each string reference against filesystem
    for asset_type, refs in string_refs.items():
        for ref in refs:
            # Try to find corresponding file
            possible_paths = []
            
            if asset_type == 'sprites':
                possible_paths.append(f"sprites/{ref}/{ref}.yy")
            elif asset_type == 'sounds':
                possible_paths.extend([
                    f"sounds/{ref}/{ref}.yy",
                    f"sounds/{ref}.wav",
                    f"sounds/{ref}.mp3",
                    f"sounds/{ref}.ogg"
                ])
            elif asset_type == 'objects':
                possible_paths.append(f"objects/{ref}/{ref}.yy")
            elif asset_type == 'scripts':
                possible_paths.append(f"scripts/{ref}/{ref}.yy")
            elif asset_type == 'rooms':
                possible_paths.append(f"rooms/{ref}/{ref}.yy")
            elif asset_type == 'fonts':
                possible_paths.append(f"fonts/{ref}/{ref}.yy")
            elif asset_type == 'shaders':
                possible_paths.append(f"shaders/{ref}/{ref}.yy")
            
            found = False
            for path in possible_paths:
                if path in filesystem_files:
                    results['string_refs_found_exact'].append(f"{ref} ({asset_type}) -> {path}")
                    found = True
                    break
                else:
                    # Try case-insensitive
                    actual_path = find_file_case_insensitive(path, filesystem_map)
                    if actual_path:
                        results['string_refs_found_case_diff'].append(f"{ref} ({asset_type}) -> {actual_path}")
                        found = True
                        break
            
            if not found:
                results['string_refs_missing'].append(f"{ref} ({asset_type})")
    
    return results


def identify_derivable_orphans(
    filesystem_files: Set[str], 
    referenced_files: Set[str],
    string_refs: Dict[str, Set[str]],
    config: Optional["NamingConfig"] = None
) -> List[str]:
    """
    Identify orphaned files that could be derived from naming conventions or string references.
    These are files that exist but aren't directly referenced, but follow patterns that suggest they might be used.
    
    Args:
        filesystem_files: Set of all files in the filesystem
        referenced_files: Set of files that are referenced
        string_refs: Dict of string references by type
        config: Optional NamingConfig to use for pattern checking
    """
    derivable_orphans = []
    
    # Get all string references as a flat set
    all_string_refs = set()
    for refs in string_refs.values():
        all_string_refs.update(refs)
    
    # Build set of prefixes to check from config
    known_prefixes = set()
    if config:
        for asset_type in ['sprite', 'object', 'room', 'font', 'sound', 'shader']:
            prefixes = config.get_prefixes(asset_type)
            known_prefixes.update(prefixes)
    
    # Fallback to default prefixes if no config
    if not known_prefixes:
        known_prefixes = {'spr_', 'o_', 'r_', 'fnt_', 'snd_', 'mus_', 'shd_'}
    
    for file_path in filesystem_files:
        if file_path not in referenced_files:
            # This is an orphaned file
            path_parts = file_path.split('/')
            
            if len(path_parts) >= 2:
                asset_name = path_parts[1]
                
                # Check if asset name appears in string references
                if asset_name in all_string_refs:
                    derivable_orphans.append(f"{file_path} (referenced as string: {asset_name})")
                
                # Check naming convention patterns using configured prefixes
                elif any(asset_name.startswith(prefix) for prefix in known_prefixes):
                    derivable_orphans.append(f"{file_path} (follows naming convention)")
                
                # Also check for event-like patterns
                elif any(pattern in asset_name.lower() for pattern in ['_create', '_step', '_draw', '_collision']):
                    derivable_orphans.append(f"{file_path} (follows naming convention)")
    
    return derivable_orphans
