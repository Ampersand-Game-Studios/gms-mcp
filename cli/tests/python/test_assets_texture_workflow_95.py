#!/usr/bin/env python3
"""Push assets, texture_groups, and workflow modules toward 95% coverage."""

from __future__ import annotations

import builtins
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.assets import (
    AnimCurveAsset,
    FolderAsset,
    FontAsset,
    NoteAsset,
    ObjectAsset,
    PathAsset,
    RoomAsset,
    ScriptAsset,
    SequenceAsset,
    ShaderAsset,
    SoundAsset,
    SpriteAsset,
    TileSetAsset,
    TimelineAsset,
)
from gms_helpers.exceptions import AssetExistsError, InvalidAssetTypeError, JSONParseError
from gms_helpers.texture_groups import (
    _asset_supports_texture_groups,
    _iter_resource_assets,
    _replace_asset_group_references,
    find_texture_group,
    get_asset_group_assignments,
    get_project_configs,
    load_project_yyp,
    parse_group_ref,
    set_asset_group,
    texture_group_assign,
    texture_group_create,
    texture_group_delete,
    texture_group_members,
    texture_group_rename,
    texture_group_scan,
    texture_group_update,
)
from gms_helpers.utils import load_json_loose, save_pretty_json
from gms_helpers.workflow import (
    _c,
    _cleanup_symbol_references,
    _collect_incoming_dependencies,
    delete_asset,
    duplicate_asset,
    lint_project,
    rename_asset,
    swap_sprite_png,
)


def _fake_config(rule):
    return SimpleNamespace(naming_enabled=True, get_rule=lambda _kind: rule)


