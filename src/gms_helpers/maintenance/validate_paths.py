"""
Path Validation - Check that all folder paths referenced in assets exist
"""

import os
from typing import List, Tuple, Dict, Set

from ..utils import load_json, find_yyp_file


class PathValidationIssue:
    """Represents a path validation issue."""
    def __init__(self, asset_path: str, asset_name: str, referenced_folder: str, issue_type: str, severity: str = 'error'):
        self.asset_path = asset_path
        self.asset_name = asset_name
        self.referenced_folder = referenced_folder
        self.issue_type = issue_type
        self.severity = severity


def validate_folder_paths(project_root: str = '.', strict_mode: bool = False, include_parent_folders: bool = False) -> List[PathValidationIssue]:
    """
    Validate folder path references in GameMaker project.
    
    Args:
        project_root: Path to project root directory
        strict_mode: If True, also check that folder .yy files exist on disk (legacy behavior)
        include_parent_folders: If True, include parent folders in orphan detection (legacy behavior)
    
    Returns:
        List of PathValidationIssue objects
    """
    try:
        # Load project file
        yyp_path = os.path.join(project_root, find_yyp_file())
        project_data = load_json(yyp_path)
        
        folders = project_data.get('Folders', [])
        resources = project_data.get('resources', [])
        
        # Build set of folder paths defined in .yyp
        defined_folders = set()
        for folder in folders:
            folder_path = folder.get('folderPath', '')
            if folder_path:
                defined_folders.add(folder_path)
        
        # If strict_mode is enabled, also check physical files (legacy behavior)
        existing_folders = set()
        if strict_mode:
            for folder_path in defined_folders:
                if os.path.exists(os.path.join(project_root, folder_path)):
                    existing_folders.add(folder_path)
        else:
            # In non-strict mode, assume all defined folders "exist" logically
            existing_folders = defined_folders.copy()
        
        issues = []
        
        # Check each resource's parent folder reference
        for resource in resources:
            resource_id = resource.get('id', {})
            asset_path = resource_id.get('path', '')
            asset_name = resource_id.get('name', '')
            
            # Skip options files and other non-asset resources
            if 'options' in asset_path.lower() or not asset_path:
                continue
                
            # Load asset file and check parent reference
            full_asset_path = os.path.join(project_root, asset_path)
            if os.path.exists(full_asset_path):
                try:
                    asset_data = load_json(full_asset_path)
                    parent = asset_data.get('parent', {})
                    parent_path = parent.get('path', '')
                    
                    if parent_path:
                        # Skip root-level assets (parent is the .yyp file itself)
                        if parent_path.lower().endswith('.yyp'):
                            continue
                            
                        # Check if parent folder is defined in .yyp
                        if parent_path not in defined_folders:
                            issues.append(PathValidationIssue(
                                asset_path=asset_path,
                                asset_name=asset_name,
                                referenced_folder=parent_path,
                                issue_type='missing_folder_definition',
                                severity='error'
                            ))
                        # In strict mode, also check if folder file exists on disk
                        elif strict_mode and parent_path not in existing_folders:
                            issues.append(PathValidationIssue(
                                asset_path=asset_path,
                                asset_name=asset_name,
                                referenced_folder=parent_path,
                                issue_type='folder_file_missing_on_disk',
                                severity='warning'
                            ))
                    else:
                        # Asset has no parent folder reference
                        issues.append(PathValidationIssue(
                            asset_path=asset_path,
                            asset_name=asset_name,
                            referenced_folder='',
                            issue_type='no_parent_folder',
                            severity='warning'
                        ))
                        
                except Exception as e:
                    # Could not load asset file
                    issues.append(PathValidationIssue(
                        asset_path=asset_path,
                        asset_name=asset_name,
                        referenced_folder='',
                        issue_type=f'asset_load_error: {str(e)}',
                        severity='error'
                    ))
        
        # Check for orphaned folders (folders that exist but aren't referenced by any assets)
        referenced_folders = set()
        
        # Collect all valid folder references from assets
        for resource in resources:
            resource_id = resource.get('id', {})
            asset_path = resource_id.get('path', '')
            
            if asset_path and os.path.exists(os.path.join(project_root, asset_path)) and 'options' not in asset_path.lower():
                try:
                    asset_data = load_json(os.path.join(project_root, asset_path))
                    parent = asset_data.get('parent', {})
                    parent_path = parent.get('path', '')
                    # Skip root-level assets (parent is the .yyp file itself)
                    if parent_path and not parent_path.lower().endswith('.yyp') and parent_path in defined_folders:
                        referenced_folders.add(parent_path)
                except:
                    pass
        
        # Build folder hierarchy tree for subtree analysis
        def build_folder_tree(defined_folders):
            """Build parent-child relationships for all folders"""
            children = {}  # parent_path -> [child_paths]
            
            for folder_path in defined_folders:
                # Extract parent path
                path_parts = folder_path.split('/')
                if len(path_parts) > 2:  # More than just "folders/something.yy"
                    parent_parts = path_parts[:-1]
                    parent_path = '/'.join(parent_parts) + '.yy'
                    
                    if parent_path in defined_folders:
                        if parent_path not in children:
                            children[parent_path] = []
                        children[parent_path].append(folder_path)
            
            return children
        
        def get_assets_in_subtree(folder_path, children, referenced_folders):
            """Recursively count assets in this folder and all its descendants"""
            asset_count = 0
            
            # Count direct assets in this folder
            if folder_path in referenced_folders:
                asset_count += 1
            
            # Count assets in all child folders recursively
            if folder_path in children:
                for child_folder in children[folder_path]:
                    asset_count += get_assets_in_subtree(child_folder, children, referenced_folders)
            
            return asset_count
        
        # Build the folder tree
        folder_children = build_folder_tree(defined_folders)
        
        # Find truly orphaned folders (no assets anywhere in subtree)
        for folder_path in defined_folders:
            # Skip this logic if include_parent_folders is True (use old behavior)
            if include_parent_folders:
                # Original behavior - only check direct references
                if folder_path not in referenced_folders:
                    issues.append(PathValidationIssue(
                        asset_path='',
                        asset_name='',
                        referenced_folder=folder_path,
                        issue_type='orphaned_folder',
                        severity='info'
                    ))
            else:
                # New behavior - check entire subtree for assets
                total_assets_in_subtree = get_assets_in_subtree(folder_path, folder_children, referenced_folders)
                if total_assets_in_subtree == 0:
                    issues.append(PathValidationIssue(
                        asset_path='',
                        asset_name='',
                        referenced_folder=folder_path,
                        issue_type='orphaned_folder',
                        severity='info'
                    ))
        
        return issues
        
    except Exception as e:
        return [PathValidationIssue(
            asset_path='',
            asset_name='',
            referenced_folder='',
            issue_type=f'validation_error: {str(e)}',
            severity='error'
        )]


