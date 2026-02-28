#!/usr/bin/env python3
"""
Tests for post_evergreen module.
Run with: python -m pytest .github/scripts/test_post_evergreen.py -v
Or standalone: python .github/scripts/test_post_evergreen.py
"""

import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# Add scripts directory to path for local imports.
sys.path.insert(0, str(Path(__file__).parent))

import post_evergreen
import post_tweet


class TestHelpers(unittest.TestCase):
    def test_normalize_slot(self):
        self.assertEqual(post_evergreen.normalize_slot("8"), "08")
        self.assertEqual(post_evergreen.normalize_slot("20"), "20")
        with self.assertRaises(ValueError):
            post_evergreen.normalize_slot("24")

    def test_has_non_evergreen_post_today(self):
        today = datetime(2026, 2, 24, 10, 0, tzinfo=timezone.utc)
        history = {
            "posted": [
                {
                    "timestamp": today.isoformat(),
                    "status": "posted",
                    "generated_by": "manual",
                }
            ]
        }
        self.assertTrue(post_evergreen.has_non_evergreen_post_today(history, today.date()))

        history["posted"][0]["generated_by"] = post_evergreen.EXPERIMENT_GENERATED_BY
        self.assertFalse(post_evergreen.has_non_evergreen_post_today(history, today.date()))

    def test_has_evergreen_post_in_slot_today(self):
        ts = datetime(2026, 2, 24, 14, 5, tzinfo=timezone.utc)
        history = {
            "posted": [
                {
                    "timestamp": ts.isoformat(),
                    "status": "posted",
                    "generated_by": post_evergreen.EXPERIMENT_GENERATED_BY,
                }
            ]
        }
        self.assertTrue(post_evergreen.has_evergreen_post_in_slot_today(history, ts.date(), "14"))
        self.assertFalse(post_evergreen.has_evergreen_post_in_slot_today(history, ts.date(), "20"))

    def test_pick_queue_item_honors_max_uses(self):
        queue = {
            "posts": [
                {
                    "id": "EVG-001",
                    "text": "Evergreen content #gamedev #GameMaker",
                    "active": True,
                    "max_uses": 1,
                    "slots": ["20"],
                }
            ]
        }
        history = {
            "posted": [
                {
                    "format": "EVG-001",
                    "generated_by": post_evergreen.EXPERIMENT_GENERATED_BY,
                    "status": "posted",
                    "timestamp": "2026-02-24T20:00:00+00:00",
                }
            ]
        }
        chosen, reason = post_evergreen.pick_queue_item(queue, "20", history)
        self.assertIsNone(chosen)
        self.assertEqual(reason, "queue_exhausted")


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.queue_file = Path(self.temp_dir) / "queue.json"
        self.history_file = Path(self.temp_dir) / "tweet_history.json"
        self.output_file = Path(self.temp_dir) / "gha_output.txt"

        self.original_history_file = post_tweet.HISTORY_FILE
        post_tweet.HISTORY_FILE = self.history_file

        queue = {
            "version": 1,
            "experiment_id": "test",
            "posts": [
                {
                    "id": "EVG-100",
                    "text": "Test evergreen tweet for queue selection #gamedev #GameMaker",
                    "active": True,
                    "max_uses": 1,
                    "slots": ["20"],
                }
            ],
        }
        with open(self.queue_file, "w", encoding="utf-8") as fh:
            json.dump(queue, fh)

        with open(self.history_file, "w", encoding="utf-8") as fh:
            json.dump({"posted": []}, fh)

    def tearDown(self):
        post_tweet.HISTORY_FILE = self.original_history_file

    def _read_outputs(self):
        if not self.output_file.exists():
            return {}
        data = {}
        for line in self.output_file.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key] = value
        return data

    def test_execute_dry_run_success(self):
        now = datetime(2026, 2, 24, 20, 0, tzinfo=timezone.utc)
        args = Namespace(
            queue_file=str(self.queue_file),
            slot="20",
            now_utc=now.isoformat(),
            dry_run=True,
        )
        env = {
            "GITHUB_OUTPUT": str(self.output_file),
            "X_EVERGREEN_EXPERIMENT_START_UTC": (now - timedelta(days=1)).isoformat(),
            "X_EVERGREEN_EXPERIMENT_END_UTC": (now + timedelta(days=1)).isoformat(),
        }
        with patch.dict(os.environ, env, clear=False):
            result = post_evergreen.execute(args)
        self.assertEqual(result, 0)
        outputs = self._read_outputs()
        self.assertEqual(outputs.get("posted"), "false")
        self.assertEqual(outputs.get("skip_reason"), "dry_run")
        self.assertEqual(outputs.get("queue_id"), "EVG-100")

    def test_execute_collision_skip(self):
        now = datetime(2026, 2, 24, 20, 0, tzinfo=timezone.utc)
        history = {
            "posted": [
                {
                    "status": "posted",
                    "generated_by": "manual",
                    "timestamp": now.isoformat(),
                }
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as fh:
            json.dump(history, fh)

        args = Namespace(
            queue_file=str(self.queue_file),
            slot="20",
            now_utc=now.isoformat(),
            dry_run=True,
        )
        env = {
            "GITHUB_OUTPUT": str(self.output_file),
            "X_EVERGREEN_EXPERIMENT_START_UTC": (now - timedelta(days=1)).isoformat(),
            "X_EVERGREEN_EXPERIMENT_END_UTC": (now + timedelta(days=1)).isoformat(),
        }
        with patch.dict(os.environ, env, clear=False):
            result = post_evergreen.execute(args)
        self.assertEqual(result, 0)
        outputs = self._read_outputs()
        self.assertEqual(outputs.get("skip_reason"), "collision_non_evergreen_today")

    def test_execute_already_posted_slot_skip(self):
        now = datetime(2026, 2, 24, 20, 0, tzinfo=timezone.utc)
        history = {
            "posted": [
                {
                    "status": "posted",
                    "generated_by": post_evergreen.EXPERIMENT_GENERATED_BY,
                    "timestamp": now.isoformat(),
                    "hash": "existing-evergreen-hash",
                }
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as fh:
            json.dump(history, fh)

        args = Namespace(
            queue_file=str(self.queue_file),
            slot="20",
            now_utc=now.isoformat(),
            dry_run=True,
        )
        env = {
            "GITHUB_OUTPUT": str(self.output_file),
            "X_EVERGREEN_EXPERIMENT_START_UTC": (now - timedelta(days=1)).isoformat(),
            "X_EVERGREEN_EXPERIMENT_END_UTC": (now + timedelta(days=1)).isoformat(),
        }
        with patch.dict(os.environ, env, clear=False):
            result = post_evergreen.execute(args)
        self.assertEqual(result, 0)
        outputs = self._read_outputs()
        self.assertEqual(outputs.get("skip_reason"), "already_posted_slot_today")

    def test_execute_outside_window(self):
        now = datetime(2026, 2, 24, 20, 0, tzinfo=timezone.utc)
        args = Namespace(
            queue_file=str(self.queue_file),
            slot="20",
            now_utc=now.isoformat(),
            dry_run=True,
        )
        env = {
            "GITHUB_OUTPUT": str(self.output_file),
            "X_EVERGREEN_EXPERIMENT_START_UTC": (now + timedelta(days=1)).isoformat(),
            "X_EVERGREEN_EXPERIMENT_END_UTC": (now + timedelta(days=2)).isoformat(),
        }
        with patch.dict(os.environ, env, clear=False):
            result = post_evergreen.execute(args)
        self.assertEqual(result, 0)
        outputs = self._read_outputs()
        self.assertEqual(outputs.get("skip_reason"), "outside_window_before_start")


def run_tests() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestHelpers))
    suite.addTests(loader.loadTestsFromTestCase(TestExecute))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
