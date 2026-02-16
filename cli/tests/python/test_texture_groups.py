#!/usr/bin/env python3
"""
Test suite for texture group helpers.
Covers CRUD, membership scanning, assignment, rename/delete safety, and config handling.
"""

import json
import sys
import unittest
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.texture_groups import (
    get_project_configs,
    get_texture_groups_list,
    load_project_yyp,
    parse_group_ref,
    texture_group_assign,
    texture_group_create,
    texture_group_delete,
    texture_group_members,
    texture_group_rename,
    texture_group_scan,
    texture_group_update,
)
from gms_helpers.utils import load_json_loose


class TestTextureGroups(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.test_dir.name)

        # Realistic-ish texture groups, based on GameMaker output.
        default_group = {
            "$GMTextureGroup": "",
            "%Name": "Default",
            "autocrop": True,
            "border": 2,
            "compressFormat": "bz2",
            "ConfigValues": {
                "desktop": {
                    "autocrop": "true",
                    "compressFormat": "bz2",
                    "groupParent": "null",
                    "loadType": "default",
                }
            },
            "customOptions": "",
            "directory": "",
            "groupParent": None,
            "isScaled": True,
            "loadType": "default",
            "mipsToGenerate": 0,
            "name": "Default",
            "resourceType": "GMTextureGroup",
            "resourceVersion": "2.0",
            "targets": -1,
        }
        game_group = json.loads(json.dumps(default_group))
        game_group["%Name"] = "game"
        game_group["name"] = "game"
        game_group["loadType"] = "dynamicpages"
        game_group["ConfigValues"]["desktop"]["loadType"] = "dynamicpages"

        fonts_group = json.loads(json.dumps(default_group))
        fonts_group["%Name"] = "fonts"
        fonts_group["name"] = "fonts"
        fonts_group["loadType"] = "dynamicpages"
        fonts_group["ConfigValues"]["desktop"]["loadType"] = "dynamicpages"

        self.yyp_data = {
            "$GMProject": "v1",
            "%Name": "TestGame",
            "name": "TestGame",
            "resourceType": "GMProject",
            "resourceVersion": "2.0",
            "configs": {
                "name": "Default",
                "children": [
                    {"name": "desktop", "children": []},
                    {"name": "android", "children": []},
                    {"name": "ios", "children": []},
                ],
            },
            "resources": [
                {"id": {"name": "spr_test", "path": "sprites/spr_test/spr_test.yy"}},
                {"id": {"name": "fnt_test", "path": "fonts/fnt_test/fnt_test.yy"}},
                {"id": {"name": "ts_test", "path": "tilesets/ts_test/ts_test.yy"}},
            ],
            "TextureGroups": [default_group, game_group, fonts_group],
            "MetaData": {"IDEVersion": "2024.14.0.0"},
        }

        (self.project_root / "TestGame.yyp").write_text(json.dumps(self.yyp_data, indent=2), encoding="utf-8")

        # Asset fixtures
        (self.project_root / "sprites" / "spr_test").mkdir(parents=True)
        (self.project_root / "fonts" / "fnt_test").mkdir(parents=True)
        (self.project_root / "tilesets" / "ts_test").mkdir(parents=True)

        self._write_sprite(
            top_name="Default",
            cfg_desktop="{ \"name\":\"game\", \"path\":\"texturegroups/game\" }",
        )
        self._write_font(
            top_value=None,
            cfg_desktop="{ \"name\":\"fonts\", \"path\":\"texturegroups/fonts\" }",
        )
        # Tileset intentionally mismatched + contains a missing group reference in config.
        self._write_tileset(
            top_name="game",
            cfg_desktop="{ \"name\":\"missing_group\", \"path\":\"texturegroups/missing_group\" }",
        )

    def tearDown(self):
        self.test_dir.cleanup()

    def _write_sprite(self, *, top_name: str, cfg_desktop: str) -> None:
        data = {
            "$GMSprite": "",
            "%Name": "spr_test",
            "name": "spr_test",
            "resourceType": "GMSprite",
            "resourceVersion": "2.0",
            "ConfigValues": {"desktop": {"textureGroupId": cfg_desktop}},
            "textureGroupId": {"name": top_name, "path": f"texturegroups/{top_name}"},
        }
        (self.project_root / "sprites" / "spr_test" / "spr_test.yy").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def _write_font(self, *, top_value, cfg_desktop: str) -> None:
        data = {
            "$GMFont": "",
            "%Name": "fnt_test",
            "name": "fnt_test",
            "resourceType": "GMFont",
            "resourceVersion": "2.0",
            "ConfigValues": {"desktop": {"textureGroupId": cfg_desktop}},
            "textureGroupId": top_value,
        }
        (self.project_root / "fonts" / "fnt_test" / "fnt_test.yy").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def _write_tileset(self, *, top_name: str, cfg_desktop: str) -> None:
        data = {
            "$GMTileSet": "v1",
            "%Name": "ts_test",
            "name": "ts_test",
            "resourceType": "GMTileSet",
            "resourceVersion": "2.0",
            "ConfigValues": {"desktop": {"textureGroupId": cfg_desktop}},
            "textureGroupId": {"name": top_name, "path": f"texturegroups/{top_name}"},
        }
        (self.project_root / "tilesets" / "ts_test" / "ts_test.yy").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def test_list_configs_and_groups(self):
        yyp_path, yyp_data = load_project_yyp(self.project_root)
        self.assertEqual(yyp_path.name, "TestGame.yyp")
        self.assertEqual(get_project_configs(yyp_data), ["desktop", "android", "ios"])
        groups = get_texture_groups_list(yyp_data)
        self.assertEqual(sorted([g.get("name") for g in groups]), ["Default", "fonts", "game"])

    def test_create_clones_default_and_dry_run(self):
        # dry-run does not write
        res = texture_group_create(self.project_root, "new_group", dry_run=True)
        self.assertTrue(res.get("ok"))
        yyp_data = load_json_loose(self.project_root / "TestGame.yyp")
        self.assertNotIn("new_group", [g.get("name") for g in yyp_data.get("TextureGroups", [])])

        # real create writes and preserves fields from template
        res = texture_group_create(self.project_root, "new_group", dry_run=False)
        self.assertTrue(res.get("ok"))
        yyp_data = load_json_loose(self.project_root / "TestGame.yyp")
        created = next(g for g in yyp_data.get("TextureGroups", []) if g.get("name") == "new_group")
        self.assertEqual(created.get("compressFormat"), "bz2")
        self.assertIn("ConfigValues", created)

    def test_update_group_and_config_values(self):
        res = texture_group_update(
            self.project_root,
            "Default",
            patch={"autocrop": False, "loadType": "dynamicpages"},
            dry_run=False,
        )
        self.assertTrue(res.get("ok"))
        yyp_data = load_json_loose(self.project_root / "TestGame.yyp")
        default = next(g for g in yyp_data.get("TextureGroups", []) if g.get("name") == "Default")
        self.assertFalse(default.get("autocrop"))
        self.assertEqual(default.get("loadType"), "dynamicpages")
        self.assertEqual(default["ConfigValues"]["desktop"]["autocrop"], "false")
        self.assertEqual(default["ConfigValues"]["desktop"]["loadType"], "dynamicpages")

        # Explicit configs creates/overwrites that config dict and sets string values.
        res = texture_group_update(
            self.project_root,
            "Default",
            patch={"mipsToGenerate": 2},
            configs=["android"],
            dry_run=False,
        )
        self.assertTrue(res.get("ok"))
        yyp_data = load_json_loose(self.project_root / "TestGame.yyp")
        default = next(g for g in yyp_data.get("TextureGroups", []) if g.get("name") == "Default")
        self.assertEqual(default["ConfigValues"]["android"]["mipsToGenerate"], "2")

    def test_members_reports_top_and_config(self):
        res = texture_group_members(self.project_root, "game")
        self.assertTrue(res.get("ok"))
        names = sorted([m["name"] for m in res["members"]])
        self.assertEqual(names, ["spr_test", "ts_test"])

        res = texture_group_members(self.project_root, "fonts")
        self.assertTrue(res.get("ok"))
        names = sorted([m["name"] for m in res["members"]])
        self.assertEqual(names, ["fnt_test"])

    def test_scan_missing_groups_and_mismatches(self):
        res = texture_group_scan(self.project_root, include_assets=False)
        self.assertTrue(res.get("ok"))
        self.assertIn("missing_group", res["missing_groups_referenced"])
        self.assertEqual(len(res["mismatched_assets"]), 2)
        self.assertIn("game", res["groups_referenced"])
        self.assertIn("fonts", res["groups_referenced"])

    def test_assign_updates_sprite_top_level_and_font_config_only(self):
        res = texture_group_assign(
            self.project_root,
            "game",
            asset_identifiers=["spr_test", "fnt_test"],
            include_top_level=True,
            update_existing_configs=True,
            dry_run=False,
        )
        self.assertTrue(res.get("ok"))

        sprite = load_json_loose(self.project_root / "sprites" / "spr_test" / "spr_test.yy")
        self.assertEqual(sprite["textureGroupId"]["name"], "game")

        font = load_json_loose(self.project_root / "fonts" / "fnt_test" / "fnt_test.yy")
        self.assertIsNone(font["textureGroupId"])  # should not force top-level when null
        ref = parse_group_ref(font["ConfigValues"]["desktop"]["textureGroupId"])
        self.assertEqual(ref["name"], "game")

    def test_rename_updates_yyp_and_asset_references(self):
        res = texture_group_rename(self.project_root, "game", "game2", update_references=True, dry_run=False)
        self.assertTrue(res.get("ok"))

        yyp_data = load_json_loose(self.project_root / "TestGame.yyp")
        names = [g.get("name") for g in yyp_data.get("TextureGroups", [])]
        self.assertIn("game2", names)
        self.assertNotIn("game", names)

        sprite = load_json_loose(self.project_root / "sprites" / "spr_test" / "spr_test.yy")
        ref = parse_group_ref(sprite["ConfigValues"]["desktop"]["textureGroupId"])
        self.assertEqual(ref["name"], "game2")

        tileset = load_json_loose(self.project_root / "tilesets" / "ts_test" / "ts_test.yy")
        self.assertEqual(tileset["textureGroupId"]["name"], "game2")

    def test_delete_blocks_without_reassign_and_reassigns_safely(self):
        res = texture_group_delete(self.project_root, "game", reassign_to=None, dry_run=False)
        self.assertFalse(res.get("ok"))
        self.assertIn("references_found", (res.get("details") or {}))

        res = texture_group_delete(self.project_root, "game", reassign_to="Default", dry_run=False)
        self.assertTrue(res.get("ok"))

        yyp_data = load_json_loose(self.project_root / "TestGame.yyp")
        names = [g.get("name") for g in yyp_data.get("TextureGroups", [])]
        self.assertNotIn("game", names)

        sprite = load_json_loose(self.project_root / "sprites" / "spr_test" / "spr_test.yy")
        ref = parse_group_ref(sprite["ConfigValues"]["desktop"]["textureGroupId"])
        self.assertEqual(ref["name"], "Default")

        tileset = load_json_loose(self.project_root / "tilesets" / "ts_test" / "ts_test.yy")
        self.assertEqual(tileset["textureGroupId"]["name"], "Default")
        # The missing_group override should remain untouched (delete should only replace references to the deleted group)
        ref = parse_group_ref(tileset["ConfigValues"]["desktop"]["textureGroupId"])
        self.assertEqual(ref["name"], "missing_group")


if __name__ == "__main__":
    unittest.main()

