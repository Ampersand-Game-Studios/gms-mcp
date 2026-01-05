#!/usr/bin/env python3
"""
Reference Scanner - Comprehensive asset reference detection and updating
Finds ALL references to assets across GameMaker project files
"""

import json
import re
import os
from pathlib import Path
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass

from .utils import load_json_loose, save_pretty_json_gm
from .exceptions import GMSError


@dataclass
class AssetReference:
    """Represents a reference to an asset that needs updating"""
    file_path: Path
    line_number: int
    old_text: str
    new_text: str
    reference_type: str  # 'json_field', 'sprite_sequence', 'script_reference', etc.
    context: str  # Additional context about the reference


class ReferenceScanner:
    """Comprehensive asset reference scanner and updater"""
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.references: List[AssetReference] = []
    
    def find_all_asset_references(self, old_name: str, new_name: str, asset_type: str) -> List[AssetReference]:
        """Find ALL references to an asset across the project"""
        self.references.clear()
        
        # 1. Scan .yyp project files
        self._scan_project_files(old_name, new_name, asset_type)
        
        # 2. Scan resource order files
        self._scan_resource_order_files(old_name, new_name, asset_type)
        
        # 3. Scan sprite internal references (sequences, keyframes)
        if asset_type == "sprite":
            self._scan_sprite_internal_references(old_name, new_name)
        
        # 4. Scan script files for asset references
        self._scan_script_references(old_name, new_name, asset_type)
        
        # 5. Scan object event files
        self._scan_object_event_references(old_name, new_name, asset_type)
        
        # 6. Scan asset internal JSON files
        self._scan_asset_internal_json(old_name, new_name, asset_type)
        
        return self.references
    
    def _scan_project_files(self, old_name: str, new_name: str, asset_type: str):
        """Scan .yyp project files for asset references"""
        for yyp_file in self.project_root.glob("*.yyp"):
            try:
                with open(yyp_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if old_name in line:
                        # Check if this is a resource reference
                        if '"name"' in line and f'"{old_name}"' in line:
                            new_line = line.replace(f'"{old_name}"', f'"{new_name}"')
                            self.references.append(AssetReference(
                                file_path=yyp_file,
                                line_number=i + 1,
                                old_text=line.strip(),
                                new_text=new_line.strip(),
                                reference_type="project_resource_name",
                                context=f"Project file resource name reference"
                            ))
                        
                        # Check if this is a path reference
                        if '"path"' in line and old_name in line:
                            old_path_pattern = f"{asset_type}s/{old_name}/{old_name}.yy"
                            new_path_pattern = f"{asset_type}s/{new_name}/{new_name}.yy"
                            if old_path_pattern in line:
                                new_line = line.replace(old_path_pattern, new_path_pattern)
                                self.references.append(AssetReference(
                                    file_path=yyp_file,
                                    line_number=i + 1,
                                    old_text=line.strip(),
                                    new_text=new_line.strip(),
                                    reference_type="project_resource_path",
                                    context=f"Project file resource path reference"
                                ))
                                
            except Exception as e:
                print(f"Warning: Could not scan {yyp_file}: {e}")
    
    def _scan_resource_order_files(self, old_name: str, new_name: str, asset_type: str):
        """Scan .resource_order files for asset references"""
        for resource_file in self.project_root.glob("*.resource_order"):
            try:
                with open(resource_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if old_name in line:
                        # Update resource order entries
                        old_path_pattern = f"{asset_type}s/{old_name}/{old_name}.yy"
                        new_path_pattern = f"{asset_type}s/{new_name}/{new_name}.yy"
                        
                        # Handle path references
                        if old_path_pattern in line:
                            new_line = line.replace(old_name, new_name).replace(old_path_pattern, new_path_pattern)
                            self.references.append(AssetReference(
                                file_path=resource_file,
                                line_number=i + 1,
                                old_text=line.strip(),
                                new_text=new_line.strip(),
                                reference_type="resource_order",
                                context=f"Resource order file reference"
                            ))
                        # Handle standalone name references
                        elif '"name"' in line and f'"{old_name}"' in line:
                            new_line = line.replace(f'"{old_name}"', f'"{new_name}"')
                            self.references.append(AssetReference(
                                file_path=resource_file,
                                line_number=i + 1,
                                old_text=line.strip(),
                                new_text=new_line.strip(),
                                reference_type="resource_order_name",
                                context=f"Resource order name reference"
                            ))
                            
            except Exception as e:
                print(f"Warning: Could not scan {resource_file}: {e}")
    
    def _scan_sprite_internal_references(self, old_name: str, new_name: str):
        """Scan sprite .yy files for internal sequence and keyframe references"""
        # Try old directory first (if rename hasn't happened yet)
        sprite_dir = self.project_root / "sprites" / old_name
        sprite_yy = sprite_dir / f"{old_name}.yy"
        
        # If old directory doesn't exist, sprite was already moved - look in new directory
        if not sprite_dir.exists() or not sprite_yy.exists():
            sprite_dir = self.project_root / "sprites" / new_name
            sprite_yy = sprite_dir / f"{new_name}.yy"
            
        if not sprite_dir.exists() or not sprite_yy.exists():
            return
            
        try:
            with open(sprite_yy, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if old_name in line:
                    # Update sequence names
                    if '"%Name"' in line and f'"{old_name}"' in line:
                        new_line = line.replace(f'"{old_name}"', f'"{new_name}"')
                        self.references.append(AssetReference(
                            file_path=sprite_yy,
                            line_number=i + 1,
                            old_text=line.strip(),
                            new_text=new_line.strip(),
                            reference_type="sprite_sequence_name",
                            context=f"Sprite sequence name reference"
                        ))
                    
                    # Update sequence object names
                    if '"name"' in line and f'"{old_name}"' in line and '"$GMSequence"' in content[max(0, content.find(line) - 200):content.find(line) + 200]:
                        new_line = line.replace(f'"{old_name}"', f'"{new_name}"')
                        self.references.append(AssetReference(
                            file_path=sprite_yy,
                            line_number=i + 1,
                            old_text=line.strip(),
                            new_text=new_line.strip(),
                            reference_type="sprite_sequence_object_name",
                            context=f"Sprite sequence object name reference"
                        ))
                    
                    # Update keyframe path references (handle full path in one go)
                    if '"path"' in line and f"sprites/{old_name}/{old_name}.yy" in line:
                        new_line = line.replace(f"sprites/{old_name}/{old_name}.yy", f"sprites/{new_name}/{new_name}.yy")
                        self.references.append(AssetReference(
                            file_path=sprite_yy,
                            line_number=i + 1,
                            old_text=line.strip(),
                            new_text=new_line.strip(),
                            reference_type="sprite_keyframe_path",
                            context=f"Sprite keyframe full path reference"
                        ))
                    # Handle partial directory path references
                    elif '"path"' in line and f"sprites/{old_name}/" in line:
                        new_line = line.replace(f"sprites/{old_name}/", f"sprites/{new_name}/")
                        self.references.append(AssetReference(
                            file_path=sprite_yy,
                            line_number=i + 1,
                            old_text=line.strip(),
                            new_text=new_line.strip(),
                            reference_type="sprite_keyframe_path",
                            context=f"Sprite keyframe directory path reference"
                        ))
                    # Handle standalone filename references
                    elif '"path"' in line and f"/{old_name}.yy" in line:
                        new_line = line.replace(f"/{old_name}.yy", f"/{new_name}.yy")
                        self.references.append(AssetReference(
                            file_path=sprite_yy,
                            line_number=i + 1,
                            old_text=line.strip(),
                            new_text=new_line.strip(),
                            reference_type="sprite_keyframe_filename",
                            context=f"Sprite keyframe .yy filename reference"
                        ))
                        
        except Exception as e:
            print(f"Warning: Could not scan sprite internals for {sprite_yy}: {e}")
    
    def _scan_script_references(self, old_name: str, new_name: str, asset_type: str):
        """Scan script files for asset references"""
        scripts_dir = self.project_root / "scripts"
        if not scripts_dir.exists():
            return
            
        for script_file in scripts_dir.rglob("*.gml"):
            try:
                with open(script_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    # Look for asset references in GML code
                    if old_name in line:
                        # Object references
                        if asset_type == "object" and re.search(rf'\b{re.escape(old_name)}\b', line):
                            new_line = re.sub(rf'\b{re.escape(old_name)}\b', new_name, line)
                            self.references.append(AssetReference(
                                file_path=script_file,
                                line_number=i + 1,
                                old_text=line.strip(),
                                new_text=new_line.strip(),
                                reference_type="script_object_reference",
                                context=f"Script object reference"
                            ))
                        
                        # Sprite references  
                        elif asset_type == "sprite" and re.search(rf'\b{re.escape(old_name)}\b', line):
                            new_line = re.sub(rf'\b{re.escape(old_name)}\b', new_name, line)
                            self.references.append(AssetReference(
                                file_path=script_file,
                                line_number=i + 1,
                                old_text=line.strip(),
                                new_text=new_line.strip(),
                                reference_type="script_sprite_reference",
                                context=f"Script sprite reference"
                            ))
                    
                    # TestEnum references (check separately from direct name references)
                    if asset_type == "object" and "TestEnum." in line and old_name.startswith("o_"):
                        # Generic pattern: o_prefix_name -> TestEnum.prefix_name
                        # Extract the enum part by removing "o_" prefix
                        enum_old = old_name[2:]  # Remove "o_" prefix
                        enum_new = new_name[2:]  # Remove "o_" prefix
                        
                        if f"TestEnum.{enum_old}" in line:
                            new_line = line.replace(f"TestEnum.{enum_old}", f"TestEnum.{enum_new}")
                            self.references.append(AssetReference(
                                file_path=script_file,
                                line_number=i + 1,
                                old_text=line.strip(),
                                new_text=new_line.strip(),
                                reference_type="script_enum_reference",
                                context=f"Script TestEnum enum reference"
                            ))
                        
            except Exception as e:
                print(f"Warning: Could not scan script {script_file}: {e}")
    
    def _scan_object_event_references(self, old_name: str, new_name: str, asset_type: str):
        """Scan object event files for asset references"""
        objects_dir = self.project_root / "objects"
        if not objects_dir.exists():
            return
            
        for event_file in objects_dir.rglob("*.gml"):
            try:
                with open(event_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if old_name in line:
                        # Similar to script references but in object events
                        if asset_type == "object" and re.search(rf'\b{re.escape(old_name)}\b', line):
                            new_line = re.sub(rf'\b{re.escape(old_name)}\b', new_name, line)
                            self.references.append(AssetReference(
                                file_path=event_file,
                                line_number=i + 1,
                                old_text=line.strip(),
                                new_text=new_line.strip(),
                                reference_type="event_object_reference",
                                context=f"Object event reference"
                            ))
                            
            except Exception as e:
                print(f"Warning: Could not scan object event {event_file}: {e}")
    
    def _scan_asset_internal_json(self, old_name: str, new_name: str, asset_type: str):
        """Scan asset's own .yy files for internal references that weren't caught by rename"""
        # This catches any remaining internal references within the asset's own JSON
        # Look in the old directory since renaming hasn't happened yet
        asset_dir = self.project_root / f"{asset_type}s" / old_name
        if not asset_dir.exists():
            return
            
        for yy_file in asset_dir.glob("*.yy"):
            try:
                with open(yy_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if old_name in line and new_name not in line:
                        # Catch any remaining old name references
                        new_line = line.replace(old_name, new_name)
                        self.references.append(AssetReference(
                            file_path=yy_file,
                            line_number=i + 1,
                            old_text=line.strip(),
                            new_text=new_line.strip(),
                            reference_type="asset_internal_json",
                            context=f"Asset internal JSON reference"
                        ))
                        
            except Exception as e:
                print(f"Warning: Could not scan asset internal JSON {yy_file}: {e}")
    
    def update_all_references(self, references: List[AssetReference]) -> Tuple[int, int]:
        """Update all found references atomically"""
        updated_files = set()
        total_updates = 0
        
        # Group references by file for batch updates
        file_references: Dict[Path, List[AssetReference]] = {}
        for ref in references:
            if ref.file_path not in file_references:
                file_references[ref.file_path] = []
            file_references[ref.file_path].append(ref)
        
        # Update each file
        for file_path, refs in file_references.items():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Sort references by line number in reverse order to avoid line number shifts
                refs_sorted = sorted(refs, key=lambda r: r.line_number, reverse=True)
                
                for ref in refs_sorted:
                    if ref.line_number <= len(lines):
                        # Update the line
                        lines[ref.line_number - 1] = lines[ref.line_number - 1].replace(
                            ref.old_text.strip(), 
                            ref.new_text.strip()
                        )
                        if not lines[ref.line_number - 1].endswith('\n'):
                            lines[ref.line_number - 1] += '\n'
                        total_updates += 1
                
                # Write back the file
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                
                updated_files.add(file_path)
                
            except Exception as e:
                print(f"Error updating {file_path}: {e}")
        
        return len(updated_files), total_updates
    
    def validate_no_stale_references(self, old_name: str) -> List[str]:
        """Validate that no stale references to the old name remain"""
        stale_references = []
        
        # Search all relevant files for any remaining references
        search_patterns = [
            "*.yyp", "*.resource_order", "*.yy", "*.gml"
        ]
        
        for pattern in search_patterns:
            for file_path in self.project_root.rglob(pattern):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if old_name in content:
                        # Check if this is a legitimate reference or a stale one
                        lines = content.split('\n')
                        for i, line in enumerate(lines):
                            if old_name in line:
                                stale_references.append(f"{file_path}:{i+1}: {line.strip()}")
                                
                except Exception:
                    # Skip files that can't be read
                    continue
        
        return stale_references


def comprehensive_rename_asset(project_root: Path, old_name: str, new_name: str, asset_type: str) -> bool:
    """
    Perform comprehensive asset renaming with full reference updates
    
    Args:
        project_root: Path to GameMaker project root
        old_name: Current asset name
        new_name: New asset name
        asset_type: Type of asset (sprite, object, script, etc.)
        
    Returns:
        True if successful, False if errors occurred
    """
    scanner = ReferenceScanner(project_root)
    
    print(f"[SCAN] Scanning for all references to {old_name}...")
    references = scanner.find_all_asset_references(old_name, new_name, asset_type)
    
    if references:
        print(f"[FILE] Found {len(references)} references to update:")
        for ref in references[:10]:  # Show first 10
            print(f"   {ref.file_path.name}:{ref.line_number} - {ref.reference_type}")
        if len(references) > 10:
            print(f"   ... and {len(references) - 10} more")
        
        print("[MAINT] Updating all references...")
        files_updated, total_updates = scanner.update_all_references(references)
        print(f"[OK] Updated {total_updates} references in {files_updated} files")
    else:
        print("[INFO]  No additional references found to update")
    
    # Validate no stale references remain
    print("[SCAN] Validating no stale references remain...")
    stale_refs = scanner.validate_no_stale_references(old_name)
    if stale_refs:
        print("[WARN]  Warning: Some references may still contain the old name:")
        for ref in stale_refs[:5]:  # Show first 5
            print(f"   {ref}")
        if len(stale_refs) > 5:
            print(f"   ... and {len(stale_refs) - 5} more")
        return False
    else:
        print("[OK] No stale references found - rename completed successfully")
        return True


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python reference_scanner.py <project_root> <old_name> <new_name> <asset_type>")
        sys.exit(1)
    
    project_root = Path(sys.argv[1])
    old_name = sys.argv[2]
    new_name = sys.argv[3]
    asset_type = sys.argv[4]
    
    try:
        success = comprehensive_rename_asset(project_root, old_name, new_name, asset_type)
        sys.exit(0 if success else 1)
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        sys.exit(e.exit_code)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
