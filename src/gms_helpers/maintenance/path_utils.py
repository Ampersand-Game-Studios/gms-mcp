import os
import platform
from pathlib import Path
from typing import Set, Dict, List, Optional

def normalize_path(path: str) -> str:
    """
    Normalize a path for cross-platform comparison.
    On Windows/macOS, converts to lowercase for case-insensitive comparison.
    """
    normalized = str(Path(path)).replace('\\', '/')
    
    # Case-insensitive on Windows and macOS
    if platform.system().lower() in ['windows', 'darwin']:
        normalized = normalized.lower()
    
    return normalized

def build_filesystem_map(root_dir: str) -> Dict[str, str]:
    """
    Build a mapping of normalized paths to actual filesystem paths.
    This allows case-insensitive lookups while preserving actual casing.
    """
    filesystem_map = {}
    
    for root, dirs, files in os.walk(root_dir):
        # Skip certain directories
        skip_dirs = {'.git', '__pycache__', 'node_modules', '.vscode'}
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            actual_path = os.path.join(root, file)
            relative_path = os.path.relpath(actual_path, root_dir)
            normalized_path = normalize_path(relative_path)
            filesystem_map[normalized_path] = relative_path
    
    return filesystem_map

def find_file_case_insensitive(target_path: str, filesystem_map: Dict[str, str]) -> Optional[str]:
    """
    Find a file using case-insensitive matching.
    Returns the actual filesystem path if found, None otherwise.
    """
    normalized_target = normalize_path(target_path)
    return filesystem_map.get(normalized_target)

def categorize_path_differences(referenced_files: Set[str], filesystem_map: Dict[str, str]) -> Dict[str, List[str]]:
    """
    Categorize differences between referenced files and filesystem.
    Returns dict with categories: found_exact, found_case_diff, missing
    """
    categories = {
        'found_exact': [],
        'found_case_diff': [],
        'missing': []
    }
    
    for ref_file in referenced_files:
        if os.path.exists(ref_file):
            # Exact match (case-sensitive)
            categories['found_exact'].append(ref_file)
        else:
            # Try case-insensitive match
            actual_path = find_file_case_insensitive(ref_file, filesystem_map)
            if actual_path:
                categories['found_case_diff'].append(f"{ref_file} -> {actual_path}")
            else:
                categories['missing'].append(ref_file)
    
    return categories

def get_gamemaker_files(root_dir: str) -> Set[str]:
    """
    Get all GameMaker-related files from the filesystem.
    Filters out non-GameMaker files like tools/, docs/, .py files, etc.
    """
    gamemaker_files = set()
    
    # GameMaker file extensions
    gm_extensions = {'.yy', '.yyp', '.gml', '.png', '.jpg', '.jpeg', '.wav', '.mp3', '.ogg', '.fnt', '.ttf'}
    
    # Directories to skip
    skip_dirs = {
        'tools', 'docs', '__pycache__', '.git', 'node_modules', '.vscode',
        'maintenance_keep.txt', 'maintenance_report.json'
    }
    
    for root, dirs, files in os.walk(root_dir):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        # Skip if we're in a tools or docs directory
        rel_root = os.path.relpath(root, root_dir)
        if any(skip_part in rel_root.split(os.sep) for skip_part in skip_dirs):
            continue
            
        for file in files:
            # Skip non-GameMaker files
            if file.startswith('.') or file.endswith('.py') or file.endswith('.md'):
                continue
                
            file_ext = os.path.splitext(file)[1].lower()
            if file_ext in gm_extensions or file.endswith('.resource_order'):
                actual_path = os.path.join(root, file)
                relative_path = os.path.relpath(actual_path, root_dir)
                gamemaker_files.add(relative_path.replace('\\', '/'))
    
    return gamemaker_files 