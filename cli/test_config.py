"""Test configuration - single source of truth for import paths.

This file centralizes all test import configuration so that if we need to 
reorganize the project structure in the future, we only need to change paths here.

## Purpose
Manages import paths for the entire test suite to avoid hardcoded package references.
When the package structure changes, update REAL_PACKAGE_PATH and run the bulk updater.

## Usage
- **View current config**: Check REAL_PACKAGE_PATH below
- **Change package location**: Update REAL_PACKAGE_PATH 
- **Apply changes**: Run `python cli/update_test_imports.py`
- **Verify**: All imports across 20+ test files update automatically

## Project Structure
Current organization:
```
gms2-template/
├── gamemaker/           # GameMaker project (.yyp, assets)
├── cli/
│   ├── gms_helpers/     # Main CLI toolkit
│   ├── test_config.py   # This file
│   └── update_test_imports.py  # Bulk updater
└── tests/python/        # Test suite
```

## Example Migration
To change import prefixes across tests:
1. Change REAL_PACKAGE_PATH below
2. Run: python cli/update_test_imports.py
3. Done! All 110+ imports updated automatically
"""

from pathlib import Path

# The real import prefix used by tests
# Note: the CLI code lives in ./cli/gms_helpers, but the Python package name remains "gms_helpers".
# Tests should ensure ./cli is on sys.path so "import gms_helpers" works.
REAL_PACKAGE_PATH = "gms_helpers"

# Legacy import patterns to replace (in order of specificity)
IMPORT_REPLACEMENTS = [
    # Patch decorators
    (r"@patch\('tooling\.gms_helpers\.([^']+)'\)", rf"@patch('{REAL_PACKAGE_PATH}.\1')"),
    (r"@patch\('gms_helpers\.([^']+)'\)", rf"@patch('{REAL_PACKAGE_PATH}.\1')"),
    
    # Direct imports
    (r"from tooling\.gms_helpers\.([^\s]+) import", rf"from {REAL_PACKAGE_PATH}.\1 import"),
    (r"from tooling\.gms_helpers import", rf"from {REAL_PACKAGE_PATH} import"),
    (r"import tooling\.gms_helpers\.([^\s]+)", rf"import {REAL_PACKAGE_PATH}.\1"),
    (r"import tooling\.gms_helpers", rf"import {REAL_PACKAGE_PATH}"),
    (r"from gms_helpers\.([^\s]+) import", rf"from {REAL_PACKAGE_PATH}.\1 import"),
    (r"from gms_helpers import", rf"from {REAL_PACKAGE_PATH} import"),
    (r"import gms_helpers\.([^\s]+)", rf"import {REAL_PACKAGE_PATH}.\1"),
    (r"import gms_helpers", rf"import {REAL_PACKAGE_PATH}"),
    
    # importlib calls
    (r'importlib\.import_module\("tooling\.gms_helpers\.([^"]+)"\)', rf'importlib.import_module("{REAL_PACKAGE_PATH}.\1")'),
    (r'importlib\.import_module\("tooling\.gms_helpers"\)', rf'importlib.import_module("{REAL_PACKAGE_PATH}")'),
    (r'importlib\.import_module\("gms_helpers\.([^"]+)"\)', rf'importlib.import_module("{REAL_PACKAGE_PATH}.\1")'),
    (r'importlib\.import_module\("gms_helpers"\)', rf'importlib.import_module("{REAL_PACKAGE_PATH}")'),
]

# Project structure
PROJECT_ROOT_RELATIVE_TO_TESTS = "../.."  # tests/python -> project root
TEST_DIRECTORIES = ["tests/python"]

def get_project_root_setup_code():
    """Generate the standard project root setup code for test files."""
    return f"""# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))"""

def get_real_import_path(legacy_path):
    """Convert a legacy import path to the real package path."""
    if legacy_path.startswith("gms_helpers"):
        return legacy_path.replace("gms_helpers", REAL_PACKAGE_PATH, 1)
    return legacy_path 