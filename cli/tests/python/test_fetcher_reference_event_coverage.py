#!/usr/bin/env python3
"""Targeted coverage tests for fetcher, reference collector, and event helper."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.diagnostics import CODE_CASE_MISMATCH, CODE_ORPHAN_FILE, CODE_REFERENCE_MISSING
from gms_helpers.event_helper import (
    _event_to_filename,
    _filename_to_event,
    add_event,
    duplicate_event,
    handle_fix,
    handle_validate,
    list_events,
    main as event_main,
    remove_event,
)
from gms_helpers.exceptions import AssetNotFoundError, GMSError, ValidationError
from gms_helpers.gml_docs.cache import CachedDoc, FunctionIndexEntry
from gms_helpers.gml_docs.fetcher import (
    GMLDocParser,
    IndexParser,
    SimpleHTMLTextExtractor,
    _fetch_url,
    _rate_limit,
    fetch_function_doc,
    fetch_function_index,
)
from gms_helpers.maintenance.audit.reference_collector import (
    ReferenceCollector,
    audit_to_diagnostics,
    collect_project_references,
    comprehensive_analysis,
)
from gms_helpers.maintenance.path_utils import normalize_path
class TestFetcherCoverage(unittest.TestCase):
    def test_simple_html_text_extractor_ignores_script_and_style(self):
        parser = SimpleHTMLTextExtractor()
        parser.feed(
            "<div>Hello<br>World<script>bad()</script>"
            "<style>.x{color:red;}</style><p>Done</p></div>"
        )

        text = parser.get_text()
        self.assertIn("Hello\nWorld", text)
        self.assertIn("Done", text)
        self.assertNotIn("bad()", text)
        self.assertNotIn("color:red", text)

    def test_gml_doc_parser_extracts_sections(self):
        parser = GMLDocParser()
        parser.feed(
            "<html><title>draw_sprite</title><body>"
            "<p>Draws a sprite.</p>"
            "<h3>Syntax</h3><pre>draw_sprite(sprite, 0, x, y);</pre>"
            "<h3>Arguments</h3>"
            "<table><thead><tr><th>Argument</th><th>Type</th><th>Description</th></tr></thead>"
            "<tr><td>sprite</td><td>Sprite</td><td>The sprite asset.</td></tr></table>"
            "<h3>Returns</h3><p>N/A</p>"
            "<h3>Example</h3><pre>draw_sprite(sprite, 0, x, y);</pre>"
            "</body></html>"
        )
        parser.post_process("draw_sprite")

        self.assertEqual(parser.title, "draw_sprite")
        self.assertIn("Draws a sprite.", parser.get_description())
        self.assertEqual(parser.syntax, "draw_sprite(sprite, 0, x, y);")
        self.assertEqual(parser.parameters[0]["name"], "sprite")
        self.assertEqual(parser.parameters[0]["type"], "Sprite")
        self.assertEqual(parser.returns, "N/AExample")
        self.assertEqual(parser.examples, ["draw_sprite(sprite, 0, x, y);"])

    def test_gml_doc_parser_post_process_fills_missing_syntax_and_returns(self):
        parser = GMLDocParser()
        parser.feed(
            "<body><p>move_towards_point(x, y); Returns: Real number</p></body>"
        )
        parser.post_process("move_towards_point")

        self.assertEqual(parser.syntax, "move_towards_point(x, y);")
        self.assertEqual(parser.returns, "Real number")

    def test_index_parser_extracts_function_links(self):
        parser = IndexParser("https://manual.gamemaker.io/monthly/en/page.htm")
        parser.feed(
            "<a href='Sprites/draw_sprite.htm'>draw_sprite</a>"
            "<a href='https://example.com/nope.htm'>skip</a>"
            "<a href='Other/Not_A_Function.htm'>not-a-function</a>"
        )

        self.assertIn("draw_sprite", parser.functions)
        entry = parser.functions["draw_sprite"]
        self.assertEqual(entry.name, "draw_sprite")
        self.assertIn("draw_sprite.htm", entry.url)
        self.assertNotIn("not-a-function", parser.functions)

    def test_rate_limit_sleeps_when_called_too_quickly(self):
        import gms_helpers.gml_docs.fetcher as fetcher_mod

        with patch.object(fetcher_mod, "_last_request_time", 10.0):
            with patch("gms_helpers.gml_docs.fetcher.time.time", side_effect=[10.1, 10.6]):
                with patch("gms_helpers.gml_docs.fetcher.time.sleep") as mock_sleep:
                    _rate_limit()

        mock_sleep.assert_called_once()

    def test_fetch_url_success_and_error_paths(self):
        response = MagicMock()
        response.read.return_value = b"<html>ok</html>"
        response.__enter__.return_value = response
        response.__exit__.return_value = False

        with patch("gms_helpers.gml_docs.fetcher._rate_limit"):
            with patch("gms_helpers.gml_docs.fetcher.urllib.request.urlopen", return_value=response):
                html = _fetch_url("https://example.com/test")
        self.assertEqual(html, "<html>ok</html>")

        with patch("gms_helpers.gml_docs.fetcher._rate_limit"):
            with patch(
                "gms_helpers.gml_docs.fetcher.urllib.request.urlopen",
                side_effect=__import__("urllib.error").error.HTTPError(
                    "https://example.com/test",
                    404,
                    "missing",
                    hdrs=None,
                    fp=None,
                ),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    _fetch_url("https://example.com/test")
        self.assertIn("HTTP error 404", str(ctx.exception))

        with patch("gms_helpers.gml_docs.fetcher._rate_limit"):
            with patch(
                "gms_helpers.gml_docs.fetcher.urllib.request.urlopen",
                side_effect=__import__("urllib.error").error.URLError("offline"),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    _fetch_url("https://example.com/test")
        self.assertIn("Network error", str(ctx.exception))

        with patch("gms_helpers.gml_docs.fetcher._rate_limit"):
            with patch(
                "gms_helpers.gml_docs.fetcher.urllib.request.urlopen",
                side_effect=TimeoutError,
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    _fetch_url("https://example.com/test")
        self.assertIn("Timeout fetching", str(ctx.exception))

    def test_fetch_function_index_uses_cache_when_available(self):
        entry = FunctionIndexEntry(
            name="draw_sprite",
            category="Drawing",
            subcategory="Sprites",
            url="https://manual.gamemaker.io/draw_sprite.htm",
        )
        cache = MagicMock()
        cache.get_index.return_value = {"draw_sprite": entry}

        result = fetch_function_index(cache=cache, force_refresh=False)

        self.assertEqual(result["draw_sprite"].name, "draw_sprite")
        cache.save_index.assert_not_called()

    def test_fetch_function_index_fetches_and_saves_when_cache_empty(self):
        cache = MagicMock()
        cache.get_index.return_value = None

        def fake_fetch(url: str, timeout: float = 30.0) -> str:
            if "Sprites_And_Tiles.htm" in url:
                return "<a href='draw_sprite.htm'>draw_sprite</a>"
            raise RuntimeError("skip")

        with patch("gms_helpers.gml_docs.fetcher._fetch_url", side_effect=fake_fetch):
            result = fetch_function_index(cache=cache, force_refresh=False)

        self.assertIn("draw_sprite", result)
        self.assertEqual(result["draw_sprite"].category, "Drawing")
        self.assertEqual(result["draw_sprite"].subcategory, "Sprites_And_Tiles")
        cache.save_index.assert_called_once()

    def test_fetch_function_doc_variants(self):
        cached_doc = CachedDoc(
            name="draw_sprite",
            category="Drawing",
            subcategory="Sprites",
            url="https://manual.gamemaker.io/draw_sprite.htm",
            description="Cached doc",
            syntax="draw_sprite();",
            parameters=[],
            returns="N/A",
            examples=[],
            cached_at=123.0,
        )
        cache = MagicMock()
        cache.get_function.return_value = cached_doc

        result = fetch_function_doc("draw_sprite", cache=cache, force_refresh=False)
        self.assertIs(result, cached_doc)

        cache = MagicMock()
        cache.get_function.return_value = None
        with patch("gms_helpers.gml_docs.fetcher.fetch_function_index", return_value={}):
            self.assertIsNone(fetch_function_doc("missing_fn", cache=cache))

        entry = FunctionIndexEntry(
            name="draw_sprite",
            category="Drawing",
            subcategory="Sprites",
            url="https://manual.gamemaker.io/draw_sprite.htm",
        )
        cache = MagicMock()
        cache.get_function.return_value = None
        with patch("gms_helpers.gml_docs.fetcher.fetch_function_index", return_value={"draw_sprite": entry}):
            with patch("gms_helpers.gml_docs.fetcher._fetch_url", side_effect=RuntimeError("offline")):
                self.assertIsNone(fetch_function_doc("draw_sprite", cache=cache))

        cache = MagicMock()
        cache.get_function.return_value = None
        with patch("gms_helpers.gml_docs.fetcher.fetch_function_index", return_value={"draw_sprite": entry}):
            with patch(
                "gms_helpers.gml_docs.fetcher._fetch_url",
                return_value=(
                    "<body><p>Draws a sprite.</p><h3>Syntax</h3>"
                    "<pre>draw_sprite(sprite, 0, x, y);</pre></body>"
                ),
            ):
                doc = fetch_function_doc("draw_sprite", cache=cache)

        self.assertIsNotNone(doc)
        self.assertEqual(doc.name, "draw_sprite")
        self.assertEqual(doc.syntax, "draw_sprite(sprite, 0, x, y);")
        cache.save_function.assert_called_once()


class TestReferenceCollectorCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

        resources = []

        def add_resource(rel_path: str) -> None:
            resources.append({"id": {"name": Path(rel_path).stem, "path": rel_path}})

        (self.project_root / "objects" / "o_player").mkdir(parents=True)
        (self.project_root / "objects" / "o_player" / "o_player.yy").write_text(
            json.dumps(
                {
                    "$GMObject": "",
                    "eventList": [
                        {"eventType": 0, "eventNum": 0, "collisionObjectId": None},
                        {"eventType": 4, "eventNum": 0, "collisionObjectId": "o_wall"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.project_root / "objects" / "o_player" / "Create_0.gml").write_text("// create\n", encoding="utf-8")
        (self.project_root / "objects" / "o_player" / "Collision_o_wall.gml").write_text(
            "// collision\n", encoding="utf-8"
        )
        add_resource("objects/o_player/o_player.yy")

        (self.project_root / "scripts" / "scr_boot").mkdir(parents=True)
        (self.project_root / "scripts" / "scr_boot" / "scr_boot.yy").write_text(
            json.dumps({"name": "scr_boot"}),
            encoding="utf-8",
        )
        (self.project_root / "scripts" / "scr_boot" / "scr_boot.gml").write_text("// boot\n", encoding="utf-8")
        add_resource("scripts/scr_boot/scr_boot.yy")

        (self.project_root / "sprites" / "spr_logo" / "layers" / "layerA").mkdir(parents=True)
        (self.project_root / "sprites" / "spr_logo" / "spr_logo.yy").write_text(
            json.dumps({"$GMSprite": "", "frames": [{"name": "frameA"}]}),
            encoding="utf-8",
        )
        (self.project_root / "sprites" / "spr_logo" / "frameA.png").write_bytes(b"png")
        (self.project_root / "sprites" / "spr_logo" / "layers" / "layerA" / "image.png").write_bytes(b"png")
        add_resource("sprites/spr_logo/spr_logo.yy")

        (self.project_root / "sounds" / "snd_beep").mkdir(parents=True)
        (self.project_root / "sounds" / "snd_beep" / "snd_beep.yy").write_text(
            json.dumps({"$GMSound": "", "soundFile": "beep.wav"}),
            encoding="utf-8",
        )
        (self.project_root / "sounds" / "snd_beep" / "beep.wav").write_bytes(b"wav")
        add_resource("sounds/snd_beep/snd_beep.yy")

        (self.project_root / "rooms" / "r_intro").mkdir(parents=True)
        (self.project_root / "rooms" / "r_intro" / "r_intro.yy").write_text(json.dumps({"$GMRoom": ""}), encoding="utf-8")
        add_resource("rooms/r_intro/r_intro.yy")

        (self.project_root / "fonts" / "fnt_main").mkdir(parents=True)
        (self.project_root / "fonts" / "fnt_main" / "fnt_main.yy").write_text(
            json.dumps({"$GMFont": "", "texture": "font.png"}),
            encoding="utf-8",
        )
        (self.project_root / "fonts" / "fnt_main" / "font.png").write_bytes(b"png")
        add_resource("fonts/fnt_main/fnt_main.yy")

        (self.project_root / "shaders" / "shd_tint").mkdir(parents=True)
        (self.project_root / "shaders" / "shd_tint" / "shd_tint.yy").write_text(
            json.dumps({"$GMShader": ""}),
            encoding="utf-8",
        )
        (self.project_root / "shaders" / "shd_tint" / "shd_tint.vsh").write_text("// vsh\n", encoding="utf-8")
        (self.project_root / "shaders" / "shd_tint" / "shd_tint.fsh").write_text("// fsh\n", encoding="utf-8")
        add_resource("shaders/shd_tint/shd_tint.yy")

        for rel_path, gm_key in [
            ("animcurves/ac_curve/ac_curve.yy", "$GMAnimCurve"),
            ("sequences/seq_cut/seq_cut.yy", "$GMSequence"),
            ("tilesets/ts_ground/ts_ground.yy", "$GMTileSet"),
            ("timelines/tl_day/tl_day.yy", "$GMTimeline"),
            ("paths/path_enemy/path_enemy.yy", "$GMPath"),
        ]:
            yy_path = self.project_root / rel_path
            yy_path.parent.mkdir(parents=True)
            yy_path.write_text(json.dumps({gm_key: ""}), encoding="utf-8")
            add_resource(rel_path)

        (self.project_root / "TestGame.yyp").write_text(
            json.dumps({"resources": resources}, indent=2),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_collect_project_references_discovers_companion_files(self):
        refs = collect_project_references(str(self.project_root))

        self.assertIn(normalize_path("TestGame.yyp"), refs)
        self.assertIn(normalize_path("objects/o_player/Create_0.gml"), refs)
        self.assertIn(normalize_path("objects/o_player/Collision_o_wall.gml"), refs)
        self.assertIn(normalize_path("scripts/scr_boot/scr_boot.gml"), refs)
        self.assertIn(normalize_path("sprites/spr_logo/frameA.png"), refs)
        self.assertIn(normalize_path("sprites/spr_logo/layers/layerA/image.png"), refs)
        self.assertIn(normalize_path("sounds/snd_beep/beep.wav"), refs)
        self.assertIn(normalize_path("fonts/fnt_main/font.png"), refs)
        self.assertIn(normalize_path("shaders/shd_tint/shd_tint.vsh"), refs)
        self.assertIn(normalize_path("shaders/shd_tint/shd_tint.fsh"), refs)

    def test_reference_collector_helper_methods_and_fallbacks(self):
        collector = ReferenceCollector(str(self.project_root))

        collector._add_reference("Objects\\o_player\\Create_0.gml")
        self.assertIn(normalize_path("Objects/o_player/Create_0.gml"), collector.referenced_files)

        self.assertEqual(
            collector._determine_asset_type({}, Path("objects/o_enemy/o_enemy.yy")),
            "object",
        )
        self.assertEqual(
            collector._determine_asset_type({}, Path("scripts/scr_misc/scr_misc.yy")),
            "script",
        )
        self.assertEqual(
            collector._determine_asset_type({}, Path("folders/UI.yy")),
            "folder",
        )
        self.assertEqual(collector._determine_asset_type({}, Path("misc/x.yy")), "unknown")

        self.assertEqual(collector._get_event_filename(0, 0), "Create_0.gml")
        self.assertEqual(collector._get_event_filename(4, 0, "o_enemy"), "Collision_o_enemy.gml")
        self.assertIsNone(collector._get_event_filename(99, 0))

    def test_reference_collector_queue_and_error_paths(self):
        collector = ReferenceCollector(str(self.project_root))
        collector.parsing_queue = [self.project_root / "bad.yy", self.project_root / "good.yy"]

        with patch.object(collector, "_process_single_asset", side_effect=[RuntimeError("boom"), None]) as mock_process:
            collector._process_asset_queue()

        self.assertEqual(mock_process.call_count, 2)

        with patch(
            "gms_helpers.maintenance.audit.reference_collector.find_yyp_file",
            side_effect=FileNotFoundError("missing"),
        ):
            with self.assertRaises(FileNotFoundError):
                collector._load_primary_assets()

    def test_comprehensive_analysis_and_diagnostics(self):
        with patch(
            "gms_helpers.maintenance.audit.reference_collector.ReferenceCollector.collect_all_references",
            return_value={"Scripts/Boot.gml", "sprites/spr_logo/spr_logo.yy"},
        ):
            with patch(
                "gms_helpers.maintenance.audit.reference_collector.build_filesystem_map",
                return_value={"scripts/boot.gml": "Scripts/Boot.gml"},
            ):
                with patch(
                    "gms_helpers.maintenance.audit.reference_collector.get_gamemaker_files",
                    return_value=[
                        "Scripts/Boot.gml",
                        "Sprites/spr_logo/spr_logo.yy",
                        "Sprites/Case.PNG",
                        "assets/from_string.png",
                        "orphan.txt",
                    ],
                ):
                    with patch(
                        "gms_helpers.maintenance.audit.reference_collector.categorize_path_differences",
                        return_value={
                            "found_exact": ["scripts/boot.gml"],
                            "found_case_diff": ["sprites/spr_logo/spr_logo.yy -> Sprites/spr_logo/spr_logo.yy"],
                            "missing": ["missing/file.yy"],
                        },
                    ):
                        with patch(
                            "gms_helpers.maintenance.audit.reference_collector.find_string_references_in_gml",
                            return_value={"raw": {"foo"}},
                        ):
                            with patch(
                                "gms_helpers.maintenance.audit.reference_collector.cross_reference_strings_to_files",
                                return_value={
                                    "string_refs_found_exact": ["foo -> assets/from_string.png"],
                                    "string_refs_found_case_diff": ["bar -> Sprites/Case.PNG"],
                                },
                            ):
                                with patch(
                                    "gms_helpers.maintenance.audit.reference_collector.identify_derivable_orphans",
                                    return_value=["maybe_used.txt (string references)"],
                                ):
                                    results = comprehensive_analysis(str(self.project_root))

        self.assertEqual(results["final_analysis"]["true_orphans"], ["orphan.txt"])
        self.assertEqual(results["final_analysis"]["missing_but_referenced_count"], 1)
        self.assertEqual(results["final_analysis"]["case_sensitivity_issues_count"], 1)

        diagnostics = audit_to_diagnostics(
            {
                "final_analysis": {
                    "missing_but_referenced": ["missing/file.yy"],
                    "case_sensitivity_issues": ["bad/path.yy -> Good/Path.yy"],
                    "true_orphans": ["orphan.txt"],
                },
                "phase_2_results": {
                    "derivable_orphans": ["maybe_used.txt (naming conventions)"],
                },
            }
        )

        self.assertEqual(len(diagnostics), 4)
        self.assertEqual(diagnostics[0].code, CODE_REFERENCE_MISSING)
        self.assertEqual(diagnostics[1].code, CODE_CASE_MISMATCH)
        self.assertEqual(diagnostics[2].code, CODE_ORPHAN_FILE)
        self.assertEqual(diagnostics[3].severity, "info")


class TestEventHelperCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.old_cwd = os.getcwd()
        os.chdir(self.project_root)
        (self.project_root / "objects" / "o_test").mkdir(parents=True)
        (self.project_root / "TestGame.yyp").write_text("{}", encoding="utf-8")
        self.yy_path = self.project_root / "objects" / "o_test" / "o_test.yy"
        self.yy_path.write_text(json.dumps({"name": "o_test", "eventList": []}), encoding="utf-8")

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_filename_to_event_invalid_cases(self):
        self.assertEqual(_filename_to_event("not_gml.txt"), (None, None))
        self.assertEqual(_filename_to_event("too_many_parts_here.gml"), (None, None))
        self.assertEqual(_filename_to_event("Create_nope.gml"), (None, None))
        self.assertEqual(_event_to_filename(-1, 0), "PreCreate_0.gml")

    def test_list_events_and_error_paths(self):
        self.assertEqual(list_events("o_test"), [])

        with self.assertRaises(AssetNotFoundError):
            list_events("o_missing")

        with patch("gms_helpers.event_helper.load_json_loose", return_value=None):
            with self.assertRaises(GMSError):
                list_events("o_test")

    def test_add_remove_and_duplicate_event_edge_cases(self):
        with self.assertRaises(ValidationError):
            add_event("o_test", "step:not_a_number")
        with self.assertRaises(ValidationError):
            add_event("o_test", "unknown")

        add_event("o_test", "step")
        self.assertTrue((self.project_root / "objects" / "o_test" / "Step_0.gml").exists())

        # Duplicate add is a success path with a warning.
        self.assertTrue(add_event("o_test", "step"))

        # Remove while keeping file.
        self.assertTrue(remove_event("o_test", "step", keep_file=True))
        self.assertTrue((self.project_root / "objects" / "o_test" / "Step_0.gml").exists())

        # Removing a missing event reports False.
        self.assertFalse(remove_event("o_test", "step"))

        # Duplicate from a source file that exists only on disk creates the new event entry.
        create_path = self.project_root / "objects" / "o_test" / "Create_0.gml"
        create_path.write_text("// create\n", encoding="utf-8")
        self.assertTrue(duplicate_event("o_test", "create", 1))
        duplicated = self.project_root / "objects" / "o_test" / "Create_1.gml"
        self.assertTrue(duplicated.exists())

        # Existing target is treated as success.
        self.assertTrue(duplicate_event("o_test", "create", 1))

        # Missing source raises validation error.
        with self.assertRaises(ValidationError):
            duplicate_event("o_test", "alarm:2", 3)

        with self.assertRaises(ValidationError):
            duplicate_event("o_test", "step:not_a_number", 1)

    def test_handle_validate_and_fix(self):
        args = SimpleNamespace(object="o_test")

        with patch("gms_helpers.event_helper.sync_object_events", return_value={"orphaned_found": 0, "missing_found": 0}):
            self.assertTrue(handle_validate(args))

        with patch("gms_helpers.event_helper.sync_object_events", return_value={"orphaned_found": 2, "missing_found": 1}):
            self.assertTrue(handle_validate(args))

        with patch(
            "gms_helpers.event_helper.sync_object_events",
            return_value={"missing_created": 0, "orphaned_fixed": 0},
        ):
            self.assertTrue(handle_fix(args))

        with patch(
            "gms_helpers.event_helper.sync_object_events",
            return_value={"missing_created": 2, "orphaned_fixed": 1},
        ):
            self.assertTrue(handle_fix(args))

    def test_main_branches(self):
        with patch("gms_helpers.event_helper.validate_working_directory"):
            with patch.object(sys, "argv", ["event_helper.py"]):
                self.assertFalse(event_main())

        with patch("gms_helpers.event_helper.validate_working_directory"):
            with patch.object(sys, "argv", ["event_helper.py", "list", "o_test"]):
                self.assertTrue(event_main())

        with patch("gms_helpers.event_helper.validate_working_directory"):
            with patch("gms_helpers.event_helper.handle_list", side_effect=GMSError("bad")):
                with patch.object(sys, "argv", ["event_helper.py", "list", "o_test"]):
                    with self.assertRaises(GMSError):
                        event_main()

        with patch("gms_helpers.event_helper.validate_working_directory"):
            with patch("gms_helpers.event_helper.handle_list", side_effect=RuntimeError("boom")):
                with patch.object(sys, "argv", ["event_helper.py", "list", "o_test"]):
                    self.assertFalse(event_main())


if __name__ == "__main__":
    unittest.main()
