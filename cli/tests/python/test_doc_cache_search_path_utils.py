#!/usr/bin/env python3
"""Coverage tests for doc cache/search and path utilities."""

from __future__ import annotations

import json
import importlib
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.gml_docs.cache import (
    CachedDoc,
    DEFAULT_TTL_SECONDS,
    DocCache,
    FunctionIndexEntry,
    clear_cache,
    get_cache_stats,
)
doc_search = importlib.import_module("gms_helpers.gml_docs.search")
from gms_helpers.maintenance import path_utils


def _sample_doc(name: str = "draw_sprite", cached_at: float | None = None, ttl: float = DEFAULT_TTL_SECONDS):
    return CachedDoc(
        name=name,
        category="Drawing",
        subcategory="Sprites",
        url=f"https://example/{name}",
        description="Draw something",
        syntax=f"{name}(...)",
        parameters=[{"name": "sprite", "type": "resource", "description": "Sprite asset"}],
        returns="void",
        examples=[f"{name}(spr_player, 0, x, y);"],
        cached_at=cached_at if cached_at is not None else time.time(),
        ttl=ttl,
    )


class TestDocCache(unittest.TestCase):
    def test_cached_doc_helpers_and_function_entry_round_trip(self):
        fresh = _sample_doc(cached_at=time.time())
        expired = _sample_doc(cached_at=time.time() - 10, ttl=1)
        self.assertFalse(fresh.is_expired())
        self.assertTrue(expired.is_expired())

        payload = fresh.to_dict()
        self.assertEqual(CachedDoc.from_dict(payload).name, "draw_sprite")

        entry = FunctionIndexEntry(
            name="draw_sprite",
            category="Drawing",
            subcategory="Sprites",
            url="https://example/draw_sprite",
        )
        self.assertEqual(FunctionIndexEntry.from_dict(entry.to_dict()).name, "draw_sprite")

    def test_doc_cache_index_and_function_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = DocCache(Path(temp_dir))
            self.assertEqual(
                cache._get_function_path("Draw/Sprite\\Test").name,
                "draw_sprite_test.json",
            )

            entries = {
                "draw_sprite": FunctionIndexEntry(
                    name="draw_sprite",
                    category="Drawing",
                    subcategory="Sprites",
                    url="https://example/draw_sprite",
                )
            }
            cache.save_index(entries)
            loaded = cache.get_index()
            self.assertEqual(loaded["draw_sprite"].url, "https://example/draw_sprite")

            doc = _sample_doc()
            cache.save_function(doc)
            loaded_doc = cache.get_function("DRAW_SPRITE")
            self.assertEqual(loaded_doc.name, "draw_sprite")

    def test_doc_cache_handles_expired_and_invalid_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = DocCache(Path(temp_dir))

            expired = _sample_doc(cached_at=time.time() - 120, ttl=1)
            function_path = cache._get_function_path(expired.name)
            function_path.write_text(json.dumps(expired.to_dict()), encoding="utf-8")
            self.assertIsNone(cache.get_function(expired.name))
            self.assertFalse(function_path.exists())

            cache._get_index_path().write_text("{not-json}", encoding="utf-8")
            self.assertIsNone(cache.get_index())

            function_path.write_text("{not-json}", encoding="utf-8")
            self.assertIsNone(cache.get_function("draw_sprite"))

            stale_index = {
                "cached_at": time.time() - (8 * 24 * 60 * 60),
                "entries": {
                    "draw_sprite": {
                        "name": "draw_sprite",
                        "category": "Drawing",
                        "subcategory": "Sprites",
                        "url": "https://example/draw_sprite",
                    }
                },
            }
            cache._get_index_path().write_text(json.dumps(stale_index), encoding="utf-8")
            self.assertIsNone(cache.get_index())

    def test_clear_cache_and_stats_use_home_cache_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with patch("gms_helpers.gml_docs.cache.Path.home", return_value=home):
                cache_dir = home / ".gms-mcp" / "doc_cache"
                functions_dir = cache_dir / "functions"
                functions_dir.mkdir(parents=True)
                (functions_dir / "draw_sprite.json").write_text("{}", encoding="utf-8")
                (functions_dir / "draw_text.json").write_text("{}", encoding="utf-8")
                (cache_dir / "index.json").write_text(
                    json.dumps({"cached_at": time.time(), "entries": {"draw_sprite": {}}}),
                    encoding="utf-8",
                )

                stats = get_cache_stats()
                self.assertTrue(stats["index_exists"])
                self.assertEqual(stats["cached_function_count"], 2)

                cleared = clear_cache(functions_only=True)
                self.assertEqual(cleared["functions_removed"], 2)
                self.assertFalse(cleared["index_removed"])
                self.assertTrue((cache_dir / "index.json").exists())

                cleared = clear_cache(functions_only=False)
                self.assertTrue(cleared["index_removed"])
                self.assertFalse((cache_dir / "index.json").exists())


