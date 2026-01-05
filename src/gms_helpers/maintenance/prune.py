"""
Asset Pruning - Remove missing asset references from project file
"""

import os
import shutil
from typing import List, Tuple, Dict, Any

from ..utils import load_json, save_json, find_yyp_file


def prune_missing_assets(project_root: str = '.', dry_run: bool = False) -> List[Tuple[str, str]]:
    """
    Remove references to missing assets from the .yyp file.
    
    Args:
        project_root: Root directory of the project
        dry_run: If True, don't modify files, just report what would be removed
        
    Returns:
        List of (asset_path, asset_type) tuples for removed entries
    """
    removed_entries = []
    
    try:
        # Load .yyp file
        yyp_path = find_yyp_file()
        yyp_data = load_json(yyp_path)
        
        # Process resources array
        original_resources = yyp_data.get('resources', [])
        valid_resources = []
        
        for resource in original_resources:
            resource_id = resource.get('id', {})
            path = resource_id.get('path', '')
            
            if path:
                # Skip options files - they have special format and locations
                if 'options' in path.lower():
                    valid_resources.append(resource)
                    continue
                
                # Determine asset type first
                asset_type = _get_asset_type_from_path(path)
                # Folders are logical only - treat them as always existing
                if asset_type == 'folder':
                    valid_resources.append(resource)
                    continue
                
                # Check if file exists for non-folder assets
                if os.path.exists(path):
                    valid_resources.append(resource)
                else:
                    # File is missing - mark for removal
                    removed_entries.append((path, asset_type))
            else:
                # Keep resources without paths (shouldn't happen but be safe)
                valid_resources.append(resource)
        
        # Process resourceOrder array (if it exists)
        original_resource_order = yyp_data.get('resourceOrder', [])
        valid_resource_order = []
        
        for order_entry in original_resource_order:
            # Resource order entries can be strings or objects
            if isinstance(order_entry, str):
                path = order_entry
            elif isinstance(order_entry, dict):
                path = order_entry.get('path', '')
            else:
                # Unknown format, keep it
                valid_resource_order.append(order_entry)
                continue
            
            if path:
                # Skip options files
                if 'options' in path.lower():
                    valid_resource_order.append(order_entry)
                    continue
                
                asset_type = _get_asset_type_from_path(path)
                if asset_type == 'folder':
                    valid_resource_order.append(order_entry)
                    continue
                
                # Check if file exists
                if os.path.exists(path):
                    valid_resource_order.append(order_entry)
                # If missing, don't add to valid list (effectively removes it)
            else:
                # Keep entries without paths
                valid_resource_order.append(order_entry)
        
        # Apply changes if not dry run
        if not dry_run and removed_entries:
            # Create backup
            backup_path = yyp_path + '.bak'
            shutil.copy2(yyp_path, backup_path)
            
            # Update the data
            yyp_data['resources'] = valid_resources
            if 'resourceOrder' in yyp_data:
                yyp_data['resourceOrder'] = valid_resource_order
            
            # Save the updated file
            save_json(yyp_data, yyp_path)
        
        return removed_entries
        
    except Exception as e:
        print(f"Error during asset pruning: {e}")
        return []


def _get_asset_type_from_path(path: str) -> str:
    """Determine asset type from file path."""
    # Normalize path separators for consistent matching
    normalized_path = path.replace('\\', '/').lower()
    
    if normalized_path.startswith('scripts/'):
        return 'script'
    elif normalized_path.startswith('objects/'):
        return 'object'
    elif normalized_path.startswith('sprites/'):
        return 'sprite'
    elif normalized_path.startswith('rooms/'):
        return 'room'
    elif normalized_path.startswith('sounds/'):
        return 'sound'
    elif normalized_path.startswith('fonts/'):
        return 'font'
    elif normalized_path.startswith('shaders/'):
        return 'shader'
    elif normalized_path.startswith('animcurves/'):
        return 'animcurve'
    elif normalized_path.startswith('folders/'):
        return 'folder'
    else:
        return 'unknown'


def print_prune_report(removed_entries: List[Tuple[str, str]], dry_run: bool = False):
    """Print a formatted report of pruning results."""
    
    action = "Would remove" if dry_run else "Removed"
    
    print(f"\n[CLEAN] Asset Pruning Report")
    print(f"   {action}: {len(removed_entries)} missing reference(s)")
    print("-" * 50)
    
    if removed_entries:
        # Group by type
        by_type = {}
        for path, asset_type in removed_entries:
            if asset_type not in by_type:
                by_type[asset_type] = []
            by_type[asset_type].append(path)
        
        print(f"\n{action.upper()}:")
        for asset_type, paths in by_type.items():
            print(f"\n  {asset_type.upper()}S ({len(paths)}):")
            for path in sorted(paths):
                print(f"    [DELETE]  {path}")
        
        if dry_run:
            print(f"\n[INFO] Run without --dry-run to apply changes")
        else:
            print(f"\n[OK] Backup created: gms2-template.yyp.bak")
            print(f"[OK] Project file cleaned and formatted")
    else:
        print("\n[OK] No missing asset references found!")
        print("Project file is already clean.") 
