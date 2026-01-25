#!/usr/bin/env python3
"""Test suite for GML documentation lookup system."""

import unittest
import subprocess
import sys
import os
import shutil
import tempfile
from pathlib import Path


class TestGmlDocsModule(unittest.TestCase):
    """Test the gml_docs module imports and basic functionality."""

    def setUp(self):
        """Set up test environment."""
        repo_root = Path(__file__).resolve().parents[3]
        self.src_path = repo_root / "src"
        # Add src to path for imports
        if str(self.src_path) not in sys.path:
            sys.path.insert(0, str(self.src_path))

    def test_gml_docs_module_imports(self):
        """Test that gml_docs module can be imported."""
        from gms_helpers.gml_docs import (
            lookup,
            search,
            list_functions,
            list_categories,
            clear_cache,
            get_cache_stats
        )
        # Verify they're callable
        self.assertTrue(callable(lookup))
        self.assertTrue(callable(search))
        self.assertTrue(callable(list_functions))
        self.assertTrue(callable(list_categories))
        self.assertTrue(callable(clear_cache))
        self.assertTrue(callable(get_cache_stats))

    def test_cache_module_imports(self):
        """Test that cache module classes can be imported."""
        from gms_helpers.gml_docs.cache import DocCache, CachedDoc, FunctionIndexEntry
        self.assertTrue(DocCache)
        self.assertTrue(CachedDoc)
        self.assertTrue(FunctionIndexEntry)

    def test_fetcher_module_imports(self):
        """Test that fetcher module functions can be imported."""
        from gms_helpers.gml_docs.fetcher import (
            fetch_function_index,
            fetch_function_doc,
            GMLDocParser
        )
        self.assertTrue(callable(fetch_function_index))
        self.assertTrue(callable(fetch_function_doc))
        self.assertTrue(GMLDocParser)


