#!/usr/bin/env python3
"""Tests for workflow utilities (Part C)."""

import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to the path
import sys

SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import from the correct location
from gms_helpers.workflow import duplicate_asset, rename_asset, delete_asset, lint_project, safe_delete_asset
from gms_helpers.commands.workflow_commands import (
    handle_workflow_duplicate,
    handle_workflow_rename,
    handle_workflow_safe_delete,
)
from gms_helpers.exceptions import JSONParseError
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

    def test_standalone_cli_rename_rolls_back_semantic_failure(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_original", "")
            original_path = "scripts/scr_original/scr_original.yy"
            self._register_resource(proj, "scr_original", original_path)
            yyp_before = (proj / "test.yyp").read_bytes()

            with patch("gms_helpers.reference_scanner.comprehensive_rename_asset", return_value=False):
                with self.assertRaises(JSONParseError):
                    handle_workflow_rename(
                        SimpleNamespace(
                            project_root=str(proj),
                            asset_path=original_path,
                            new_name="scr_renamed",
                        )
                    )

            self.assertTrue((proj / "scripts" / "scr_original" / "scr_original.yy").exists())
            self.assertFalse((proj / "scripts" / "scr_renamed").exists())
            self.assertEqual((proj / "test.yyp").read_bytes(), yyp_before)

    def test_standalone_cli_rename_commits_validated_transaction(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_original", "")
            original_path = "scripts/scr_original/scr_original.yy"
            self._register_resource(proj, "scr_original", original_path)

            result = handle_workflow_rename(
                SimpleNamespace(
                    project_root=str(proj),
                    asset_path=original_path,
                    new_name="scr_renamed",
                )
            )

            transaction = result.data["transaction"]
            self.assertTrue(result.success)
            self.assertTrue(transaction["committed"])
            self.assertTrue(transaction["ownership_checkpoint_captured"])
            self.assertTrue(transaction["validation"]["success"])
            self.assertTrue((proj / "scripts" / "scr_renamed" / "scr_renamed.yy").exists())

    def test_standalone_cli_duplicate_commits_validated_transaction(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_original", "")
            original_path = "scripts/scr_original/scr_original.yy"
            self._register_resource(proj, "scr_original", original_path)

            result = handle_workflow_duplicate(
                SimpleNamespace(
                    project_root=str(proj),
                    asset_path=original_path,
                    new_name="scr_copy",
                    yes=True,
                )
            )

            self.assertTrue(result.success)
            self.assertTrue(result.data["transaction"]["committed"])
            self.assertTrue((proj / "scripts" / "scr_copy" / "scr_copy.yy").exists())

    def test_standalone_safe_delete_dry_run_does_not_open_transaction(self):
        with TempProject() as proj:
            with patch("gms_helpers.commands.workflow_commands.GameMakerProjectTransaction") as transaction_class:
                result = handle_workflow_safe_delete(
                    SimpleNamespace(
                        project_root=str(proj),
                        asset_type="script",
                        asset_name="missing",
                        force=False,
                        apply=False,
                    )
                )

            self.assertFalse(result.success)
            transaction_class.assert_not_called()

    def test_standalone_safe_delete_apply_commits_validated_transaction(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_delete", "")
            self._register_resource(proj, "scr_delete", "scripts/scr_delete/scr_delete.yy")

            result = handle_workflow_safe_delete(
                SimpleNamespace(
                    project_root=str(proj),
                    asset_type="script",
                    asset_name="scr_delete",
                    force=False,
                    apply=True,
                )
            )

            self.assertTrue(result.success)
            self.assertTrue(result.data["transaction"]["committed"])
            self.assertFalse((proj / "scripts" / "scr_delete").exists())

    def test_delete_and_lint(self):
        with TempProject() as proj:
            # Create a script asset to delete using ScriptAsset class
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "todelete", "")
            yy_path = "scripts/todelete/todelete.yy"
            self._register_resource(proj, "todelete", yy_path)
            # Delete asset
            delete_asset(proj, yy_path, dry_run=False)
            self.assertFalse((proj / "scripts" / "todelete").exists())
            # Lint should pass (zero problems)
            result = lint_project(proj)
            self.assertTrue(result.success)
            self.assertEqual(result.issues_found, 0)

    def test_delete_rejects_path_traversal_before_filesystem_mutation(self):
        with TempProject() as proj:
            with self.assertRaisesRegex(Exception, "Path traversal"):
                delete_asset(proj, "scripts/../anything/anything.yy", dry_run=False)

            self.assertTrue(proj.exists())
            self.assertTrue((proj / "test.yyp").exists())

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

    def test_safe_delete_ignores_comments_strings_and_longer_identifiers(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_target", "")
            script_asset.create_files(proj, "scr_caller", "")
            caller_gml = proj / "scripts" / "scr_caller" / "scr_caller.gml"
            caller_gml.write_text(
                '// scr_target is documentation only\nvar label = "scr_target";\nvar scr_target_variant = 1;\n',
                encoding="utf-8",
            )
            self._register_resource(proj, "scr_target", "scripts/scr_target/scr_target.yy")
            self._register_resource(proj, "scr_caller", "scripts/scr_caller/scr_caller.yy")

            result = safe_delete_asset(proj, "script", "scr_target", dry_run=True)

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(result["dependency_count"], 0)

    def test_safe_delete_blocks_asset_get_index_string_reference(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_target", "")
            script_asset.create_files(proj, "scr_caller", "")
            caller_gml = proj / "scripts" / "scr_caller" / "scr_caller.gml"
            caller_gml.write_text('var target = asset_get_index("scr_target");\n', encoding="utf-8")
            self._register_resource(proj, "scr_target", "scripts/scr_target/scr_target.yy")
            self._register_resource(proj, "scr_caller", "scripts/scr_caller/scr_caller.yy")

            result = safe_delete_asset(proj, "script", "scr_target", dry_run=True)

            self.assertTrue(result["blocked"])
            self.assertTrue(any(item["asset_name"] == "scr_caller" for item in result["dependencies"]))

    def test_safe_delete_blocks_exact_structured_resource_reference(self):
        with TempProject() as proj:
            target_path = "objects/o_target/o_target.yy"
            holder_path = "objects/o_holder/o_holder.yy"
            for name, path, data in (
                ("o_target", target_path, {"$GMObject": "", "%Name": "o_target", "name": "o_target"}),
                (
                    "o_holder",
                    holder_path,
                    {
                        "$GMObject": "",
                        "%Name": "o_holder",
                        "name": "o_holder",
                        "parentObjectId": {"name": "o_target", "path": target_path},
                    },
                ),
            ):
                asset_dir = proj / "objects" / name
                asset_dir.mkdir(parents=True)
                save_pretty_json(asset_dir / f"{name}.yy", data)
                self._register_resource(proj, name, path)

            result = safe_delete_asset(proj, "object", "o_target", dry_run=True)

            self.assertTrue(result["blocked"])
            self.assertTrue(any(item["asset_name"] == "o_holder" for item in result["dependencies"]))

    def test_safe_delete_blocks_object_property_expression_reference(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_target", "")
            self._register_resource(proj, "scr_target", "scripts/scr_target/scr_target.yy")
            holder_path = "objects/o_holder/o_holder.yy"
            holder_dir = proj / "objects" / "o_holder"
            holder_dir.mkdir(parents=True)
            save_pretty_json(
                holder_dir / "o_holder.yy",
                {
                    "$GMObject": "",
                    "%Name": "o_holder",
                    "name": "o_holder",
                    "properties": [
                        {
                            "$GMObjectProperty": "v2",
                            "resourceType": "GMObjectProperty",
                            "value": "scr_target",
                        }
                    ],
                },
            )
            self._register_resource(proj, "o_holder", holder_path)

            result = safe_delete_asset(proj, "script", "scr_target", dry_run=True)

            self.assertTrue(result["blocked"])
            self.assertTrue(any(item["asset_name"] == "o_holder" for item in result["dependencies"]))

    def test_safe_delete_blocks_room_creation_code_reference(self):
        with TempProject() as proj:
            script_asset = ScriptAsset()
            script_asset.create_files(proj, "scr_target", "")
            self._register_resource(proj, "scr_target", "scripts/scr_target/scr_target.yy")
            room_dir = proj / "rooms" / "r_holder"
            room_dir.mkdir(parents=True)
            save_pretty_json(
                room_dir / "r_holder.yy",
                {"$GMRoom": "", "%Name": "r_holder", "name": "r_holder"},
            )
            (room_dir / "RoomCreationCode.gml").write_text("scr_target();\n", encoding="utf-8")
            self._register_resource(proj, "r_holder", "rooms/r_holder/r_holder.yy")

            result = safe_delete_asset(proj, "script", "scr_target", dry_run=True)

            self.assertTrue(result["blocked"])
            self.assertTrue(
                any(
                    item["asset_name"] == "r_holder" and item["asset_type"] == "room" for item in result["dependencies"]
                )
            )

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

    def test_safe_delete_force_leaves_references_explicitly_unresolved(self):
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
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["deleted"])
            self.assertFalse((proj / "scripts" / "scr_target").exists())
            updated = caller_gml.read_text(encoding="utf-8")
            self.assertIn("scr_target", updated)
            self.assertNotIn("undefined", updated)
            self.assertTrue(any("unresolved" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
