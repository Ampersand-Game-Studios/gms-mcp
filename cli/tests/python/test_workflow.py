#!/usr/bin/env python3
"""Tests for workflow utilities (Part C)."""

import os
import shutil
import tempfile
from pathlib import Path
import unittest

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add the tooling directory to the path
import sys
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'tooling' / 'gms_helpers'))

# Import from the correct location
from workflow import duplicate_asset, rename_asset, delete_asset, lint_project
from utils import save_pretty_json
from assets import ScriptAsset

class TempProject:
    """Context manager to build a tiny GM project for testing."""
    def __enter__(self):
        self.original_cwd = os.getcwd()  # Save current directory
        self.dir = Path(tempfile.mkdtemp())
        # Build basic project
        for f in ["scripts", "objects", "sprites", "rooms", "folders"]:
            (self.dir / f).mkdir()
        # Minimal .yyp
        save_pretty_json(self.dir / "test.yyp", {"resources": [], "Folders": []})
        os.chdir(self.dir)  # Change to temp directory
        return self.dir
    def __exit__(self, exc_type, exc, tb):
        os.chdir(self.original_cwd)  # Restore original directory
        shutil.rmtree(self.dir)

class TestWorkflow(unittest.TestCase):
    def test_duplicate_and_rename(self):
        with TempProject() as proj:
            # Create a script asset to duplicate using ScriptAsset class
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "original", "")
            original_path = "scripts/original/original.yy"
            # Duplicate
            duplicate_asset(proj, original_path, "copy")
            self.assertTrue((proj / "scripts" / "copy" / "copy.yy").exists())
            # Rename
            rename_asset(proj, original_path, "renamed")
            self.assertTrue((proj / "scripts" / "renamed" / "renamed.yy").exists())
        
    def test_delete_and_lint(self):
        with TempProject() as proj:
            # Create a script asset to delete using ScriptAsset class
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "todelete", "")
            yy_path = "scripts/todelete/todelete.yy"
            # Delete asset
            delete_asset(proj, yy_path, dry_run=False)
            self.assertFalse((proj / "scripts" / "todelete").exists())
            # Lint should pass (zero problems)
            self.assertEqual(lint_project(proj), 0)

if __name__ == "__main__":
    unittest.main(verbosity=2) 