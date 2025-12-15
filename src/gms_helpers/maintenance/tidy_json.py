"""
JSON Validation - Check JSON files for syntax issues (non-destructive)
"""

import os
import re
import glob
from pathlib import Path
from typing import List, Tuple

from ..utils import load_json, save_json


def validate_file(file_path: str) -> Tuple[bool, str]:
    """
    Validate JSON syntax in a file without modifying it.
    
    Returns:
        (is_valid, message) - whether file has valid JSON and status message
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Skip options files - they have special format
        if 'options' in file_path.lower():
            return True, "Skipped (options file)"
        
        # Try to parse the JSON content using our load_json function that handles trailing commas
        try:
            # Use our load_json function which handles trailing commas properly
            from pathlib import Path
            load_json(file_path)
            return True, "Valid JSON"
        except Exception as e:
            return False, f"Invalid JSON: {e}"
            
    except Exception as e:
        return False, f"Error reading file: {e}"


def validate_project_json(project_root: str = '.') -> List[Tuple[str, bool, str]]:
    """
    Validate JSON syntax in all project files without modifying them.
    
    Returns:
        List of (file_path, is_valid, message) tuples
    """
    results = []
    
    # Find all .yy files and the main .yyp file
    yy_pattern = str(Path(project_root) / "**" / "*.yy")
    yy_files = glob.glob(yy_pattern, recursive=True)
    
    # Add .yyp file
    yyp_pattern = str(Path(project_root) / "*.yyp")
    yyp_files = glob.glob(yyp_pattern)
    
    all_files = yy_files + yyp_files
    
    for file_path in all_files:
        is_valid, message = validate_file(file_path)
        results.append((file_path, is_valid, message))
    
    return results


def print_json_validation_report(results: List[Tuple[str, bool, str]]):
    """Print a formatted report of JSON validation results."""
    valid_files = [r for r in results if r[1]]
    invalid_files = [r for r in results if not r[1]]
    
    print(f"\n[SCAN] JSON Validation Report")
    print(f"   Valid: {len(valid_files)} file(s)")
    print(f"   Invalid: {len(invalid_files)} file(s)")
    print("-" * 50)
    
    if invalid_files:
        print(f"\n[ERROR] INVALID FILES:")
        for file_path, _, message in invalid_files:
            print(f"  [ERROR] {file_path}: {message}")
    
    if valid_files and len(valid_files) <= 10:  # Don't spam with too many valid files
        print(f"\n[OK] VALID FILES:")
        for file_path, _, message in valid_files:
            print(f"  [OK] {file_path}: {message}")
    elif len(valid_files) > 10:
        print(f"\n[OK] VALID FILES: {len(valid_files)} files (not shown)")
    
    if invalid_files:
        print(f"\n[INFO] Fix syntax errors in the invalid files listed above")
    else:
        print(f"\n[OK] All JSON files have valid syntax!") 
