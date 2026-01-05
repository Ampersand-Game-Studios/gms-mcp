#!/usr/bin/env python3
"""
Bulk update test imports to use the correct package path.
Reads configuration from test_config.py for easy future changes.

Usage:
    python cli/update_test_imports.py [--dry-run] [--verbose]
"""

import re
import sys
import argparse
from pathlib import Path
from typing import List, Tuple

# Make console output Unicode-safe on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from test_config import IMPORT_REPLACEMENTS, TEST_DIRECTORIES, get_project_root_setup_code

def update_imports_in_file(file_path: Path, dry_run: bool = False, verbose: bool = False) -> Tuple[bool, List[str]]:
    """
    Update all import patterns in a single file.
    
    Returns:
        (changed, changes_made): Whether file was modified and list of changes
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"ERROR reading {file_path}: {e}")
        return False, []
    
    original_content = content
    changes_made = []
    
    # Apply all import replacements
    for pattern, replacement in IMPORT_REPLACEMENTS:
        matches = list(re.finditer(pattern, content))
        if matches:
            content = re.sub(pattern, replacement, content)
            for match in matches:
                changes_made.append(f"Line ~{content[:match.start()].count(chr(10)) + 1}: {match.group()}")
    
    # Update sys.path setup patterns
    legacy_path_patterns = [
        (r"sys\.path\.insert\(0, os\.path\.join\(os\.path\.dirname\(__file__\), '[^']+'\)\)",
         "sys.path.insert(0, str(PROJECT_ROOT))"),
        (r"sys\.path\.insert\(0, str\(Path\(__file__\)\.parent\)\)",
         "sys.path.insert(0, str(PROJECT_ROOT))"),
        (r"# Add parent directory to path",
         "# Add project root to path"),
    ]
    
    for pattern, replacement in legacy_path_patterns:
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            changes_made.append(f"Updated sys.path setup")
    
    # Add PROJECT_ROOT setup if missing and we have imports
    if "gms_helpers" in content and "PROJECT_ROOT = Path(__file__)" not in content:
        # Find where to insert the setup code
        lines = content.split('\n')
        insert_index = 0
        
        # Find good insertion point (after imports, before main code)
        for i, line in enumerate(lines):
            if line.strip().startswith('import ') or line.strip().startswith('from '):
                insert_index = i + 1
            elif line.strip() and not line.strip().startswith('#') and not line.strip().startswith('"""'):
                break
        
        # Insert the setup code
        setup_lines = get_project_root_setup_code().split('\n')
        lines[insert_index:insert_index] = [''] + setup_lines + ['']
        content = '\n'.join(lines)
        changes_made.append("Added PROJECT_ROOT setup")
    
    # Check if file actually changed
    if content == original_content:
        return False, []
    
    if not dry_run:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if verbose:
                print(f"[OK] Updated {file_path}")
        except Exception as e:
            print(f"[ERROR] Error writing {file_path}: {e}")
            return False, changes_made
    else:
        if verbose:
            print(f"[SCAN] Would update {file_path}")
    
    return True, changes_made

def find_test_files() -> List[Path]:
    """Find all Python test files in configured directories."""
    project_root = Path(__file__).parent.parent
    test_files = []
    
    for test_dir in TEST_DIRECTORIES:
        test_path = project_root / test_dir
        if test_path.exists():
            # Find all .py files
            for py_file in test_path.rglob("*.py"):
                # Skip __pycache__ and other non-test files
                if "__pycache__" not in str(py_file) and py_file.name != "__init__.py":
                    test_files.append(py_file)
    
    return sorted(test_files)

def update_all_test_files(dry_run: bool = False, verbose: bool = False) -> None:
    """Find and update all test files."""
    print("Bulk Test Import Updater")
    print("=" * 50)
    
    test_files = find_test_files()
    print(f"Found {len(test_files)} test files")
    
    if dry_run:
        print("DRY RUN MODE - No files will be modified")
    
    print()
    
    total_updated = 0
    total_changes = 0
    
    for test_file in test_files:
        changed, changes = update_imports_in_file(test_file, dry_run, verbose)
        
        if changed:
            total_updated += 1
            total_changes += len(changes)
            
            if verbose and changes:
                print(f"  Changes in {test_file.name}:")
                for change in changes[:3]:  # Show first 3 changes
                    print(f"    - {change}")
                if len(changes) > 3:
                    print(f"    - ... and {len(changes) - 3} more")
                print()
    
    print("=" * 50)
    print("Summary:")
    print(f"  Files updated: {total_updated}")
    print(f"  Total changes: {total_changes}")
    
    if dry_run and total_updated > 0:
        print("\nRun without --dry-run to apply these changes")
    elif total_updated > 0:
        print("\nImport updates completed successfully.")
        print("You can now run the tests to verify everything works.")
    else:
        print("\nAll imports are already up to date.")

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bulk update test imports to use correct package paths"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Preview changes without modifying files"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true", 
        help="Show detailed information about changes"
    )
    
    args = parser.parse_args()
    
    try:
        update_all_test_files(dry_run=args.dry_run, verbose=args.verbose)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 