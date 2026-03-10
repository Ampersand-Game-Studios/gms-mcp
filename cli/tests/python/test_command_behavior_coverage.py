#!/usr/bin/env python3
"""Behavior-focused coverage tests for thin command and maintenance modules."""

from __future__ import annotations

import io
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

from gms_helpers.commands.doc_commands import (
    handle_doc_cache_clear,
    handle_doc_cache_stats,
    handle_doc_categories,
    handle_doc_list,
    handle_doc_lookup,
    handle_doc_search,
)
from gms_helpers.commands.sprite_commands import (
    handle_sprite_add_frame,
    handle_sprite_duplicate_frame,
    handle_sprite_frame_count,
    handle_sprite_import_strip,
    handle_sprite_remove_frame,
)
from gms_helpers.commands.texture_group_commands import (
    _parse_csv,
    _parse_set_kv,
    handle_texture_groups_assign,
    handle_texture_groups_create,
    handle_texture_groups_delete,
    handle_texture_groups_list,
    handle_texture_groups_members,
    handle_texture_groups_rename,
    handle_texture_groups_scan,
    handle_texture_groups_show,
    handle_texture_groups_update,
)
from gms_helpers.maintenance.prune import (
    _get_asset_type_from_path,
    print_prune_report,
    prune_missing_assets,
)
from gms_helpers.maintenance.static_search import (
    _build_prefix_pattern,
    _get_asset_patterns_from_config,
    cross_reference_strings_to_files,
    find_asset_name_patterns,
    find_string_references_in_gml,
    identify_derivable_orphans,
)


def _capture_output(func, *args, **kwargs):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


class FakeNamingConfig:
    def __init__(self, prefixes: dict[str, list[str]]):
        self._prefixes = prefixes

    def get_prefixes(self, asset_type: str) -> list[str]:
        return list(self._prefixes.get(asset_type, []))


class TestDocCommandBehavior(unittest.TestCase):
    def test_handle_doc_lookup_success_formats_sections(self):
        args = SimpleNamespace(function_name="draw_sprite", refresh=True)
        payload = {
            "ok": True,
            "name": "draw_sprite",
            "category": "Drawing",
            "subcategory": "Sprites",
            "url": "https://manual.example/draw_sprite",
            "description": "Draws a sprite.",
            "syntax": "draw_sprite(sprite, subimg, x, y);",
            "parameters": [{"name": "sprite", "type": "sprite", "description": "Asset name"}],
            "returns": "N/A",
            "examples": ["draw_sprite(spr_player, 0, x, y);"],
        }
        with patch("gms_helpers.gml_docs.lookup", return_value=payload):
            result, output = _capture_output(handle_doc_lookup, args)

        self.assertTrue(result)
        self.assertIn("draw_sprite", output)
        self.assertIn("Description:", output)
        self.assertIn("Syntax:", output)
        self.assertIn("Parameters:", output)
        self.assertIn("Examples:", output)

    def test_handle_doc_lookup_failure_prints_suggestions(self):
        args = SimpleNamespace(function_name="dra_sprite", refresh=False)
        payload = {"ok": False, "error": "Not found", "suggestions": ["draw_sprite", "draw_self"]}
        with patch("gms_helpers.gml_docs.lookup", return_value=payload):
            result, output = _capture_output(handle_doc_lookup, args)

        self.assertFalse(result)
        self.assertIn("[ERROR] Not found", output)
        self.assertIn("Did you mean:", output)
        self.assertIn("draw_sprite", output)

    def test_search_list_categories_and_cache_handlers(self):
        with patch(
            "gms_helpers.gml_docs.search",
            return_value={
                "ok": True,
                "query": "draw",
                "count": 1,
                "category_filter": "Drawing",
                "results": [{"name": "draw_sprite", "category": "Drawing", "subcategory": "Sprites"}],
            },
        ):
            search_result, search_output = _capture_output(
                handle_doc_search,
                SimpleNamespace(query="draw", category="Drawing", limit=5),
            )
        self.assertTrue(search_result)
        self.assertIn("Search results for 'draw'", search_output)
        self.assertIn("draw_sprite", search_output)

        with patch(
            "gms_helpers.gml_docs.list_functions",
            return_value={
                "ok": True,
                "count": 2,
                "total_in_index": 4,
                "category_filter": "Drawing",
                "pattern_filter": "^draw_",
                "results": [
                    {"name": "draw_self", "category": "Drawing"},
                    {"name": "draw_sprite", "category": "Drawing"},
                ],
            },
        ):
            list_result, list_output = _capture_output(
                handle_doc_list,
                SimpleNamespace(category="Drawing", pattern="^draw_", limit=10),
            )
        self.assertTrue(list_result)
        self.assertIn("GML Functions", list_output)
        self.assertIn("[Drawing]", list_output)

        with patch(
            "gms_helpers.gml_docs.list_categories",
            return_value={
                "ok": True,
                "count": 1,
                "categories": [{"name": "Drawing", "function_count": 12, "subcategories": [{"name": "Sprites", "count": 5}]}],
            },
        ):
            categories_result, categories_output = _capture_output(handle_doc_categories, SimpleNamespace())
        self.assertTrue(categories_result)
        self.assertIn("Drawing", categories_output)
        self.assertIn("Sprites", categories_output)

        with patch(
            "gms_helpers.gml_docs.get_cache_stats",
            return_value={
                "cache_dir": "/tmp/doc-cache",
                "index_exists": True,
                "index_age_seconds": 7200,
                "index_function_count": 42,
                "cached_function_count": 12,
                "cache_size_kb": 3.5,
            },
        ):
            stats_result, stats_output = _capture_output(handle_doc_cache_stats, SimpleNamespace())
        self.assertTrue(stats_result)
        self.assertIn("2.0 hours", stats_output)
        self.assertIn("Functions in index: 42", stats_output)

        with patch(
            "gms_helpers.gml_docs.clear_cache",
            return_value={"functions_removed": 2, "index_removed": False},
        ):
            clear_result, clear_output = _capture_output(
                handle_doc_cache_clear,
                SimpleNamespace(functions_only=False),
            )
        self.assertTrue(clear_result)
        self.assertIn("Functions removed: 2", clear_output)
        self.assertIn("Index removed: False", clear_output)


