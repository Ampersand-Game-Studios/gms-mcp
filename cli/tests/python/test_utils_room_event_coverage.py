#!/usr/bin/env python3
"""Coverage tests for utils, room helpers, and event sync."""

from __future__ import annotations

import io
import json
import os
import runpy
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers import room_helper, room_instance_helper
from gms_helpers.exceptions import AssetNotFoundError, GMSError, ProjectNotFoundError, ValidationError
from gms_helpers.maintenance import event_sync
from gms_helpers.utils import (
    _list_yyp_files,
    _search_upwards_for_gamemaker_yyp,
    _search_upwards_for_yyp,
    check_resource_conflicts,
    detect_asset_format_version,
    find_yyp_file,
    list_folders_in_yyp,
    remove_folder_from_yyp,
    resolve_project_directory,
    update_yyp_file,
    validate_name,
    validate_parent_path,
    validate_working_directory,
    dedupe_resources,
    load_json_loose,
)


def _capture_output(func, *args, **kwargs):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


def _run_room_helper_as_main(argv: list[str]):
    module_name = "gms_helpers.room_helper"
    existing_module = sys.modules.pop(module_name, None)
    original_argv = sys.argv[:]
    try:
        sys.argv = argv
        return runpy.run_module(module_name, run_name="__main__")
    finally:
        sys.argv = original_argv
        if existing_module is not None:
            sys.modules[module_name] = existing_module


class TestUtilsCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_project(self, name: str = "demo") -> Path:
        yyp_path = self.temp_dir / f"{name}.yyp"
        yyp_path.write_text(json.dumps({"resources": [], "Folders": []}), encoding="utf-8")
        return yyp_path

    def test_detect_asset_format_version_and_validate_name_branches(self):
        obj_dir = self.temp_dir / "objects" / "o_player"
        obj_dir.mkdir(parents=True)
        (obj_dir / "o_player.yy").write_text(json.dumps({"$GMObject": "v2"}), encoding="utf-8")
        self.assertEqual(detect_asset_format_version(self.temp_dir, "objects"), "v2")
        self.assertIsNone(detect_asset_format_version(self.temp_dir, "sprites"))

        broken_dir = self.temp_dir / "objects" / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "broken.yy").write_text("{bad json", encoding="utf-8")
        self.assertEqual(detect_asset_format_version(self.temp_dir, "objects"), "v2")

        disabled_config = SimpleNamespace(naming_enabled=False, get_rule=lambda _asset_type: {"pattern": ".*"})
        validate_name("anything", "object", config=disabled_config)

        no_rule_config = SimpleNamespace(naming_enabled=True, get_rule=lambda _asset_type: None)
        validate_name("anything", "object", config=no_rule_config)

        constructor_config = SimpleNamespace(
            naming_enabled=True,
            get_rule=lambda _asset_type: {"pattern": "^[a-z_]+$"},
            allows_pascal_constructors=lambda _asset_type: True,
        )
        validate_name("PlayerFactory", "script", allow_constructor=True, config=constructor_config)

        no_pattern_config = SimpleNamespace(
            naming_enabled=True,
            get_rule=lambda _asset_type: {"pattern": ""},
            allows_pascal_constructors=lambda _asset_type: False,
        )
        validate_name("anything", "script", config=no_pattern_config)

        with self.assertRaisesRegex(ValueError, "cannot be None"):
            validate_name(None, "object", config=no_rule_config)

        desc_config = SimpleNamespace(
            naming_enabled=True,
            get_rule=lambda _asset_type: {"pattern": "^o_", "description": "needs o_ prefix"},
            allows_pascal_constructors=lambda _asset_type: False,
        )
        with self.assertRaisesRegex(ValueError, "needs o_ prefix"):
            validate_name("player", "object", config=desc_config)

        no_prefix_config = SimpleNamespace(
            naming_enabled=True,
            get_rule=lambda _asset_type: {"pattern": "^foo$"},
            allows_pascal_constructors=lambda _asset_type: False,
        )
        with self.assertRaisesRegex(ValueError, "does not match expected naming pattern"):
            validate_name("bar", "object", config=no_prefix_config)

    def test_project_resolution_and_working_directory_branches(self):
        repo_root = self.temp_dir / "repo"
        gm_dir = repo_root / "gamemaker"
        gm_dir.mkdir(parents=True)
        (gm_dir / "game.yyp").touch()
        nested = repo_root / "scripts" / "nested"
        nested.mkdir(parents=True)

        self.assertEqual(_search_upwards_for_yyp(gm_dir), gm_dir.resolve())
        self.assertEqual(_search_upwards_for_gamemaker_yyp(nested), gm_dir.resolve())
        self.assertEqual(resolve_project_directory(repo_root).resolve(), gm_dir.resolve())

        direct_root = self.temp_dir / "direct"
        direct_root.mkdir()
        (direct_root / "direct.yyp").touch()
        self.assertEqual(resolve_project_directory(direct_root), direct_root)
        self.assertEqual(resolve_project_directory(direct_root / "direct.yyp"), direct_root)

        with patch.dict(os.environ, {"GM_PROJECT_ROOT": str(direct_root)}):
            self.assertEqual(resolve_project_directory(None), direct_root)

        with patch("gms_helpers.utils._list_yyp_files", return_value=[]), patch(
            "gms_helpers.utils._search_upwards_for_yyp",
            return_value=None,
        ), patch(
            "gms_helpers.utils._search_upwards_for_gamemaker_yyp",
            return_value=None,
        ):
            with self.assertRaisesRegex(FileNotFoundError, "No GameMaker project"):
                resolve_project_directory(self.temp_dir / "missing")

        with patch("gms_helpers.utils.Path.glob", side_effect=RuntimeError("glob fail")):
            self.assertEqual(_list_yyp_files(self.temp_dir), [])

        with self.assertRaises(ProjectNotFoundError):
            validate_working_directory()

        (self.temp_dir / "a.yyp").touch()
        (self.temp_dir / "b.yyp").touch()
        result, output = _capture_output(validate_working_directory)
        self.assertIn(result, {"a.yyp", "b.yyp"})
        self.assertIn("Multiple .yyp files", output)

        with self.assertRaisesRegex(ValueError, "Multiple .yyp files"):
            find_yyp_file()

    def test_update_yyp_parent_folder_and_listing_branches(self):
        self._write_project()

        can_create, conflict_type, message = check_resource_conflicts(
            {"resources": [{"id": {"name": "foo", "path": "old.yy"}}]},
            "foo",
            "new.yy",
        )
        self.assertFalse(can_create)
        self.assertEqual(conflict_type, "name_conflict")
        self.assertIn("duplicate", message)

        exact = check_resource_conflicts(
            {"resources": [{"id": {"name": "foo", "path": "same.yy"}}]},
            "foo",
            "same.yy",
        )
        self.assertEqual(exact[1], "exact_duplicate")

        path_conflict = check_resource_conflicts(
            {"resources": [{"id": {"name": "bar", "path": "same.yy"}}]},
            "foo",
            "same.yy",
        )
        self.assertEqual(path_conflict[1], "path_conflict")

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            side_effect=RuntimeError("load fail"),
        ):
            result, output = _capture_output(update_yyp_file, {"id": {"name": "foo", "path": "foo.yy"}})
        self.assertFalse(result)
        self.assertIn("load fail", output)

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"resources": [{"id": {"name": "foo", "path": "old.yy"}}]},
        ):
            result, output = _capture_output(update_yyp_file, {"id": {"name": "foo", "path": "new.yy"}})
        self.assertFalse(result)
        self.assertIn("dedupe-resources", output)

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"resources": []},
        ), patch("gms_helpers.utils.save_json", side_effect=RuntimeError("save fail")):
            result, output = _capture_output(update_yyp_file, {"id": {"name": "foo", "path": "foo.yy"}})
        self.assertFalse(result)
        self.assertIn("save fail", output)

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"Folders": [{"folderPath": "folders/A.yy"}]},
        ):
            self.assertTrue(validate_parent_path("folders/A.yy"))

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"Folders": [{"folderPath": "folders/A.yy"}]},
        ):
            with self.assertRaises(ValidationError):
                validate_parent_path("folders/B.yy")

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            side_effect=GMSError("boom"),
        ):
            with self.assertRaises(GMSError):
                validate_parent_path("folders/A.yy")

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            side_effect=RuntimeError("bad"),
        ):
            with self.assertRaises(ValidationError):
                validate_parent_path("folders/A.yy")

        project_file = self.temp_dir / "resource.yy"
        project_file.write_text(json.dumps({"parent": {"path": "folders/A.yy"}, "resourceType": "GMObject"}), encoding="utf-8")
        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            side_effect=[
                {"Folders": [{"folderPath": "folders/A.yy", "name": "Folder A"}], "resources": [{"id": {"name": "obj", "path": str(project_file)}}]},
                {"parent": {"path": "folders/A.yy"}, "resourceType": "GMObject"},
            ],
        ):
            success, message, assets = remove_folder_from_yyp("folders/A.yy", force=False, dry_run=False)
        self.assertFalse(success)
        self.assertIn("contains 1 assets", message)
        self.assertEqual(assets[0]["name"], "obj")

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"Folders": [{"folderPath": "folders/A.yy", "name": "Folder A"}], "resources": []},
        ):
            success, message, _assets = remove_folder_from_yyp("folders/A.yy", force=False, dry_run=True)
        self.assertTrue(success)
        self.assertIn("Would remove folder", message)

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            return_value={"Folders": [{"folderPath": "folders/A.yy", "name": "Folder A"}], "resources": []},
        ), patch("gms_helpers.utils.save_json", side_effect=RuntimeError("save fail")):
            success, message, _assets = remove_folder_from_yyp("folders/A.yy", force=True, dry_run=False)
        self.assertFalse(success)
        self.assertIn("save fail", message)

        with patch("gms_helpers.utils.find_yyp_file", return_value="demo.yyp"), patch(
            "gms_helpers.utils.load_json",
            side_effect=RuntimeError("list fail"),
        ):
            success, folders, message = list_folders_in_yyp()
        self.assertFalse(success)
        self.assertEqual(folders, [])
        self.assertIn("list fail", message)

        data = {
            "resources": [
                {"id": {"name": "dup", "path": "a.yy"}},
                {"id": {"name": "dup", "path": "b.yy"}},
                {"id": {"name": "ok", "path": "c.yy"}},
            ]
        }
        with patch("builtins.input", side_effect=["bad", "3", "1"]):
            updated, removed, report = dedupe_resources(data, interactive=True)
        self.assertEqual(removed, 1)
        self.assertEqual(len(updated["resources"]), 2)
        self.assertTrue(any("Keeping" in line for line in report))


class TestRoomHelperCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir)
        (self.temp_dir / "rooms").mkdir()
        (self.temp_dir / "game.yyp").touch()

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_room_helper_branches(self):
        with patch("gms_helpers.room_helper.validate_name", side_effect=ValueError("bad name")):
            result, output = _capture_output(room_helper.duplicate_room, "r_old", "bad")
        self.assertFalse(result)
        self.assertIn("bad name", output)

        result, output = _capture_output(room_helper.duplicate_room, "missing", "r_new")
        self.assertFalse(result)
        self.assertIn("Room 'missing' not found", output)

        room_dir = self.temp_dir / "rooms" / "r_old"
        room_dir.mkdir()
        (room_dir / "r_old.yy").touch()
        with patch("gms_helpers.room_helper.duplicate_asset", return_value=SimpleNamespace(success=False, message="duplicate failed")):
            result, output = _capture_output(room_helper.duplicate_room, "r_old", "r_copy")
        self.assertFalse(result)
        self.assertIn("Failed to duplicate room", output)

        result, output = _capture_output(room_helper.rename_room, "missing", "r_new")
        self.assertFalse(result)
        self.assertIn("not found", output)

        with patch("gms_helpers.room_helper.validate_name", side_effect=ValueError("bad rename")):
            result, output = _capture_output(room_helper.rename_room, "r_old", "bad")
        self.assertFalse(result)
        self.assertIn("bad rename", output)

        with patch("gms_helpers.room_helper.rename_asset", return_value=SimpleNamespace(success=False, message="rename failed")):
            result, output = _capture_output(room_helper.rename_room, "r_old", "r_renamed")
        self.assertFalse(result)
        self.assertIn("Failed to rename room", output)

        with patch("gms_helpers.room_helper.delete_asset", return_value=SimpleNamespace(success=False, message="nope")):
            room_dir = self.temp_dir / "rooms" / "r_delete"
            room_dir.mkdir()
            (room_dir / "r_delete.yy").touch()
            result, output = _capture_output(room_helper.delete_room, "r_delete")
        self.assertFalse(result)
        self.assertIn("Failed to delete room", output)

        result, output = _capture_output(room_helper.delete_room, "missing")
        self.assertFalse(result)
        self.assertIn("Room 'missing' not found", output)

        room_dir = self.temp_dir / "rooms" / "r_delete"
        room_dir.mkdir(exist_ok=True)
        (room_dir / "r_delete.yy").touch()
        result, output = _capture_output(room_helper.delete_room, "r_delete", True)
        self.assertTrue(result)
        self.assertIn("Would delete room", output)

        shutil.rmtree(self.temp_dir / "rooms")
        result, output = _capture_output(room_helper.list_rooms)
        self.assertEqual(result, [])
        self.assertIn("No rooms directory found", output)

        (self.temp_dir / "rooms").mkdir()
        result, output = _capture_output(room_helper.list_rooms)
        self.assertEqual(result, [])
        self.assertIn("No rooms found in project", output)

        broken = self.temp_dir / "rooms" / "r_broken"
        broken.mkdir()
        result, output = _capture_output(room_helper.list_rooms)
        self.assertEqual(result[0]["error"], "Missing .yy file")
        self.assertIn("NO .YY", output)

        yy_room = self.temp_dir / "rooms" / "r_bad"
        yy_room.mkdir()
        (yy_room / "r_bad.yy").write_text("{bad json", encoding="utf-8")
        result, output = _capture_output(room_helper.list_rooms)
        self.assertTrue(any(item["name"] == "r_bad" and item["error"] == "Invalid JSON" for item in result))
        self.assertIn("ERROR", output)

        good = self.temp_dir / "rooms" / "r_good"
        good.mkdir()
        (good / "r_good.yy").write_text(
            json.dumps({"roomSettings": {"Width": 10, "Height": 20}, "layers": [{"name": "Instances"}]}),
            encoding="utf-8",
        )
        result, output = _capture_output(room_helper.list_rooms, True)
        self.assertTrue(any(item["name"] == "r_good" for item in result))
        self.assertIn("Layers: Instances", output)

        with patch("gms_helpers.room_helper.load_json_loose", side_effect=RuntimeError("boom")):
            result, output = _capture_output(room_helper.list_rooms, True)
        self.assertTrue(any(item["error"] == "boom" for item in result))
        self.assertIn("Error: boom", output)

    def test_room_helper_handlers_and___main___paths(self):
        with patch("gms_helpers.room_helper.duplicate_room", return_value=True) as mock_duplicate:
            self.assertTrue(room_helper.handle_duplicate(SimpleNamespace(source="r_old", new_name="r_new")))
        mock_duplicate.assert_called_once_with("r_old", "r_new")

        with patch("gms_helpers.room_helper.rename_room", return_value=True) as mock_rename:
            self.assertTrue(room_helper.handle_rename(SimpleNamespace(old_name="r_old", new_name="r_new")))
        mock_rename.assert_called_once_with("r_old", "r_new")

        with patch("gms_helpers.room_helper.delete_room", return_value=True) as mock_delete:
            self.assertTrue(room_helper.handle_delete(SimpleNamespace(room_name="r_old", dry_run=True)))
        mock_delete.assert_called_once_with("r_old", True)

        with patch("gms_helpers.room_helper.list_rooms", return_value=[{"name": "r_main"}]) as mock_list:
            self.assertEqual(room_helper.handle_list(SimpleNamespace(verbose=True)), [{"name": "r_main"}])
        mock_list.assert_called_once_with(True)

    def test_room_helper_main_branches(self):
        with patch.object(sys, "argv", ["room_helper"]):
            result, _output = _capture_output(room_helper.main)
        self.assertFalse(result)

        with patch.object(sys, "argv", ["room_helper", "list"]), patch(
            "gms_helpers.room_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(GMSError("boom"))),
        ):
            with self.assertRaises(GMSError):
                room_helper.main()

        with patch.object(sys, "argv", ["room_helper", "list"]), patch(
            "gms_helpers.room_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(RuntimeError("boom"))),
        ):
            result, output = _capture_output(room_helper.main)
        self.assertFalse(result)
        self.assertIn("Unexpected error", output)

        with patch.object(sys, "argv", ["room_helper", "list"]), patch(
            "gms_helpers.room_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(),
        ):
            result, _output = _capture_output(room_helper.main)
        self.assertFalse(result)

        with self.assertRaises(SystemExit) as false_exit:
            _run_room_helper_as_main(["room_helper"])
        self.assertEqual(false_exit.exception.code, 1)

        with patch(
            "gms_helpers.room_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(ProjectNotFoundError("missing project"))),
        ), self.assertRaises(SystemExit) as gms_error_exit:
            _run_room_helper_as_main(["room_helper", "list"])
        self.assertEqual(gms_error_exit.exception.code, ProjectNotFoundError.exit_code)

        with patch(
            "gms_helpers.room_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(RuntimeError("kaboom"))),
        ), self.assertRaises(SystemExit) as generic_error_exit:
            _run_room_helper_as_main(["room_helper", "list"])
        self.assertEqual(generic_error_exit.exception.code, 1)


class TestRoomInstanceAndEventSyncCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir)
        (self.temp_dir / "game.yyp").touch()
        room_dir = self.temp_dir / "rooms" / "r_test"
        room_dir.mkdir(parents=True)
        self.room_path = room_dir / "r_test.yy"
        self.room_path.write_text(
            json.dumps(
                {
                    "name": "r_test",
                    "layers": [{"name": "Instances", "resourceType": "GMRInstanceLayer", "instances": []}],
                    "instanceCreationOrder": ["inst_existing"],
                }
            ),
            encoding="utf-8",
        )
        object_dir = self.temp_dir / "objects" / "o_test"
        object_dir.mkdir(parents=True)
        self.object_path = object_dir
        (object_dir / "o_test.yy").write_text(
            json.dumps(
                {
                    "eventList": [
                        {"eventType": 0, "eventNum": 0, "resourceVersion": "2.0", "resourceType": "GMEvent"},
                        {"eventType": 3, "eventNum": 0, "resourceVersion": "2.0", "resourceType": "GMEvent"},
                        {"eventType": 8, "eventNum": 0, "resourceVersion": "2.0", "resourceType": "GMEvent"},
                        {"eventType": 1, "eventNum": 0, "resourceVersion": "2.0", "resourceType": "GMEvent"},
                        {"eventType": 7, "eventNum": 2, "resourceVersion": "2.0", "resourceType": "GMEvent"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (object_dir / "Create_0.gml").write_text("// create\n", encoding="utf-8")
        (object_dir / "o_test.gml").write_text("// object code\n", encoding="utf-8")

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_room_instance_helper_branches(self):
        with self.assertRaises(GMSError):
            room_instance_helper._load_room_data(self.temp_dir / "missing.yy")

        data = {"layers": [{"name": "Background", "resourceType": "GMRBackgroundLayer"}]}
        self.room_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValidationError):
            room_instance_helper.add_instance("r_test", "o_player", 1, 2, "Background")

        self.room_path.write_text(
            json.dumps({"layers": [{"name": "Instances", "resourceType": "GMRInstanceLayer"}], "instanceCreationOrder": ["inst_existing"]}),
            encoding="utf-8",
        )
        with patch("uuid.uuid4", return_value=SimpleNamespace(hex="abc123")):
            instance_id = room_instance_helper.add_instance("r_test", "o_player", 3, 4, "Instances")
        self.assertEqual(instance_id, "inst_abc123")
        saved = load_json_loose(self.room_path)
        self.assertIn("instances", saved["layers"][0])
        self.assertIn("inst_abc123", saved["instanceCreationOrder"])

        code_file = self.temp_dir / "rooms" / "r_test" / "inst_abc123.gml"
        code_file.write_text("// init", encoding="utf-8")
        self.assertTrue(room_instance_helper.remove_instance("r_test", "inst_abc123"))
        self.assertFalse(code_file.exists())

        with self.assertRaises(AssetNotFoundError):
            room_instance_helper.remove_instance("r_test", "inst_missing")

        result, output = _capture_output(room_instance_helper.list_instances, "r_test")
        self.assertEqual(result, [])
        self.assertIn("No instances found", output)

        with self.assertRaises(ValidationError):
            room_instance_helper.list_instances("r_test", "Missing")

        self.room_path.write_text(
            json.dumps(
                {
                    "layers": [
                        {
                            "name": "Instances",
                            "resourceType": "GMRInstanceLayer",
                            "instances": [{"name": "inst_mod", "x": 0, "y": 0, "scaleX": 1, "scaleY": 1, "rotation": 0, "objectId": {"name": "o_old"}}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            room_instance_helper.modify_instance(
                "r_test",
                "inst_mod",
                x=5,
                y=6,
                scaleX=2,
                scaleY=3,
                rotation=45,
                object_name="o_new",
            )
        )
        self.assertTrue(room_instance_helper.set_creation_code("r_test", "inst_mod", "show_debug_message('x');"))
        self.assertTrue((self.temp_dir / "rooms" / "r_test" / "inst_mod.gml").exists())

        with self.assertRaises(AssetNotFoundError):
            room_instance_helper.set_creation_code("r_test", "missing", "code")

        handler_args = SimpleNamespace(room="r_test", object="o_player", x=1.0, y=2.0, layer="Instances")
        with patch("gms_helpers.room_instance_helper.add_instance", return_value="inst_handler"):
            self.assertEqual(room_instance_helper.handle_add_instance(handler_args), "inst_handler")

        modify_args = SimpleNamespace(
            room="r_test",
            instance_id="inst_mod",
            x=1,
            y=2,
            scale_x=3,
            scale_y=4,
            rotation=5,
            object="o_new",
        )
        with patch("gms_helpers.room_instance_helper.modify_instance", return_value=True) as modify_mock:
            self.assertTrue(room_instance_helper.handle_modify_instance(modify_args))
        modify_mock.assert_called_once_with(
            "r_test",
            "inst_mod",
            x=1,
            y=2,
            scaleX=3,
            scaleY=4,
            rotation=5,
            object_name="o_new",
        )

        with patch.object(sys, "argv", ["room_instance_helper"]):
            result, _output = _capture_output(room_instance_helper.main)
        self.assertFalse(result)

        with patch.object(sys, "argv", ["room_instance_helper", "list-instances"]), patch(
            "gms_helpers.room_instance_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(GMSError("boom"))),
        ):
            with self.assertRaises(GMSError):
                room_instance_helper.main()

        with patch.object(sys, "argv", ["room_instance_helper", "list-instances"]), patch(
            "gms_helpers.room_instance_helper.validate_working_directory"
        ), patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(func=lambda _args: (_ for _ in ()).throw(RuntimeError("boom"))),
        ):
            result, output = _capture_output(room_instance_helper.main)
        self.assertFalse(result)
        self.assertIn("Unexpected error", output)

    def test_event_sync_branches(self):
        self.assertEqual(event_sync.parse_gml_filename("bad.txt"), (None, None))
        self.assertEqual(event_sync.parse_gml_filename("badname.gml"), (None, None))
        self.assertEqual(event_sync.parse_gml_filename("Step_bad.gml"), (None, None))

        with patch("gms_helpers.maintenance.event_sync.load_json_loose", side_effect=RuntimeError("parse fail")):
            _result, output = _capture_output(event_sync.scan_object_events, str(self.object_path))
        self.assertIn("Could not parse", output)

        self.assertEqual(event_sync.fix_orphaned_gml_files(str(self.temp_dir / "objects" / "missing")), (0, 0))

        orphan_file = self.object_path / "Other_1.gml"
        orphan_file.write_text("// orphan", encoding="utf-8")
        found, fixed = event_sync.fix_orphaned_gml_files(str(self.object_path), dry_run=True)
        self.assertEqual((found, fixed), (1, 0))

        found, fixed = event_sync.fix_orphaned_gml_files(str(self.object_path), dry_run=False)
        self.assertEqual((found, fixed), (1, 1))

        found, created = event_sync.create_missing_gml_files(str(self.object_path), dry_run=False)
        self.assertEqual(found, 4)
        self.assertEqual(created, 4)
        self.assertTrue((self.object_path / "Step_0.gml").exists())
        self.assertTrue((self.object_path / "Draw_0.gml").exists())
        self.assertTrue((self.object_path / "Destroy_0.gml").exists())
        self.assertTrue((self.object_path / "Other_2.gml").exists())

        (self.object_path / "Step_0.gml").unlink()
        with patch("gms_helpers.maintenance.event_sync.save_json_loose", side_effect=RuntimeError("save fail")):
            _result, output = _capture_output(event_sync.fix_missing_gml_files, str(self.object_path), False)
        self.assertIn("Error fixing o_test", output)

        self.assertEqual(event_sync.sync_object_events(str(self.object_path), dry_run=True)["missing_found"], 1)

        empty_project = self.temp_dir / "empty_project"
        empty_project.mkdir()
        with patch(
            "gms_helpers.maintenance.event_sync.resolve_project_directory",
            return_value=empty_project,
        ):
            self.assertEqual(event_sync.sync_all_object_events(str(empty_project), dry_run=True)["objects_processed"], 0)

        all_stats, output = _capture_output(event_sync.sync_all_object_events, str(self.temp_dir), True)
        self.assertEqual(all_stats["objects_processed"], 1)
        self.assertIn("o_test", output)

        with patch.object(sys, "argv", ["event_sync", "--project-root", str(self.temp_dir), "--object", "o_test"]):
            _result, output = _capture_output(event_sync.main)
        self.assertIn("Processed o_test", output)

        with patch.object(sys, "argv", ["event_sync", "--project-root", str(self.temp_dir), "--object", "o_missing"]):
            _result, output = _capture_output(event_sync.main)
        self.assertIn("not found", output)

        with patch.object(sys, "argv", ["event_sync", "--project-root", str(self.temp_dir)]):
            _result, output = _capture_output(event_sync.main)
        self.assertIn("Summary", output)


if __name__ == "__main__":
    unittest.main()
