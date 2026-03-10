#!/usr/bin/env python3
"""Additional coverage tests for gms_helpers.asset_helper."""

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
from unittest.mock import patch


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
        "path": "folders/Test Folder.yy",
        "asset_type": "script",
        "dry_run": False,
        "skip_maintenance": False,
        "no_auto_fix": False,
        "maintenance_verbose": True,
        "constructor": False,
        "sprite_id": None,
        "parent_object": None,
        "frame_count": 1,
        "width": 640,
        "height": 480,
        "font_name": "Arial",
        "size": 16,
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
        "content": "note",
        "fix": False,
        "delete": False,
        "skip_types": ["folder"],
        "object": None,
        "auto": False,
        "output": "audit.json",
        "apply": False,
        "keep": None,
        "folder_path": "folders/Test.yy",
        "force": False,
        "show_paths": False,
        "strict_disk_check": False,
        "include_parent_folders": False,
        "verbose": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


CREATE_CASES = [
    ("create_script", "ScriptAsset", _create_args("PlayerData", constructor=True), "scripts/PlayerData/PlayerData.yy"),
    (
        "create_object",
        "ObjectAsset",
        _create_args("o_player", sprite_id="spr_player", parent_object="o_parent"),
        "objects/o_player/o_player.yy",
    ),
    ("create_sprite", "SpriteAsset", _create_args("spr_player", frame_count=3), "sprites/spr_player/spr_player.yy"),
    ("create_room", "RoomAsset", _create_args("r_start", width=1024, height=768), "rooms/r_start/r_start.yy"),
    ("create_font", "FontAsset", _create_args("fnt_ui"), "fonts/fnt_ui/fnt_ui.yy"),
    ("create_shader", "ShaderAsset", _create_args("sh_blur", shader_type=2), "shaders/sh_blur/sh_blur.yy"),
    ("create_animcurve", "AnimCurveAsset", _create_args("curve_jump"), "animcurves/curve_jump/curve_jump.yy"),
    ("create_sound", "SoundAsset", _create_args("snd_click"), "sounds/snd_click/snd_click.yy"),
    ("create_path", "PathAsset", _create_args("pth_test"), "paths/pth_test/pth_test.yy"),
    (
        "create_tileset",
        "TileSetAsset",
        _create_args("ts_world", sprite_id="spr_tiles"),
        "tilesets/ts_world/ts_world.yy",
    ),
    ("create_timeline", "TimelineAsset", _create_args("tl_intro"), "timelines/tl_intro/tl_intro.yy"),
    ("create_sequence", "SequenceAsset", _create_args("seq_intro"), "sequences/seq_intro/seq_intro.yy"),
    ("create_note", "NoteAsset", _create_args("Design Notes"), "notes/Design Notes/Design Notes.yy"),
]


