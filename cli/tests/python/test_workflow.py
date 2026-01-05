#!/usr/bin/env python3
"""Tests for workflow utilities (Part C)."""

import os
import shutil
import tempfile
from pathlib import Path
import unittest

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to the path
import sys
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import from the correct location
from gms_helpers.workflow import duplicate_asset, rename_asset, delete_asset, lint_project
from gms_helpers.utils import save_pretty_json, load_json_loose
from gms_helpers.assets import ScriptAsset

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
            # Register the asset in the .yyp so maintenance doesn't treat it as orphaned.
            yyp_path = proj / "test.yyp"
            project_data = load_json_loose(yyp_path) or {}
            resources = project_data.setdefault("resources", [])
            resources.append({"id": {"name": "original", "path": original_path}})
            save_pretty_json(yyp_path, project_data)
            # Duplicate
            duplicate_asset(proj, original_path, "copy")
            self.assertTrue((proj / "scripts" / "copy" / "copy.yy").exists())
            self.assertFalse((proj / "scripts" / "copy" / "original.yy").exists())
            # Rename
            rename_asset(proj, original_path, "renamed")
            self.assertTrue((proj / "scripts" / "renamed" / "renamed.yy").exists())
            self.assertFalse((proj / "scripts" / "renamed" / "original.yy").exists())

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
            result = lint_project(proj)
            self.assertTrue(result.success)
            self.assertEqual(result.issues_found, 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
