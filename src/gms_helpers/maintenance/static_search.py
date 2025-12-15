import os
import re
from typing import Set, Dict, List
from pathlib import Path

def find_string_references_in_gml(root_dir: str) -> Dict[str, Set[str]]:
    """
    Search through all .gml files for string references to assets.
    Returns dict mapping reference types to sets of found references.
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
    
    # Common GameMaker asset prefixes
    asset_patterns = {
        'sprites': [r'\bspr_\w+\b', r'sprite_get_name\(["\']([^"\']+)["\']', r'asset_get_index\(["\']([^"\']+)["\']'],
        'sounds': [r'\bsnd_\w+\b', r'\bmus_\w+\b', r'audio_play_sound\(["\']([^"\']+)["\']'],
        'objects': [r'\bo_\w+\b', r'instance_create\w*\([^,]+,\s*[^,]+,\s*([^,\)]+)', r'object_get_name\(["\']([^"\']+)["\']'],
        'scripts': [r'\b[a-z_][a-z0-9_]*\s*\(', r'script_execute\(["\']([^"\']+)["\']'],
        'rooms': [r'\br_\w+\b', r'room_goto\(([^)]+)\)', r'room_get_name\(["\']([^"\']+)["\']'],
        'fonts': [r'\bfnt_\w+\b', r'font_get_name\(["\']([^"\']+)["\']'],
        'shaders': [r'\bshd_\w+\b', r'shader_get_name\(["\']([^"\']+)["\']']
    }
    
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

def identify_derivable_orphans(filesystem_files: Set[str], 
                             referenced_files: Set[str],
                             string_refs: Dict[str, Set[str]]) -> List[str]:
    """
    Identify orphaned files that could be derived from naming conventions or string references.
    These are files that exist but aren't directly referenced, but follow patterns that suggest they might be used.
    """
    derivable_orphans = []
    
    # Get all string references as a flat set
    all_string_refs = set()
    for refs in string_refs.values():
        all_string_refs.update(refs)
    
    for file_path in filesystem_files:
        if file_path not in referenced_files:
            # This is an orphaned file
            path_parts = file_path.split('/')
            
            if len(path_parts) >= 2:
                asset_name = path_parts[1]
                
                # Check if asset name appears in string references
                if asset_name in all_string_refs:
                    derivable_orphans.append(f"{file_path} (referenced as string: {asset_name})")
                
                # Check naming convention patterns
                elif (asset_name.startswith(('spr_', 'o_', 'r_', 'fnt_', 'snd_', 'mus_', 'shd_')) or
                      any(pattern in asset_name.lower() for pattern in ['_create', '_step', '_draw', '_collision'])):
                    derivable_orphans.append(f"{file_path} (follows naming convention)")
    
    return derivable_orphans 