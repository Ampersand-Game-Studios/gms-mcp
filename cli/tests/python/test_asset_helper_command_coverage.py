#!/usr/bin/env python3
"""Focused coverage tests for gms_helpers.asset_helper."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers import asset_helper
from gms_helpers.exceptions import GMSError, ProjectNotFoundError


def _capture_output(func, *args, **kwargs):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


def _maintenance_result(has_errors: bool = False):
    return SimpleNamespace(has_errors=has_errors)


def _create_args(name: str, **overrides):
    defaults = {
        "name": name,
        "parent_path": "folders/Test.yy",
        "skip_maintenance": False,
        "no_auto_fix": False,
        "maintenance_verbose": True,
        "constructor": False,
        "sprite_id": None,
        "parent_object": None,
        "frame_count": 1,
        "width": 1024,
        "height": 768,
        "path": "folders/Test Folder.yy",
        "font_name": "Arial",
        "size": 12,
        "bold": False,
        "italic": False,
        "aa_level": 1,
        "uses_sdf": True,
        "shader_type": 1,
        "curve_type": "linear",
        "channel_name": "curve",
        "volume": 1.0,
        "pitch": 1.0,
        "sound_type": 0,
        "bitrate": 128,
        "sample_rate": 44100,
        "format": 2,
        "closed": False,
        "precision": 4,
        "path_type": "straight",
        "tile_width": 32,
        "tile_height": 32,
        "tile_xsep": 0,
        "tile_ysep": 0,
        "tile_xoff": 0,
        "tile_yoff": 0,
        "length": 60.0,
        "playback_speed": 30.0,
        "content": "hello",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestGameMakerContext(unittest.TestCase):
    def test_validate_gamemaker_context_from_subdirectory_prints_guidance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "demo.yyp").write_text("{}", encoding="utf-8")
            for folder in ("objects", "sprites", "scripts", "rooms"):
                (root / folder).mkdir()
            subdir = root / "scripts" / "nested"
            subdir.mkdir(parents=True)

            with patch("gms_helpers.asset_helper.Path.cwd", return_value=subdir):
                result, output = _capture_output(asset_helper.validate_gamemaker_context)

        self.assertEqual(result, root)
        self.assertIn("GameMaker project found at", output)
        self.assertIn(str(root), output)

    def test_validate_gamemaker_context_rejects_non_project_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = Path(temp_dir)
            with patch("gms_helpers.asset_helper.Path.cwd", return_value=outside):
                with self.assertRaises(asset_helper.GameMakerContextError):
                    asset_helper.validate_gamemaker_context()

    def test_validate_gamemaker_context_rejects_missing_standard_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "demo.yyp").write_text("{}", encoding="utf-8")

            with patch("gms_helpers.asset_helper.Path.cwd", return_value=root):
                with self.assertRaises(asset_helper.GameMakerContextError):
                    asset_helper.validate_gamemaker_context()

    def test_validate_asset_directory_structure_wraps_context_error(self):
        with patch(
            "gms_helpers.asset_helper.validate_gamemaker_context",
            side_effect=asset_helper.GameMakerContextError("bad context"),
        ):
            with self.assertRaises(ProjectNotFoundError) as error:
                asset_helper.validate_asset_directory_structure()

        self.assertIn("Navigate to your GameMaker project directory", str(error.exception))


class TestCreateCommands(unittest.TestCase):
    def test_create_script_success_covers_validation_and_maintenance(self):
        args = _create_args("PlayerData", constructor=True)
        with ExitStack() as stack:
            validate_dir = stack.enter_context(
                patch("gms_helpers.asset_helper.validate_asset_directory_structure", return_value=Path("/tmp/project"))
            )
            run_maintenance = stack.enter_context(
                patch(
                    "gms_helpers.asset_helper.run_auto_maintenance",
                    side_effect=[_maintenance_result(), _maintenance_result()],
                )
            )
            safe_check = stack.enter_context(
                patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True)
            )
            validate_name = stack.enter_context(patch("gms_helpers.asset_helper.validate_name"))
            validate_parent = stack.enter_context(patch("gms_helpers.asset_helper.validate_parent_path"))
            update_yyp = stack.enter_context(patch("gms_helpers.asset_helper.update_yyp_file", return_value=True))
            script_cls = stack.enter_context(patch("gms_helpers.asset_helper.ScriptAsset"))
            script_instance = script_cls.return_value
            script_instance.create_files.return_value = "scripts/PlayerData/PlayerData.yy"

            result, output = _capture_output(asset_helper.create_script, args)

        self.assertTrue(result)
        self.assertIn("Script 'PlayerData' created successfully", output)
        validate_dir.assert_called_once()
        safe_check.assert_called_once()
        validate_name.assert_called_once_with("PlayerData", "script", allow_constructor=True)
        validate_parent.assert_called_once_with("folders/Test.yy")
        script_instance.create_files.assert_called_once_with(
            Path("."), "PlayerData", "folders/Test.yy", is_constructor=True
        )
        update_yyp.assert_called_once_with(
            {"id": {"name": "PlayerData", "path": "scripts/PlayerData/PlayerData.yy"}}
        )
        self.assertEqual(run_maintenance.call_count, 2)

    def test_create_asset_wrappers_success_paths(self):
        cases = [
            {
                "func": asset_helper.create_object,
                "class_name": "ObjectAsset",
                "name": "o_player",
                "path": "objects/o_player/o_player.yy",
                "extra": {"sprite_id": "spr_player", "parent_object": "o_actor"},
                "kwargs": {"sprite_id": "spr_player", "parent_object": "o_actor"},
                "validate_type": "object",
                "success_text": "Object 'o_player' created successfully",
            },
            {
                "func": asset_helper.create_sprite,
                "class_name": "SpriteAsset",
                "name": "spr_player",
                "path": "sprites/spr_player/spr_player.yy",
                "extra": {"frame_count": 4},
                "kwargs": {"frame_count": 4},
                "validate_type": "sprite",
                "success_text": "Sprite 'spr_player' created successfully with 4 frames",
            },
            {
                "func": asset_helper.create_room,
                "class_name": "RoomAsset",
                "name": "r_level",
                "path": "rooms/r_level/r_level.yy",
                "extra": {"width": 1920, "height": 1080},
                "kwargs": {"width": 1920, "height": 1080},
                "validate_type": "room",
                "success_text": "Room 'r_level' created successfully",
            },
            {
                "func": asset_helper.create_font,
                "class_name": "FontAsset",
                "name": "fnt_ui",
                "path": "fonts/fnt_ui/fnt_ui.yy",
                "extra": {"font_name": "Futura", "size": 24, "bold": True, "italic": True, "aa_level": 2, "uses_sdf": False},
                "kwargs": {"font_name": "Futura", "size": 24, "bold": True, "italic": True, "aa_level": 2, "uses_sdf": False},
                "validate_type": "font",
                "success_text": "Font 'fnt_ui' created successfully",
            },
            {
                "func": asset_helper.create_shader,
                "class_name": "ShaderAsset",
                "name": "sh_blur",
                "path": "shaders/sh_blur/sh_blur.yy",
                "extra": {"shader_type": 2},
                "kwargs": {"shader_type": 2},
                "validate_type": "shader",
                "success_text": "Shader 'sh_blur' created successfully",
            },
            {
                "func": asset_helper.create_animcurve,
                "class_name": "AnimCurveAsset",
                "name": "curve_ease",
                "path": "animcurves/curve_ease/curve_ease.yy",
                "extra": {"curve_type": "ease_in", "channel_name": "bounce"},
                "kwargs": {"curve_type": "ease_in", "channel_name": "bounce"},
                "validate_type": "animcurve",
                "success_text": "Animation curve 'curve_ease' created successfully",
            },
            {
                "func": asset_helper.create_sound,
                "class_name": "SoundAsset",
                "name": "snd_boom",
                "path": "sounds/snd_boom/snd_boom.yy",
                "extra": {"volume": 0.7, "pitch": 1.2, "sound_type": 2, "bitrate": 192, "sample_rate": 22050, "format": 1},
                "kwargs": {"volume": 0.7, "pitch": 1.2, "sound_type": 2, "bitrate": 192, "sample_rate": 22050, "format": 1},
                "validate_type": "sound",
                "success_text": "Sound 'snd_boom' created successfully",
            },
            {
                "func": asset_helper.create_path,
                "class_name": "PathAsset",
                "name": "pth_patrol",
                "path": "paths/pth_patrol/pth_patrol.yy",
                "extra": {"closed": True, "precision": 8, "path_type": "circle"},
                "kwargs": {"closed": True, "precision": 8, "path_type": "circle"},
                "validate_type": "path",
                "success_text": "Path 'pth_patrol' created successfully",
            },
            {
                "func": asset_helper.create_tileset,
                "class_name": "TileSetAsset",
                "name": "ts_world",
                "path": "tilesets/ts_world/ts_world.yy",
                "extra": {
                    "tile_width": 16,
                    "tile_height": 24,
                    "tile_xsep": 1,
                    "tile_ysep": 2,
                    "tile_xoff": 3,
                    "tile_yoff": 4,
                    "sprite_id": "spr_tiles",
                },
                "kwargs": {
                    "tile_width": 16,
                    "tile_height": 24,
                    "tile_xsep": 1,
                    "tile_ysep": 2,
                    "tile_xoff": 3,
                    "tile_yoff": 4,
                    "sprite_id": "spr_tiles",
                },
                "validate_type": "tileset",
                "success_text": "Tileset 'ts_world' created successfully",
            },
            {
                "func": asset_helper.create_timeline,
                "class_name": "TimelineAsset",
                "name": "tl_intro",
                "path": "timelines/tl_intro/tl_intro.yy",
                "extra": {},
                "kwargs": {},
                "validate_type": "timeline",
                "success_text": "Timeline 'tl_intro' created successfully",
            },
            {
                "func": asset_helper.create_sequence,
                "class_name": "SequenceAsset",
                "name": "seq_intro",
                "path": "sequences/seq_intro/seq_intro.yy",
                "extra": {"length": 120.0, "playback_speed": 60.0},
                "kwargs": {"length": 120.0, "playback_speed": 60.0},
                "validate_type": "sequence",
                "success_text": "Sequence 'seq_intro' created successfully",
            },
            {
                "func": asset_helper.create_note,
                "class_name": "NoteAsset",
                "name": "Design Notes",
                "path": "notes/Design Notes/Design Notes.yy",
                "extra": {"content": "Initial design"},
                "kwargs": {"content": "Initial design"},
                "validate_type": "note",
                "success_text": "Note 'Design Notes' created successfully",
            },
        ]

        for case in cases:
            with self.subTest(case=case["func"].__name__):
                args = _create_args(case["name"], **case["extra"])
                with ExitStack() as stack:
                    run_maintenance = stack.enter_context(
                        patch(
                            "gms_helpers.asset_helper.run_auto_maintenance",
                            side_effect=[_maintenance_result(), _maintenance_result()],
                        )
                    )
                    safe_check = stack.enter_context(
                        patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True)
                    )
                    validate_name = stack.enter_context(patch("gms_helpers.asset_helper.validate_name"))
                    validate_parent = stack.enter_context(patch("gms_helpers.asset_helper.validate_parent_path"))
                    update_yyp = stack.enter_context(patch("gms_helpers.asset_helper.update_yyp_file", return_value=True))
                    asset_cls = stack.enter_context(patch(f"gms_helpers.asset_helper.{case['class_name']}"))
                    asset_instance = asset_cls.return_value
                    asset_instance.create_files.return_value = case["path"]

                    result, output = _capture_output(case["func"], args)

                self.assertTrue(result)
                self.assertIn(case["success_text"], output)
                safe_check.assert_called_once()
                validate_name.assert_called_once_with(case["name"], case["validate_type"])
                validate_parent.assert_called_once_with("folders/Test.yy")
                asset_instance.create_files.assert_called_once_with(
                    Path("."), case["name"], "folders/Test.yy", **case["kwargs"]
                )
                update_yyp.assert_called_once_with({"id": {"name": case["name"], "path": case["path"]}})
                self.assertEqual(run_maintenance.call_count, 2)

    def test_create_folder_success(self):
        args = _create_args("Utility", path="folders/Utility.yy")
        with ExitStack() as stack:
            run_maintenance = stack.enter_context(
                patch(
                    "gms_helpers.asset_helper.run_auto_maintenance",
                    side_effect=[_maintenance_result(), _maintenance_result()],
                )
            )
            safe_check = stack.enter_context(
                patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True)
            )
            folder_cls = stack.enter_context(patch("gms_helpers.asset_helper.FolderAsset"))
            folder_instance = folder_cls.return_value
            folder_instance.create_files.return_value = "folders/Utility.yy"

            result, output = _capture_output(asset_helper.create_folder, args)

        self.assertTrue(result)
        self.assertIn("Folder 'Utility' created at logical path", output)
        safe_check.assert_called_once()
        folder_instance.create_files.assert_called_once_with(Path("."), "Utility", "folders/Utility.yy")
        self.assertEqual(run_maintenance.call_count, 2)

    def test_create_wrapper_returns_false_on_failed_yyp_update(self):
        args = _create_args("spr_fail")
        with patch("gms_helpers.asset_helper.run_auto_maintenance", side_effect=[_maintenance_result(), _maintenance_result()]), \
             patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True), \
             patch("gms_helpers.asset_helper.validate_name"), \
             patch("gms_helpers.asset_helper.validate_parent_path"), \
             patch("gms_helpers.asset_helper.update_yyp_file", return_value=False), \
             patch("gms_helpers.asset_helper.SpriteAsset") as sprite_cls:
            sprite_cls.return_value.create_files.return_value = "sprites/spr_fail/spr_fail.yy"

            result, output = _capture_output(asset_helper.create_sprite, args)

        self.assertFalse(result)
        self.assertIn("Failed to update .yyp file for sprite 'spr_fail'", output)

    def test_create_wrapper_returns_maintenance_failure_when_precheck_fails(self):
        args = _create_args("o_guard")
        with patch("gms_helpers.asset_helper.run_auto_maintenance", return_value=_maintenance_result()), \
             patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=False), \
             patch("gms_helpers.asset_helper.handle_maintenance_failure", return_value=False) as failure_handler:
            result = asset_helper.create_object(args)

        self.assertFalse(result)
        failure_handler.assert_called_once()


class TestDeleteAndMain(unittest.TestCase):
    def test_delete_asset_dry_run_lists_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_dir = root / "scripts" / "scr_demo"
            asset_dir.mkdir(parents=True)
            (asset_dir / "scr_demo.yy").write_text("{}", encoding="utf-8")
            (asset_dir / "scr_demo.gml").write_text("// test", encoding="utf-8")
            args = SimpleNamespace(
                asset_type="script",
                name="scr_demo",
                dry_run=True,
                skip_maintenance=True,
                no_auto_fix=False,
                maintenance_verbose=True,
            )
            project_data = {"resources": [{"id": {"name": "scr_demo", "path": "scripts/scr_demo/scr_demo.yy"}}]}

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                with patch("gms_helpers.utils.find_yyp_file", return_value=root / "demo.yyp"), \
                     patch("gms_helpers.utils.load_json", return_value=project_data):
                    result, output = _capture_output(asset_helper.delete_asset, args)
            finally:
                os.chdir(old_cwd)

        self.assertTrue(result)
        self.assertIn("[DRY-RUN] Would delete asset 'scr_demo' (script)", output)
        self.assertIn("scripts/scr_demo", output)

    def test_delete_asset_updates_project_and_runs_post_maintenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_dir = root / "objects" / "o_enemy"
            asset_dir.mkdir(parents=True)
            (asset_dir / "o_enemy.yy").write_text("{}", encoding="utf-8")
            (asset_dir / "o_enemy_Create_0.gml").write_text("// create", encoding="utf-8")
            args = SimpleNamespace(
                asset_type="object",
                name="o_enemy",
                dry_run=False,
                skip_maintenance=False,
                no_auto_fix=False,
                maintenance_verbose=True,
            )
            project_data = {"resources": [{"id": {"name": "o_enemy", "path": "objects/o_enemy/o_enemy.yy"}}]}

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                with patch(
                    "gms_helpers.asset_helper.run_auto_maintenance",
                    side_effect=[_maintenance_result(), _maintenance_result()],
                ) as run_maintenance, \
                     patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True), \
                     patch("gms_helpers.utils.find_yyp_file", return_value=root / "demo.yyp"), \
                     patch("gms_helpers.utils.load_json", return_value=json.loads(json.dumps(project_data))), \
                     patch("gms_helpers.utils.save_json") as save_json:
                    result, output = _capture_output(asset_helper.delete_asset, args)
            finally:
                os.chdir(old_cwd)

        self.assertTrue(result)
        self.assertIn("Asset 'o_enemy' deleted successfully", output)
        self.assertFalse(asset_dir.exists())
        save_json.assert_called_once()
        self.assertEqual(run_maintenance.call_count, 2)

    def test_delete_asset_rejects_unknown_type(self):
        args = SimpleNamespace(
            asset_type="bogus",
            name="whatever",
            dry_run=False,
            skip_maintenance=True,
            no_auto_fix=False,
            maintenance_verbose=True,
        )
        result, output = _capture_output(asset_helper.delete_asset, args)
        self.assertFalse(result)
        self.assertIn("Unsupported asset type", output)

    def test_main_builds_parser_and_routes_command(self):
        with patch.object(sys, "argv", ["asset_helper", "maint", "lint"]), \
             patch("gms_helpers.asset_helper.validate_working_directory"), \
             patch("gms_helpers.asset_helper.maint_lint_command", return_value=True) as maint_lint:
            result = asset_helper.main()

        self.assertTrue(result)
        maint_lint.assert_called_once()

    def test_main_propagates_gms_error_and_handles_interrupt_and_unexpected(self):
        error = GMSError("broken")
        with patch.object(sys, "argv", ["asset_helper", "maint", "lint"]), \
             patch("gms_helpers.asset_helper.validate_working_directory"), \
             patch("gms_helpers.asset_helper.maint_lint_command", side_effect=error):
            with self.assertRaises(GMSError):
                asset_helper.main()

        with patch.object(sys, "argv", ["asset_helper", "maint", "lint"]), \
             patch("gms_helpers.asset_helper.validate_working_directory"), \
             patch("gms_helpers.asset_helper.maint_lint_command", side_effect=KeyboardInterrupt):
            result, output = _capture_output(asset_helper.main)
            self.assertFalse(result)
            self.assertIn("Operation cancelled.", output)

        with patch.object(sys, "argv", ["asset_helper", "maint", "lint"]), \
             patch("gms_helpers.asset_helper.validate_working_directory"), \
             patch("gms_helpers.asset_helper.maint_lint_command", side_effect=RuntimeError("boom")):
            result, output = _capture_output(asset_helper.main)
            self.assertFalse(result)
            self.assertIn("Unexpected error: boom", output)


class TestMaintenanceCommands(unittest.TestCase):
    def test_basic_maintenance_commands(self):
        with patch("gms_helpers.asset_helper.lint_project", return_value=[SimpleNamespace(severity="warning")]), \
             patch("gms_helpers.asset_helper.print_lint_report"):
            result, output = _capture_output(asset_helper.maint_lint_command, SimpleNamespace(fix=False))
        self.assertTrue(result)
        self.assertIn("Scanning project for issues", output)

        with patch("gms_helpers.maintenance.tidy_json.validate_project_json", return_value=[("a.yy", True), ("b.yy", False)]), \
             patch("gms_helpers.maintenance.tidy_json.print_json_validation_report"):
            result, output = _capture_output(asset_helper.maint_validate_json_command, SimpleNamespace())
        self.assertFalse(result)
        self.assertIn("Validating JSON syntax", output)

        with patch("gms_helpers.asset_helper.find_orphaned_assets", return_value=[("obj", "object")]), \
             patch("gms_helpers.asset_helper.find_missing_assets", return_value=["missing.yy"]), \
             patch("gms_helpers.asset_helper.print_orphan_report"):
            result, output = _capture_output(asset_helper.maint_list_orphans_command, SimpleNamespace())
        self.assertTrue(result)
        self.assertIn("orphaned and missing assets", output)

        with patch("gms_helpers.asset_helper.prune_missing_assets", return_value=["ghost.yy"]), \
             patch("gms_helpers.asset_helper.print_prune_report"):
            result, output = _capture_output(
                asset_helper.maint_prune_missing_command,
                SimpleNamespace(dry_run=True),
            )
        self.assertTrue(result)
        self.assertIn("Scanning for missing asset references", output)

        issues = [SimpleNamespace(severity="error"), SimpleNamespace(severity="warning")]
        with patch("gms_helpers.asset_helper.validate_folder_paths", return_value=issues), \
             patch("gms_helpers.asset_helper.print_path_validation_report"):
            result, output = _capture_output(
                asset_helper.maint_validate_paths_command,
                SimpleNamespace(strict_disk_check=True, include_parent_folders=True),
            )
        self.assertFalse(result)
        self.assertIn("including parent folders", output)

    def test_dedupe_resources_and_fix_issues(self):
        args = SimpleNamespace(dry_run=True, auto=False)
        project_data = {"resources": []}
        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), \
             patch("gms_helpers.utils.load_json", return_value=project_data), \
             patch(
                 "gms_helpers.utils.dedupe_resources",
                 return_value=(project_data, 2, ["dup 1", "dup 2"]),
             ), \
             patch("gms_helpers.utils.save_json") as save_json:
            result, output = _capture_output(asset_helper.maint_dedupe_resources_command, args)
        self.assertTrue(result)
        self.assertIn("Would remove 2 duplicate resource entries", output)
        save_json.assert_not_called()

        with patch("gms_helpers.asset_helper.run_auto_maintenance") as run_maintenance:
            result, output = _capture_output(asset_helper.maint_fix_issues_command, SimpleNamespace(verbose=True))
        self.assertTrue(result)
        self.assertIn("Auto-maintenance completed successfully", output)
        run_maintenance.assert_called_once_with(".", fix_issues=True, verbose=True)

    def test_sync_events_command_handles_specific_and_all_objects(self):
        with patch("gms_helpers.maintenance.event_sync.sync_object_events", return_value={"orphaned_found": 1, "orphaned_fixed": 1, "missing_found": 1, "missing_created": 1}), \
             patch("gms_helpers.asset_helper.os.path.exists", return_value=True):
            result, output = _capture_output(
                asset_helper.maint_sync_events_command,
                SimpleNamespace(fix=True, object="o_player"),
            )
        self.assertTrue(result)
        self.assertIn("o_player", output)
        self.assertIn("CREATED", output)

        with patch("gms_helpers.maintenance.event_sync.sync_all_object_events", return_value={"objects_processed": 4, "orphaned_found": 0, "orphaned_fixed": 0, "missing_found": 0, "missing_created": 0}):
            result, output = _capture_output(
                asset_helper.maint_sync_events_command,
                SimpleNamespace(fix=False, object=None),
            )
        self.assertTrue(result)
        self.assertIn("All object events are properly synchronized", output)

    def test_clean_old_files_and_clean_orphans(self):
        with patch("gms_helpers.maintenance.clean_unused_assets.clean_old_yy_files", return_value=(3, 0)):
            result, output = _capture_output(
                asset_helper.maint_clean_old_files_command,
                SimpleNamespace(delete=False),
            )
        self.assertTrue(result)
        self.assertIn("Found 3 .old.yy files", output)

        cleanup_result = {
            "total_deleted": 25,
            "deleted_directories": ["objects/old"],
            "errors": ["failed one", "failed two"],
            "deleted_files": [f"file_{i}.yy" for i in range(25)],
        }
        with patch("gms_helpers.asset_helper.delete_orphan_files", return_value=cleanup_result):
            result, output = _capture_output(
                asset_helper.maint_clean_orphans_command,
                SimpleNamespace(delete=False, skip_types=["folder"]),
            )
        self.assertTrue(result)
        self.assertIn("Found 25 orphaned files to remove", output)
        self.assertIn("and 5 more files", output)
        self.assertIn("2 errors occurred", output)

        cleanup_result_delete = {
            "total_deleted": 3,
            "deleted_directories": ["objects/a", "sprites/b"],
            "errors": [],
            "deleted_files": [],
        }
        with patch("gms_helpers.asset_helper.delete_orphan_files", return_value=cleanup_result_delete):
            result, output = _capture_output(
                asset_helper.maint_clean_orphans_command,
                SimpleNamespace(delete=True, skip_types=[]),
            )
        self.assertTrue(result)
        self.assertIn("Removed 2 empty directories", output)

    def test_audit_purge_folder_and_list_commands(self):
        analysis_results = {
            "phase_1_results": {"referenced_files_count": 10},
            "phase_2_results": {
                "filesystem_files_count": 14,
                "derivable_orphans": ["a.yy", "b.yy"],
                "string_references": {
                    "by_type": {"sprite": ["spr_player"]},
                    "cross_reference": {
                        "string_refs_found_exact": ["spr_player"],
                        "string_refs_found_case_diff": [],
                        "string_refs_missing": ["spr_missing"],
                    },
                },
            },
            "final_analysis": {
                "missing_but_referenced_count": 1,
                "true_orphans_count": 2,
                "case_sensitivity_issues_count": 1,
                "missing_but_referenced": ["missing.yy"],
                "true_orphans": ["orphan_1.yy", "orphan_2.yy"],
                "case_sensitivity_issues": ["Sprite.yy vs sprite.yy"],
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "audit.json"
            with patch("gms_helpers.maintenance.audit.comprehensive_analysis", return_value=analysis_results):
                result, output = _capture_output(
                    asset_helper.maint_audit_command,
                    SimpleNamespace(output=str(output_file)),
                )
            self.assertTrue(result)
            self.assertIn("Comprehensive audit complete", output)
            saved = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["counts"]["truly_orphan"], 2)

        with patch("gms_helpers.asset_helper.resolve_project_directory", return_value=Path("/tmp/project")), \
             patch("gms_helpers.asset_helper.find_orphaned_assets", return_value=[("objects/o_ghost/o_ghost.yy", "object")]), \
             patch("gms_helpers.asset_helper.get_keep_patterns", return_value=[]), \
             patch(
                 "gms_helpers.asset_helper.move_to_trash",
                 return_value={"errors": ["warn"], "moved_count": 1, "trash_folder": "/tmp/project/.maintenance_trash/trash_1"},
             ):
            result, output = _capture_output(
                asset_helper.maint_purge_command,
                SimpleNamespace(apply=True, delete=True, keep=[], project_root="/tmp/project"),
            )
        self.assertTrue(result)
        self.assertIn("Final deletion from trash folder not yet implemented", output)
        self.assertIn("[ERROR] warn", output)

        with patch("gms_helpers.asset_helper.remove_folder_from_yyp", return_value=(True, "Removed folder", [])):
            result, output = _capture_output(
                asset_helper.remove_folder_command,
                SimpleNamespace(folder_path="folders/Test.yy", force=False, dry_run=True),
            )
        self.assertTrue(result)
        self.assertIn("DRY RUN", output)

        folders = [{"name": "Audio", "path": "folders/Audio.yy"}, {"name": "Sprites", "path": "folders/Sprites.yy"}]
        with patch("gms_helpers.asset_helper.list_folders_in_yyp", return_value=(True, folders, "2 folders found")):
            result, output = _capture_output(
                asset_helper.list_folders_command,
                SimpleNamespace(show_paths=True),
            )
        self.assertTrue(result)
        self.assertIn("Audio -> folders/Audio.yy", output)

        with patch("gms_helpers.asset_helper.list_folders_in_yyp", return_value=(False, [], "bad project")):
            result, output = _capture_output(
                asset_helper.list_folders_command,
                SimpleNamespace(show_paths=False),
            )
        self.assertFalse(result)
        self.assertIn("[ERROR] bad project", output)

    def test_test_command_and_purge_no_orphans(self):
        result, output = _capture_output(asset_helper.maint_test_command, SimpleNamespace())
        self.assertTrue(result)
        self.assertIn("Maintenance system initialized", output)

        with patch("gms_helpers.asset_helper.resolve_project_directory", return_value=Path("/tmp/project")), \
             patch("gms_helpers.asset_helper.find_orphaned_assets", return_value=[]):
            result, output = _capture_output(
                asset_helper.maint_purge_command,
                SimpleNamespace(apply=False, delete=False, keep=[], project_root="/tmp/project"),
            )
        self.assertTrue(result)
        self.assertIn("No orphaned assets found to purge", output)


if __name__ == "__main__":
    unittest.main()