class TestSpriteCommandBehavior(unittest.TestCase):
    def test_sprite_frame_handlers_format_results(self):
        add_args = SimpleNamespace(project_root=".", sprite_path="sprites/spr_test/spr_test.yy", position=2, source="frame.png")
        with patch(
            "gms_helpers.sprite_frames.add_frame",
            return_value={"position": 2, "frame_uuid": "abc123", "new_frame_count": 3},
        ):
            add_result, add_output = _capture_output(handle_sprite_add_frame, add_args)
        self.assertEqual(add_result["position"], 2)
        self.assertIn("Added frame at position 2", add_output)

        remove_args = SimpleNamespace(project_root=".", sprite_path="sprites/spr_test/spr_test.yy", position=1)
        with patch(
            "gms_helpers.sprite_frames.remove_frame",
            return_value={"removed_position": 1, "removed_frame_uuid": "old", "new_frame_count": 2},
        ):
            remove_result, remove_output = _capture_output(handle_sprite_remove_frame, remove_args)
        self.assertEqual(remove_result["removed_position"], 1)
        self.assertIn("Removed frame at position 1", remove_output)

        duplicate_args = SimpleNamespace(project_root=".", sprite_path="sprites/spr_test/spr_test.yy", source_position=0, target=4)
        with patch(
            "gms_helpers.sprite_frames.duplicate_frame",
            return_value={"position": 4, "frame_uuid": "dup", "new_frame_count": 5},
        ):
            dup_result, dup_output = _capture_output(handle_sprite_duplicate_frame, duplicate_args)
        self.assertEqual(dup_result["position"], 4)
        self.assertIn("Duplicated frame to position 4", dup_output)

        import_args = SimpleNamespace(
            project_root=".",
            name="spr_strip",
            source="strip.png",
            parent_path="folders/Sprites.yy",
            layout="grid",
            frame_width=32,
            frame_height=32,
            columns=4,
        )
        with patch(
            "gms_helpers.sprite_import.import_strip_to_sprite",
            return_value={
                "sprite_name": "spr_strip",
                "frame_count": 8,
                "frame_size": (32, 32),
                "path": "sprites/spr_strip/spr_strip.yy",
            },
        ):
            import_result, import_output = _capture_output(handle_sprite_import_strip, import_args)
        self.assertEqual(import_result["sprite_name"], "spr_strip")
        self.assertIn("Imported sprite 'spr_strip'", import_output)

        count_args = SimpleNamespace(project_root=".", sprite_path="sprites/spr_test/spr_test.yy")
        with patch("gms_helpers.sprite_frames.get_frame_count", return_value=6):
            count_result, count_output = _capture_output(handle_sprite_frame_count, count_args)
        self.assertEqual(count_result["frame_count"], 6)
        self.assertIn("Frame count: 6", count_output)


