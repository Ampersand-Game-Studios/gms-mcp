#!/usr/bin/env python3
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_helpers.health import gm_mcp_health
from gms_helpers.results import MaintenanceResult

class TestHealthCheck(unittest.TestCase):
    @patch("gms_helpers.health.GameMakerRunner")
    @patch("gms_helpers.health.resolve_project_directory")
    @patch("gms_helpers.health.find_yyp")
    def test_health_check_success(self, mock_find_yyp, mock_resolve_root, mock_runner_class):
        """Test that health check reports success when all components are found."""
        mock_resolve_root.return_value = Path("/fake/project")
        mock_find_yyp.return_value = Path("/fake/project/test.yyp")
        
        mock_runner = mock_runner_class.return_value
        mock_runner.find_gamemaker_runtime.return_value = Path("/fake/igor.exe")
        mock_runner.runtime_path = Path("/fake/runtime-1.2.3")
        mock_runner.find_license_file.return_value = Path("/fake/license.plist")
        
        # Mock dependencies to all be present using sys.modules
        mock_modules = {
            "mcp": MagicMock(),
            "fastmcp": MagicMock(),
            "colorama": MagicMock(),
            "tqdm": MagicMock()
        }
        with patch.dict("sys.modules", mock_modules):
            result = gm_mcp_health("/fake/project")
            
        self.assertTrue(result.success, f"Health check failed: {result.message}\nDetails: {result.details}")
        self.assertEqual(result.issues_found, 0)
        self.assertIn("checks", result.data)
        checks = {check["id"]: check for check in result.data["checks"]}
        self.assertEqual(checks["project"]["status"], "ok")
        self.assertEqual(checks["project"]["data"]["yyp"], "test.yyp")
        self.assertEqual(checks["runtime"]["status"], "ok")
        self.assertIn("igor", checks["runtime"]["summary"].lower())
        self.assertEqual(checks["license"]["status"], "ok")
        self.assertIn("license.plist", checks["license"]["summary"].lower())
        self.assertEqual(checks["dependencies"]["status"], "ok")

    @patch("gms_helpers.health.GameMakerRunner")
    @patch("gms_helpers.health.resolve_project_directory")
    @patch("gms_helpers.health.find_yyp")
    def test_health_check_failures(self, mock_find_yyp, mock_resolve_root, mock_runner_class):
        """Test that health check reports issues when components are missing."""
        mock_resolve_root.side_effect = Exception("No project")
        
        mock_runner = mock_runner_class.return_value
        mock_runner.find_gamemaker_runtime.return_value = None
        mock_runner.find_license_file.return_value = None
        
        # Mock missing dependency using sys.modules
        # Setting a module to None in sys.modules causes an ImportError on import
        with patch.dict("sys.modules", {"mcp": None}):
            result = gm_mcp_health("/fake/project")
            
        self.assertFalse(result.success)
        self.assertGreater(result.issues_found, 0)
        checks = {check["id"]: check for check in result.data["checks"]}
        self.assertEqual(checks["project"]["status"], "error")
        self.assertIn("Project not found", checks["project"]["summary"])
        self.assertEqual(checks["runtime"]["status"], "error")
        self.assertIn("GameMaker runtime or Igor", checks["runtime"]["summary"])
        self.assertEqual(checks["license"]["status"], "error")
        self.assertIn("GameMaker license file not found", checks["license"]["summary"])
        self.assertEqual(checks["dependencies"]["status"], "error")
        self.assertIn("Missing dependencies: mcp", checks["dependencies"]["summary"])

if __name__ == "__main__":
    unittest.main()
