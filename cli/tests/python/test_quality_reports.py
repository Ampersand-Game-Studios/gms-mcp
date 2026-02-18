#!/usr/bin/env python3
"""Tests for scripts/generate_quality_reports.py."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.generate_quality_reports as quality_reports


class TestQualityReportParsing(unittest.TestCase):
    def test_parse_junit_testsuite_root(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="5" failures="1" errors="0" skipped="1" time="2.5"></testsuite>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            junit_path = Path(temp_dir) / "junit.xml"
            junit_path.write_text(xml, encoding="utf-8")

            parsed = quality_reports.parse_junit(junit_path)

        self.assertEqual(parsed["tests"], 5)
        self.assertEqual(parsed["failures"], 1)
        self.assertEqual(parsed["errors"], 0)
        self.assertEqual(parsed["skipped"], 1)
        self.assertEqual(parsed["passed"], 3)
        self.assertEqual(parsed["time"], "2.500")
        self.assertEqual(parsed["suites"], 1)

    def test_parse_junit_testsuites_root_aggregates_children(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="suite_a" tests="4" failures="1" errors="0" skipped="0" time="1.25"></testsuite>
  <testsuite name="suite_b" tests="6" failures="0" errors="1" skipped="2" time="3.75"></testsuite>
</testsuites>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            junit_path = Path(temp_dir) / "junit.xml"
            junit_path.write_text(xml, encoding="utf-8")

            parsed = quality_reports.parse_junit(junit_path)

        self.assertEqual(parsed["tests"], 10)
        self.assertEqual(parsed["failures"], 1)
        self.assertEqual(parsed["errors"], 1)
        self.assertEqual(parsed["skipped"], 2)
        self.assertEqual(parsed["passed"], 6)
        self.assertEqual(parsed["time"], "5.000")
        self.assertEqual(parsed["suites"], 2)

    def test_main_writes_non_zero_tests_to_summary(self):
        junit_xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="7" failures="0" errors="0" skipped="1" time="4.2"></testsuite>
</testsuites>
"""
        coverage_xml = """<?xml version="1.0" ?>
<coverage line-rate="0.5">
  <packages>
    <package name="pkg">
      <classes>
        <class filename="src/example.py" line-rate="1.0" branch-rate="0.0"></class>
      </classes>
    </package>
  </packages>
</coverage>
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            junit_path = temp_path / "pytest_results.xml"
            coverage_path = temp_path / "coverage.xml"
            output_dir = temp_path / "reports"
            junit_path.write_text(junit_xml, encoding="utf-8")
            coverage_path.write_text(coverage_xml, encoding="utf-8")

            argv_backup = sys.argv[:]
            try:
                sys.argv = [
                    "generate_quality_reports.py",
                    "--skip-test-run",
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--output-dir",
                    str(output_dir),
                    "--junit-xml",
                    str(junit_path),
                    "--coverage-xml",
                    str(coverage_path),
                ]
                exit_code = quality_reports.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(exit_code, 0)
            summary = json.loads((output_dir / "quality_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["tests"]["tests"], 7)
        self.assertEqual(summary["tests"]["passed"], 6)


if __name__ == "__main__":
    unittest.main()
