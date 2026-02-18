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
from gms_helpers.workflow import duplicate_asset, rename_asset, delete_asset, lint_project, safe_delete_asset
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
    def _register_resource(self, project_root: Path, name: str, rel_path: str):
        yyp_path = project_root / "test.yyp"
        project_data = load_json_loose(yyp_path) or {}
        resources = project_data.setdefault("resources", [])
        resources.append({"id": {"name": name, "path": rel_path}})
        save_pretty_json(yyp_path, project_data)

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

    def test_safe_delete_dry_run_blocked_by_dependencies(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_target", "")
            script_asset.create_files(proj, "scr_caller", "")
            caller_gml = proj / "scripts" / "scr_caller" / "scr_caller.gml"
            caller_gml.write_text("function scr_caller() {\n    script_execute(scr_target);\n}\n", encoding="utf-8")

            self._register_resource(proj, "scr_target", "scripts/scr_target/scr_target.yy")
            self._register_resource(proj, "scr_caller", "scripts/scr_caller/scr_caller.yy")

            result = safe_delete_asset(proj, "script", "scr_target", dry_run=True)
            self.assertTrue(result["blocked"])
            self.assertFalse(result["deleted"])
            self.assertGreaterEqual(result["dependency_count"], 1)
            self.assertTrue((proj / "scripts" / "scr_target").exists())

    def test_safe_delete_apply_without_dependencies(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_lonely", "")
            self._register_resource(proj, "scr_lonely", "scripts/scr_lonely/scr_lonely.yy")

            result = safe_delete_asset(proj, "script", "scr_lonely", dry_run=False)
            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertTrue(result["deleted"])
            self.assertFalse((proj / "scripts" / "scr_lonely").exists())

    def test_safe_delete_apply_blocked_without_force(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_target", "")
            script_asset.create_files(proj, "scr_caller", "")
            caller_gml = proj / "scripts" / "scr_caller" / "scr_caller.gml"
            caller_gml.write_text("function scr_caller() {\n    script_execute(scr_target);\n}\n", encoding="utf-8")

            self._register_resource(proj, "scr_target", "scripts/scr_target/scr_target.yy")
            self._register_resource(proj, "scr_caller", "scripts/scr_caller/scr_caller.yy")

            result = safe_delete_asset(proj, "script", "scr_target", dry_run=False, force=False)
            self.assertTrue(result["blocked"])
            self.assertFalse(result["deleted"])
            self.assertTrue((proj / "scripts" / "scr_target").exists())

    def test_safe_delete_force_with_clean_refs(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_target", "")
            script_asset.create_files(proj, "scr_caller", "")
            caller_gml = proj / "scripts" / "scr_caller" / "scr_caller.gml"
            caller_gml.write_text("function scr_caller() {\n    script_execute(scr_target);\n}\n", encoding="utf-8")

            self._register_resource(proj, "scr_target", "scripts/scr_target/scr_target.yy")
            self._register_resource(proj, "scr_caller", "scripts/scr_caller/scr_caller.yy")

            result = safe_delete_asset(
                proj,
                "script",
                "scr_target",
                dry_run=False,
                force=True,
                clean_refs=True,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["deleted"])
            self.assertGreaterEqual(result["cleaned_refs"]["replacements"], 1)
            self.assertFalse((proj / "scripts" / "scr_target").exists())
            updated = caller_gml.read_text(encoding="utf-8")
            self.assertNotIn("scr_target", updated)
            self.assertIn("undefined", updated)

if __name__ == "__main__":
    unittest.main(verbosity=2)