class TestTextureGroupCommandBehavior(unittest.TestCase):
    def test_parse_helpers(self):
        self.assertEqual(_parse_csv("a, b ,, c"), ["a", "b", "c"])
        self.assertIsNone(_parse_csv(""))
        patch_dict = _parse_set_kv(["autocrop=false", "mips=2", "scale=1.5", "parent=null", "name=game"])
        self.assertEqual(
            patch_dict,
            {"autocrop": False, "mips": 2, "scale": 1.5, "parent": None, "name": "game"},
        )

    def test_texture_group_handlers_cover_success_and_failure_paths(self):
        with patch("gms_helpers.commands.texture_group_commands.load_project_yyp", return_value=(Path("TestGame.yyp"), {})), patch(
            "gms_helpers.commands.texture_group_commands.get_project_configs",
            return_value=["desktop"],
        ), patch(
            "gms_helpers.commands.texture_group_commands.get_texture_groups_list",
            return_value=[{"name": "Default", "loadType": "default"}],
        ):
            list_result, list_output = _capture_output(handle_texture_groups_list, SimpleNamespace(project_root="."))
        self.assertTrue(list_result.success)
        self.assertIn("Texture groups (1):", list_output)

        with patch("gms_helpers.commands.texture_group_commands.load_project_yyp", return_value=(Path("TestGame.yyp"), {})), patch(
            "gms_helpers.commands.texture_group_commands.find_texture_group",
            return_value=None,
        ):
            show_result, show_output = _capture_output(
                handle_texture_groups_show,
                SimpleNamespace(project_root=".", name="missing"),
            )
        self.assertFalse(show_result.success)
        self.assertIn("Texture group 'missing' not found", show_output)

        with patch(
            "gms_helpers.commands.texture_group_commands.texture_group_members",
            return_value={"ok": True, "warnings": ["watch this"], "count": 1, "members": [{"type": "sprite", "name": "spr_test", "path": "sprites/spr_test/spr_test.yy", "top_level_group": "Default", "config_groups": ["desktop"]}]},
        ):
            members_result, members_output = _capture_output(
                handle_texture_groups_members,
                SimpleNamespace(project_root=".", group="Default", types="sprite", configs="desktop"),
            )
        self.assertTrue(members_result.success)
        self.assertIn("[WARN]", members_output)
        self.assertIn("spr_test", members_output)

        with patch(
            "gms_helpers.commands.texture_group_commands.texture_group_scan",
            return_value={"ok": True, "groups_defined": ["Default"], "groups_referenced": ["Default"], "missing_groups_referenced": {"missing": ["sprites/spr_test/spr_test.yy"]}, "mismatched_assets": ["spr_test"]},
        ):
            scan_result, scan_output = _capture_output(
                handle_texture_groups_scan,
                SimpleNamespace(project_root=".", types=None, configs=None, include_assets=True),
            )
        self.assertTrue(scan_result.success)
        self.assertIn("Missing groups referenced: 1", scan_output)

        success_payload = {"ok": True, "message": "Updated", "warnings": ["heads up"], "changed_files": ["TestGame.yyp"]}
        with patch("gms_helpers.commands.texture_group_commands.texture_group_create", return_value=success_payload):
            create_result, create_output = _capture_output(
                handle_texture_groups_create,
                SimpleNamespace(project_root=".", name="game", template="Default", set=["autocrop=false"], dry_run=True),
            )
        self.assertTrue(create_result.success)
        self.assertIn("[DRY] Would change", create_output)

        with patch("gms_helpers.commands.texture_group_commands.texture_group_update", return_value=success_payload):
            update_result, update_output = _capture_output(
                handle_texture_groups_update,
                SimpleNamespace(project_root=".", name="game", set=["mips=2"], configs="desktop", update_existing_configs=True, dry_run=False),
            )
        self.assertTrue(update_result.success)
        self.assertIn("[OK] Updated", update_output)

        with patch("gms_helpers.commands.texture_group_commands.texture_group_rename", return_value=success_payload):
            rename_result, rename_output = _capture_output(
                handle_texture_groups_rename,
                SimpleNamespace(project_root=".", old_name="old", new_name="new", update_references=True, dry_run=False),
            )
        self.assertTrue(rename_result.success)
        self.assertIn("[WARN]", rename_output)

        delete_failure = {"ok": False, "error": "Blocked", "details": {"references_found": ["spr_test"]}}
        with patch("gms_helpers.commands.texture_group_commands.texture_group_delete", return_value=delete_failure):
            delete_result, delete_output = _capture_output(
                handle_texture_groups_delete,
                SimpleNamespace(project_root=".", name="game", reassign_to=None, dry_run=False),
            )
        self.assertFalse(delete_result.success)
        self.assertIn("References found: 1", delete_output)

        with patch("gms_helpers.commands.texture_group_commands.texture_group_assign", return_value=success_payload):
            assign_result, assign_output = _capture_output(
                handle_texture_groups_assign,
                SimpleNamespace(
                    project_root=".",
                    group="game",
                    assets="sprites/spr_test/spr_test.yy",
                    asset_type="sprite",
                    name_contains="spr_",
                    folder_prefix="sprites/",
                    from_group="Default",
                    configs="desktop",
                    no_top_level=False,
                    no_update_existing_configs=False,
                    dry_run=True,
                ),
            )
        self.assertTrue(assign_result.success)
        self.assertIn("[DRY] Would change", assign_output)


