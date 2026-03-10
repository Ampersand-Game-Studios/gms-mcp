#!/usr/bin/env python3
"""Tests for scripts/generate_quality_reports.py."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_cleanup_coverage_data_removes_root_and_gamemaker_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gamemaker = root / "gamemaker"
            gamemaker.mkdir()
            root_file = root / ".coverage.123"
            gm_file = gamemaker / ".coverage.456"
            root_file.write_text("root", encoding="utf-8")
            gm_file.write_text("gm", encoding="utf-8")

            quality_reports.cleanup_coverage_data(
                {
                    "root": root,
                    "gamemaker_dir": gamemaker,
                }
            )

            self.assertFalse(root_file.exists())
            self.assertFalse(gm_file.exists())

    def test_has_parallel_coverage_data_detects_parallel_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gamemaker = root / "gamemaker"
            gamemaker.mkdir()
            (root / ".coverage").write_text("main", encoding="utf-8")
            self.assertFalse(quality_reports.has_parallel_coverage_data({"root": root, "gamemaker_dir": gamemaker}))

            (gamemaker / ".coverage.worker").write_text("child", encoding="utf-8")
            self.assertTrue(quality_reports.has_parallel_coverage_data({"root": root, "gamemaker_dir": gamemaker}))

    @patch("scripts.generate_quality_reports.write_coverage_xml", return_value=0)
    @patch("scripts.generate_quality_reports.run_command")
    def test_run_quality_suite_uses_cov_config_and_subprocess_coverage_env(self, mock_run_command, mock_write_coverage):
        mock_run_command.return_value = subprocess.CompletedProcess(args=["pytest"], returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text("[tool.coverage.run]\npatch = ['subprocess']\n", encoding="utf-8")
            tests_dir = root / "cli" / "tests" / "python"
            tests_dir.mkdir(parents=True)
            final_verification = tests_dir / "test_final_verification.py"
            final_verification.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")

            paths = {
                "root": root,
                "output_dir": root / "build" / "reports",
                "junit_xml": root / "build" / "reports" / "pytest_results.xml",
                "coverage_xml": root / "build" / "reports" / "coverage.xml",
                "cov_config": root / "pyproject.toml",
                "tests_dir": tests_dir,
                "gamemaker_dir": root / "gamemaker",
            }

            exit_code = quality_reports.run_quality_suite(paths, skip_final_verification=False)

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_run_command.call_count, 2)

        pytest_cmd = mock_run_command.call_args_list[0].args[0]
        self.assertIn("--cov-config", pytest_cmd)
        self.assertIn(str(root / "pyproject.toml"), pytest_cmd)
        self.assertIn("--cov-report=", pytest_cmd)

        pytest_env = mock_run_command.call_args_list[0].args[2]
        self.assertEqual(pytest_env["COVERAGE_FILE"], str(root / ".coverage"))
        mock_write_coverage.assert_called_once()

    @patch("scripts.generate_quality_reports.run_command")
    def test_write_coverage_xml_skips_combine_when_main_data_exists(self, mock_run_command):
        mock_run_command.return_value = subprocess.CompletedProcess(args=["coverage"], returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gamemaker = root / "gamemaker"
            gamemaker.mkdir()
            (root / "pyproject.toml").write_text("[tool.coverage.run]\nparallel = true\n", encoding="utf-8")
            (root / ".coverage").write_text("main", encoding="utf-8")
            paths = {
                "root": root,
                "gamemaker_dir": gamemaker,
                "cov_config": root / "pyproject.toml",
                "coverage_xml": root / "coverage.xml",
            }

            exit_code = quality_reports.write_coverage_xml(paths, {})

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_run_command.call_count, 1)
        xml_cmd = mock_run_command.call_args.args[0]
        self.assertIn("xml", xml_cmd)

    @patch("scripts.generate_quality_reports.run_command")
    def test_write_coverage_xml_combines_parallel_files(self, mock_run_command):
        mock_run_command.return_value = subprocess.CompletedProcess(args=["coverage"], returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gamemaker = root / "gamemaker"
            gamemaker.mkdir()
            (root / "pyproject.toml").write_text("[tool.coverage.run]\nparallel = true\n", encoding="utf-8")
            (root / ".coverage.worker").write_text("child", encoding="utf-8")
            (root / ".coverage").write_text("main", encoding="utf-8")
            paths = {
                "root": root,
                "gamemaker_dir": gamemaker,
                "cov_config": root / "pyproject.toml",
                "coverage_xml": root / "coverage.xml",
            }

            exit_code = quality_reports.write_coverage_xml(paths, {})

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_run_command.call_count, 2)
        combine_cmd = mock_run_command.call_args_list[0].args[0]
        self.assertIn("combine", combine_cmd)


if __name__ == "__main__":
    unittest.main()
