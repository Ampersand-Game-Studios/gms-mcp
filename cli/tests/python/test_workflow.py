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
from gms_helpers.exceptions import JSONParseError, ValidationError
from gms_helpers.utils import save_pretty_json, load_json_loose
from gms_helpers.assets import NoteAsset, ObjectAsset, ScriptAsset, SpriteAsset


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


class TestWorkflowRegisteredPaths(unittest.TestCase):
    """Assets are resolved from their registered path, whatever the folder casing."""

    def _create(self, proj: Path, asset, name: str, **kwargs) -> str:
        rel_path = asset.create_files(proj, name, "", **kwargs)
        project_data = load_json_loose(proj / "test.yyp") or {}
        project_data.setdefault("resources", []).append({"id": {"name": name, "path": rel_path}})
        save_pretty_json(proj / "test.yyp", project_data)
        return rel_path

    def _move_to_ide_casing(self, proj: Path, name: str, directory: str) -> str:
        """Re-home a tool-created asset in the IDE's exact-case folder."""
        (proj / directory / name.lower()).rename(proj / directory / f"{name}.tmp")
        (proj / directory / f"{name}.tmp").rename(proj / directory / name)
        ide_path = f"{directory}/{name}/{name}.yy"
        text = (proj / "test.yyp").read_text(encoding="utf-8")
        (proj / "test.yyp").write_text(text.replace(f"{directory}/{name.lower()}/", f"{directory}/{name}/"))
        return ide_path

    def _assert_committed(self, result):
        self.assertTrue(result.success, getattr(result, "message", result))
        self.assertTrue(result.data["transaction"]["committed"], result.data["transaction"])

    def test_tool_created_mixed_case_asset_duplicates_renames_and_deletes(self):
        with TempProject() as proj:
            sprite_path = self._create(proj, SpriteAsset(), "sPlayer")
            self.assertEqual(sprite_path, "sprites/splayer/sPlayer.yy")
            object_path = self._create(proj, ObjectAsset(), "oPlayer", sprite_id="sPlayer")

            self._assert_committed(
                handle_workflow_duplicate(
                    SimpleNamespace(project_root=str(proj), asset_path=object_path, new_name="oCopy", yes=True)
                )
            )
            self._assert_committed(
                handle_workflow_rename(
                    SimpleNamespace(project_root=str(proj), asset_path=sprite_path, new_name="sHero")
                )
            )
            for holder in ("objects/oplayer/oPlayer.yy", "objects/ocopy/oCopy.yy"):
                self.assertEqual(
                    load_json_loose(proj / holder)["spriteId"], {"name": "sHero", "path": "sprites/shero/sHero.yy"}
                )
            result = delete_asset(proj, "objects/ocopy/oCopy.yy")
            self.assertTrue(result.success)
            self.assertFalse((proj / "objects" / "ocopy").exists())

    def test_ide_cased_asset_rename_rewrites_references_to_registered_path(self):
        with TempProject() as proj:
            self._create(proj, SpriteAsset(), "sPlayer")
            self._create(proj, ObjectAsset(), "oPlayer", sprite_id="sPlayer")
            ide_path = self._move_to_ide_casing(proj, "sPlayer", "sprites")
            holder = proj / "objects" / "oplayer" / "oPlayer.yy"
            holder.write_text(
                holder.read_text(encoding="utf-8").replace("sprites/splayer/", "sprites/sPlayer/"), encoding="utf-8"
            )
            sprite_yy = proj / ide_path
            sprite_yy.write_text(
                sprite_yy.read_text(encoding="utf-8").replace("sprites/splayer/", "sprites/sPlayer/"),
                encoding="utf-8",
            )

            self._assert_committed(
                handle_workflow_rename(SimpleNamespace(project_root=str(proj), asset_path=ide_path, new_name="sHero"))
            )

            self.assertEqual(load_json_loose(holder)["spriteId"]["path"], "sprites/shero/sHero.yy")
            renamed = (proj / "sprites" / "shero" / "sHero.yy").read_text(encoding="utf-8")
            self.assertNotIn("sPlayer", renamed)

    def test_duplicate_renames_self_collision_event_code(self):
        from gms_helpers.event_helper import add_event

        with TempProject() as proj:
            object_path = self._create(proj, ObjectAsset(), "oBall")
            add_event("oBall", "collision:oBall", project_root=proj)

            self._assert_committed(
                handle_workflow_duplicate(
                    SimpleNamespace(project_root=str(proj), asset_path=object_path, new_name="oBall2", yes=True)
                )
            )

            copy_dir = proj / "objects" / "oball2"
            self.assertTrue((copy_dir / "Collision_oBall2.gml").is_file())
            self.assertFalse((copy_dir / "Collision_oBall.gml").exists())

    def test_note_text_moves_with_rename_and_duplicate(self):
        with TempProject() as proj:
            note_path = self._create(proj, NoteAsset(), "Readme")
            self._assert_committed(
                handle_workflow_duplicate(
                    SimpleNamespace(project_root=str(proj), asset_path=note_path, new_name="Guide", yes=True)
                )
            )
            self._assert_committed(
                handle_workflow_rename(SimpleNamespace(project_root=str(proj), asset_path=note_path, new_name="Intro"))
            )
            self.assertTrue((proj / "notes" / "guide" / "Guide.txt").is_file())
            self.assertTrue((proj / "notes" / "intro" / "Intro.txt").is_file())
            self.assertFalse((proj / "notes" / "intro" / "Readme.txt").exists())

    def test_duplicating_script_with_extra_global_function_is_refused(self):
        with TempProject() as proj:
            script_path = self._create(proj, ScriptAsset(), "scr_tools")
            (proj / "scripts" / "scr_tools" / "scr_tools.gml").write_text(
                "function scr_tools() {}\nfunction tool_helper() {}\n", encoding="utf-8"
            )
            with self.assertRaises(ValidationError) as ctx:
                duplicate_asset(proj, script_path, "scr_tools_copy")
            self.assertIn("function tool_helper", str(ctx.exception))
            self.assertFalse((proj / "scripts" / "scr_tools_copy").exists())

    def test_forced_delete_detaches_structural_references_and_commits(self):
        with TempProject() as proj:
            self._create(proj, SpriteAsset(), "sGone")
            object_path = self._create(proj, ObjectAsset(), "oUser", sprite_id="sGone")

            result = handle_workflow_safe_delete(
                SimpleNamespace(project_root=str(proj), asset_type="sprite", asset_name="sGone", force=True, apply=True)
            )

            self._assert_committed(result)
            self.assertIsNone(load_json_loose(proj / object_path)["spriteId"])

    def test_forced_delete_detaches_project_dir_prefixed_references(self):
        with TempProject() as proj:
            sprite_path = self._create(proj, SpriteAsset(), "sGone")
            object_path = self._create(proj, ObjectAsset(), "oUser", sprite_id="sGone")
            data = load_json_loose(proj / object_path)
            data["spriteId"]["path"] = "${project_dir}/" + sprite_path
            save_pretty_json(proj / object_path, data)

            result = handle_workflow_safe_delete(
                SimpleNamespace(project_root=str(proj), asset_type="sprite", asset_name="sGone", force=True, apply=True)
            )

            self._assert_committed(result)
            self.assertIsNone(load_json_loose(proj / object_path)["spriteId"])

    def test_rename_preserves_crlf_and_refuses_non_utf8_before_moving(self):
        with TempProject() as proj:
            target_path = self._create(proj, ScriptAsset(), "scr_target")
            self._create(proj, ScriptAsset(), "scr_caller")
            caller = proj / "scripts" / "scr_caller" / "scr_caller.gml"
            caller.write_bytes(b"function scr_caller() {\r\n    scr_target();\r\n}\r\n")

            rename_asset(proj, target_path, "scr_moved")
            self.assertEqual(caller.read_bytes(), b"function scr_caller() {\r\n    scr_moved();\r\n}\r\n")

            caller.write_bytes(b"// caf\xe9\nscr_moved();\n")
            with self.assertRaises(ValidationError):
                rename_asset(proj, "scripts/scr_moved/scr_moved.yy", "scr_again")
            self.assertTrue((proj / "scripts" / "scr_moved" / "scr_moved.yy").exists())

    def test_rename_fails_before_moving_when_any_yy_is_unparseable(self):
        with TempProject() as proj:
            target_path = self._create(proj, ScriptAsset(), "scr_target")
            broken = proj / "objects" / "o_broken"
            broken.mkdir()
            (broken / "o_broken.yy").write_text("{ not json", encoding="utf-8")

            with self.assertRaises(ValidationError):
                rename_asset(proj, target_path, "scr_moved")
            self.assertTrue((proj / target_path).exists())

    def test_lint_reports_malformed_resource_entries(self):
        with TempProject() as proj:
            save_pretty_json(proj / "test.yyp", {"resources": [{"id": {"name": "x"}}], "Folders": []})
            result = lint_project(proj)
            self.assertFalse(result.success)
            self.assertTrue(any("Malformed .yyp resource entry" in problem for problem in result.details))


