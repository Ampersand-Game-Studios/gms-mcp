"""
Trash system for GameMaker maintenance.
Safely moves assets to a trash folder instead of permanent deletion.
"""

import os
import shutil
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

def move_to_trash(project_root: str, files_to_move: List[str], trash_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Move a list of project files to a timestamped trash folder.
    
    Args:
        project_root: Path to the GameMaker project root
        files_to_move: List of paths relative to project root
        trash_name: Optional custom name for the trash subfolder
        
    Returns:
        Dictionary with statistics and manifest of moved files
    """
    project_root_path = Path(project_root)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_folder_name = f"trash_{timestamp}" if not trash_name else trash_name
    trash_root = project_root_path / ".maintenance_trash" / trash_folder_name
    
    os.makedirs(trash_root, exist_ok=True)
    
    moved_count = 0
    errors = []
    manifest = []
    
    for rel_path in files_to_move:
        src = project_root_path / rel_path
        if not src.exists():
            continue
            
        dst = trash_root / rel_path
        os.makedirs(dst.parent, exist_ok=True)
        
        try:
            # Move the file
            shutil.move(str(src), str(dst))
            moved_count += 1
            manifest.append(rel_path)
        except Exception as e:
            errors.append(f"Failed to move {rel_path}: {e}")
            
    # Write manifest file
    if manifest:
        manifest_path = trash_root / "MANIFEST.txt"
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(f"Maintenance Trash Manifest - {timestamp}\n")
            f.write("=" * 40 + "\n")
            for item in manifest:
                f.write(f"{item}\n")
                
    return {
        "trash_folder": str(trash_root.relative_to(project_root_path)),
        "moved_count": moved_count,
        "errors": errors,
        "manifest": manifest
    }

def get_keep_patterns(project_root: str) -> List[str]:
    """Load patterns from maintenance_keep.txt."""
    keep_file = Path(project_root) / "maintenance_keep.txt"
    if not keep_file.exists():
        return []
        
    patterns = []
    with open(keep_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns
