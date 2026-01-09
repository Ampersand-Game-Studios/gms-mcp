#!/usr/bin/env python3
"""
Tests for the post_tweet module.
Run with: python -m pytest .github/scripts/test_post_tweet.py -v
Or standalone: python .github/scripts/test_post_tweet.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent directory to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent))

import post_tweet


class TestHashFunction(unittest.TestCase):
    def test_compute_hash_consistency(self):
        """Same content should produce same hash."""
        content = "Hello, world!"
        hash1 = post_tweet.compute_hash(content)
        hash2 = post_tweet.compute_hash(content)
        self.assertEqual(hash1, hash2)

    def test_compute_hash_normalization(self):
        """Hash should be case-insensitive and trim whitespace."""
        hash1 = post_tweet.compute_hash("Hello World")
        hash2 = post_tweet.compute_hash("  hello world  ")
        hash3 = post_tweet.compute_hash("HELLO WORLD")
        self.assertEqual(hash1, hash2)
        self.assertEqual(hash2, hash3)

    def test_compute_hash_different_content(self):
        """Different content should produce different hashes."""
        hash1 = post_tweet.compute_hash("Hello")
        hash2 = post_tweet.compute_hash("Goodbye")
        self.assertNotEqual(hash1, hash2)

    def test_compute_hash_length(self):
        """Hash should be truncated to 16 characters."""
        hash1 = post_tweet.compute_hash("Test content")
        self.assertEqual(len(hash1), 16)


class TestHistoryManagement(unittest.TestCase):
    def setUp(self):
        """Create a temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_history_file = post_tweet.HISTORY_FILE
        post_tweet.HISTORY_FILE = Path(self.temp_dir) / "tweet_history.json"

    def tearDown(self):
        """Restore original file path."""
        post_tweet.HISTORY_FILE = self.original_history_file

    def test_load_history_no_file(self):
        """Should return empty history if file doesn't exist."""
        history = post_tweet.load_history()
        self.assertEqual(history, {"posted": []})

    def test_load_history_valid_file(self):
        """Should load valid JSON history."""
        test_history = {"posted": [{"hash": "abc123", "status": "posted"}]}
        with open(post_tweet.HISTORY_FILE, "w") as f:
            json.dump(test_history, f)

        history = post_tweet.load_history()
        self.assertEqual(history, test_history)

    def test_load_history_invalid_json(self):
        """Should return empty history if JSON is invalid."""
        with open(post_tweet.HISTORY_FILE, "w") as f:
            f.write("not valid json")

        history = post_tweet.load_history()
        self.assertEqual(history, {"posted": []})

    def test_save_history(self):
        """Should save history to file."""
        test_history = {"posted": [{"hash": "abc123"}]}
        post_tweet.save_history(test_history)

        with open(post_tweet.HISTORY_FILE, "r") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, test_history)

    def test_save_history_trims_old_entries(self):
        """Should trim history to MAX_HISTORY_ENTRIES."""
        old_max = post_tweet.MAX_HISTORY_ENTRIES
        post_tweet.MAX_HISTORY_ENTRIES = 5

        test_history = {"posted": [{"hash": f"hash{i}"} for i in range(10)]}
        post_tweet.save_history(test_history)

        with open(post_tweet.HISTORY_FILE, "r") as f:
            loaded = json.load(f)

        self.assertEqual(len(loaded["posted"]), 5)
        # Should keep the last 5 entries
        self.assertEqual(loaded["posted"][0]["hash"], "hash5")

        post_tweet.MAX_HISTORY_ENTRIES = old_max

    def test_is_duplicate_in_history(self):
        """Should detect duplicates correctly."""
        history = {"posted": [{"hash": "abc123"}, {"hash": "def456"}]}

        self.assertTrue(post_tweet.is_duplicate_in_history(history, "abc123"))
        self.assertTrue(post_tweet.is_duplicate_in_history(history, "def456"))
        self.assertFalse(post_tweet.is_duplicate_in_history(history, "xyz789"))

    def test_add_to_history(self):
        """Should add entry with correct fields."""
        history = {"posted": []}
        post_tweet.add_to_history(history, "abc123", "Test tweet content here", "posted", "12345")

        self.assertEqual(len(history["posted"]), 1)
        entry = history["posted"][0]
        self.assertEqual(entry["hash"], "abc123")
        self.assertEqual(entry["status"], "posted")
        self.assertEqual(entry["tweet_id"], "12345")
        self.assertIn("timestamp", entry)
        self.assertIn("preview", entry)

    def test_add_to_history_truncates_preview(self):
        """Should truncate long previews."""
        history = {"posted": []}
        long_content = "A" * 100
        post_tweet.add_to_history(history, "abc123", long_content, "posted")

        entry = history["posted"][0]
        self.assertTrue(entry["preview"].endswith("..."))
        self.assertLessEqual(len(entry["preview"]), 53)  # 50 + "..."


