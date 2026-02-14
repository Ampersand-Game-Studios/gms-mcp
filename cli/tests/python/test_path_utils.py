#!/usr/bin/env python3
"""Tests for maintenance path normalization utilities."""

import unittest
from unittest.mock import patch

from gms_helpers.maintenance.path_utils import normalize_path


class TestPathUtils(unittest.TestCase):
    """Tests for path normalization behavior."""

    def test_normalize_path_lowercases_on_windows(self):
        """Windows paths should be lowercased for case-insensitive matching."""
        with patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Windows"):
            self.assertEqual(normalize_path("Test\\Path/FILE.GM"), "test/path/file.gm")

    def test_normalize_path_preserves_case_on_macos_case_sensitive(self):
        """Case-sensitive APFS should preserve path case."""
        with (
            patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Darwin"),
            patch("gms_helpers.maintenance.path_utils._is_macos_case_sensitive", return_value=True),
        ):
            self.assertEqual(normalize_path("Test/Path/FILE.GM"), "Test/Path/FILE.GM")

    def test_normalize_path_lowercases_on_macos_case_insensitive(self):
        """Case-insensitive macOS volumes should lower-case paths."""
        with (
            patch("gms_helpers.maintenance.path_utils.platform.system", return_value="Darwin"),
            patch("gms_helpers.maintenance.path_utils._is_macos_case_sensitive", return_value=False),
        ):
            self.assertEqual(normalize_path("Test/Path/FILE.GM"), "test/path/file.gm")


if __name__ == "__main__":
    unittest.main()
