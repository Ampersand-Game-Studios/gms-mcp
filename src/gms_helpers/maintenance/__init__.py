"""
GameMaker Asset Maintenance Tools
=================================

This sub-package contains tools for maintaining existing GameMaker assets:
- Linting and validation
- Asset duplication and renaming
- Project cleanup utilities
- JSON formatting fixes
"""

# Import maintenance modules
from .orphans import find_orphaned_assets
from .validate_paths import validate_folder_paths
from .clean_unused_assets import clean_unused_folders, clean_old_yy_files
from .orphan_cleanup import delete_orphan_files, find_delete_candidates

__version__ = "1.0.0"
__all__ = [
    "lint",
    "tidy_json", 
    "orphans",
    "dup",
    "rename",
    "move",
    "delete",
    "find_orphaned_assets",
    "validate_folder_paths",
    "clean_unused_folders",
    "clean_old_yy_files",
    "delete_orphan_files",
    "find_delete_candidates"
] 