class TestReferenceRewriteRules(unittest.TestCase):
    def test_project_dir_prefixed_paths_are_rewritten_and_counted(self):
        from gms_helpers.reference_scanner import count_json_resource_references, rewrite_json_asset_references

        data = {
            "name": "rMain",
            "creationCodeFile": "${project_dir}/rooms/rMain/RoomCreationCode.gml",
            "parentRoom": {"name": "rMain", "path": "rooms/rMain/rMain.yy"},
        }
        rewrite_json_asset_references(
            data,
            "rMain",
            "rCopy",
            "room",
            old_path="rooms/rMain/rMain.yy",
            new_path="rooms/rcopy/rCopy.yy",
            own_asset=True,
        )
        self.assertEqual(data["creationCodeFile"], "${project_dir}/rooms/rcopy/RoomCreationCode.gml")
        self.assertEqual(data["parentRoom"], {"name": "rCopy", "path": "rooms/rcopy/rCopy.yy"})
        self.assertEqual(
            count_json_resource_references(
                {"file": "${project_dir}/rooms/rcopy/rCopy.yy"}, "rooms/rcopy/rCopy.yy", "x"
            ),
            1,
        )

    def test_template_string_interpolations_are_code(self):
        from gms_helpers.reference_scanner import count_gml_identifier, rewrite_gml_asset_identifiers

        source = 'show_debug_message($"hp {oEnemy.hp} of oEnemy {$"{oEnemy}"}");'
        rewritten, count = rewrite_gml_asset_identifiers(source, {"oEnemy": "oFoe"})
        self.assertEqual(count, 2)
        self.assertEqual(rewritten, 'show_debug_message($"hp {oFoe.hp} of oEnemy {$"{oFoe}"}");')
        self.assertEqual(count_gml_identifier('var s = "oEnemy";', "oEnemy"), 0)

    def test_build_outputs_are_ignored_only_at_project_root(self):
        from gms_helpers.reference_scanner import is_ignored_project_path

        self.assertTrue(is_ignored_project_path(Path("build/x.gml")))
        self.assertFalse(is_ignored_project_path(Path("scripts/build/build.gml")))
        self.assertTrue(is_ignored_project_path(Path("scripts/x/.git/y.gml")))

    def test_room_duplicate_keeps_inherited_instance_identities(self):
        from gms_helpers.workflow import _regenerate_duplicate_identities

        room = {
            "layers": [
                {
                    "instances": [
                        {"resourceType": "GMRInstance", "name": "inst_LOCAL"},
                        {
                            "resourceType": "GMRInstance",
                            "name": "inst_PARENT",
                            "inheritedItemId": {"name": "inst_PARENT", "path": "rooms/rBase/rBase.yy"},
                        },
                    ]
                }
            ],
            "instanceCreationOrder": [
                {"name": "inst_LOCAL", "path": "rooms/rMain/rMain.yy"},
                {"name": "inst_PARENT", "path": "rooms/rBase/rBase.yy"},
            ],
        }
        updated, identities = _regenerate_duplicate_identities("room", room)
        self.assertEqual(list(identities), ["inst_LOCAL"])
        inherited = updated["layers"][0]["instances"][1]
        self.assertEqual(inherited["name"], "inst_PARENT")
        self.assertEqual(inherited["inheritedItemId"]["name"], "inst_PARENT")
        self.assertEqual(updated["instanceCreationOrder"][1]["name"], "inst_PARENT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
