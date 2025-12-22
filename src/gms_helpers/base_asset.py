"""
Base class for GameMaker asset creation
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional

from .utils import ensure_directory, save_pretty_json_gm


class BaseAsset(ABC):
    """Base class for all GameMaker asset types."""
    
    # Override these in subclasses
    kind: str = "base"
    folder_prefix: str = "unknown"
    gm_tag: str = "GMUnknown"
    
    def __init__(self):
        pass
    
    @abstractmethod
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        """Create the .yy JSON data for this asset type."""
        pass
    
    @abstractmethod
    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        """Create any additional files (like .gml files for scripts)."""
        pass
    
    def get_folder_path(self, project_root: Path, name: str) -> Path:
        """Get the full path where this asset should be created."""
        # All physical folders are stored on disk in *lower-case* to avoid
        # cross-platform case-sensitivity headaches (e.g. Linux CI runners).
        # File names (.yy, .gml, etc.) retain their original GameMaker-style
        # casing, only the directory slug is normalised.
        return project_root / self.folder_prefix / name.lower()
    
    def get_yy_path(self, asset_folder: Path, name: str) -> Path:
        """Get the path for the .yy file."""
        return asset_folder / f"{name}.yy"
    
    def create_files(self, project_root: Path, name: str, parent_path: str, **kwargs) -> str:
        """
        Create all files for this asset type.
        Returns the relative path to the .yy file for .yyp insertion.
        """
        # If no parent folder is provided, match GameMaker IDE behavior:
        # root-level assets use the project itself as parent (e.g. "BLANK GAME.yyp"),
        # not an empty parent path (which breaks linking).
        if not parent_path:
            try:
                from .utils import find_yyp
                parent_path = find_yyp(project_root).name
            except Exception:
                # Best-effort fallback: keep original (may be empty) if we can't resolve a .yyp.
                pass

        # Create the asset folder
        asset_folder = self.get_folder_path(project_root, name)
        ensure_directory(asset_folder)
        
        # Create the .yy file
        yy_path = self.get_yy_path(asset_folder, name)
        if not yy_path.exists():
            yy_data = self.create_yy_data(name, parent_path, **kwargs)
            save_pretty_json_gm(yy_path, yy_data)
            print(f"Created {yy_path.relative_to(project_root)}")
        else:
            print(f"Asset {name} already exists - skipping .yy creation")
        
        # Create stub files
        self.create_stub_files(asset_folder, name, **kwargs)
        
        # Return relative path for .yyp insertion
        return yy_path.relative_to(project_root).as_posix()
    
    def validate_name(self, name: str) -> bool:
        """Validate asset name according to GameMaker conventions."""
        # Basic validation - can be overridden in subclasses
        if not name:
            return False
        if not name.replace("_", "").replace("-", "").isalnum():
            return False
        return True
    
    def get_parent_name(self, parent_path: str) -> str:
        """Extract parent folder name from path."""
        return Path(parent_path).stem 
