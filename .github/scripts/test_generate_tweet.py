#!/usr/bin/env python3
"""
Tests for the tweet generation module.
Run with: python .github/scripts/test_generate_tweet.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

import generate_tweet
import tweet_context


class TestTopicSelection(unittest.TestCase):
    def test_select_uncovered_topic(self):
        """Should select topic that has never been covered."""
        coverage = {
            "code_intelligence": "2026-01-09T08:00:00Z",
            "asset_creation": "2026-01-08T14:00:00Z",
            "maintenance": None,  # Never covered
            "runtime_build": "2026-01-07T08:00:00Z",
        }
        topic = tweet_context.select_topic(coverage)
        self.assertEqual(topic, "maintenance")

    def test_select_oldest_topic(self):
        """Should select least recently covered topic when all are covered."""
        coverage = {
            "code_intelligence": "2026-01-09T08:00:00Z",
            "asset_creation": "2026-01-08T14:00:00Z",
            "maintenance": "2026-01-07T08:00:00Z",  # Oldest
        }
        topic = tweet_context.select_topic(coverage)
        self.assertEqual(topic, "maintenance")

    def test_select_with_all_none(self):
        """Should select first topic when none are covered."""
        coverage = {
            "code_intelligence": None,
            "asset_creation": None,
            "maintenance": None,
        }
        topic = tweet_context.select_topic(coverage)
        # Should return one of them (first alphabetically or by dict order)
        self.assertIn(topic, coverage.keys())


class TestTweetValidation(unittest.TestCase):
    def test_valid_tweet(self):
        """Should accept valid tweet."""
        history = {"posted": []}
        valid, reason = generate_tweet.validate_tweet(
            "Check out gm_find_references - trace every usage of a symbol across your project. #gamedev",
            history
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "valid")

    def test_too_long(self):
        """Should reject tweet over 280 chars."""
        history = {"posted": []}
        long_tweet = "x" * 300
        valid, reason = generate_tweet.validate_tweet(long_tweet, history)
        self.assertFalse(valid)
        self.assertIn("too_long", reason)

    def test_too_short(self):
        """Should reject tweet under 50 chars."""
        history = {"posted": []}
        valid, reason = generate_tweet.validate_tweet("Too short", history)
        self.assertFalse(valid)
        self.assertIn("too_short", reason)

    def test_duplicate(self):
        """Should reject duplicate tweet."""
        tweet = "This is a test tweet about gms-mcp features that is long enough to pass validation"
        tweet_hash = generate_tweet.compute_hash(tweet)
        history = {"posted": [{"hash": tweet_hash}]}
        valid, reason = generate_tweet.validate_tweet(tweet, history)
        self.assertFalse(valid)
        self.assertEqual(reason, "duplicate")

    def test_too_many_hashtags(self):
        """Should reject tweet with more than 2 hashtags."""
        history = {"posted": []}
        tweet = "Check this GameMaker workflow update today #gamedev #GameMaker #indiedev"
        valid, reason = generate_tweet.validate_tweet(tweet, history)
        self.assertFalse(valid)
        self.assertIn("too_many_hashtags", reason)

    def test_zero_hashtags_allowed(self):
        """Should accept tweet with zero hashtags."""
        history = {"posted": []}
        tweet = "gm_find_references maps call sites across your project so refactors are safer and faster for teams"
        valid, reason = generate_tweet.validate_tweet(tweet, history)
        self.assertTrue(valid)
        self.assertEqual(reason, "valid")

    def test_corporate_speak(self):
        """Should reject corporate speak patterns."""
        history = {"posted": []}

        bad_tweets = [
            "We are pleased to announce the new feature for GameMaker developers",
            "Excited to announce our latest update to gms-mcp tooling suite",
            "Leverage AI to synergize your GameMaker workflow today",
        ]

        for tweet in bad_tweets:
            # Pad to minimum length if needed
            if len(tweet) < 50:
                tweet = tweet + " " * (50 - len(tweet))
            valid, reason = generate_tweet.validate_tweet(tweet, history)
            self.assertFalse(valid, f"Should reject: {tweet[:50]}...")
            self.assertIn("bad_pattern", reason)


class TestHashComputation(unittest.TestCase):
    def test_hash_consistency(self):
        """Same content should produce same hash."""
        content = "Test tweet content"
        hash1 = generate_tweet.compute_hash(content)
        hash2 = generate_tweet.compute_hash(content)
        self.assertEqual(hash1, hash2)

    def test_hash_normalization(self):
        """Hash should be case-insensitive and trim whitespace."""
        hash1 = generate_tweet.compute_hash("Hello World")
        hash2 = generate_tweet.compute_hash("  hello world  ")
        hash3 = generate_tweet.compute_hash("HELLO WORLD")
        self.assertEqual(hash1, hash2)
        self.assertEqual(hash2, hash3)

    def test_hash_length(self):
        """Hash should be 16 characters."""
        hash1 = generate_tweet.compute_hash("Test")
        self.assertEqual(len(hash1), 16)


class TestContextBuilding(unittest.TestCase):
    def test_context_contains_topic(self):
        """Context should mention the target topic."""
        context = tweet_context.build_context_for_claude(
            topic="code_intelligence",
            tweet_format="problem_solution",
            selected_angle="Test angle",
            recent_tweets=[],
            changelog_entries=[]
        )
        self.assertIn("Code Intelligence", context)

    def test_context_contains_tools(self):
        """Context should list tools for the topic."""
        context = tweet_context.build_context_for_claude(
            topic="code_intelligence",
            tweet_format="problem_solution",
            selected_angle="Test angle",
            recent_tweets=[],
            changelog_entries=[]
        )
        self.assertIn("gm_build_index", context)

    def test_context_includes_recent_tweets(self):
        """Context should include recent tweet previews."""
        recent = [{"preview": "Previous tweet about testing"}]
        context = tweet_context.build_context_for_claude(
            topic="code_intelligence",
            tweet_format="problem_solution",
            selected_angle="Test angle",
            recent_tweets=recent,
            changelog_entries=[]
        )
        self.assertIn("Previous tweet", context)

    def test_context_includes_opening_pattern(self):
        """Context should include suggested opening pattern."""
        context = tweet_context.build_context_for_claude(
            topic="code_intelligence",
            tweet_format="problem_solution",
            selected_angle="Test angle",
            recent_tweets=[],
            changelog_entries=[],
            suggested_opening="discovery"
        )
        self.assertIn("SUGGESTED OPENING STYLE: discovery", context)
        self.assertIn("TIL", context)  # Example text for discovery pattern

    def test_context_uses_freeform_hashtag_strategy(self):
        """Context should guide freeform hashtags, not fixed options."""
        context = tweet_context.build_context_for_claude(
            topic="code_intelligence",
            tweet_format="problem_solution",
            selected_angle="Test angle",
            recent_tweets=[],
            changelog_entries=[]
        )
        self.assertIn("HASHTAG STRATEGY (freeform)", context)
        self.assertNotIn("HASHTAG OPTIONS (pick 1-2)", context)


class TestHistoryManagement(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_history_file = generate_tweet.HISTORY_FILE
        generate_tweet.HISTORY_FILE = Path(self.temp_dir) / "history.json"

    def tearDown(self):
        generate_tweet.HISTORY_FILE = self.original_history_file

    def test_load_empty_history(self):
        """Should return default structure when no file exists."""
        history = generate_tweet.load_history()
        self.assertIn("posted", history)
        self.assertIn("topic_coverage", history)
        self.assertIn("generation_stats", history)

    def test_save_and_load_history(self):
        """Should persist history correctly."""
        history = {
            "posted": [{"hash": "abc123", "status": "posted"}],
            "topic_coverage": {"test": "2026-01-01T00:00:00Z"},
            "generation_stats": {"total_generated": 1}
        }
        generate_tweet.save_history(history)

        loaded = generate_tweet.load_history()
        self.assertEqual(loaded["posted"][0]["hash"], "abc123")
        self.assertEqual(loaded["topic_coverage"]["test"], "2026-01-01T00:00:00Z")


class TestChangelogParsing(unittest.TestCase):
    def test_parse_returns_list(self):
        """Should return a list of changelog entries."""
        entries = tweet_context.parse_changelog_released()
        self.assertIsInstance(entries, list)

    def test_excludes_unreleased(self):
        """Should not include unreleased section."""
        entries = tweet_context.parse_changelog_released()
        for entry in entries:
            self.assertNotEqual(entry.get("version", "").lower(), "unreleased")


class TestTimeSlot(unittest.TestCase):
    def test_returns_valid_slot(self):
        """Should return morning, afternoon, or evening."""
        slot = tweet_context.get_time_slot()
        self.assertIn(slot, ["morning", "afternoon", "evening"])


class TestSemanticDuplicateDetection(unittest.TestCase):
    def test_word_overlap_identical(self):
        """Identical texts should have 100% overlap."""
        overlap = generate_tweet.compute_word_overlap(
            "This is a test tweet about GameMaker",
            "This is a test tweet about GameMaker"
        )
        self.assertEqual(overlap, 1.0)

    def test_word_overlap_different(self):
        """Completely different texts should have low overlap."""
        overlap = generate_tweet.compute_word_overlap(
            "GameMaker sprites objects rooms",
            "Python functions classes modules"
        )
        self.assertLess(overlap, 0.3)

    def test_word_overlap_partial(self):
        """Partially similar texts should have medium overlap."""
        overlap = generate_tweet.compute_word_overlap(
            "gm_find_references traces function calls across your project",
            "gm_find_definition locates function definitions across your codebase"
        )
        self.assertGreater(overlap, 0.3)
        self.assertLess(overlap, 0.8)

    def test_word_overlap_ignores_hashtags(self):
        """Hashtags should not count toward overlap."""
        overlap = generate_tweet.compute_word_overlap(
            "Great feature #gamedev #GameMaker",
            "Great feature #indiedev #coding"
        )
        # Only "great" and "feature" should count
        self.assertGreater(overlap, 0.5)

    def test_semantic_duplicate_detected(self):
        """Should detect semantic duplicates with >60% overlap."""
        history = {
            "posted": [
                {"content": "gm_find_references traces every usage of a symbol across your GameMaker project"}
            ]
        }
        is_dup, reason = generate_tweet.is_semantic_duplicate(
            "gm_find_references traces symbol usage across your entire GameMaker project",
            history,
            threshold=0.6
        )
        self.assertTrue(is_dup)
        self.assertIn("semantic_duplicate", reason)

    def test_semantic_duplicate_not_detected(self):
        """Should not flag genuinely different tweets."""
        history = {
            "posted": [
                {"content": "gm_find_references traces function calls"}
            ]
        }
        is_dup, reason = generate_tweet.is_semantic_duplicate(
            "TCP bridge lets your AI see game logs in real-time",
            history,
            threshold=0.6
        )
        self.assertFalse(is_dup)


class TestOpeningPatternSelection(unittest.TestCase):
    def test_select_uncovered_pattern(self):
        """Should select pattern that has never been used."""
        coverage = {
            "statement": "2026-01-09T08:00:00Z",
            "scenario": "2026-01-08T14:00:00Z",
            "discovery": None,  # Never used
            "comparison": "2026-01-07T08:00:00Z",
        }
        pattern = tweet_context.select_opening_pattern(coverage)
        self.assertEqual(pattern, "discovery")

    def test_select_oldest_pattern(self):
        """Should select least recently used pattern when all are used."""
        # Must include ALL patterns or missing ones will be added with None
        coverage = tweet_context.initialize_opening_coverage()
        # Set all to recent except one
        for p in coverage:
            coverage[p] = "2026-01-09T08:00:00Z"
        coverage["discovery"] = "2026-01-07T08:00:00Z"  # Oldest
        pattern = tweet_context.select_opening_pattern(coverage)
        self.assertEqual(pattern, "discovery")

    def test_initialize_opening_coverage(self):
        """Should create coverage dict for all configured patterns."""
        coverage = tweet_context.initialize_opening_coverage()
        self.assertEqual(len(coverage), len(tweet_context.OPENING_PATTERNS))
        self.assertIn("statement", coverage)
        self.assertIn("shortcut", coverage)
        for pattern, timestamp in coverage.items():
            self.assertIsNone(timestamp)

    def test_all_opening_patterns_have_descriptions(self):
        """All patterns should have descriptions in build_context_for_claude."""
        # Build context with each pattern and verify it includes guidance
        for pattern in tweet_context.OPENING_PATTERNS:
            context = tweet_context.build_context_for_claude(
                topic="code_intelligence",
                tweet_format="problem_solution",
                selected_angle="Test angle",
                recent_tweets=[],
                changelog_entries=[],
                suggested_opening=pattern
            )
            self.assertIn(f"SUGGESTED OPENING STYLE: {pattern}", context)


def run_tests():
    """Run all tests and print summary."""
    print("=" * 60)
    print("Running generate_tweet.py tests")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestTopicSelection))
    suite.addTests(loader.loadTestsFromTestCase(TestTweetValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestHashComputation))
    suite.addTests(loader.loadTestsFromTestCase(TestContextBuilding))
    suite.addTests(loader.loadTestsFromTestCase(TestHistoryManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestChangelogParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestTimeSlot))
    suite.addTests(loader.loadTestsFromTestCase(TestSemanticDuplicateDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestOpeningPatternSelection))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("ALL TESTS PASSED!")
        return 0
    else:
        print(f"FAILURES: {len(result.failures)}, ERRORS: {len(result.errors)}")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
