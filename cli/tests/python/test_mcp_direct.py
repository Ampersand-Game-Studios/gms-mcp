#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_mcp.gamemaker_mcp_server import _capture_output


class TestCaptureOutputSystemExit(unittest.TestCase):
    def test_system_exit_nonzero_captured(self):
        def _fn():
            print("hello")
            print("oops", file=sys.stderr)
            raise SystemExit(2)

        ok, out, err, result, error_text = _capture_output(_fn)
        self.assertFalse(ok)
        self.assertIn("hello", out)
        self.assertIn("oops", err)
        self.assertIsNone(result)
        self.assertIsNotNone(error_text)
        self.assertIn("SystemExit: 2", error_text)
        self.assertIn("stdout:", error_text)
        self.assertIn("stderr:", error_text)
        self.assertIn("hello", error_text)
        self.assertIn("oops", error_text)

    def test_system_exit_zero_ok(self):
        def _fn():
            print("done")
            raise SystemExit(0)

        ok, out, err, result, error_text = _capture_output(_fn)
        self.assertTrue(ok)
        self.assertIn("done", out)
        self.assertEqual(err, "")
        self.assertIsNone(error_text)


if __name__ == "__main__":
    unittest.main()
