#!/usr/bin/env python3
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_helpers.results import OperationResult, AssetResult, MaintenanceResult, RunnerResult
from gms_helpers.workflow import duplicate_asset, rename_asset, delete_asset, lint_project
from gms_mcp.gamemaker_mcp_server import _capture_output

class TestGMSResults(unittest.TestCase):
    def test_operation_result_to_dict(self):
        """Test conversion of OperationResult to dictionary."""
        res = OperationResult(success=True, message="Success", warnings=["Warn 1"])
        d = res.to_dict()
        self.assertEqual(d["success"], True)
        self.assertEqual(d["message"], "Success")
        self.assertEqual(d["warnings"], ["Warn 1"])

    def test_asset_result_inheritance(self):
        """Test AssetResult inherits from OperationResult and has extra fields."""
        res = AssetResult(
            success=True, 
            message="Created", 
            asset_name="spr_test",
            asset_type="sprite",
            asset_path="sprites/spr_test/spr_test.yy"
        )
        self.assertTrue(isinstance(res, OperationResult))
        self.assertEqual(res.asset_name, "spr_test")
        self.assertEqual(res.asset_type, "sprite")

class TestCaptureWithTypedResults(unittest.TestCase):
    def test_capture_operation_result_success(self):
        """Test _capture_output handles OperationResult(success=True)."""
        def _fn():
            return OperationResult(success=True, message="Done")
        
        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        self.assertTrue(ok)
        self.assertEqual(result.message, "Done")

    def test_capture_operation_result_failure(self):
        """Test _capture_output handles OperationResult(success=False)."""
        def _fn():
            return OperationResult(success=False, message="Failed")
        
        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        self.assertFalse(ok)
        self.assertEqual(result.message, "Failed")

class TestWorkflowResults(unittest.TestCase):
    @patch("gms_helpers.workflow._asset_from_path")
    @patch("shutil.copytree")
    @patch("pathlib.Path.rename")
    @patch("gms_helpers.workflow.load_json_loose")
    @patch("gms_helpers.workflow.save_pretty_json_gm")
    @patch("gms_helpers.workflow.find_yyp")
    @patch("gms_helpers.workflow.insert_into_resources")
    def test_duplicate_asset_returns_asset_result(self, *args):
        # Set environment to skip maintenance in workflow functions
        os.environ['PYTEST_CURRENT_TEST'] = '1'
        
        # Mock setup
        from gms_helpers.workflow import _asset_from_path
        _asset_from_path.return_value = ("script", Path("/fake/src"), "old_script")
        
        from gms_helpers.workflow import load_json_loose
        load_json_loose.return_value = {"name": "old_script"}
        
        from gms_helpers.workflow import find_yyp
        find_yyp.return_value = Path("/fake/project.yyp")
        
        res = duplicate_asset(Path("/fake"), "scripts/old_script.yy", "new_script")
        
        self.assertTrue(isinstance(res, AssetResult))
        self.assertTrue(res.success)
        self.assertEqual(res.asset_name, "new_script")
        self.assertEqual(res.asset_type, "script")

if __name__ == "__main__":
    unittest.main()
