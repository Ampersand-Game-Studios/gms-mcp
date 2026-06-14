#!/usr/bin/env python3
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_helpers.results import (
    AssetResult,
    ErrorInfo,
    MaintenanceResult,
    OperationResult,
    RunnerResult,
    legacy_bool_result,
    normalize_result,
)
from gms_helpers.workflow import duplicate_asset, rename_asset, delete_asset, lint_project
from gms_mcp.server.direct import _capture_output


class TestGMSResults(unittest.TestCase):
    def test_operation_result_to_dict(self):
        """Test conversion of OperationResult to dictionary."""
        res = OperationResult(success=True, message="Success", warnings=["Warn 1"])
        d = res.to_dict()
        self.assertEqual(d["success"], True)
        self.assertEqual(d["ok"], True)
        self.assertEqual(d["message"], "Success")
        self.assertEqual(d["warnings"], ["Warn 1"])

    def test_operation_result_failure_to_dict_has_structured_error(self):
        """Failed operation results expose a stable error object."""
        res = OperationResult.fail(
            "Nope",
            code="nope_failed",
            error_type="validation_error",
            details={"field": "name"},
        )
        d = res.to_dict()

        self.assertFalse(res)
        self.assertFalse(d["success"])
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"]["code"], "nope_failed")
        self.assertEqual(d["error"]["type"], "validation_error")
        self.assertEqual(d["error"]["details"], {"field": "name"})

    def test_error_info_to_dict(self):
        error = ErrorInfo(code="bad", message="Bad input", type="validation_error", details={"x": 1})
        self.assertEqual(
            error.to_dict(),
            {"code": "bad", "message": "Bad input", "type": "validation_error", "details": {"x": 1}},
        )

    def test_legacy_bool_result_wraps_old_helpers(self):
        ok = legacy_bool_result(True, operation="legacy op").to_dict()
        fail = legacy_bool_result(False, operation="legacy op").to_dict()

        self.assertTrue(ok["ok"])
        self.assertFalse(fail["ok"])
        self.assertEqual(fail["error"]["type"], "legacy_boolean_result")

    def test_normalize_result_wraps_lists_as_structured_data(self):
        result = normalize_result([{"name": "r_test"}], operation="Room list", data_key="rooms")

        payload = result.to_dict()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["rooms"], [{"name": "r_test"}])
        self.assertEqual(payload["data"]["count"], 1)

    def test_normalize_result_wraps_legacy_error_dict(self):
        result = normalize_result({"error": "bad input", "items": []}, operation="Legacy helper")

        payload = result.to_dict()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["message"], "bad input")
        self.assertEqual(payload["error"]["code"], "legacy_dict_error")
        self.assertEqual(payload["error"]["type"], "legacy_dict_result")

    def test_asset_result_inheritance(self):
        """Test AssetResult inherits from OperationResult and has extra fields."""
        res = AssetResult(
            success=True,
            message="Created",
            asset_name="spr_test",
            asset_type="sprite",
            asset_path="sprites/spr_test/spr_test.yy",
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

    def test_capture_legacy_error_dict_without_ok_is_failure(self):
        """Test _capture_output treats legacy {"error": ...} dicts as failures."""

        def _fn():
            return {"error": "bad", "items": []}

        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        self.assertFalse(ok)
        self.assertEqual(result["error"], "bad")


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
        os.environ["PYTEST_CURRENT_TEST"] = "1"

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