class TestPruneMaintenanceBehavior(unittest.TestCase):
    def test_get_asset_type_from_path_maps_known_types(self):
        self.assertEqual(_get_asset_type_from_path("scripts/scr_test/scr_test.yy"), "script")
        self.assertEqual(_get_asset_type_from_path("folders/Scripts.yy"), "folder")
        self.assertEqual(_get_asset_type_from_path("misc/data.bin"), "unknown")

    def test_prune_missing_assets_dry_run_filters_missing_entries(self):
        yyp_data = {
            "resources": [
                {"id": {"path": "scripts/existing/existing.yy"}},
                {"id": {"path": "scripts/missing/missing.yy"}},
                {"id": {"path": "folders/Keep.yy"}},
                {"id": {"path": "options/main/options_main.yy"}},
                {"id": {}},
            ],
            "resourceOrder": [
                "scripts/existing/existing.yy",
                "scripts/missing/missing.yy",
                {"path": "rooms/missing_room/missing_room.yy"},
                {"path": "folders/Keep.yy"},
                123,
            ],
        }
        with patch("gms_helpers.maintenance.prune.find_yyp_file", return_value="TestGame.yyp"), patch(
            "gms_helpers.maintenance.prune.load_json",
            return_value=yyp_data,
        ), patch(
            "gms_helpers.maintenance.prune.os.path.exists",
            side_effect=lambda path: path == "scripts/existing/existing.yy",
        ), patch("gms_helpers.maintenance.prune.shutil.copy2") as mock_copy, patch(
            "gms_helpers.maintenance.prune.save_json"
        ) as mock_save:
            removed = prune_missing_assets(dry_run=True)

        self.assertEqual(
            removed,
            [
                ("scripts/missing/missing.yy", "script"),
            ],
        )
        mock_copy.assert_not_called()
        mock_save.assert_not_called()

    def test_prune_missing_assets_apply_writes_cleaned_project(self):
        yyp_data = {"resources": [{"id": {"path": "scripts/missing/missing.yy"}}], "resourceOrder": []}
        saved_payload = {}

        def _save_json(data, path):
            saved_payload["data"] = data
            saved_payload["path"] = path

        with patch("gms_helpers.maintenance.prune.find_yyp_file", return_value="TestGame.yyp"), patch(
            "gms_helpers.maintenance.prune.load_json",
            return_value=yyp_data,
        ), patch(
            "gms_helpers.maintenance.prune.os.path.exists",
            return_value=False,
        ), patch("gms_helpers.maintenance.prune.shutil.copy2") as mock_copy, patch(
            "gms_helpers.maintenance.prune.save_json",
            side_effect=_save_json,
        ):
            removed = prune_missing_assets(dry_run=False)

        self.assertEqual(removed, [("scripts/missing/missing.yy", "script")])
        mock_copy.assert_called_once_with("TestGame.yyp", "TestGame.yyp.bak")
        self.assertEqual(saved_payload["data"]["resources"], [])
        self.assertEqual(saved_payload["path"], "TestGame.yyp")

    def test_prune_missing_assets_handles_exceptions_and_reports_output(self):
        with patch("gms_helpers.maintenance.prune.find_yyp_file", side_effect=RuntimeError("boom")):
            removed, error_output = _capture_output(prune_missing_assets, dry_run=False)
        self.assertEqual(removed, [])
        self.assertIn("Error during asset pruning: boom", error_output)

        _, report_output = _capture_output(
            print_prune_report,
            [("scripts/missing.yy", "script"), ("rooms/missing.yy", "room")],
            True,
        )
        self.assertIn("Would remove: 2 missing reference(s)", report_output)
        self.assertIn("Run without --dry-run to apply changes", report_output)

        _, clean_output = _capture_output(print_prune_report, [], False)
        self.assertIn("No missing asset references found", clean_output)


