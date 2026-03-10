#!/usr/bin/env python3
"""Targeted coverage tests for assets, texture groups, and workflow helpers."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import wave
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
from gms_helpers.exceptions import InvalidAssetTypeError, JSONParseError
from gms_helpers.texture_groups import (
    _asset_supports_texture_groups,
    _iter_resource_assets,
    _replace_asset_group_references,
    find_texture_group,
    get_asset_group_assignments,
    get_project_configs,
    get_texture_groups_list,
    load_project_yyp,
    parse_group_ref,
    serialize_group_ref_for_config,
    set_asset_group,
    texture_group_assign,
    texture_group_create,
    texture_group_delete,
    texture_group_rename,
    texture_group_update,
)
from gms_helpers.utils import load_json_loose, save_pretty_json
from gms_helpers.workflow import (
    _asset_from_path,
    _cleanup_symbol_references,
    _copy_tree,
    _patch_gml_stub,
    _try_import,
    duplicate_asset,
    lint_project,
    rename_asset,
    safe_delete_asset,
    swap_sprite_png,
)


def _fake_config(*, naming_enabled: bool = True, rule=None):
    return SimpleNamespace(naming_enabled=naming_enabled, get_rule=lambda _kind: rule)


class TestAssetsGapCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "folders").mkdir()
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

    def test_script_constructor_stub_and_validation_shortcuts(self):
        asset = ScriptAsset()
        asset_folder = self.project_root / "scripts" / "scr_build"
        asset_folder.mkdir(parents=True)
        asset.create_stub_files(asset_folder, "scr_build", is_constructor=True)
        content = (asset_folder / "scr_build.gml").read_text(encoding="utf-8")
        self.assertIn("constructor", content)

        with patch("gms_helpers.assets.get_config", return_value=_fake_config(naming_enabled=False)):
            self.assertTrue(asset.validate_name("scr_build"))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule=None)):
            self.assertTrue(asset.validate_name("scr_build"))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule={})):
            self.assertTrue(asset.validate_name("scr_build"))

    def test_validate_name_shortcuts_across_asset_types(self):
        cases = [
            (ObjectAsset(), "o_actor"),
            (SpriteAsset(), "spr_actor"),
            (RoomAsset(), "r_stage"),
            (FontAsset(), "fnt_ui"),
            (ShaderAsset(), "shd_light"),
            (AnimCurveAsset(), "ac_curve"),
            (SoundAsset(), "snd_hit"),
            (PathAsset(), "pth_route"),
            (TileSetAsset(), "ts_ground"),
            (TimelineAsset(), "tl_intro"),
            (SequenceAsset(), "seq_intro"),
        ]

        for asset, valid_name in cases:
            with self.subTest(asset=asset.kind):
                with patch("gms_helpers.assets.get_config", return_value=_fake_config(naming_enabled=False)):
                    self.assertTrue(asset.validate_name(valid_name))
                with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule=None)):
                    self.assertTrue(asset.validate_name(valid_name))
                with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule={})):
                    self.assertTrue(asset.validate_name(valid_name))

        folder_asset = FolderAsset()
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(naming_enabled=False)):
            self.assertTrue(folder_asset.validate_name("UI/Button Bar"))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule=None)):
            self.assertTrue(folder_asset.validate_name("UI/Button Bar"))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule={})):
            self.assertTrue(folder_asset.validate_name("UI"))

        note_asset = NoteAsset()
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(naming_enabled=False)):
            self.assertTrue(note_asset.validate_name("Note Name"))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule=None)):
            self.assertTrue(note_asset.validate_name("Note Name"))
        with patch("gms_helpers.assets.get_config", return_value=_fake_config(rule={})):
            self.assertTrue(note_asset.validate_name("Note_Name"))

    def test_folder_asset_path_variants_and_create_files(self):
        asset = FolderAsset()
        self.assertEqual(asset.create_yy_data("UI")["folderPath"], "folders/UI.yy")
        self.assertEqual(asset.create_yy_data("Buttons", "folders/UI.yy")["folderPath"], "folders/UI/Buttons.yy")
        self.assertEqual(asset.create_yy_data("Buttons", "folders/UI/Buttons.yy")["folderPath"], "folders/UI/Buttons.yy")
        self.assertEqual(asset.create_yy_data("Buttons", "folders/UI/")["folderPath"], "folders/UI/Buttons.yy")

        yyp_path = self.project_root / "TestGame.yyp"
        save_pretty_json(yyp_path, {"Folders": []})

        with patch("gms_helpers.utils.insert_into_folders", return_value=True):
            rel_path = asset.create_files(self.project_root, "UI")
        self.assertEqual(rel_path, "folders/UI.yy")

        with patch("gms_helpers.utils.insert_into_folders", return_value=False):
            rel_path = asset.create_files(self.project_root, "Buttons", parent_path="folders/UI.yy")
        self.assertEqual(rel_path, "folders/UI/Buttons.yy")

        shutil.rmtree(self.project_root / "folders", ignore_errors=True)
        with self.assertRaises(NotImplementedError):
            asset.get_yy_path(self.project_root, "Any")

        empty_root = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(FileNotFoundError):
                asset.create_files(empty_root, "Missing")
        finally:
            shutil.rmtree(empty_root, ignore_errors=True)

    def test_misc_asset_variants(self):
        shader_asset = ShaderAsset()
        shader_dir = self.project_root / "shaders" / "shd_light"
        shader_dir.mkdir(parents=True)
        shader_asset.create_stub_files(shader_dir, "shd_light")
        self.assertTrue((shader_dir / "shd_light.vsh").exists())
        self.assertTrue((shader_dir / "shd_light.fsh").exists())

        anim_asset = AnimCurveAsset()
        ease_in = anim_asset.create_yy_data("ac_in", self.parent_path, curve_type="ease_in")
        ease_out = anim_asset.create_yy_data("ac_out", self.parent_path, curve_type="ease_out")
        self.assertEqual(len(ease_in["channels"][0]["points"]), 4)
        self.assertEqual(len(ease_out["channels"][0]["points"]), 4)

        sound_asset = SoundAsset()
        self.assertEqual(sound_asset._normalize_format("bad"), 2)
        self.assertEqual(sound_asset._normalize_format(99), 2)
        self.assertEqual(sound_asset._requested_extension(1), "mp3")
        self.assertEqual(sound_asset._placeholder_extension(0), "wav")

        wav_path = self.project_root / "silent.wav"
        sound_asset._write_silent_wav(wav_path, sample_rate="0", duration_seconds=0)
        with wave.open(str(wav_path), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 44100)
            self.assertGreater(wav_file.getnframes(), 0)

        path_asset = PathAsset()
        circle = path_asset.create_yy_data("pth_circle", self.parent_path, path_type="circle")
        smooth = path_asset.create_yy_data("pth_smooth", self.parent_path, path_type="smooth")
        self.assertEqual(len(circle["points"]), 8)
        self.assertEqual(len(smooth["points"]), 4)

        tileset = TileSetAsset().create_yy_data("ts_ground", self.parent_path, sprite_id="spr_ground")
        self.assertEqual(tileset["spriteId"]["name"], "spr_ground")

        normalized = TimelineAsset._normalize_moment(
            {"moment": "bad", "evnt": {"eventNum": "bad", "eventType": "bad"}},
            2,
        )
        self.assertEqual(normalized["moment"], 2)
        self.assertEqual(normalized["evnt"]["eventNum"], 0)
        self.assertEqual(normalized["evnt"]["eventType"], 0)

        timeline_dir = self.project_root / "timelines" / "tl_intro"
        timeline_dir.mkdir(parents=True)
        TimelineAsset().create_stub_files(timeline_dir, "tl_intro")
        self.assertTrue((timeline_dir / "moment_0.gml").exists())

        sequence = SequenceAsset().create_yy_data("seq_intro", self.parent_path, length=12.0, playback_speed=24.0)
        self.assertEqual(sequence["length"], 12.0)
        self.assertEqual(sequence["playbackSpeed"], 24.0)

        note_dir = self.project_root / "notes" / "nt_design"
        note_dir.mkdir(parents=True)
        NoteAsset().create_stub_files(note_dir, "nt_design", content="hello")
        self.assertEqual((note_dir / "nt_design.txt").read_text(encoding="utf-8"), "hello")


class TestTextureGroupGapCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "sprites" / "spr_test").mkdir(parents=True)
        (self.project_root / "fonts" / "fnt_test").mkdir(parents=True)
        self.yyp_path = self.project_root / "TestGame.yyp"
        self.yyp_path.write_text(
            json.dumps(
                {
                    "configs": {"name": "Default", "children": [{"name": "desktop", "children": []}]},
                    "resources": [
                        {"id": {"name": "spr_test", "path": "sprites/spr_test/spr_test.yy"}},
                        {"id": {"name": "fnt_test", "path": "fonts/fnt_test/fnt_test.yy"}},
                    ],
                    "TextureGroups": [
                        {"name": "Default", "%Name": "Default", "ConfigValues": {"desktop": {"loadType": "default"}}},
                        {"name": "game", "%Name": "game", "groupParent": "Default", "ConfigValues": {"desktop": {"groupParent": "Default"}}},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (self.project_root / "sprites" / "spr_test" / "spr_test.yy").write_text(
            json.dumps(
                {
                    "textureGroupId": {"name": "game", "path": "texturegroups/game"},
                    "ConfigValues": {
                        "desktop": {
                            "textureGroupId": "{ \"name\":\"game\", \"path\":\"texturegroups/game\", }"
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.project_root / "fonts" / "fnt_test" / "fnt_test.yy").write_text(
            json.dumps({"textureGroupId": None, "ConfigValues": {}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_texture_group_helpers(self):
        _, yyp_data = load_project_yyp(self.project_root)
        self.assertEqual(get_project_configs(yyp_data), ["desktop"])
        self.assertEqual(len(get_texture_groups_list({"textureGroups": [{"name": "lower"}]})), 1)
        self.assertEqual(get_texture_groups_list({"TextureGroups": "bad"}), [])
        self.assertIsNotNone(find_texture_group(yyp_data, "GAME"))
        self.assertIsNone(find_texture_group(yyp_data, "", case_insensitive=False))

        parsed = parse_group_ref('{ "name":"game", "path":"texturegroups/game", }')
        self.assertEqual(parsed["name"], "game")
        self.assertEqual(serialize_group_ref_for_config({"name": "ui", "path": "texturegroups/ui"}), '{ "name":"ui", "path":"texturegroups/ui" }')
        self.assertIsNone(parse_group_ref({"bad": True}))
        self.assertFalse(_asset_supports_texture_groups({}))
        self.assertTrue(_asset_supports_texture_groups({"ConfigValues": {"desktop": {"textureGroupId": "x"}}}))

        assignments = get_asset_group_assignments(
            {
                "textureGroupId": {"name": "game", "path": "texturegroups/game"},
                "ConfigValues": {"desktop": {"textureGroupId": '{ "name":"Default", "path":"texturegroups/Default" }'}},
            }
        )
        self.assertEqual(assignments["top"], "game")
        self.assertEqual(assignments["configs"]["desktop"], "Default")

        with patch("gms_helpers.texture_groups.list_assets_by_type", return_value="bad"):
            self.assertEqual(_iter_resource_assets(self.project_root), [])

    def test_set_and_replace_asset_group_edge_cases(self):
        changed, warnings = set_asset_group(
            {},
            "ui",
            include_top_level=True,
            configs_to_set=["desktop"],
            update_existing_configs=False,
        )
        self.assertTrue(changed)
        self.assertTrue(any("no top-level textureGroupId" in warning for warning in warnings))

        asset_yy = {"textureGroupId": "{ \"name\":\"game\", \"path\":\"texturegroups/game\" }", "ConfigValues": {"desktop": {}}}
        changed, warnings = set_asset_group(
            asset_yy,
            "ui",
            include_top_level=True,
            configs_to_set=None,
            update_existing_configs=True,
        )
        self.assertTrue(changed)
        self.assertTrue(any("normalized to dict" in warning for warning in warnings))
        self.assertEqual(asset_yy["textureGroupId"]["name"], "ui")

        replace_target = {
            "textureGroupId": "{ \"name\":\"ui\", \"path\":\"texturegroups/ui\" }",
            "ConfigValues": {"desktop": {"textureGroupId": '{ "name":"ui", "path":"texturegroups/ui" }'}},
        }
        changed, warnings = _replace_asset_group_references(
            replace_target,
            from_group="ui",
            to_group="Default",
            include_top_level=True,
            configs_to_consider=["desktop"],
            update_existing_configs=False,
        )
        self.assertTrue(changed)
        self.assertTrue(any("normalized to dict" in warning for warning in warnings))
        self.assertEqual(replace_target["textureGroupId"]["name"], "Default")

    def test_texture_group_crud_error_paths(self):
        result = texture_group_create(self.project_root, "game")
        self.assertFalse(result["ok"])

        result = texture_group_create(self.project_root, "ui", patch="bad")
        self.assertTrue(result["ok"])
        self.assertTrue(any("patch was not a dict" in warning for warning in result["warnings"]))

        result = texture_group_update(self.project_root, "missing", patch={})
        self.assertFalse(result["ok"])
        result = texture_group_update(self.project_root, "Default", patch="bad")  # type: ignore[arg-type]
        self.assertFalse(result["ok"])
        result = texture_group_update(self.project_root, "Default", patch={"name": "bad"})
        self.assertTrue(result["ok"])
        self.assertTrue(any("ignored" in warning for warning in result["warnings"]))

        result = texture_group_rename(self.project_root, "missing", "new")
        self.assertFalse(result["ok"])
        result = texture_group_rename(self.project_root, "game", "Default")
        self.assertFalse(result["ok"])

        result = texture_group_delete(self.project_root, "game", reassign_to="missing")
        self.assertFalse(result["ok"])

        broken_root = Path(tempfile.mkdtemp())
        try:
            (broken_root / "TestGame.yyp").write_text(json.dumps({"TextureGroups": "bad"}), encoding="utf-8")
            result = texture_group_delete(broken_root, "missing")
            self.assertFalse(result["ok"])
        finally:
            shutil.rmtree(broken_root, ignore_errors=True)

        result = texture_group_assign(self.project_root, "missing_group")
        self.assertFalse(result["ok"])
        result = texture_group_assign(self.project_root, "Default", asset_identifiers=["spr_test", "ghost_asset"])
        self.assertTrue(result["ok"])
        self.assertIn("ghost_asset", result["details"]["assets_skipped"])


class WorkflowProjectMixin:
    def build_project(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp())
        for folder in ["scripts", "objects", "sprites", "rooms", "folders"]:
            (temp_dir / folder).mkdir()
        save_pretty_json(temp_dir / "TestGame.yyp", {"resources": []})
        return temp_dir


class TestWorkflowGapCoverage(unittest.TestCase, WorkflowProjectMixin):
    def test_try_import_and_asset_path_validation(self):
        self.assertIsNone(_try_import("definitely_missing_module_for_tests"))

        with self.assertRaises(InvalidAssetTypeError):
            _asset_from_path(Path("."), "bad")
        with self.assertRaises(InvalidAssetTypeError):
            _asset_from_path(Path("."), "unknown/test/test.yy")

    def test_duplicate_rename_and_safe_delete_error_paths(self):
        project_root = self.build_project()
        try:
            script_asset = ScriptAsset()
            script_asset.create_files(project_root, "scr_old", "")
            yyp_path = project_root / "TestGame.yyp"
            yyp_data = load_json_loose(yyp_path) or {}
            yyp_data["resources"] = [{"id": {"name": "scr_old", "path": "scripts/scr_old/scr_old.yy"}}]
            save_pretty_json(yyp_path, yyp_data)

            with self.assertRaises(JSONParseError):
                with patch("gms_helpers.workflow.load_json_loose", return_value=None):
                    duplicate_asset(project_root, "scripts/scr_old/scr_old.yy", "scr_copy")

            with patch("gms_helpers.reference_scanner.comprehensive_rename_asset", return_value=False):
                with patch("gms_helpers.auto_maintenance.run_auto_maintenance", return_value=SimpleNamespace(has_errors=True)):
                    with patch.dict(os.environ, {}, clear=True):
                        result = rename_asset(project_root, "scripts/scr_old/scr_old.yy", "scr_new")
            self.assertTrue(result.success)
            self.assertTrue(result.warnings)

            missing = safe_delete_asset(project_root, "script", "missing")
            self.assertFalse(missing["ok"])

            gml_path = project_root / "scripts" / "scr_new" / "scr_new.gml"
            gml_path.write_text("function scr_new() {\n    scr_new();\n}\n", encoding="utf-8")
            cleanup = _cleanup_symbol_references(project_root, "scr_new")
            self.assertGreaterEqual(cleanup["replacements"], 2)

        finally:
            shutil.rmtree(project_root, ignore_errors=True)

    def test_swap_sprite_png_and_lint_problem_paths(self):
        project_root = self.build_project()
        try:
            sprite_dir = project_root / "sprites" / "spr_test"
            sprite_dir.mkdir(parents=True, exist_ok=True)
            frame_png = sprite_dir / "frame0.png"
            frame_png.write_bytes(b"png")
            layer_dir = sprite_dir / "layers" / "frame0"
            layer_dir.mkdir(parents=True)
            layer_png = layer_dir / "layer0.png"
            layer_png.write_bytes(b"png")
            (sprite_dir / "spr_test.yy").write_text(
                json.dumps({"frames": [{"name": "frame0"}], "layers": [{"name": "layer0"}]}),
                encoding="utf-8",
            )

            result = swap_sprite_png(project_root, "sprites/spr_test/spr_test.yy", frame_png, frame_index=0)
            self.assertTrue(result.success)
            self.assertIn("no-op", result.message)

            with self.assertRaises(ValueError):
                swap_sprite_png(project_root, "sprites/spr_test/spr_test.yy", frame_png, frame_index=2)

            source_png = project_root / "replacement.png"
            source_png.write_bytes(b"replacement")
            with patch("gms_helpers.workflow.shutil.copy2", side_effect=PermissionError("locked")):
                with patch("gms_helpers.workflow.time.sleep", return_value=None):
                    with self.assertRaises(PermissionError):
                        swap_sprite_png(project_root, "sprites/spr_test/spr_test.yy", source_png, frame_index=0)

            yyp_path = project_root / "TestGame.yyp"
            yyp_path.write_text(
                json.dumps(
                    {
                        "resources": [
                            {"id": {"name": "z_item", "path": "scripts/z_item/z_item.yy"}},
                            {"id": {"name": "a_item", "path": "scripts/a_item/a_item.yy"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (project_root / "scripts" / "extra" ).mkdir(parents=True, exist_ok=True)
            (project_root / "scripts" / "extra" / "extra.yy").write_text("{}", encoding="utf-8")
            lint = lint_project(project_root)
            self.assertFalse(lint.success)
            self.assertGreater(lint.issues_found, 0)
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

    def test_copy_tree_and_patch_gml_stub(self):
        src = Path(tempfile.mkdtemp())
        dst = Path(tempfile.mkdtemp())
        try:
            (src / "nested").mkdir()
            (src / "nested" / "file.txt").write_text("hello", encoding="utf-8")

            fake_tqdm = SimpleNamespace(tqdm=lambda items, **kwargs: items)
            with patch("gms_helpers.workflow.tqdm", fake_tqdm):
                with patch("gms_helpers.workflow.sys.stdout.isatty", return_value=True):
                    _copy_tree(src, dst)
            self.assertEqual((dst / "nested" / "file.txt").read_text(encoding="utf-8"), "hello")

            gml_file = dst / "stub.gml"
            gml_file.write_text("function old_name() {\n    return 1;\n}\n", encoding="utf-8")
            _patch_gml_stub(gml_file, "new_name")
            self.assertIn("function new_name() {", gml_file.read_text(encoding="utf-8"))
            _patch_gml_stub(dst / "missing.gml", "unused")
        finally:
            shutil.rmtree(src, ignore_errors=True)
            shutil.rmtree(dst, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
