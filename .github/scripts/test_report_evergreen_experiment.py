#!/usr/bin/env python3
"""
Tests for report_evergreen_experiment module.
Run with: python -m pytest .github/scripts/test_report_evergreen_experiment.py -v
Or standalone: python .github/scripts/test_report_evergreen_experiment.py
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import report_evergreen_experiment as report


class TestParsing(unittest.TestCase):
    def test_parse_metric(self):
        self.assertEqual(report.parse_metric("123"), 123)
        self.assertEqual(report.parse_metric("1.2K"), 1200)
        self.assertEqual(report.parse_metric("2M"), 2_000_000)

    def test_extract_metrics_from_html(self):
        html = """
        <i class="fas fa-comment"></i><span><ins></ins> 1</span>
        <i class="fas fa-retweet"></i><span><ins></ins> 2</span>
        <i class="fas fa-heart"></i><span><ins></ins> 3</span>
        <i class="fas fa-chart-simple"></i><span><ins></ins> 40</span>
        <i class="fas fa-bookmark"></i><span><ins></ins> 5</span>
        """
        metrics = report.extract_metrics_from_html(html)
        assert metrics is not None
        self.assertEqual(metrics["replies"], 1)
        self.assertEqual(metrics["retweets"], 2)
        self.assertEqual(metrics["likes"], 3)
        self.assertEqual(metrics["views"], 40)
        self.assertEqual(metrics["engagement"], 6)


class TestEvaluation(unittest.TestCase):
    def test_evaluate_success_pass(self):
        baseline = report.Aggregate(10, 10, 0, 1000, 50, 100.0, 0.05)
        experiment = report.Aggregate(10, 10, 0, 1300, 63, 130.0, 0.04846153846153846)
        result = report.evaluate_success(
            baseline,
            experiment,
            min_views_uplift=0.15,
            max_er_drop=0.10,
        )
        self.assertEqual(result["verdict"], "passed")
        self.assertTrue(result["success"])

    def test_evaluate_success_fail(self):
        baseline = report.Aggregate(10, 10, 0, 1000, 50, 100.0, 0.05)
        experiment = report.Aggregate(10, 10, 0, 900, 30, 90.0, 0.03333333333333333)
        result = report.evaluate_success(
            baseline,
            experiment,
            min_views_uplift=0.15,
            max_er_drop=0.10,
        )
        self.assertEqual(result["verdict"], "failed")
        self.assertFalse(result["success"])


class TestMainFlow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.history_file = Path(self.temp_dir) / "tweet_history.json"
        self.output_json = Path(self.temp_dir) / "report.json"
        self.output_csv = Path(self.temp_dir) / "report.csv"

        start = datetime(2026, 2, 24, 0, 0, tzinfo=timezone.utc)
        self.start = start
        self.end = start + timedelta(days=14)
        baseline_time = start - timedelta(days=3)
        experiment_time = start + timedelta(days=1)

        history = {
            "posted": [
                {
                    "tweet_id": "1001",
                    "timestamp": baseline_time.isoformat(),
                    "status": "posted",
                    "generated_by": "claude-api",
                },
                {
                    "tweet_id": "2001",
                    "timestamp": experiment_time.isoformat(),
                    "status": "posted",
                    "generated_by": "evergreen-experiment",
                },
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as fh:
            json.dump(history, fh)

    def test_main_generates_outputs(self):
        # Baseline: 100 views, 5 engagement. Experiment: 120 views, 6 engagement.
        fake_metrics = {
            "1001": {"views": 100, "likes": 5, "replies": 0, "retweets": 0, "quotes": 0, "bookmarks": 0, "engagement": 5},
            "2001": {"views": 120, "likes": 6, "replies": 0, "retweets": 0, "quotes": 0, "bookmarks": 0, "engagement": 6},
        }

        def fake_fetch(tweet_id):
            return fake_metrics[tweet_id], None

        args = [
            "report_evergreen_experiment.py",
            "--history-file",
            str(self.history_file),
            "--start-utc",
            self.start.isoformat(),
            "--end-utc",
            self.end.isoformat(),
            "--output-json",
            str(self.output_json),
            "--output-csv",
            str(self.output_csv),
            "--now-utc",
            (self.start + timedelta(days=2)).isoformat(),
        ]

        with patch.object(sys, "argv", args), patch.object(report, "fetch_metrics", side_effect=fake_fetch):
            code = report.main()

        self.assertEqual(code, 0)
        self.assertTrue(self.output_json.exists())
        self.assertTrue(self.output_csv.exists())

        with open(self.output_json, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertIn("baseline", payload)
        self.assertIn("experiment", payload)
        self.assertIn("verdict", payload)


def run_tests() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestEvaluation))
    suite.addTests(loader.loadTestsFromTestCase(TestMainFlow))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