class TestStaticSearchBehavior(unittest.TestCase):
    def test_pattern_building_and_asset_name_discovery(self):
        self.assertIsNone(_build_prefix_pattern([]))
        self.assertEqual(_build_prefix_pattern(["spr_"]), r"\bspr_\w+\b")
        self.assertEqual(_build_prefix_pattern(["spr_", "sprite_"]), r"\b(spr_|sprite_)\w+\b")

        config = FakeNamingConfig({"sprite": ["spr_"], "sound": ["snd_"]})
        patterns = _get_asset_patterns_from_config(config)
        self.assertIn(r"\bspr_\w+\b", patterns["sprites"])
        self.assertTrue(any("audio_play_sound" in pattern for pattern in patterns["sounds"]))

        names = find_asset_name_patterns(
            {
                "sprites/spr_player/spr_player.yy",
                "scripts/scr_move/scr_move.yy",
                "fonts/fnt_ui/fnt_ui.yy",
            }
        )
        self.assertEqual(names["sprites"], {"spr_player"})
        self.assertEqual(names["scripts"], {"scr_move"})
        self.assertEqual(names["fonts"], {"fnt_ui"})

    def test_find_string_references_and_cross_reference_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "scripts").mkdir()
            (root / "docs").mkdir()
            (root / "scripts" / "logic.gml").write_text(
                'sprite_index = spr_player;\n'
                'audio_play_sound("snd_boom", 1, false);\n'
                'room_goto(r_menu);\n'
                'font = "fnt_ui";\n',
                encoding="utf-8",
            )
            (root / "docs" / "ignored.gml").write_text("spr_should_not_count", encoding="utf-8")

            with patch("gms_helpers.maintenance.static_search.get_config", side_effect=RuntimeError("ignore config")):
                refs = find_string_references_in_gml(str(root))

        self.assertIn("spr_player", refs["sprites"])
        self.assertIn("snd_boom", refs["sounds"])
        self.assertIn("r_menu", refs["rooms"])

        filesystem_files = {
            "sprites/spr_player/spr_player.yy",
            "sounds/SND_BOOM/SND_BOOM.yy",
            "rooms/r_menu/r_menu.yy",
        }
        filesystem_map = {
            "sprites/spr_player/spr_player.yy": "sprites/spr_player/spr_player.yy",
            "sounds/snd_boom/snd_boom.yy": "sounds/SND_BOOM/SND_BOOM.yy",
            "rooms/r_menu/r_menu.yy": "rooms/r_menu/r_menu.yy",
        }
        results = cross_reference_strings_to_files(refs, filesystem_files, filesystem_map)
        self.assertTrue(any("spr_player" in item for item in results["string_refs_found_exact"]))
        self.assertTrue(any("snd_boom" in item for item in results["string_refs_found_case_diff"]))
        self.assertFalse(any("r_menu" in item for item in results["string_refs_missing"]))

    def test_identify_derivable_orphans_uses_string_refs_and_prefixes(self):
        config = FakeNamingConfig({"sprite": ["spr_"], "sound": ["snd_"]})
        derivable = identify_derivable_orphans(
            filesystem_files={
                "sprites/spr_enemy/spr_enemy.yy",
                "scripts/player_create/player_create.yy",
                "sounds/snd_boom/snd_boom.yy",
            },
            referenced_files={"sounds/snd_boom/snd_boom.yy"},
            string_refs={"sprites": {"spr_enemy"}, "sounds": set()},
            config=config,
        )
        self.assertTrue(any("referenced as string: spr_enemy" in item for item in derivable))
        self.assertTrue(any("follows naming convention" in item for item in derivable))


if __name__ == "__main__":
    unittest.main()
