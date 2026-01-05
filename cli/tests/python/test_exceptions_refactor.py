#!/usr/bin/env python3
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_helpers.exceptions import (
    GMSError, 
    ProjectNotFoundError, 
    AssetExistsError,
    AssetNotFoundError,
    InvalidAssetTypeError,
    JSONParseError,
    RuntimeNotFoundError,
    LicenseNotFoundError,
    ValidationError
)
from gms_helpers.utils import find_yyp, validate_working_directory
from gms_mcp.gamemaker_mcp_server import _capture_output

class TestGMSExceptions(unittest.TestCase):
    def test_exception_hierarchy(self):
        """Test that all custom exceptions inherit from GMSError."""
        self.assertTrue(issubclass(ProjectNotFoundError, GMSError))
        self.assertTrue(issubclass(AssetExistsError, GMSError))
        self.assertTrue(issubclass(AssetNotFoundError, GMSError))
        self.assertTrue(issubclass(InvalidAssetTypeError, GMSError))
        self.assertTrue(issubclass(JSONParseError, GMSError))
        self.assertTrue(issubclass(RuntimeNotFoundError, GMSError))
        self.assertTrue(issubclass(LicenseNotFoundError, GMSError))
        self.assertTrue(issubclass(ValidationError, GMSError))

    def test_exception_properties(self):
        """Test that exceptions have correct exit_code and message."""
        e = ProjectNotFoundError("Project not found")
        self.assertEqual(e.exit_code, 2)
        self.assertEqual(e.json_rpc_code, -32001)
        self.assertEqual(str(e), "Project not found")

class TestCaptureOutputWithGMSError(unittest.TestCase):
    def test_capture_gms_error(self):
        """Test that _capture_output correctly catches GMSError and returns exit_code."""
        def _fn():
            raise AssetExistsError("Asset already exists")
        
        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        
        self.assertFalse(ok)
        self.assertEqual(exit_code, 3)
        self.assertIn("AssetExistsError", error_text)
        self.assertIn("Asset already exists", error_text)

    def test_capture_normal_exception(self):
        """Test that _capture_output still handles normal exceptions."""
        def _fn():
            raise ValueError("Something went wrong")
        
        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        
        self.assertFalse(ok)
        self.assertIsNone(exit_code) # exit_code is only set for GMSError or SystemExit
        self.assertIn("ValueError", error_text)

class TestUtilsRefactor(unittest.TestCase):
    @patch("pathlib.Path.glob")
    def test_find_yyp_raises_exception(self, mock_glob):
        """Test that find_yyp now raises ProjectNotFoundError instead of sys.exit."""
        mock_glob.return_value = []
        
        with self.assertRaises(ProjectNotFoundError):
            find_yyp(Path("/fake/path"))

    @patch("os.listdir")
    def test_validate_working_directory_raises_exception(self, mock_listdir):
        """Test that validate_working_directory now raises ProjectNotFoundError."""
        mock_listdir.return_value = ["not_a_project.txt"]
        
        with self.assertRaises(ProjectNotFoundError):
            validate_working_directory()

if __name__ == "__main__":
    unittest.main()