class TestAssets95Coverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "folders").mkdir()
        (self.project_root / "TestGame.yyp").write_text(json.dumps({"Folders": [], "resources": []}), encoding="utf-8")
        self.parent_path = "folders/TestFolder.yy"
        (self.project_root / self.parent_path).write_text(
            json.dumps(
                {
                    "$GMFolder": "",
                    "%Name": "TestFolder",
                    "folderPath": self.parent_path,
                    "name": "TestFolder",
                    "resourceType": "GMFolder",
                    "resourceVersion": "2.0",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_validation_false_empty_pattern_and_real_pattern_branches(self):
        cases = [
            (ScriptAsset(), "scr_alpha"),
            (ObjectAsset(), "o_actor"),
            (SpriteAsset(), "spr_actor"),
            (RoomAsset(), "r_room"),
            (FontAsset(), "fnt_ui"),
            (ShaderAsset(), "shd_light"),
            (AnimCurveAsset(), "ac_curve"),
            (SoundAsset(), "snd_hit"),
            (PathAsset(), "pth_path"),
            (TileSetAsset(), "ts_ground"),
            (TimelineAsset(), "tl_intro"),
            (SequenceAsset(), "seq_intro"),
        ]

        for asset, valid_name in cases:
            with self.subTest(asset=asset.kind):
                self.assertFalse(asset.validate_name(""))
                with patch(
                    "gms_helpers.assets.get_config",
                    return_value=_fake_config({"pattern": ""}),
                ):
                    self.assertTrue(asset.validate_name(valid_name))
                with patch(
                    "gms_helpers.assets.get_config",
                    return_value=_fake_config({"pattern": rf"^{re.escape(valid_name)}$"}),
                ):
                    self.assertTrue(asset.validate_name(valid_name))

        folder_asset = FolderAsset()
        self.assertFalse(folder_asset.validate_name(""))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config({"pattern": ""})):
            self.assertTrue(folder_asset.validate_name("UI / Bar"))
        with patch(
            "gms_helpers.assets.get_config",
            return_value=_fake_config({"pattern": r"^UI(/[A-Za-z0-9_ ]+)?$"}),
        ):
            self.assertTrue(folder_asset.validate_name("UI/Sub Menu"))

        note_asset = NoteAsset()
        self.assertFalse(note_asset.validate_name(""))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config({"pattern": ""})):
            self.assertTrue(note_asset.validate_name("Design Note"))
        with patch(
            "gms_helpers.assets.get_config",
            return_value=_fake_config({"pattern": r"^Design Note$"}),
        ):
            self.assertTrue(note_asset.validate_name("Design Note"))

    def test_misc_asset_branches(self):
        folder_asset = FolderAsset()
        self.assertEqual(folder_asset.create_yy_data("Loose", "/")["folderPath"], "folders/Loose.yy")
        created_folder = folder_asset.create_files(self.project_root, "RootFolder", parent_path="/")
        self.assertEqual(created_folder, "folders/RootFolder.yy")

        smooth_curve = AnimCurveAsset().create_yy_data("ac_curve", self.parent_path, curve_type="smooth")
        self.assertEqual(len(smooth_curve["channels"][0]["points"]), 3)

        wav_path = self.project_root / "silent.wav"
        SoundAsset()._write_silent_wav(wav_path, sample_rate="invalid")
        self.assertTrue(wav_path.exists())


class TestTextureGroups95Coverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.yyp_path = self.project_root / "TestGame.yyp"
        (self.project_root / "sprites" / "spr_ok").mkdir(parents=True)
        self.sprite_yy = self.project_root / "sprites" / "spr_ok" / "spr_ok.yy"
        self.sprite_yy.write_text(
            json.dumps({"textureGroupId": {"name": "old", "path": "texturegroups/old"}}),
            encoding="utf-8",
        )
        self._write_yyp(
            {
                "configs": {"name": "Default", "children": [None, {"name": "desktop", "children": []}]},
                "resources": [{"id": {"name": "spr_ok", "path": "sprites/spr_ok/spr_ok.yy"}}],
                "TextureGroups": [
                    {
                        "name": "Default",
                        "%Name": "Default",
                        "groupParent": None,
                        "ConfigValues": {"desktop": {"groupParent": "old", "loadType": "default"}},
                    },
                    {
                        "name": "old",
                        "%Name": "old",
                        "groupParent": "old",
                        "ConfigValues": {"desktop": {"groupParent": "old", "loadType": "default"}},
                    },
                ],
            }
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_yyp(self, data):
        self.yyp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_helper_and_guard_branches(self):
        with patch("gms_helpers.texture_groups.load_json_loose", return_value=[]):
            with self.assertRaises(FileNotFoundError):
                load_project_yyp(self.project_root)

        self.assertEqual(get_project_configs({"configs": []}), [])
        self.assertEqual(
            get_project_configs({"configs": {"name": "Default", "children": [None, {"name": "desktop", "children": []}]}}),
            ["desktop"],
        )
        self.assertIsNotNone(find_texture_group({"TextureGroups": [{"name": None}, {"name": "UI"}]}, "UI"))
        self.assertIsNone(parse_group_ref("not-json"))

        with patch("gms_helpers.texture_groups.strip_trailing_commas", return_value="{still-bad}"):
            self.assertIsNone(parse_group_ref("{broken json}"))
        self.assertIsNone(parse_group_ref("{}"))
        self.assertFalse(_asset_supports_texture_groups([]))

        assignments = get_asset_group_assignments({"ConfigValues": {1: {}, "bad": "value", "skip": {}}})
        self.assertEqual(assignments["configs"], {})

        asset_yy = {"textureGroupId": [], "ConfigValues": {"desktop": "bad"}}
        changed, warnings = set_asset_group(
            asset_yy,
            "ui",
            include_top_level=True,
            configs_to_set=None,
            update_existing_configs=True,
        )
        self.assertFalse(changed)
        self.assertTrue(any("unexpected type" in warning for warning in warnings))

        changed, _ = set_asset_group(
            {"textureGroupId": {"name": "old", "path": "texturegroups/old"}},
            "ui",
            include_top_level=False,
            configs_to_set=["", "desktop"],
            update_existing_configs=False,
        )
        self.assertTrue(changed)

        changed, warnings = _replace_asset_group_references(
            {"ConfigValues": {"desktop": "bad", "mobile": {}, "ios": {"textureGroupId": '{ "name":"old", "path":"texturegroups/old" }'}}},
            from_group="old",
            to_group="new",
            include_top_level=False,
            configs_to_consider=["desktop", "mobile", "ios"],
            update_existing_configs=False,
        )
        self.assertTrue(changed)
        self.assertEqual(warnings, [])

        with patch(
            "gms_helpers.texture_groups.list_assets_by_type",
            return_value={"sprite": [{"name": "spr_ok", "path": "sprites/spr_ok/spr_ok.yy"}], "font": "bad", "script": [{}]},
        ):
            self.assertEqual(len(_iter_resource_assets(self.project_root, asset_types=["sprite"])), 1)
            self.assertEqual(len(_iter_resource_assets(self.project_root)), 1)

    def test_members_scan_create_update_assign_and_rename_branches(self):
        with patch("gms_helpers.texture_groups._iter_resource_assets", return_value=[{"name": "bad", "path": "bad.yy", "type": "sprite"}, {"name": "spr_ok", "path": "sprites/spr_ok/spr_ok.yy", "type": "sprite"}]):
            with patch("gms_helpers.texture_groups.read_asset_yy", side_effect=[None, {"textureGroupId": {"name": "ghost", "path": "texturegroups/ghost"}, "ConfigValues": {"desktop": None, "mobile": {"textureGroupId": '{ "name":"ghost", "path":"texturegroups/ghost" }'}}}]):
                members = texture_group_members(self.project_root, "ghost", configs=["desktop"])
        self.assertTrue(any("not defined" in warning for warning in members["warnings"]))
        self.assertEqual(members["members"][0]["config_groups"], {"desktop": None})

        with patch("gms_helpers.texture_groups._iter_resource_assets", return_value=[{"name": "bad", "path": "bad.yy", "type": "sprite"}, {"name": "spr_ok", "path": "sprites/spr_ok/spr_ok.yy", "type": "sprite"}]):
            with patch("gms_helpers.texture_groups.read_asset_yy", side_effect=[None, {"textureGroupId": {"name": "ghost", "path": "texturegroups/ghost"}, "ConfigValues": {"desktop": None, "mobile": {"textureGroupId": '{ "name":"ghost", "path":"texturegroups/ghost" }'}}}]):
                scan = texture_group_scan(self.project_root, configs=["desktop"], include_assets=True)
        self.assertIn("ghost", scan["missing_groups_referenced"])
        self.assertEqual(scan["assets"][0]["config_groups"], {})

        self._write_yyp(
            {
                "configs": {"name": "Default", "children": [{"name": "desktop", "children": []}]},
                "resources": [],
                "textureGroups": [
                    {"name": "Default", "%Name": "Default", "ConfigValues": {"desktop": {"loadType": "default"}}}
                ],
            }
        )
        create_res = texture_group_create(
            self.project_root,
            "ui",
            patch={"name": "wrong", "%Name": "wrong", "border": 4},
            dry_run=False,
        )
        self.assertTrue(create_res["ok"])
        created_groups = load_json_loose(self.yyp_path)["textureGroups"]
        self.assertEqual(created_groups[-1]["name"], "ui")
        self.assertEqual(created_groups[-1]["%Name"], "ui")

        self._write_yyp({"TextureGroups": {}})
        self.assertFalse(texture_group_create(self.project_root, "bad")["ok"])

        self._write_yyp({"TextureGroups": []})
        self.assertFalse(texture_group_create(self.project_root, "bad")["ok"])

        self._write_yyp(
            {
                "TextureGroups": [{"name": "Default", "%Name": "Default", "ConfigValues": None}],
                "configs": {"name": "Default", "children": [{"name": "desktop", "children": []}]},
            }
        )
        update_res = texture_group_update(
            self.project_root,
            "Default",
            patch={"loadType": "dynamicpages"},
            configs=["desktop"],
            dry_run=False,
        )
        self.assertTrue(update_res["ok"])

        self._write_yyp(
            {
                "TextureGroups": [{"name": "Default", "%Name": "Default", "ConfigValues": {"desktop": "bad", "ios": {"loadType": "default"}}}],
                "configs": {"name": "Default", "children": [{"name": "desktop", "children": []}]},
            }
        )
        update_res = texture_group_update(
            self.project_root,
            "Default",
            patch={"loadType": "dynamicpages"},
            configs=None,
            update_existing_configs=True,
            dry_run=False,
        )
        self.assertTrue(update_res["ok"])

        self._write_yyp(
            {
                "configs": {"name": "Default", "children": [{"name": "desktop", "children": []}]},
                "resources": [{"id": {"name": "spr_ok", "path": "sprites/spr_ok/spr_ok.yy"}}],
                "TextureGroups": [
                    {"name": "Default", "%Name": "Default", "groupParent": "old", "ConfigValues": {"desktop": {"groupParent": "old"}}},
                    {"name": "old", "%Name": "old", "groupParent": "old", "ConfigValues": {"desktop": {"groupParent": "old"}}},
                ],
            }
        )
        with patch("gms_helpers.texture_groups._iter_resource_assets", return_value=[{"name": "bad", "path": "bad.yy", "type": "sprite"}, {"name": "spr_ok", "path": "sprites/spr_ok/spr_ok.yy", "type": "sprite"}]):
            with patch("gms_helpers.texture_groups.read_asset_yy", side_effect=["bad", {"textureGroupId": {"name": "old", "path": "texturegroups/old"}}]):
                with patch("gms_helpers.texture_groups.get_asset_yy_path", side_effect=[None, self.sprite_yy]):
                    with patch("gms_helpers.texture_groups._replace_asset_group_references", return_value=(True, ["warned"])):
                        rename_res = texture_group_rename(self.project_root, "old", "new", update_references=True, dry_run=True)
        self.assertTrue(rename_res["ok"])
        self.assertTrue(any("warned" in warning for warning in rename_res["warnings"]))

        with patch("gms_helpers.texture_groups.get_asset_yy_path", return_value=None):
            assign_res = texture_group_assign(
                self.project_root,
                "old",
                asset_identifiers=["", "missing_asset"],
                dry_run=True,
            )
        self.assertTrue(assign_res["ok"])
        self.assertIn("missing_asset", assign_res["details"]["assets_skipped"])

        def assign_reader(_project_root, asset_path):
            if asset_path == "sprites/spr_ok/spr_ok.yy":
                return {"textureGroupId": {"name": "old", "path": "texturegroups/old"}, "ConfigValues": {}}
            return {"textureGroupId": {"name": "other", "path": "texturegroups/other"}, "ConfigValues": {}}

        with patch("gms_helpers.texture_groups._iter_resource_assets", return_value=[{"name": "spr_ok", "path": "sprites/spr_ok/spr_ok.yy", "type": "sprite"}, {"name": "other", "path": "sprites/other/other.yy", "type": "sprite"}]):
            with patch("gms_helpers.texture_groups.read_asset_yy", side_effect=assign_reader):
                with patch("gms_helpers.texture_groups.get_asset_yy_path", side_effect=[None]):
                    assign_res = texture_group_assign(
                        self.project_root,
                        "old",
                        from_group="old",
                        dry_run=True,
                    )
        self.assertTrue(assign_res["ok"])

    def test_delete_lower_key_and_invalid_groups_branches(self):
        self._write_yyp({"textureGroups": {}})
        with patch("gms_helpers.texture_groups.find_texture_group", return_value=(0, {"name": "old"})):
            res = texture_group_delete(self.project_root, "old", dry_run=True)
        self.assertFalse(res["ok"])

        self._write_yyp({"textureGroups": []})
        with patch("gms_helpers.texture_groups.find_texture_group", return_value=(0, {"name": "old"})):
            res = texture_group_delete(self.project_root, "old", dry_run=True)
        self.assertFalse(res["ok"])


class TestWorkflow95Coverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        for folder in ("scripts", "objects", "sprites", "rooms", "folders"):
            (self.project_root / folder).mkdir()
        self.yyp_path = self.project_root / "TestGame.yyp"
        save_pretty_json(self.yyp_path, {"resources": [], "Folders": []})

    def tearDown(self):
        self.temp_dir.cleanup()

    def _register_script(self, name: str) -> str:
        ScriptAsset().create_files(self.project_root, name, "")
        rel_path = f"scripts/{name}/{name}.yy"
        yyp_data = load_json_loose(self.yyp_path)
        yyp_data["resources"].append({"id": {"name": name, "path": rel_path}})
        save_pretty_json(self.yyp_path, yyp_data)
        return rel_path

    def test_color_output_and_dependency_cleanup_helpers(self):
        fake_colorama = SimpleNamespace(
            Fore=SimpleNamespace(GREEN="<g>"),
            Style=SimpleNamespace(RESET_ALL="</g>"),
        )
        with patch("gms_helpers.workflow.colorama", fake_colorama):
            with patch("gms_helpers.workflow.sys.stdout.isatty", return_value=True):
                self.assertEqual(_c("ok", "green"), "<g>ok</g>")

        with patch(
            "gms_helpers.introspection.build_asset_graph",
            return_value={
                "nodes": [{"id": "caller", "type": "script", "path": "scripts/caller/caller.yy"}],
                "edges": [
                    "bad-edge",
                    {"from": "caller", "to": "other"},
                    {"from": "target", "to": "target"},
                    {"from": "caller", "to": "target"},
                ],
            },
        ):
            deps = _collect_incoming_dependencies(self.project_root, "target")
        self.assertEqual(deps[0]["relation"], "unknown")

        (self.project_root / "scripts" / "caller").mkdir(parents=True)
        gml_path = self.project_root / "scripts" / "caller" / "caller.gml"
        gml_path.write_text("target();", encoding="utf-8")
        original_read_text = Path.read_text

        def selective_read_text(path_obj, *args, **kwargs):
            if path_obj == gml_path:
                raise OSError("locked")
            return original_read_text(path_obj, *args, **kwargs)

        with patch.object(Path, "read_text", selective_read_text):
            cleanup = _cleanup_symbol_references(self.project_root, "target")
        self.assertEqual(cleanup["replacements"], 0)

    def test_duplicate_rename_delete_swap_and_lint_branches(self):
        original_path = self._register_script("original")
        (self.project_root / "scripts" / "copy").mkdir(parents=True)
        with self.assertRaises(AssetExistsError):
            duplicate_asset(self.project_root, original_path, "copy")
        shutil.rmtree(self.project_root / "scripts" / "copy", ignore_errors=True)

        real_loader = load_json_loose

        def duplicate_loader(path_obj):
            if Path(path_obj) == self.yyp_path:
                return None
            return real_loader(path_obj)

        with patch("gms_helpers.workflow.load_json_loose", side_effect=duplicate_loader):
            with self.assertRaises(JSONParseError):
                duplicate_asset(self.project_root, original_path, "copy")

        fake_maintenance = types.ModuleType("gms_helpers.auto_maintenance")
        fake_maintenance.run_auto_maintenance = lambda *args, **kwargs: SimpleNamespace(has_errors=True)
        with patch.dict(sys.modules, {"gms_helpers.auto_maintenance": fake_maintenance}):
            with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=True):
                result = duplicate_asset(self.project_root, original_path, "copy_warn")
        self.assertTrue(any("maintenance found issues" in warning for warning in result.warnings))

        original_import = builtins.__import__

        def import_without_auto_maintenance(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "auto_maintenance" and level == 1:
                raise ImportError("missing")
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=import_without_auto_maintenance):
            with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=True):
                result = duplicate_asset(self.project_root, original_path, "copy_no_maint")
        self.assertTrue(result.success)

        rename_source = self._register_script("rename_me")
        (self.project_root / "scripts" / "exists").mkdir(parents=True)
        with self.assertRaises(AssetExistsError):
            rename_asset(self.project_root, rename_source, "exists")
        shutil.rmtree(self.project_root / "scripts" / "exists", ignore_errors=True)

        def yy_none_loader(path_obj):
            if Path(path_obj).name == "rename_new.yy":
                return None
            return real_loader(path_obj)

        with self.assertRaises(JSONParseError):
            with patch("gms_helpers.workflow.load_json_loose", side_effect=yy_none_loader):
                rename_asset(self.project_root, rename_source, "rename_new")

        rename_source = self._register_script("rename_again")

        def yyp_none_loader(path_obj):
            if Path(path_obj) == self.yyp_path:
                return None
            return real_loader(path_obj)

        with self.assertRaises(JSONParseError):
            with patch("gms_helpers.workflow.load_json_loose", side_effect=yyp_none_loader):
                rename_asset(self.project_root, "scripts/rename_again/rename_again.yy", "renamed")

        rename_source = self._register_script("scan_me")
        absolute_scanner = types.ModuleType("reference_scanner")
        absolute_scanner.comprehensive_rename_asset = lambda *args, **kwargs: False

        def import_with_absolute_fallback(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "reference_scanner" and level == 1:
                raise ImportError("relative missing")
            if name == "auto_maintenance" and level == 1:
                raise ImportError("maintenance missing")
            return original_import(name, globals, locals, fromlist, level)

        with patch.dict(sys.modules, {"reference_scanner": absolute_scanner}):
            with patch("builtins.__import__", side_effect=import_with_absolute_fallback):
                with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=True):
                    result = rename_asset(self.project_root, rename_source, "scan_done")
        self.assertTrue(any("fully updated" in warning or "Reference scanner not available" in warning for warning in result.warnings))

        delete_source = self._register_script("delete_me")

        def delete_none_loader(path_obj):
            if Path(path_obj) == self.yyp_path:
                return None
            return real_loader(path_obj)

        with self.assertRaises(JSONParseError):
            with patch("gms_helpers.workflow.load_json_loose", side_effect=delete_none_loader):
                delete_asset(self.project_root, delete_source, dry_run=False)

        delete_source = self._register_script("delete_ok")
        with patch("builtins.__import__", side_effect=import_without_auto_maintenance):
            result = delete_asset(self.project_root, delete_source, dry_run=False)
        self.assertTrue(result.success)

        sprite_dir = self.project_root / "sprites" / "spr_test"
        sprite_dir.mkdir(parents=True)
        sprite_yy = sprite_dir / "spr_test.yy"
        sprite_yy.write_text(
            json.dumps({"frames": [{"name": "frame"}], "layers": [{"name": "layer"}]}),
            encoding="utf-8",
        )

        with self.assertRaises(InvalidAssetTypeError):
            swap_sprite_png(self.project_root, original_path, self.project_root / "missing.png")

        with patch("gms_helpers.workflow.load_json_loose", return_value=None):
            with self.assertRaises(JSONParseError):
                swap_sprite_png(self.project_root, "sprites/spr_test/spr_test.yy", self.project_root / "missing.png")

        with self.assertRaises(FileNotFoundError):
            swap_sprite_png(self.project_root, "sprites/spr_test/spr_test.yy", Path("relative_missing.png"))

        png_source = self.project_root / "input.png"
        png_source.write_bytes(b"png")
        (sprite_dir / "frame.png").write_bytes(b"old")

        with patch("gms_helpers.workflow.shutil.copy2", side_effect=RuntimeError("copy failed")):
            with self.assertRaises(PermissionError):
                swap_sprite_png(self.project_root, "sprites/spr_test/spr_test.yy", png_source)

        with patch("gms_helpers.workflow.find_yyp", return_value=self.yyp_path):
            with patch("gms_helpers.workflow.load_json_loose", return_value=None):
                with self.assertRaises(JSONParseError):
                    lint_project(self.project_root)

        bad_yy = self.project_root / "scripts" / "bad" / "bad.yy"
        bad_yy.parent.mkdir(parents=True)
        bad_yy.write_text("{bad json", encoding="utf-8")
        with patch("gms_helpers.workflow.load_json_loose", side_effect=lambda path_obj: (_ for _ in ()).throw(ValueError("broken")) if Path(path_obj) == bad_yy else real_loader(path_obj)):
            lint_result = lint_project(self.project_root)
        self.assertFalse(lint_result.success)


if __name__ == "__main__":
    unittest.main()
