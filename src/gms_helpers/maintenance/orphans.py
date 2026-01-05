"""
Orphan Detection - Find assets that exist on disk but aren't referenced in the project
"""

import os
import glob
from pathlib import Path
from typing import List, Set, Tuple

from ..utils import load_json, find_yyp_file


def find_orphaned_assets(project_root: str = '.') -> List[Tuple[str, str]]:
    """
    Find assets that exist on disk but aren't referenced in the .yyp file.
    
    Returns:
        List of (asset_path, asset_type) tuples for orphaned assets
    """
    orphans = []
    
    try:
        # Ensure we have the correct GameMaker project root
        if not project_root or project_root == '.':
            # Use proper project root detection if not specified or using current dir
            from ..utils import resolve_project_directory
            project_root = resolve_project_directory()
        
        # Change to project directory temporarily to use find_yyp_file()
        original_cwd = os.getcwd()
        os.chdir(project_root)
        try:
            yyp_path = find_yyp_file()
            yyp_data = load_json(yyp_path)
        finally:
            os.chdir(original_cwd)
        
        # Get all referenced asset paths
        referenced_paths = set()
        resources = yyp_data.get('resources', [])
        
        for resource in resources:
            resource_id = resource.get('id', {})
            path = resource_id.get('path', '')
            if path:
                # Normalize path separators and convert to lowercase for case-insensitive comparison
                normalized_path = path.replace('\\', '/').lower()
                referenced_paths.add(normalized_path)
        
        # Find all asset files on disk
        asset_patterns = [
            'scripts/**/*.yy',
            'objects/**/*.yy', 
            'sprites/**/*.yy',
            'rooms/**/*.yy',
            'sounds/**/*.yy',
            'fonts/**/*.yy',
            'shaders/**/*.yy',
            'animcurves/**/*.yy',
            'folders/**/*.yy'
        ]
        
        for pattern in asset_patterns:
            full_pattern = str(Path(project_root) / pattern)
            asset_files = glob.glob(full_pattern, recursive=True)
            
            for asset_file in asset_files:
                # Normalize path for comparison and convert to lowercase
                normalized_file = asset_file.replace('\\', '/').lower()
                relative_path = normalized_file
                
                # Make relative to project root if it's absolute
                if os.path.isabs(asset_file):  # Use original path for isabs check
                    try:
                        relative_path = os.path.relpath(asset_file, project_root).replace('\\', '/').lower()
                    except ValueError:
                        # Can't make relative, use as-is
                        pass
                
                # Check if this asset is referenced in the .yyp (case-insensitive comparison)
                if relative_path not in referenced_paths:
                    asset_type = _get_asset_type_from_path(relative_path)
                    orphans.append((relative_path, asset_type))
        
        return orphans
        
    except Exception as e:
        if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('GMS_TEST_SUITE'):
            print(f"[EXPECTED ERROR] Error finding orphaned assets: {e}")
        else:
            print(f"Error finding orphaned assets: {e}")
        return []


def _get_asset_type_from_path(path: str) -> str:
    normalized = path.replace('\\', '/').lower()
    if normalized.startswith('scripts/'):   return 'script'
    if normalized.startswith('objects/'):   return 'object'
    if normalized.startswith('sprites/'):   return 'sprite'
    if normalized.startswith('rooms/'):     return 'room'
    if normalized.startswith('sounds/'):    return 'sound'
    if normalized.startswith('fonts/'):     return 'font'
    if normalized.startswith('shaders/'):   return 'shader'
    if normalized.startswith('animcurves/'):return 'animcurve'
    if normalized.startswith('folders/'):   return 'folder'
    return 'unknown'


def find_missing_assets(project_root: str = '.') -> List[Tuple[str, str]]:
    """
    Find assets referenced in .yyp but missing from disk.
    
    Returns:
        List of (asset_path, asset_type) tuples for missing assets
    """
    missing = []
    
    try:
        # Load .yyp file
        yyp_path = find_yyp_file()
        yyp_data = load_json(yyp_path)
        
        resources = yyp_data.get('resources', [])
        
        for resource in resources:
            resource_id = resource.get('id', {})
            path = resource_id.get('path', '')
            
            if path:
                # Skip options files - they have special format
                if 'options' in path.lower():
                    continue
                
                asset_type = _get_asset_type_from_path(path)
                # Folders are logical-only; they should not have physical files.
                if asset_type == 'folder':
                    continue  # Never treat folders as missing
                    
                # Check if file exists
                if not os.path.exists(path):
                    missing.append((path, asset_type))
        
        return missing
        
    except Exception as e:
        if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('GMS_TEST_SUITE'):
            print(f"[EXPECTED ERROR] Error finding missing assets: {e}")
        else:
            print(f"Error finding missing assets: {e}")
        return []


def print_orphan_report(orphans: List[Tuple[str, str]], missing: List[Tuple[str, str]]):
    """Print a formatted report of orphaned and missing assets."""
    
    print(f"\n[SCAN] Asset Orphan Report")
    print(f"   Orphaned (on disk, not in .yyp): {len(orphans)}")
    print(f"   Missing (in .yyp, not on disk): {len(missing)}")
    print("-" * 50)
    
    if orphans:
        print(f"\nORPHANED ASSETS:")
        
        # Group by type
        by_type = {}
        for path, asset_type in orphans:
            if asset_type not in by_type:
                by_type[asset_type] = []
            by_type[asset_type].append(path)
        
        for asset_type, paths in by_type.items():
            print(f"\n  {asset_type.upper()}S ({len(paths)}):")
            for path in sorted(paths):
                print(f"    - {path}")
    
    if missing:
        print(f"\nMISSING ASSETS:")
        
        # Group by type
        by_type = {}
        for path, asset_type in missing:
            if asset_type not in by_type:
                by_type[asset_type] = []
            by_type[asset_type].append(path)
        
        for asset_type, paths in by_type.items():
            print(f"\n  {asset_type.upper()}S ({len(paths)}):")
            for path in sorted(paths):
                print(f"    [ERROR] {path}")
    
    if not orphans and not missing:
        print("\n[OK] No orphaned or missing assets found!")
    elif orphans and not missing:
        print(f"\n[INFO] Consider adding orphaned assets to the project or removing them from disk")
    elif missing and not orphans:
        print(f"\n[WARN]  Missing assets should be restored or removed from the .yyp file")
    else:
        print(f"\n[MAINT] Project has both orphaned and missing assets - cleanup recommended") 
