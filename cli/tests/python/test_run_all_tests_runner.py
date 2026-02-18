#!/usr/bin/env python3
"""Tests for cli/tests/python/run_all_tests.py behavior."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = PROJECT_ROOT / "cli" / "tests" / "python" / "run_all_tests.py"

spec = importlib.util.spec_from_file_location("run_all_tests_module", RUNNER_PATH)
run_all_tests = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(run_all_tests)


class TestRunAllTestsRunner(unittest.TestCase):
    def test_determine_mcp_mode_native(self):
        with patch.object(run_all_tests, "_python_has_module", return_value=True):
            mode = run_all_tests._determine_mcp_test_mode("python3")
        self.assertEqual(mode, "native")

    def test_determine_mcp_mode_uv(self):
        with patch.object(run_all_tests, "_python_has_module", return_value=False), patch(
            "shutil.which", return_value="/usr/bin/uv"
        ):
            mode = run_all_tests._determine_mcp_test_mode("python3")
        self.assertEqual(mode, "uv")

    def test_determine_mcp_mode_skip(self):
        with patch.object(run_all_tests, "_python_has_module", return_value=False), patch(
            "shutil.which", return_value=None
        ):
            mode = run_all_tests._determine_mcp_test_mode("python3")
        self.assertEqual(mode, "skip")

    def test_run_test_file_skips_mcp_when_requested(self):
        status, code = run_all_tests.run_test_file(
            Path("test_mcp_integration_tools.py"),
            mcp_test_mode="skip",
        )
        self.assertEqual(status, "skip")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