class TestAssetHelperAdditionalCoverage(unittest.TestCase):
    def test_validate_asset_directory_structure_rejects_cwd_outside_project(self):
        with patch(
            "gms_helpers.asset_helper.validate_gamemaker_context",
            return_value=Path("/tmp/project"),
        ), patch("gms_helpers.asset_helper.Path.cwd", return_value=Path("/tmp/outside")):
            with self.assertRaises(ProjectNotFoundError) as error:
                asset_helper.validate_asset_directory_structure()

        self.assertIn("outside GameMaker project", str(error.exception))

    def test_create_wrappers_precheck_failure_returns_handler_result(self):
        for func_name, class_name, args, _ in CREATE_CASES:
            with self.subTest(func=func_name):
                with ExitStack() as stack:
                    if func_name == "create_script":
                        stack.enter_context(
                            patch(
                                "gms_helpers.asset_helper.validate_asset_directory_structure",
                                return_value=Path("/tmp/project"),
                            )
                        )
                    stack.enter_context(
                        patch(
                            "gms_helpers.asset_helper.run_auto_maintenance",
                            return_value=_maintenance_result(False),
                        )
                    )
                    stack.enter_context(
                        patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=False)
                    )
                    handler = stack.enter_context(
                        patch("gms_helpers.asset_helper.handle_maintenance_failure", return_value="blocked")
                    )

                    result, _ = _capture_output(getattr(asset_helper, func_name), args)

                self.assertEqual(result, "blocked")
                handler.assert_called_once()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "gms_helpers.asset_helper.run_auto_maintenance",
                    return_value=_maintenance_result(False),
                )
            )
            stack.enter_context(
                patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=False)
            )
            handler = stack.enter_context(
                patch("gms_helpers.asset_helper.handle_maintenance_failure", return_value="blocked")
            )
            result, _ = _capture_output(asset_helper.create_folder, _create_args("Folder", path="folders/Folder.yy"))

        self.assertEqual(result, "blocked")
        handler.assert_called_once()

    def test_create_wrappers_report_yyp_update_failure(self):
        for func_name, class_name, args, relative_path in CREATE_CASES:
            with self.subTest(func=func_name):
                with ExitStack() as stack:
                    if func_name == "create_script":
                        stack.enter_context(
                            patch(
                                "gms_helpers.asset_helper.validate_asset_directory_structure",
                                return_value=Path("/tmp/project"),
                            )
                        )
                    stack.enter_context(patch("gms_helpers.asset_helper.validate_name"))
                    stack.enter_context(patch("gms_helpers.asset_helper.validate_parent_path"))
                    stack.enter_context(patch("gms_helpers.asset_helper.update_yyp_file", return_value=False))
                    asset_cls = stack.enter_context(patch(f"gms_helpers.asset_helper.{class_name}"))
                    asset_cls.return_value.create_files.return_value = relative_path

                    result, output = _capture_output(
                        getattr(asset_helper, func_name),
                        SimpleNamespace(**{**args.__dict__, "skip_maintenance": True}),
                    )

                self.assertFalse(result)
                self.assertIn("Failed to update .yyp file", output)

    def test_create_wrappers_catch_create_file_exceptions(self):
        for func_name, class_name, args, _ in CREATE_CASES:
            with self.subTest(func=func_name):
                with ExitStack() as stack:
                    if func_name == "create_script":
                        stack.enter_context(
                            patch(
                                "gms_helpers.asset_helper.validate_asset_directory_structure",
                                return_value=Path("/tmp/project"),
                            )
                        )
                    stack.enter_context(patch("gms_helpers.asset_helper.validate_name"))
                    stack.enter_context(patch("gms_helpers.asset_helper.validate_parent_path"))
                    asset_cls = stack.enter_context(patch(f"gms_helpers.asset_helper.{class_name}"))
                    asset_cls.return_value.create_files.side_effect = RuntimeError("boom")

                    result, output = _capture_output(
                        getattr(asset_helper, func_name),
                        SimpleNamespace(**{**args.__dict__, "skip_maintenance": True}),
                    )

                self.assertFalse(result)
                self.assertIn("boom", output)

        with patch("gms_helpers.asset_helper.FolderAsset") as folder_cls:
            folder_cls.return_value.create_files.side_effect = RuntimeError("folder boom")
            result, output = _capture_output(
                asset_helper.create_folder,
                _create_args("Folder", path="folders/Folder.yy", skip_maintenance=True),
            )

        self.assertFalse(result)
        self.assertIn("folder boom", output)

    def test_create_wrappers_post_maintenance_failure_returns_handler_result(self):
        for func_name, class_name, args, relative_path in CREATE_CASES:
            with self.subTest(func=func_name):
                with ExitStack() as stack:
                    if func_name == "create_script":
                        stack.enter_context(
                            patch(
                                "gms_helpers.asset_helper.validate_asset_directory_structure",
                                return_value=Path("/tmp/project"),
                            )
                        )
                    stack.enter_context(
                        patch(
                            "gms_helpers.asset_helper.run_auto_maintenance",
                            side_effect=[_maintenance_result(False), _maintenance_result(True)],
                        )
                    )
                    stack.enter_context(
                        patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True)
                    )
                    stack.enter_context(patch("gms_helpers.asset_helper.validate_name"))
                    stack.enter_context(patch("gms_helpers.asset_helper.validate_parent_path"))
                    stack.enter_context(patch("gms_helpers.asset_helper.update_yyp_file", return_value=True))
                    handler = stack.enter_context(
                        patch("gms_helpers.asset_helper.handle_maintenance_failure", return_value="post-failed")
                    )
                    asset_cls = stack.enter_context(patch(f"gms_helpers.asset_helper.{class_name}"))
                    asset_cls.return_value.create_files.return_value = relative_path

                    result, _ = _capture_output(getattr(asset_helper, func_name), args)

                self.assertEqual(result, "post-failed")
                handler.assert_called_once()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "gms_helpers.asset_helper.run_auto_maintenance",
                    side_effect=[_maintenance_result(False), _maintenance_result(True)],
                )
            )
            stack.enter_context(
                patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True)
            )
            handler = stack.enter_context(
                patch("gms_helpers.asset_helper.handle_maintenance_failure", return_value="post-failed")
            )
            folder_cls = stack.enter_context(patch("gms_helpers.asset_helper.FolderAsset"))
            folder_cls.return_value.create_files.return_value = "folders/Folder.yy"
            result, _ = _capture_output(asset_helper.create_folder, _create_args("Folder", path="folders/Folder.yy"))

        self.assertEqual(result, "post-failed")
        handler.assert_called_once()

    def test_delete_asset_handles_error_branches(self):
        unsupported = _create_args("bad", asset_type="unsupported", skip_maintenance=True)
        result, output = _capture_output(asset_helper.delete_asset, unsupported)
        self.assertFalse(result)
        self.assertIn("Unsupported asset type", output)

        missing = _create_args("missing", asset_type="script", skip_maintenance=True)
        with patch("gms_helpers.utils.find_yyp_file", return_value="project.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"resources": []},
        ):
            result, output = _capture_output(asset_helper.delete_asset, missing)
        self.assertFalse(result)
        self.assertIn("not found in project", output)

        dry_run_args = _create_args("test_asset", asset_type="script", dry_run=True, skip_maintenance=True)
        with patch("gms_helpers.utils.find_yyp_file", return_value="project.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"resources": [{"id": {"name": "test_asset", "path": "scripts/test_asset/test_asset.yy"}}]},
        ), patch("gms_helpers.asset_helper.Path.exists", return_value=False):
            result, output = _capture_output(asset_helper.delete_asset, dry_run_args)
        self.assertTrue(result)
        self.assertIn("No files found on disk", output)

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            yyp_file = project_root / "game.yyp"
            yyp_file.write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "id": {
                                    "name": "test_asset",
                                    "path": "scripts/test_asset/test_asset.yy",
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            asset_dir = project_root / "scripts" / "test_asset"
            asset_dir.mkdir(parents=True)
            (asset_dir / "test_asset.yy").write_text("{}", encoding="utf-8")

            delete_args = _create_args("test_asset", asset_type="script", skip_maintenance=False)
            with ExitStack() as stack:
                stack.enter_context(patch("gms_helpers.asset_helper.find_yyp_file", return_value=str(yyp_file)))
                stack.enter_context(
                    patch(
                        "gms_helpers.asset_helper.run_auto_maintenance",
                        side_effect=[_maintenance_result(False), _maintenance_result(True)],
                    )
                )
                stack.enter_context(
                    patch("gms_helpers.asset_helper.validate_asset_creation_safe", return_value=True)
                )
                handler = stack.enter_context(
                    patch("gms_helpers.asset_helper.handle_maintenance_failure", return_value="delete-post-failed")
                )
                stack.enter_context(
                    patch("shutil.rmtree", side_effect=OSError("unlink failed"))
                )
                cwd_before = Path.cwd()
                os.chdir(project_root)
                try:
                    result, output = _capture_output(asset_helper.delete_asset, delete_args)
                finally:
                    os.chdir(cwd_before)

        self.assertEqual(result, "delete-post-failed")
        self.assertIn("Warning: Could not delete files on disk", output)
        handler.assert_called_once()

    def test_maintenance_and_folder_command_error_paths(self):
        command_cases = [
            ("maint_lint_command", "gms_helpers.asset_helper.lint_project", RuntimeError("lint fail")),
            (
                "maint_validate_json_command",
                "gms_helpers.maintenance.tidy_json.validate_project_json",
                RuntimeError("json fail"),
            ),
            ("maint_list_orphans_command", "gms_helpers.asset_helper.find_orphaned_assets", RuntimeError("orphans fail")),
            ("maint_prune_missing_command", "gms_helpers.asset_helper.prune_missing_assets", RuntimeError("prune fail")),
            ("maint_validate_paths_command", "gms_helpers.asset_helper.validate_folder_paths", RuntimeError("paths fail")),
            ("maint_fix_issues_command", "gms_helpers.asset_helper.run_auto_maintenance", RuntimeError("auto fail")),
        ]
        for func_name, patch_target, exc in command_cases:
            with self.subTest(func=func_name):
                with patch(patch_target, side_effect=exc):
                    result, output = _capture_output(getattr(asset_helper, func_name), _create_args("arg"))
                self.assertFalse(result)
                self.assertIn(str(exc), output)

        with patch("gms_helpers.asset_helper.find_missing_assets", side_effect=RuntimeError("missing fail")):
            result, output = _capture_output(asset_helper.maint_list_orphans_command, _create_args("orphans"))
        self.assertFalse(result)
        self.assertIn("missing fail", output)

        with patch("gms_helpers.utils.find_yyp_file", return_value="project.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"resources": [{"id": {"name": "dup", "path": "a"}}, {"id": {"name": "dup", "path": "b"}}]},
        ), patch("gms_helpers.utils.dedupe_resources", return_value=({}, 1, ["dup"])), patch(
            "gms_helpers.utils.save_json",
            side_effect=RuntimeError("save fail"),
        ):
            result, output = _capture_output(
                asset_helper.maint_dedupe_resources_command,
                _create_args("dup", auto=True, dry_run=False),
            )
        self.assertFalse(result)
        self.assertIn("save fail", output)

        with patch("gms_helpers.asset_helper.remove_folder_from_yyp", return_value=(False, "blocked", [])):
            result, output = _capture_output(asset_helper.remove_folder_command, _create_args("folder"))
        self.assertFalse(result)
        self.assertIn("blocked", output)

        with patch("gms_helpers.asset_helper.remove_folder_from_yyp", side_effect=RuntimeError("remove fail")):
            result, output = _capture_output(asset_helper.remove_folder_command, _create_args("folder"))
        self.assertFalse(result)
        self.assertIn("remove fail", output)

        with patch(
            "gms_helpers.asset_helper.list_folders_in_yyp",
            return_value=(True, [{"name": "Folder", "path": "folders/Folder.yy"}], "one folder"),
        ):
            result, output = _capture_output(
                asset_helper.list_folders_command,
                _create_args("folder", show_paths=False),
            )
        self.assertTrue(result)
        self.assertIn("Use --show-paths", output)

        with patch(
            "gms_helpers.asset_helper.list_folders_in_yyp",
            return_value=(True, [], "empty"),
        ):
            result, output = _capture_output(asset_helper.list_folders_command, _create_args("folder"))
        self.assertTrue(result)
        self.assertIn("(No folders found)", output)

        with patch("gms_helpers.asset_helper.list_folders_in_yyp", side_effect=RuntimeError("list fail")):
            result, output = _capture_output(asset_helper.list_folders_command, _create_args("folder"))
        self.assertFalse(result)
        self.assertIn("list fail", output)

    def test_sync_clean_audit_and_purge_command_branches(self):
        with patch("os.path.exists", return_value=False):
            result, output = _capture_output(
                asset_helper.maint_sync_events_command,
                _create_args("sync", fix=False, object="o_missing"),
            )
        self.assertFalse(result)
        self.assertIn("not found", output)

        with patch(
            "gms_helpers.maintenance.event_sync.sync_all_object_events",
            return_value={
                "objects_processed": 1,
                "orphaned_found": 0,
                "orphaned_fixed": 0,
                "missing_found": 0,
                "missing_created": 0,
            },
        ):
            result, output = _capture_output(asset_helper.maint_sync_events_command, _create_args("sync"))
        self.assertTrue(result)
        self.assertIn("All object events are properly synchronized", output)

        with patch("gms_helpers.maintenance.clean_unused_assets.clean_old_yy_files", return_value=(2, 1)):
            result, output = _capture_output(
                asset_helper.maint_clean_old_files_command,
                _create_args("clean", delete=True),
            )
        self.assertTrue(result)
        self.assertIn("deleted 1", output)

        with patch("gms_helpers.maintenance.clean_unused_assets.clean_old_yy_files", return_value=(0, 0)):
            result, output = _capture_output(asset_helper.maint_clean_old_files_command, _create_args("clean"))
        self.assertTrue(result)
        self.assertIn("No .old.yy files found", output)

        with patch(
            "gms_helpers.asset_helper.delete_orphan_files",
            return_value={
                "total_deleted": 0,
                "deleted_directories": [],
                "deleted_files": [],
                "errors": ["one", "two", "three", "four", "five", "six"],
            },
        ):
            result, output = _capture_output(asset_helper.maint_clean_orphans_command, _create_args("orphans"))
        self.assertTrue(result)
        self.assertIn("No orphaned files found", output)
        self.assertIn("... and 1 more errors", output)

        with patch("gms_helpers.asset_helper.find_orphaned_assets", return_value=[]):
            result, output = _capture_output(
                asset_helper.maint_purge_command,
                _create_args("purge", apply=True, delete=False),
            )
        self.assertTrue(result)
        self.assertIn("No orphaned assets found", output)

        with patch("gms_helpers.asset_helper.find_orphaned_assets", return_value=[("objects/o_a/o_a.yy", "object")]), patch(
            "gms_helpers.asset_helper.get_keep_patterns",
            return_value=["o_a"],
        ):
            result, output = _capture_output(
                asset_helper.maint_purge_command,
                _create_args("purge", apply=True, delete=False),
            )
        self.assertTrue(result)
        self.assertIn("protected by keep patterns", output)

        with patch("gms_helpers.asset_helper.find_orphaned_assets", return_value=[("objects/o_a/o_a.yy", "object")]), patch(
            "gms_helpers.asset_helper.get_keep_patterns",
            return_value=[],
        ), patch(
            "gms_helpers.asset_helper.move_to_trash",
            return_value={"errors": ["trash fail"], "moved_count": 1, "trash_folder": ".trash"},
        ):
            result, output = _capture_output(
                asset_helper.maint_purge_command,
                _create_args("purge", apply=True, delete=True),
            )
        self.assertTrue(result)
        self.assertIn("trash fail", output)
        self.assertIn("Final deletion from trash folder not yet implemented", output)

        with patch("gms_helpers.maintenance.audit.comprehensive_analysis", side_effect=RuntimeError("audit fail")):
            result, output = _capture_output(asset_helper.maint_audit_command, _create_args("audit"))
        self.assertFalse(result)
        self.assertIn("audit fail", output)

    def test_main_error_paths(self):
        with patch.object(sys, "argv", ["asset_helper"]), patch(
            "gms_helpers.asset_helper.validate_working_directory"
        ):
            with self.assertRaises(SystemExit):
                asset_helper.main()

        with patch.object(sys, "argv", ["asset_helper", "test"]), patch(
            "gms_helpers.asset_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(GMSError("boom"))),
        ):
            with self.assertRaises(GMSError):
                asset_helper.main()

        with patch.object(sys, "argv", ["asset_helper", "test"]), patch(
            "gms_helpers.asset_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(RuntimeError("unexpected"))),
        ):
            result, output = _capture_output(asset_helper.main)
        self.assertFalse(result)
        self.assertIn("Unexpected error: unexpected", output)


if __name__ == "__main__":
    unittest.main()