class TestDocSearch(unittest.TestCase):
    def setUp(self):
        self.index = {
            "draw_sprite": FunctionIndexEntry("draw_sprite", "Drawing", "Sprites", "https://example/draw_sprite"),
            "draw_text": FunctionIndexEntry("draw_text", "Drawing", "Text", "https://example/draw_text"),
            "sprite_get_width": FunctionIndexEntry("sprite_get_width", "Sprites", "Info", "https://example/sprite_get_width"),
            "audio_play_sound": FunctionIndexEntry("audio_play_sound", "Audio", "Playback", "https://example/audio_play_sound"),
        }

    def test_lookup_success_and_suggestions(self):
        doc = _sample_doc()
        with patch("gms_helpers.gml_docs.search.fetch_function_doc", return_value=doc), patch(
            "gms_helpers.gml_docs.search.fetch_function_index", return_value=self.index
        ):
            result = doc_search.lookup("draw_sprite", force_refresh=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["cached"])

        with patch("gms_helpers.gml_docs.search.fetch_function_doc", return_value=None), patch(
            "gms_helpers.gml_docs.search.fetch_function_index", return_value=self.index
        ):
            result = doc_search.lookup("dra_sprite")
        self.assertFalse(result["ok"])
        self.assertIn("draw_sprite", result["suggestions"])

    def test_search_scores_and_filters_results(self):
        with patch("gms_helpers.gml_docs.search.fetch_function_index", return_value=self.index):
            result = doc_search.search("draw")
            drawing = doc_search.search("draw", category="Drawing", limit=1)
            fuzzy = doc_search.search("drw_sprte")

        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["name"], "draw_sprite")
        self.assertEqual(drawing["count"], 1)
        self.assertTrue(any(item["name"] == "draw_sprite" for item in fuzzy["results"]))

    def test_list_functions_and_categories(self):
        with patch("gms_helpers.gml_docs.search.fetch_function_index", return_value=self.index):
            invalid = doc_search.list_functions(pattern="(")
            filtered = doc_search.list_functions(category="Drawing", pattern="^draw_", limit=5)
            categories = doc_search.list_categories()

        self.assertFalse(invalid["ok"])
        self.assertEqual(filtered["count"], 2)
        self.assertEqual(categories["count"], 3)
        drawing = next(item for item in categories["categories"] if item["name"] == "Drawing")
        self.assertEqual(drawing["function_count"], 2)
        self.assertTrue(any(sub["name"] == "Sprites" for sub in drawing["subcategories"]))

    def test_find_similar_names_prefers_close_and_prefix_matches(self):
        matches = doc_search._find_similar_names(
            "dra",
            ["draw_sprite", "draw_text", "drop_shadow", "audio_play_sound"],
            limit=3,
        )
        self.assertIn("draw_sprite", matches)
        self.assertLessEqual(len(matches), 3)


class TestPathUtils(unittest.TestCase):
    def test_case_sensitivity_probe_and_normalization(self):
        with patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Linux"):
            self.assertFalse(path_utils._is_macos_case_sensitive())

        with patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Darwin"):
            self.assertIn(path_utils._is_macos_case_sensitive(), (True, False))

        with patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Windows"):
            self.assertEqual(path_utils.normalize_path(r"Sprites\Hero.PNG"), "sprites/hero.png")

        with patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Darwin"), patch(
            "gms_helpers.maintenance.path_utils._is_macos_case_sensitive",
            return_value=False,
        ):
            self.assertEqual(path_utils.normalize_path("Sprites/Hero.PNG"), "sprites/hero.png")

        with patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Darwin"), patch(
            "gms_helpers.maintenance.path_utils._is_macos_case_sensitive",
            return_value=True,
        ):
            self.assertEqual(path_utils.normalize_path("Sprites/Hero.PNG"), "Sprites/Hero.PNG")

    def test_filesystem_mapping_and_case_differences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sprites").mkdir()
            (root / ".git").mkdir()
            (root / ".git" / "ignored.yy").write_text("{}", encoding="utf-8")
            (root / "sprites" / "Hero.PNG").write_text("png", encoding="utf-8")

            with patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Windows"):
                filesystem_map = path_utils.build_filesystem_map(str(root))
                actual = path_utils.find_file_case_insensitive("sprites/hero.png", filesystem_map)
                self.assertEqual(actual.replace("\\", "/"), "sprites/Hero.PNG")

                with patch(
                    "gms_helpers.maintenance.path_utils.os.path.exists",
                    side_effect=lambda p: str(p) == "sprites/exact.yy",
                ):
                    categories = path_utils.categorize_path_differences(
                        {"sprites/exact.yy", "sprites/hero.png", "missing/file.yy"},
                        filesystem_map,
                    )

            self.assertEqual(categories["found_exact"], ["sprites/exact.yy"])
            self.assertEqual(
                [entry.replace("\\", "/") for entry in categories["found_case_diff"]],
                ["sprites/hero.png -> sprites/Hero.PNG"],
            )
            self.assertEqual(categories["missing"], ["missing/file.yy"])

    def test_get_gamemaker_files_filters_noise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sprites").mkdir()
            (root / "docs").mkdir()
            (root / "tools").mkdir()
            (root / "sprites" / "hero.yy").write_text("{}", encoding="utf-8")
            (root / "sprites" / "hero.gml").write_text("// script", encoding="utf-8")
            (root / "sprites" / "notes.md").write_text("# docs", encoding="utf-8")
            (root / "sprites" / "tool.py").write_text("print(1)", encoding="utf-8")
            (root / "tools" / "ignored.yy").write_text("{}", encoding="utf-8")
            (root / "docs" / "ignored.png").write_text("png", encoding="utf-8")
            (root / "sprites" / ".hidden.yy").write_text("{}", encoding="utf-8")
            (root / "sprites" / "order.resource_order").write_text("{}", encoding="utf-8")

            files = path_utils.get_gamemaker_files(str(root))

        self.assertIn("sprites/hero.yy", files)
        self.assertIn("sprites/hero.gml", files)
        self.assertIn("sprites/order.resource_order", files)
        self.assertNotIn("sprites/notes.md", files)
        self.assertNotIn("sprites/tool.py", files)
        self.assertNotIn("tools/ignored.yy", files)
        self.assertNotIn("docs/ignored.png", files)


if __name__ == "__main__":
    unittest.main()
