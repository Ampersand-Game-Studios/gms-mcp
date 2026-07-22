#!/usr/bin/env python3
"""Integration coverage for safe default GameMaker asset organization."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gms_helpers.asset_types import (
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
from gms_helpers.sprite_import import import_strip_to_sprite
from gms_helpers.transactions import validate_project_after_mutation
from gms_helpers.utils import create_dummy_png, load_json_loose, update_yyp_file


class TestAssetDefaultParent(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.yyp_path = self.project_root / "TestGame.yyp"
        self.yyp_path.write_text(
            json.dumps(
                {
                    "$GMProject": "v1",
                    "%Name": "TestGame",
                    "name": "TestGame",
                    "Folders": [],
                    "resources": [],
                    "resourceType": "GMProject",
                    "resourceVersion": "2.0",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _register(self, name: str, relative_path: str) -> None:
        self.assertTrue(
            update_yyp_file(
                {"id": {"name": name, "path": relative_path}},
                project_root=self.project_root,
            )
        )

    def test_every_standard_asset_type_gets_a_valid_logical_parent(self):
        cases = [
            (ScriptAsset(), "scr_default", {}),
            (ObjectAsset(), "o_default", {}),
            (SpriteAsset(), "spr_default", {}),
            (RoomAsset(), "r_default", {"width": 640, "height": 480}),
            (FontAsset(), "fnt_default", {}),
            (ShaderAsset(), "sh_default", {}),
            (AnimCurveAsset(), "curve_default", {}),
            (SoundAsset(), "snd_default", {}),
            (PathAsset(), "pth_default", {}),
            (TileSetAsset(), "ts_default", {}),
            (TimelineAsset(), "tl_default", {}),
            (SequenceAsset(), "seq_default", {}),
            (NoteAsset(), "note_default", {}),
        ]

        for asset, name, kwargs in cases:
            with self.subTest(asset=asset.kind):
                relative_path = asset.create_files(self.project_root, name, "", **kwargs)
                self._register(name, relative_path)
                data = load_json_loose(self.project_root / relative_path)
                parent_path = data["parent"]["path"]
                folders = {folder["folderPath"] for folder in load_json_loose(self.yyp_path)["Folders"]}
                self.assertTrue(parent_path.startswith("folders/"))
                self.assertTrue(parent_path.endswith(".yy"))
                self.assertFalse(parent_path.endswith(".yyp"))
                self.assertIn(parent_path, folders)

        validation = validate_project_after_mutation(self.project_root)
        self.assertTrue(validation.success, msg=validation.errors)
        self.assertFalse(
            [warning for warning in validation.warnings if "no parent path" in warning],
            msg=validation.warnings,
        )

    def test_omitted_parent_reuses_comparable_asset_folder(self):
        code_folder = FolderAsset().create_files(self.project_root, "Code")
        first_path = ScriptAsset().create_files(self.project_root, "scr_first", code_folder)
        self._register("scr_first", first_path)

        second_path = ScriptAsset().create_files(self.project_root, "scr_second", "")
        self._register("scr_second", second_path)
        second_data = load_json_loose(self.project_root / second_path)

        self.assertEqual(second_data["parent"]["path"], "folders/Code.yy")
        self.assertTrue(validate_project_after_mutation(self.project_root).success)

    def test_explicit_valid_parent_remains_authoritative(self):
        custom_folder = FolderAsset().create_files(self.project_root, "Gameplay")
        relative_path = ObjectAsset().create_files(self.project_root, "o_explicit", custom_folder)
        self._register("o_explicit", relative_path)

        data = load_json_loose(self.project_root / relative_path)
        self.assertEqual(data["parent"]["path"], "folders/Gameplay.yy")
        self.assertTrue(validate_project_after_mutation(self.project_root).success)

    def test_sprite_strip_import_uses_and_registers_default_sprite_folder(self):
        source = self.project_root / "strip.png"
        create_dummy_png(source, width=64, height=32)

        result = import_strip_to_sprite(
            self.project_root,
            "spr_strip",
            source,
            frame_width=32,
            frame_height=32,
        )
        sprite_data = load_json_loose(self.project_root / result["path"])
        parent_path = sprite_data["parent"]["path"]
        folders = {folder["folderPath"] for folder in load_json_loose(self.yyp_path)["Folders"]}

        self.assertEqual(parent_path, "folders/Sprites.yy")
        self.assertIn(parent_path, folders)
        self.assertTrue(validate_project_after_mutation(self.project_root).success)


if __name__ == "__main__":
    unittest.main()
