#!/usr/bin/env python3
"""Additional coverage tests for helper-heavy modules close to 95%."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.event_helper import (
    add_event,
    duplicate_event,
    handle_remove,
    main as event_main,
    remove_event,
)
from gms_helpers.exceptions import AssetNotFoundError, GMSError, ValidationError
from gms_helpers.gml_docs.fetcher import GMLDocParser, fetch_function_doc, fetch_function_index
from gms_helpers.maintenance.audit.reference_collector import ReferenceCollector


class TestEventHelper95Coverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.old_cwd = Path.cwd()
        (self.project_root / "TestGame.yyp").write_text("{}", encoding="utf-8")
        (self.project_root / "objects" / "o_test").mkdir(parents=True)
        self.object_yy = self.project_root / "objects" / "o_test" / "o_test.yy"
        self.object_yy.write_text(json.dumps({"name": "o_test"}), encoding="utf-8")
        os_chdir = __import__("os").chdir
        os_chdir(self.project_root)

    def tearDown(self):
        __import__("os").chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_add_and_remove_error_paths(self):
        with self.assertRaises(AssetNotFoundError):
            add_event("o_missing", "create")

        with patch("gms_helpers.event_helper.load_json_loose", return_value=None):
            with self.assertRaises(GMSError):
                add_event("o_test", "create")

        with patch("gms_helpers.event_helper.load_json_loose", return_value={"name": "o_test"}):
            with patch("gms_helpers.event_helper.save_json_loose"):
                self.assertTrue(add_event("o_test", "create"))

        with self.assertRaises(ValidationError):
            remove_event("o_test", "invalid")

        with self.assertRaises(AssetNotFoundError):
            remove_event("o_missing", "create")

        with patch("gms_helpers.event_helper.load_json_loose", return_value=None):
            with self.assertRaises(GMSError):
                remove_event("o_test", "create")

        args = SimpleNamespace(object="o_test", event="create", keep_file=True)
        with patch("gms_helpers.event_helper.remove_event", return_value=True) as mock_remove:
            self.assertTrue(handle_remove(args))
        mock_remove.assert_called_once_with("o_test", "create", True)

    def test_duplicate_event_remaining_paths(self):
        with self.assertRaises(ValidationError):
            duplicate_event("o_test", "invalid", 1)

        with self.assertRaises(AssetNotFoundError):
            duplicate_event("o_missing", "step:0", 1)

        with patch("gms_helpers.event_helper.load_json_loose", return_value=None):
            with self.assertRaises(GMSError):
                duplicate_event("o_test", "step:0", 1)

        source_path = self.project_root / "objects" / "o_test" / "Step_0.gml"
        source_path.write_text("// source\n", encoding="utf-8")
        with patch(
            "gms_helpers.event_helper.load_json_loose",
            return_value={"name": "o_test", "eventList": None},
        ):
            with patch("gms_helpers.event_helper.save_json_loose") as mock_save:
                self.assertTrue(duplicate_event("o_test", "step:0", 1))
        saved_data = mock_save.call_args.args[1]
        self.assertEqual(saved_data["eventList"][0]["eventNum"], 1)

    def test_main_without_handler_returns_false(self):
        with patch("gms_helpers.event_helper.validate_working_directory"):
            with patch("gms_helpers.event_helper.sys.argv", ["event_helper", "list", "o_test"]):
                with patch("argparse.ArgumentParser.parse_args", return_value=SimpleNamespace()):
                    self.assertFalse(event_main())


class TestFetcher95Coverage(unittest.TestCase):
    def test_doc_parser_inline_and_pre_code_paths(self):
        parser = GMLDocParser()
        parser.feed(
            "<body>"
            "<h2>Other Section</h2>"
            "<p>Description text.</p>"
            "<h3>Syntax</h3><code>draw_text(x, y, s)</code>"
            "<h4>Example</h4><pre><code>draw_text(x, y, s);</code></pre>"
            "<h3>Returns</h3><p>Real</p>"
            "</body>"
        )
        parser.post_process("draw_text")

        self.assertEqual(parser.syntax, "draw_text(x, y, s)")
        self.assertEqual(parser.examples, ["draw_text(x, y, s);"])
        self.assertEqual(parser.returns, "Real")

    def test_fetch_functions_construct_default_cache_objects(self):
        cache = MagicMock()
        entry = SimpleNamespace(
            name="draw_text",
            category="Drawing",
            subcategory="Text",
            url="https://manual.gamemaker.io/draw_text.htm",
        )

        with patch("gms_helpers.gml_docs.fetcher.DocCache", return_value=cache):
            cache.get_index.return_value = {"draw_text": entry}
            result = fetch_function_index(cache=None, force_refresh=False)
        self.assertIn("draw_text", result)

        cache = MagicMock()
        cache.get_function.return_value = None
        with patch("gms_helpers.gml_docs.fetcher.DocCache", return_value=cache):
            with patch("gms_helpers.gml_docs.fetcher.fetch_function_index", return_value={}):
                self.assertIsNone(fetch_function_doc("missing_name", cache=None, force_refresh=False))


class TestReferenceCollector95Coverage(unittest.TestCase):
    def test_determine_asset_type_fallbacks_and_process_error(self):
        collector = ReferenceCollector(".")
        self.assertEqual(collector._determine_asset_type({}, Path("rooms/r_test/r_test.yy")), "room")
        self.assertEqual(collector._determine_asset_type({}, Path("fonts/fnt_test/fnt_test.yy")), "font")
        self.assertEqual(collector._determine_asset_type({}, Path("shaders/shd_test/shd_test.yy")), "shader")

        with patch("gms_helpers.maintenance.audit.reference_collector.load_json", return_value={"name": "spr_test"}):
            with patch.object(collector, "_determine_asset_type", side_effect=RuntimeError("boom")):
                with patch("builtins.print") as mock_print:
                    collector._process_single_asset(Path("sprites/spr_test/spr_test.yy"))
        self.assertIn("Error processing asset", mock_print.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