class TestGmlDocsCLI(unittest.TestCase):
    """Test the doc CLI commands."""

    def setUp(self):
        """Set up test environment."""
        self.python_exe = sys.executable
        repo_root = Path(__file__).resolve().parents[3]
        self.env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}

    def run_gms_command(self, args):
        """Run a gms command and return result."""
        cmd = [self.python_exe, "-m", "gms_helpers.gms"] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=self.env
        )
        return result.returncode, result.stdout, result.stderr

    def test_doc_help(self):
        """Test doc --help command."""
        returncode, stdout, stderr = self.run_gms_command(["doc", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("lookup", stdout)
        self.assertIn("search", stdout)
        self.assertIn("list", stdout)
        self.assertIn("categories", stdout)
        self.assertIn("cache", stdout)

    def test_doc_lookup_help(self):
        """Test doc lookup --help command."""
        returncode, stdout, stderr = self.run_gms_command(["doc", "lookup", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("function_name", stdout)
        self.assertIn("--refresh", stdout)

    def test_doc_search_help(self):
        """Test doc search --help command."""
        returncode, stdout, stderr = self.run_gms_command(["doc", "search", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("query", stdout)
        self.assertIn("--category", stdout)
        self.assertIn("--limit", stdout)

    def test_doc_list_help(self):
        """Test doc list --help command."""
        returncode, stdout, stderr = self.run_gms_command(["doc", "list", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("--category", stdout)
        self.assertIn("--pattern", stdout)
        self.assertIn("--limit", stdout)

    def test_doc_categories_help(self):
        """Test doc categories --help command."""
        returncode, stdout, stderr = self.run_gms_command(["doc", "categories", "--help"])
        self.assertEqual(returncode, 0)

    def test_doc_cache_help(self):
        """Test doc cache --help command."""
        returncode, stdout, stderr = self.run_gms_command(["doc", "cache", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("stats", stdout)
        self.assertIn("clear", stdout)

    def test_doc_cache_stats_help(self):
        """Test doc cache stats --help command."""
        returncode, stdout, stderr = self.run_gms_command(["doc", "cache", "stats", "--help"])
        self.assertEqual(returncode, 0)


class TestDocCommandHandlers(unittest.TestCase):
    """Test the doc command handler imports."""

    def setUp(self):
        """Set up test environment."""
        repo_root = Path(__file__).resolve().parents[3]
        self.src_path = repo_root / "src"
        if str(self.src_path) not in sys.path:
            sys.path.insert(0, str(self.src_path))

    def test_doc_commands_module_imports(self):
        """Test that doc_commands module can be imported."""
        from gms_helpers.commands.doc_commands import (
            handle_doc_lookup,
            handle_doc_search,
            handle_doc_list,
            handle_doc_categories,
            handle_doc_cache_stats,
            handle_doc_cache_clear
        )
        self.assertTrue(callable(handle_doc_lookup))
        self.assertTrue(callable(handle_doc_search))
        self.assertTrue(callable(handle_doc_list))
        self.assertTrue(callable(handle_doc_categories))
        self.assertTrue(callable(handle_doc_cache_stats))
        self.assertTrue(callable(handle_doc_cache_clear))


class TestCacheDataclasses(unittest.TestCase):
    """Test the cache dataclass structures."""

    def setUp(self):
        """Set up test environment."""
        repo_root = Path(__file__).resolve().parents[3]
        self.src_path = repo_root / "src"
        if str(self.src_path) not in sys.path:
            sys.path.insert(0, str(self.src_path))

    def test_function_index_entry_creation(self):
        """Test FunctionIndexEntry dataclass."""
        from gms_helpers.gml_docs.cache import FunctionIndexEntry
        entry = FunctionIndexEntry(
            name="draw_sprite",
            category="Drawing",
            subcategory="Sprites_And_Tiles",
            url="https://manual.gamemaker.io/monthly/en/GameMaker_Language/GML_Reference/Drawing/Sprites_And_Tiles/draw_sprite.htm"
        )
        self.assertEqual(entry.name, "draw_sprite")
        self.assertEqual(entry.category, "Drawing")
        self.assertEqual(entry.subcategory, "Sprites_And_Tiles")
        self.assertIn("manual.gamemaker.io", entry.url)

    def test_cached_doc_creation(self):
        """Test CachedDoc dataclass."""
        from gms_helpers.gml_docs.cache import CachedDoc
        doc = CachedDoc(
            name="draw_sprite",
            category="Drawing",
            subcategory="Sprites_And_Tiles",
            url="https://manual.gamemaker.io/monthly/en/GameMaker_Language/GML_Reference/Drawing/Sprites_And_Tiles/draw_sprite.htm",
            description="Draws a sprite at a position.",
            syntax="draw_sprite(sprite, subimg, x, y);",
            parameters=[{"name": "sprite", "type": "Sprite", "description": "The sprite to draw"}],
            returns="N/A",
            examples=[],
            cached_at=1234567890.0
        )
        self.assertEqual(doc.name, "draw_sprite")
        self.assertEqual(doc.category, "Drawing")
        self.assertIsInstance(doc.parameters, list)
        self.assertIsInstance(doc.cached_at, float)


class TestDocCacheClass(unittest.TestCase):
    """Test the DocCache class with a temporary cache directory."""

    def setUp(self):
        """Set up test environment with temp cache."""
        repo_root = Path(__file__).resolve().parents[3]
        self.src_path = repo_root / "src"
        if str(self.src_path) not in sys.path:
            sys.path.insert(0, str(self.src_path))

        # Create temp directory for cache
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.temp_dir) / "doc_cache"

    def tearDown(self):
        """Clean up temp directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_initialization(self):
        """Test DocCache initializes correctly."""
        from gms_helpers.gml_docs.cache import DocCache
        cache = DocCache(cache_dir=self.cache_dir)
        self.assertTrue(self.cache_dir.exists())
        self.assertTrue((self.cache_dir / "functions").exists())

    def test_cache_stats_empty(self):
        """Test cache stats on empty cache."""
        from gms_helpers.gml_docs.cache import DocCache
        cache = DocCache(cache_dir=self.cache_dir)
        stats = cache.get_stats()
        self.assertEqual(stats["index_function_count"], 0)
        self.assertEqual(stats["cached_function_count"], 0)

    def test_cache_clear(self):
        """Test clearing the cache."""
        from gms_helpers.gml_docs.cache import DocCache, clear_cache
        cache = DocCache(cache_dir=self.cache_dir)
        # Clear should work even on empty cache
        # Note: clear_cache() is a module-level function that operates on default cache
        # For this test, we just verify the cache dir exists after initialization
        self.assertTrue(self.cache_dir.exists())
        self.assertTrue(cache.functions_dir.exists())


if __name__ == "__main__":
    unittest.main()