def print_path_validation_report(issues: List[PathValidationIssue], strict_mode: bool = False):
    """Print a formatted report of path validation results."""
    
    mode_text = " (Strict Mode)" if strict_mode else ""
    print(f"\nFolder Path Validation Report{mode_text}")
    print(f"Found: {len(issues)} issue(s)")
    print("-" * 50)
    
    if not issues:
        print("\nAll folder paths are valid!")
        if strict_mode:
            print("All assets reference existing folders and all folder files exist on disk.")
        else:
            print("All assets reference folders defined in the .yyp file.")
        return
    
    # Group issues by type and severity
    by_type = {}
    by_severity = {'error': [], 'warning': [], 'info': []}
    
    for issue in issues:
        issue_type = issue.issue_type
        if issue_type not in by_type:
            by_type[issue_type] = []
        by_type[issue_type].append(issue)
        by_severity[issue.severity].append(issue)
    
    # Print summary
    error_count = len(by_severity['error'])
    warning_count = len(by_severity['warning'])
    info_count = len(by_severity['info'])
    
    if error_count > 0:
        print(f"\nERRORS ({error_count}):")
        error_types = ['missing_folder_definition', 'asset_load_error']
        _print_issues_by_type(by_type, error_types)
    
    if warning_count > 0:
        print(f"\nWARNINGS ({warning_count}):")
        warning_types = ['folder_file_missing_on_disk', 'no_parent_folder']
        _print_issues_by_type(by_type, warning_types)
    
    if info_count > 0:
        print(f"\nINFO ({info_count}):")
        _print_issues_by_type(by_type, ['orphaned_folder'])
    
    # Print recommendations
    print(f"\nRECOMMENDATIONS:")
    if any(issue.issue_type == 'missing_folder_definition' for issue in issues):
        print("  - Add missing folder definitions to .yyp Folders section or update asset parent paths")
    if any(issue.issue_type == 'folder_file_missing_on_disk' for issue in issues):
        print("  - Create missing folder .yy files on disk (strict mode only)")
    if any(issue.issue_type == 'no_parent_folder' for issue in issues):
        print("  - Add parent folder references to assets")
    if any(issue.issue_type == 'orphaned_folder' for issue in issues):
        print("  - Consider removing unused folders or creating assets that use them")


def _print_issues_by_type(by_type: Dict[str, List[PathValidationIssue]], type_order: List[str]):
    """Print issues grouped by type in specified order."""
    for issue_type in type_order:
        if issue_type in by_type:
            issues = by_type[issue_type]
            
            if issue_type == 'missing_folder_definition':
                print(f"\n  MISSING FOLDER DEFINITIONS ({len(issues)}):")
                for issue in issues:
                    print(f"    MISSING: {issue.referenced_folder}")
                    print(f"             Referenced by: {issue.asset_name} ({issue.asset_path})")
                    
            elif issue_type == 'folder_file_missing_on_disk':
                print(f"\n  FOLDER FILES MISSING ON DISK ({len(issues)}):")
                for issue in issues:
                    print(f"    MISSING FILE: {issue.referenced_folder}")
                    print(f"                  Referenced by: {issue.asset_name} ({issue.asset_path})")
                    
            elif issue_type == 'no_parent_folder':
                print(f"\n  NO PARENT FOLDER ({len(issues)}):")
                for issue in issues:
                    print(f"    NO PARENT: {issue.asset_name} ({issue.asset_path})")
                    
            elif issue_type == 'orphaned_folder':
                print(f"\n  ORPHANED FOLDERS ({len(issues)}):")
                for issue in issues:
                    print(f"    ORPHANED: {issue.referenced_folder}")
                    
            elif 'asset_load_error' in issue_type:
                print(f"\n  ASSET LOAD ERRORS ({len(issues)}):")
                for issue in issues:
                    print(f"    ERROR: {issue.asset_name} ({issue.asset_path})")
                    print(f"           {issue.issue_type}") 