class TestTweetFileOperations(unittest.TestCase):
    def setUp(self):
        """Create a temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_tweet_file = post_tweet.TWEET_FILE
        post_tweet.TWEET_FILE = Path(self.temp_dir) / "next_tweet.txt"

    def tearDown(self):
        """Restore original file path."""
        post_tweet.TWEET_FILE = self.original_tweet_file

    def test_clear_tweet_file(self):
        """Should clear tweet file with placeholder."""
        # Create a tweet file with content
        with open(post_tweet.TWEET_FILE, "w") as f:
            f.write("Some tweet content")

        post_tweet.clear_tweet_file()

        content = post_tweet.TWEET_FILE.read_text()
        self.assertIn("No tweet pending", content)


class TestMainFunction(unittest.TestCase):
    def setUp(self):
        """Create a temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_tweet_file = post_tweet.TWEET_FILE
        self.original_history_file = post_tweet.HISTORY_FILE
        post_tweet.TWEET_FILE = Path(self.temp_dir) / "next_tweet.txt"
        post_tweet.HISTORY_FILE = Path(self.temp_dir) / "tweet_history.json"

    def tearDown(self):
        """Restore original file paths."""
        post_tweet.TWEET_FILE = self.original_tweet_file
        post_tweet.HISTORY_FILE = self.original_history_file

    def test_main_no_tweet_file(self):
        """Should exit 0 if no tweet file exists."""
        result = post_tweet.main()
        self.assertEqual(result, 0)

    def test_main_empty_tweet_file(self):
        """Should exit 0 if tweet file is empty."""
        post_tweet.TWEET_FILE.write_text("")
        result = post_tweet.main()
        self.assertEqual(result, 0)

    def test_main_placeholder_tweet_file(self):
        """Should exit 0 if tweet file contains placeholder."""
        post_tweet.TWEET_FILE.write_text("(No tweet pending - test)")
        result = post_tweet.main()
        self.assertEqual(result, 0)

    def test_main_duplicate_detection(self):
        """Should detect and handle duplicates."""
        tweet_content = "Test tweet content"
        tweet_hash = post_tweet.compute_hash(tweet_content)

        # Create tweet file
        post_tweet.TWEET_FILE.write_text(tweet_content)

        # Create history with the same hash
        history = {"posted": [{"hash": tweet_hash, "status": "posted"}]}
        with open(post_tweet.HISTORY_FILE, "w") as f:
            json.dump(history, f)

        result = post_tweet.main()
        self.assertEqual(result, 0)

        # Tweet file should be cleared
        content = post_tweet.TWEET_FILE.read_text()
        self.assertIn("No tweet pending", content)


def run_tests():
    """Run all tests and print summary."""
    print("=" * 60)
    print("Running post_tweet.py tests")
    print("=" * 60)

    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestHashFunction))
    suite.addTests(loader.loadTestsFromTestCase(TestHistoryManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestTweetFileOperations))
    suite.addTests(loader.loadTestsFromTestCase(TestMainFunction))

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("ALL TESTS PASSED!")
        return 0
    else:
        print(f"FAILURES: {len(result.failures)}, ERRORS: {len(result.errors)}")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
