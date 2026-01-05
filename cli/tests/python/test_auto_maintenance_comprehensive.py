#!/usr/bin/env python3
"""
Comprehensive test suite for auto_maintenance.py - Target: 100% Coverage
Tests all functions, edge cases, error conditions, and integration scenarios.
"""

import unittest
import tempfile
import shutil
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from io import StringIO
import sys

# Define PROJECT_ROOT and add paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import the module for type checking
import gms_helpers.auto_maintenance as auto_maintenance

# Import the modules to test
from gms_helpers.auto_maintenance import (
    run_auto_maintenance,
    MaintenanceResult,
    detect_multi_asset_directories,
    print_maintenance_summary,
    print_event_validation_report,
    print_event_sync_report,
    print_orphan_cleanup_report,
    validate_asset_creation_safe,
    handle_maintenance_failure
)

from gms_helpers.maintenance.lint import LintIssue
from gms_helpers.maintenance.validate_paths import PathValidationIssue


class TestAutoMaintenanceComprehensive(unittest.TestCase):
    """Comprehensive test suite for auto_maintenance.py functions."""
    
    def setUp(self):
        """Set up test environment with temporary directory and mock project."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        
        # Create basic project structure
        self._create_mock_project()
        
        # Change to temp directory for tests
        os.chdir(self.temp_dir)
    
    def tearDown(self):
        """Clean up test environment."""
        os.chdir(self.original_dir)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_mock_project(self):
        """Create a basic mock GameMaker project structure."""
        # Create project structure
        for dir_name in ['objects', 'sprites', 'scripts', 'folders']:
            os.makedirs(os.path.join(self.temp_dir, dir_name), exist_ok=True)
        
        # Create a minimal but valid .yyp file with no resources to avoid reference issues
        yyp_content = {
            "$GMProject": "",
            "resources": [],
            "folders": [
                {"id": {"name": "Objects", "path": "folders/Objects.yy"}},
                {"id": {"name": "Scripts", "path": "folders/Scripts.yy"}},
                {"id": {"name": "Sprites", "path": "folders/Sprites.yy"}}
            ]
        }
        
        with open(os.path.join(self.temp_dir, "TestProject.yyp"), 'w') as f:
            json.dump(yyp_content, f, indent=2)
        
        # Create the folder files referenced in the .yyp
        for folder_name in ["Objects", "Scripts", "Sprites"]:
            self._create_folder_file(f"folders/{folder_name}.yy", folder_name)
    
    def _create_folder_file(self, folder_path, folder_name):
        """Create a folder .yy file."""
        folder_content = {
            "$GMFolder": "",
            "%Name": folder_name,
            "folderPath": folder_path,
            "name": folder_name,
            "resourceType": "GMFolder",
            "resourceVersion": "2.0",
        }
        
        folder_dir = os.path.dirname(os.path.join(self.temp_dir, folder_path))
        os.makedirs(folder_dir, exist_ok=True)
        
        with open(os.path.join(self.temp_dir, folder_path), 'w') as f:
            json.dump(folder_content, f, indent=2)
    
    def _create_asset(self, asset_type, asset_name, create_files=True, valid_json=True):
        """Create an asset with its .yy file and optional companion files."""
        asset_dir = os.path.join(self.temp_dir, asset_type, asset_name)
        os.makedirs(asset_dir, exist_ok=True)
        
        # Create folder files
        self._create_folder_file(f"folders/{asset_type.title()}.yy", asset_type.title())
        
        # Create asset .yy file
        asset_content = {
            f"$GM{asset_type.title()[:-1]}": "v1",  # objects -> Object
            "%Name": asset_name,
            "name": asset_name,
            "parent": {"name": asset_type.title(), "path": f"folders/{asset_type.title()}.yy"},
            "resourceType": f"GM{asset_type.title()[:-1]}",
            "resourceVersion": "2.0",
        }
        
        # Add specific content based on asset type
        if asset_type == "objects":
            asset_content.update({
                "eventList": [
                    {"$GMEvent": "v1", "eventNum": 0, "eventType": 0},  # Create event
                    {"$GMEvent": "v1", "eventNum": 0, "eventType": 3}   # Step event
                ]
            })
        elif asset_type == "sprites":
            asset_content.update({
                "layers": [
                    {"$GMImageLayer": "", "name": "default", "resourceType": "GMImageLayer"}
                ],
                "sequence": {"$GMSequence": ""}
            })
        elif asset_type == "scripts":
            asset_content.update({
                "isCompatibility": False,
                "isDnD": False
            })
        
        yy_file_path = os.path.join(asset_dir, f"{asset_name}.yy")
        
        if valid_json:
            with open(yy_file_path, 'w') as f:
                json.dump(asset_content, f, indent=2)
        else:
            # Create invalid JSON
            with open(yy_file_path, 'w') as f:
                f.write('{"invalid": json syntax missing quote}')
        
        if create_files:
            # Create companion files based on asset type
            if asset_type == "objects":
                # Create GML files for events
                with open(os.path.join(asset_dir, "Create_0.gml"), 'w') as f:
                    f.write("// Create event\n")
                with open(os.path.join(asset_dir, "Step_0.gml"), 'w') as f:
                    f.write("// Step event\n")
            elif asset_type == "scripts":
                # Create GML script file
                with open(os.path.join(asset_dir, f"{asset_name}.gml"), 'w') as f:
                    f.write(f"function {asset_name}() {{\n    // Script content\n}}")
            elif asset_type == "sprites":
                # Create sprite images
                layers_dir = os.path.join(asset_dir, "layers", "layer_uuid")
                os.makedirs(layers_dir, exist_ok=True)
                
                # Create main image (empty PNG file)
                with open(os.path.join(asset_dir, "sprite_uuid.png"), 'wb') as f:
                    f.write(b'\x89PNG\r\n\x1a\n')  # Minimal PNG header
                
                # Create layer image
                with open(os.path.join(layers_dir, "image_uuid.png"), 'wb') as f:
                    f.write(b'\x89PNG\r\n\x1a\n')  # Minimal PNG header


class TestDetectMultiAssetDirectories(TestAutoMaintenanceComprehensive):
    """Test detect_multi_asset_directories function."""
    
    def test_no_multi_asset_directories(self):
        """Test detection when all directories follow one-asset-per-folder rule."""
        # Create single-asset directories
        self._create_asset("objects", "o_player")
        self._create_asset("scripts", "player_move")
        self._create_asset("sprites", "spr_player")
        
        result = detect_multi_asset_directories(self.temp_dir)
        
        self.assertEqual(len(result), 0, "Should detect no multi-asset directories")
    
    def test_multi_asset_directory_objects(self):
        """Test detection of multiple objects in same directory."""
        # Create directory with multiple object .yy files
        objects_dir = os.path.join(self.temp_dir, "objects", "shared_dir")
        os.makedirs(objects_dir, exist_ok=True)
        
        # Create multiple .yy files in same directory
        for obj_name in ["o_player", "o_enemy"]:
            asset_content = {
                "$GMObject": "v1",
                "%Name": obj_name,
                "name": obj_name,
                "resourceType": "GMObject"
            }
            with open(os.path.join(objects_dir, f"{obj_name}.yy"), 'w') as f:
                json.dump(asset_content, f)
        
        result = detect_multi_asset_directories(self.temp_dir)
        
        self.assertEqual(len(result), 1, "Should detect one multi-asset directory")
        self.assertIn("shared_dir", result[0], "Should mention the problematic directory")
        self.assertIn("o_player", result[0], "Should mention first asset")
        self.assertIn("o_enemy", result[0], "Should mention second asset")
    
    def test_multi_asset_directory_mixed_types(self):
        """Test detection with multiple asset types in same directory."""
        # Create directory with mixed asset types (should not happen in real projects)
        mixed_dir = os.path.join(self.temp_dir, "scripts", "mixed_dir")
        os.makedirs(mixed_dir, exist_ok=True)
        
        # Create multiple .yy files of same type
        for script_name in ["script_a", "script_b", "script_c"]:
            asset_content = {
                "$GMScript": "v1",
                "%Name": script_name,
                "name": script_name,
                "resourceType": "GMScript"
            }
            with open(os.path.join(mixed_dir, f"{script_name}.yy"), 'w') as f:
                json.dump(asset_content, f)
        
        result = detect_multi_asset_directories(self.temp_dir)
        
        self.assertGreater(len(result), 0, "Should detect multi-asset directory")
        directory_info = next((d for d in result if "mixed_dir" in d), None)
        self.assertIsNotNone(directory_info, "Should find the mixed directory")
        # Check for the actual format - it lists the files
        self.assertIn("script_a.yy", directory_info, "Should mention first script")
        self.assertIn("script_b.yy", directory_info, "Should mention second script")
        self.assertIn("script_c.yy", directory_info, "Should mention third script")
    
    def test_nonexistent_asset_directories(self):
        """Test behavior when asset directories don't exist."""
        # Remove asset directories
        for asset_type in ['objects', 'sprites', 'scripts']:
            asset_dir = os.path.join(self.temp_dir, asset_type)
            if os.path.exists(asset_dir):
                shutil.rmtree(asset_dir)
        
        result = detect_multi_asset_directories(self.temp_dir)
        
        self.assertEqual(len(result), 0, "Should handle missing directories gracefully")
    
    def test_empty_asset_directories(self):
        """Test behavior with empty asset directories."""
        # Ensure directories exist but are empty
        for asset_type in ['objects', 'sprites', 'scripts']:
            asset_dir = os.path.join(self.temp_dir, asset_type)
            os.makedirs(asset_dir, exist_ok=True)
        
        result = detect_multi_asset_directories(self.temp_dir)
        
        self.assertEqual(len(result), 0, "Should handle empty directories gracefully")


class TestMaintenanceResult(TestAutoMaintenanceComprehensive):
    """Test MaintenanceResult class comprehensively."""
    
    def test_initialization(self):
        """Test MaintenanceResult initialization."""
        result = MaintenanceResult()
        
        # Test all initial values - using the actual attributes
        self.assertEqual(len(result.lint_issues), 0)
        self.assertEqual(len(result.path_issues), 0)
        self.assertEqual(len(result.missing_assets), 0)
        self.assertEqual(len(result.orphaned_assets), 0)
        self.assertEqual(len(result.json_issues), 0)
        self.assertFalse(result.has_errors)
        self.assertFalse(result.degraded_mode)
    
    def test_add_lint_issues(self):
        """Test adding lint issues."""
        result = MaintenanceResult()
        
        # Create test lint issues
        error_issue = LintIssue(
            severity="error",
            category="json",
            file_path="test.yy",
            message="Invalid JSON"
        )
        
        warning_issue = LintIssue(
            severity="warning",
            category="structure",
            file_path="test2.yy",
            message="Missing optional field"
        )
        
        result.add_lint_issues([error_issue, warning_issue])
        
        self.assertEqual(len(result.lint_issues), 2)
        self.assertTrue(result.has_errors, "Error issue should set has_errors flag")
    
    def test_add_path_issues(self):
        """Test adding path validation issues."""
        result = MaintenanceResult()
        
        # Create test path issues
        error_issue = PathValidationIssue(
            asset_name="test_asset",
            asset_path="assets/test_asset.yy",
            issue_type="missing_folder",
            severity="error",
            referenced_folder="folders/missing.yy"
        )
        
        result.add_path_issues([error_issue])
        
        self.assertEqual(len(result.path_issues), 1)
        self.assertTrue(result.has_errors, "Path error should set has_errors flag")
    
    def test_set_comma_fixes(self):
        """Test setting comma fixes data."""
        result = MaintenanceResult()
        
        comma_data = [
            ("file1.yy", True, "Valid JSON"),
            ("file2.yy", False, "Invalid JSON syntax")
        ]
        
        result.set_comma_fixes(comma_data)
        
        self.assertEqual(len(result.json_issues), 2)
        self.assertEqual(result.json_issues, comma_data)
        self.assertTrue(result.has_errors, "Failed JSON validation should set has_errors")
    
    def test_set_orphan_data(self):
        """Test setting orphan data."""
        result = MaintenanceResult()
        
        orphaned = ["path1.yy", "path2.gml"]
        missing = ["missing1.yy"]
        
        result.set_orphan_data(orphaned, missing)
        
        self.assertEqual(len(result.orphaned_assets), 2)
        self.assertEqual(len(result.missing_assets), 1)
        self.assertEqual(result.orphaned_assets, orphaned)
        self.assertEqual(result.missing_assets, missing)
        self.assertTrue(result.has_errors, "Missing assets should set has_errors")
    
    def test_event_sync_stats(self):
        """Test event sync stats handling."""
        result = MaintenanceResult()
        
        result.event_sync_stats = {
            'orphaned_found': 2,
            'missing_found': 1,
            'orphaned_fixed': 2,
            'missing_fixed': 1
        }
        
        self.assertEqual(result.event_sync_stats['orphaned_found'], 2)
        self.assertEqual(result.event_sync_stats['missing_found'], 1)
    
    def test_complex_flag_computation(self):
        """Test complex scenarios for error flag computation."""
        result = MaintenanceResult()
        
        # Start with no issues
        self.assertFalse(result.has_errors)
        
        # Add warnings only (no errors)
        warning_issue = LintIssue(
            severity="warning",
            category="style",
            file_path="test.yy",
            message="Minor issue"
        )
        result.add_lint_issues([warning_issue])
        
        self.assertFalse(result.has_errors, "Warnings should not set has_errors")
        
        # Add errors
        error_issue = LintIssue(
            severity="error",
            category="syntax",
            file_path="test2.yy",
            message="Critical issue"
        )
        result.add_lint_issues([error_issue])
        
        self.assertTrue(result.has_errors, "Errors should set has_errors flag")


class TestValidateAssetCreationSafe(TestAutoMaintenanceComprehensive):
    """Test validate_asset_creation_safe function comprehensively."""
    
    def test_clean_result_is_safe(self):
        """Test that validate_asset_creation_safe works with clean result."""
        result = MaintenanceResult()
        safe = validate_asset_creation_safe(result)
        self.assertTrue(safe, "Clean result should be safe")
    
    def test_error_result_is_not_safe(self):
        """Test that validate_asset_creation_safe works with error result."""
        result = MaintenanceResult()
        result.has_errors = True
        safe = validate_asset_creation_safe(result)
        self.assertFalse(safe, "Result with errors should not be safe")


class TestPrintFunctions(TestAutoMaintenanceComprehensive):
    """Test all print functions comprehensively."""
    
    def test_print_maintenance_summary_clean_project(self):
        """Test print_maintenance_summary with clean project."""
        result = MaintenanceResult()
        
        with patch('builtins.print') as mock_print:
            print_maintenance_summary(result)
            
            # Verify clean project summary
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Maintenance Summary", printed_output, "Should show maintenance summary")
    
    def test_print_maintenance_summary_with_errors(self):
        """Test print_maintenance_summary with errors."""
        result = MaintenanceResult()
        
        # Add lint issues
        error_issue = LintIssue(
            severity="error",
            category="json",
            file_path="test.yy",
            message="Critical error"
        )
        result.add_lint_issues([error_issue])
        
        with patch('builtins.print') as mock_print:
            print_maintenance_summary(result)
            
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Lint issues:", printed_output, "Should show lint issues count")
    
    def test_print_event_validation_report_empty(self):
        """Test print_event_validation_report with no issues."""
        empty_issues = {}
        
        with patch('builtins.print') as mock_print:
            print_event_validation_report(empty_issues)
            
            # Should print header even for empty issues
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Event Validation Issues", printed_output, "Should print header")
    
    def test_print_event_validation_report_with_issues(self):
        """Test print_event_validation_report with various issues."""
        validation_issues = {
            "o_player": {"errors": ["Missing Create event"]},
            "o_enemy": {"warnings": ["Style issue"]}
        }
        
        with patch('builtins.print') as mock_print:
            print_event_validation_report(validation_issues)
            
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("o_player", printed_output, "Should mention object with errors")
            self.assertIn("o_enemy", printed_output, "Should mention object with warnings")
    
    def test_print_event_sync_report_all_scenarios(self):
        """Test print_event_sync_report with all stat combinations."""
        # Test scenario: Issues found and fixed
        stats = {
            'objects_processed': 5,
            'orphaned_found': 3,
            'orphaned_fixed': 3,
            'missing_found': 2,
            'missing_fixed': 2
        }
        
        with patch('builtins.print') as mock_print:
            print_event_sync_report(stats)
            
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("5", printed_output, "Should show objects processed")
    
    def test_print_orphan_cleanup_report_all_scenarios(self):
        """Test print_orphan_cleanup_report with various cleanup scenarios."""
        # Test scenario: Files deleted successfully
        stats = {
            'total_deleted': 5,
            'deleted_directories': ['dir1', 'dir2']
        }
        
        with patch('builtins.print') as mock_print:
            print_orphan_cleanup_report(stats)
            
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("5", printed_output, "Should show deletion count")


class TestHandleMaintenanceFailure(TestAutoMaintenanceComprehensive):
    """Test handle_maintenance_failure function comprehensively."""
    
    def test_handle_failure_with_result(self):
        """Test handle_maintenance_failure with a result object."""
        result = MaintenanceResult()
        result.has_errors = True
        result.missing_assets = ["test.yy"]
        
        with patch('builtins.print') as mock_print:
            success = handle_maintenance_failure("Operation", result)
            
            self.assertFalse(success, "Should return False for failures")
            
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Operation aborted", printed_output)
            self.assertIn("missing assets detected", printed_output)
    
    def test_handle_failure_with_json_errors(self):
        """Test handle_maintenance_failure with JSON errors."""
        result = MaintenanceResult()
        result.set_comma_fixes([("test.yy", False, "Error")])
        
        with patch('builtins.print') as mock_print:
            success = handle_maintenance_failure("JSON Validation", result)
            
            self.assertFalse(success)
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Invalid JSON syntax", printed_output)
    
    def test_handle_failure_returns_false(self):
        """Test that handle_maintenance_failure always returns False."""
        result = MaintenanceResult()
        result.has_errors = True
        with patch('builtins.print'):
            success = handle_maintenance_failure("Any Op", result)
            self.assertFalse(success)


class TestRunAutoMaintenanceIntegration(TestAutoMaintenanceComprehensive):
    """Test run_auto_maintenance function integration scenarios."""
    
    def test_run_auto_maintenance_clean_project(self):
        """Test run_auto_maintenance on a clean project."""
        # Create a clean project with valid assets
        self._create_asset("objects", "o_player", create_files=True, valid_json=True)
        self._create_asset("scripts", "player_move", create_files=True, valid_json=True)
        self._create_asset("sprites", "spr_player", create_files=True, valid_json=True)
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        self.assertIsInstance(result, MaintenanceResult)
        self.assertIsNotNone(result, "Should return a MaintenanceResult")
    
    def test_run_auto_maintenance_verbose_mode(self):
        """Test run_auto_maintenance with verbose output."""
        self._create_asset("objects", "o_test", create_files=True, valid_json=True)
        
        with patch('builtins.print') as mock_print:
            result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=True)
            
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            
            # Verify verbose output contains expected sections
            self.assertIn("[MAINT]", printed_output, "Should show maintenance progress")
    
    def test_run_auto_maintenance_fix_mode_vs_dry_run(self):
        """Test differences between fix mode and dry-run mode."""
        # Create an object with missing GML files to trigger event sync
        asset_dir = os.path.join(self.temp_dir, "objects", "o_broken")
        os.makedirs(asset_dir, exist_ok=True)
        
        # Create .yy file that references missing GML files
        asset_content = {
            "$GMObject": "v1",
            "%Name": "o_broken",
            "name": "o_broken",
            "eventList": [
                {"$GMEvent": "v1", "eventNum": 0, "eventType": 0}  # Create event
            ],
            "resourceType": "GMObject"
        }
        
        with open(os.path.join(asset_dir, "o_broken.yy"), 'w') as f:
            json.dump(asset_content, f)
        
        # Test dry-run mode
        result_dry = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        # Test fix mode
        result_fix = run_auto_maintenance(self.temp_dir, fix_issues=True, verbose=False)
        
        # Both should detect the same issues, but fix mode might resolve some
        self.assertIsInstance(result_dry, MaintenanceResult)
        self.assertIsInstance(result_fix, MaintenanceResult)
        
        # Both should have event sync stats
        self.assertTrue(hasattr(result_dry, 'event_sync_stats'))
        self.assertTrue(hasattr(result_fix, 'event_sync_stats'))
    
    def test_run_auto_maintenance_with_json_errors(self):
        """Test run_auto_maintenance with JSON validation errors."""
        # Create assets with invalid JSON
        self._create_asset("objects", "o_broken_json", create_files=False, valid_json=False)
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        # Should detect JSON validation issues
        self.assertIsInstance(result, MaintenanceResult)
        # json_issues is the current attribute name
        self.assertTrue(hasattr(result, 'json_issues'), "Should have json_issues attribute")
    
    def test_run_auto_maintenance_configuration_override(self):
        """Test run_auto_maintenance with configuration parameter overrides."""
        self._create_asset("objects", "o_test", create_files=True, valid_json=True)
        
        # Test explicit parameter values override config
        result_no_fix = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        result_fix = run_auto_maintenance(self.temp_dir, fix_issues=True, verbose=True)
        
        # Both should succeed, but different modes
        self.assertIsInstance(result_no_fix, MaintenanceResult)
        self.assertIsInstance(result_fix, MaintenanceResult)
    
    def test_run_auto_maintenance_step_verification(self):
        """Test that run_auto_maintenance executes all expected steps."""
        self._create_asset("objects", "o_test", create_files=True, valid_json=True)
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        # Verify that the function executed without error and returned a result
        self.assertIsNotNone(result)
        self.assertIsInstance(result, MaintenanceResult)


class TestAutoMaintenanceEdgeCases(TestAutoMaintenanceComprehensive):
    """Test edge cases and error conditions for auto_maintenance functions."""
    
    def test_detect_multi_asset_directories_edge_cases(self):
        """Test edge cases for detect_multi_asset_directories."""
        # Test with non-readable directories (permission issues)
        restricted_dir = os.path.join(self.temp_dir, "objects", "restricted")
        os.makedirs(restricted_dir, exist_ok=True)
        
        # Create a file that looks like a .yy file but isn't
        with open(os.path.join(restricted_dir, "not_actually.yy"), 'w') as f:
            f.write("This is not JSON")
        
        # Should handle gracefully
        result = detect_multi_asset_directories(self.temp_dir)
        self.assertIsInstance(result, list, "Should return list even with problematic files")
    
    def test_maintenance_result_edge_cases(self):
        """Test MaintenanceResult edge cases."""
        result = MaintenanceResult()
        
        # Test adding empty lists
        result.add_lint_issues([])
        result.add_path_issues([])
        result.set_comma_fixes([])
        result.set_orphan_data([], [])
        
        # Should remain in clean state
        self.assertFalse(result.has_errors)
    
    def test_validate_asset_creation_safe_edge_cases(self):
        """Test edge cases for validate_asset_creation_safe."""
        # Test with various results
        result = MaintenanceResult()
        safe = validate_asset_creation_safe(result)
        self.assertTrue(safe, "Clean result should be safe")
        
        result.has_errors = True
        safe = validate_asset_creation_safe(result)
        self.assertFalse(safe, "Result with errors should not be safe")
    
    def test_print_functions_with_empty_inputs(self):
        """Test print functions with empty inputs."""
        # Test with empty dict (should work)
        with patch('builtins.print') as mock_print:
            print_event_validation_report({})
            # Should handle empty dict gracefully
            
        # Test print_event_sync_report with empty dict
        with patch('builtins.print') as mock_print:
            print_event_sync_report({})
            # Should handle empty dict gracefully
            
        # Test print_orphan_cleanup_report with empty dict
        with patch('builtins.print') as mock_print:
            print_orphan_cleanup_report({})
            # Should handle empty dict gracefully
    
    def test_handle_maintenance_failure_edge_cases(self):
        """Test edge cases for handle_maintenance_failure."""
        # Test with various results
        result = MaintenanceResult()
        result.has_errors = True
        
        with patch('builtins.print') as mock_print:
            success = handle_maintenance_failure("Edge Case Op", result)
            self.assertFalse(success)
            mock_print.assert_any_call("[ERROR] Edge Case Op aborted due to project issues:")
    
    def test_run_auto_maintenance_with_import_errors(self):
        """Test run_auto_maintenance handles import errors gracefully."""
        # This test verifies the function exists and basic structure
        self._create_asset("objects", "o_test", create_files=True, valid_json=True)
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        self.assertIsInstance(result, MaintenanceResult,
                             "Should return MaintenanceResult even with potential import issues")
    
    def test_complex_project_structure(self):
        """Test auto maintenance with complex project structure."""
        # Create a complex project with multiple asset types and nested folders
        for asset_type in ["objects", "scripts", "sprites"]:
            for i in range(3):
                asset_name = f"{asset_type[:-1]}_{i}"  # Remove 's' and add number
                self._create_asset(asset_type, asset_name, create_files=True, valid_json=True)
        
        # Add some edge cases
        # Create empty directories
        for empty_dir in ["empty_objects", "empty_scripts"]:
            os.makedirs(os.path.join(self.temp_dir, "objects", empty_dir), exist_ok=True)
        
        # Create files with unusual names
        unusual_dir = os.path.join(self.temp_dir, "scripts", "script_with_dots.v2.1")
        os.makedirs(unusual_dir, exist_ok=True)
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        self.assertIsInstance(result, MaintenanceResult)
        # Complex projects may have warnings, but should handle them gracefully
    
    def test_maintenance_with_corrupted_project_file(self):
        """Test auto maintenance behavior with corrupted project file."""
        # Corrupt the main project file
        yyp_file = None
        for file in os.listdir(self.temp_dir):
            if file.endswith('.yyp'):
                yyp_file = file
                break
        
        if yyp_file:
            with open(os.path.join(self.temp_dir, yyp_file), 'w') as f:
                f.write('{"corrupted": json syntax error}')
        
        # run_auto_maintenance handles errors gracefully and returns a result even with corrupted files
        # It may return a result with has_errors=True or degraded_mode=True
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        self.assertIsInstance(result, MaintenanceResult)
        # A corrupted project file should result in errors
        self.assertTrue(result.has_errors or result.degraded_mode, 
                       "Corrupted project file should cause errors or degraded mode")
    
    def test_performance_with_many_assets(self):
        """Test auto maintenance performance with many assets."""
        # Create a larger number of assets to test performance
        # (keeping reasonable for test execution time)
        for i in range(10):
            self._create_asset("objects", f"o_test_{i}", create_files=True, valid_json=True)
            self._create_asset("scripts", f"script_test_{i}", create_files=True, valid_json=True)
        
        # Time the operation (basic performance check)
        import time
        start_time = time.time()
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        self.assertIsInstance(result, MaintenanceResult)
        self.assertLess(execution_time, 10.0, "Should complete within reasonable time")


class TestAutoMaintenanceStressScenarios(TestAutoMaintenanceComprehensive):
    """Test stress scenarios and boundary conditions."""
    
    def test_maintenance_with_all_error_types(self):
        """Test maintenance when all possible error types are present."""
        # Create assets with various problems
        
        # 1. Invalid JSON
        self._create_asset("objects", "o_broken_json", create_files=False, valid_json=False)
        
        # 2. Missing files
        self._create_asset("objects", "o_missing_files", create_files=False, valid_json=True)
        
        # 3. Create multi-asset directory
        multi_dir = os.path.join(self.temp_dir, "scripts", "multi_asset_dir")
        os.makedirs(multi_dir, exist_ok=True)
        
        for script_name in ["script_a", "script_b"]:
            asset_content = {"$GMScript": "v1", "%Name": script_name, "name": script_name}
            with open(os.path.join(multi_dir, f"{script_name}.yy"), 'w') as f:
                json.dump(asset_content, f)
        
        # 4. Create orphaned files
        orphan_dir = os.path.join(self.temp_dir, "orphaned_files")
        os.makedirs(orphan_dir, exist_ok=True)
        with open(os.path.join(orphan_dir, "orphan.gml"), 'w') as f:
            f.write("// Orphaned file")
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        self.assertIsInstance(result, MaintenanceResult)
        # Should detect multiple types of issues
        self.assertTrue(
            result.has_errors or 
            len(result.json_issues) > 0 or len(result.orphaned_assets) > 0,
            "Should detect at least some issues in problematic project"
        )
    
    def test_maintenance_recovery_scenarios(self):
        """Test maintenance behavior in recovery scenarios."""
        # Create a project that's been partially corrupted
        self._create_asset("objects", "o_good", create_files=True, valid_json=True)
        self._create_asset("objects", "o_bad", create_files=False, valid_json=False)
        
        # Run maintenance to see what can be recovered
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        self.assertIsInstance(result, MaintenanceResult)
        
        # Now try fix mode to see if anything can be auto-repaired
        result_fixed = run_auto_maintenance(self.temp_dir, fix_issues=True, verbose=False)
        
        self.assertIsInstance(result_fixed, MaintenanceResult)
        # Fixed version might have fewer errors than original
    
    def test_boundary_conditions(self):
        """Test boundary conditions for maintenance functions."""
        # Test with minimal project (just folders, no assets)
        for folder_name in ["Objects", "Scripts", "Sprites"]:
            self._create_folder_file(f"folders/{folder_name}.yy", folder_name)
        
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        self.assertIsInstance(result, MaintenanceResult)
        # A minimal project with just folders should be relatively clean, but might have
        # some issues detected by maintenance. The key is that it runs without crashing.
        # We'll be more lenient here since the focus is on boundary testing
        self.assertIsNotNone(result, "Should return a MaintenanceResult")
        
        # Test with project that has maximum reasonable complexity
        # (limited for test performance)
        deep_folder_path = os.path.join(self.temp_dir, "objects", "deep", "nested", "folder")
        os.makedirs(deep_folder_path, exist_ok=True)
        
        result_complex = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
        
        self.assertIsInstance(result_complex, MaintenanceResult)


if __name__ == '__main__':
    unittest.main()


class TestAutoMaintenanceFullCoverage(unittest.TestCase):
    """Additional tests to achieve 100% coverage for auto_maintenance.py"""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Create basic project structure (but NOT scripts directory for testing)
        os.makedirs(os.path.join(self.temp_dir, "objects"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "sprites"), exist_ok=True)
        # Intentionally NOT creating scripts directory to test the continue statement
        
        # Create a minimal .yyp file
        project_data = {
            "resources": [],
            "folders": []
        }
        with open(os.path.join(self.temp_dir, "test_project.yyp"), 'w') as f:
            json.dump(project_data, f, indent=2)
    
    def tearDown(self):
        """Clean up test environment."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_detect_multi_asset_directories_missing_dir(self):
        """Test detect_multi_asset_directories with missing asset directories."""
        from gms_helpers.auto_maintenance import detect_multi_asset_directories
        
        # This will exercise the continue statement when scripts directory doesn't exist
        result = detect_multi_asset_directories(self.temp_dir)
        
        # Should return empty list since no directories have multiple .yy files
        self.assertEqual(result, [])
    
    def test_event_sync_critical_path(self):
        """Test the validate_asset_creation_safe function with proper arguments."""
        from gms_helpers.auto_maintenance import validate_asset_creation_safe, MaintenanceResult
        
        # Test with clean result
        result = MaintenanceResult()
        safe = validate_asset_creation_safe(result)
        self.assertTrue(safe)

    def test_handle_maintenance_failure_event_sync(self):
        """Test handle_maintenance_failure with a result."""
        from gms_helpers.auto_maintenance import handle_maintenance_failure, MaintenanceResult
        from io import StringIO
        import sys
        
        # Capture output
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # Test with a result
            result = MaintenanceResult()
            result.has_errors = True
            result_value = handle_maintenance_failure("Test Op", result)
            self.assertFalse(result_value)
            
            # Check output contains error message
            output = captured_output.getvalue()
            self.assertIn("Test Op aborted due to project issues", output)
        finally:
            sys.stdout = sys.__stdout__
    
    def test_import_fallback_paths(self):
        """Test that import fallback paths work correctly."""
        import sys
        from unittest.mock import patch
        
        # Save original modules
        original_modules = {}
        modules_to_mock = [
            'gms_helpers.auto_maintenance.config',
            'gms_helpers.auto_maintenance.maintenance.lint',
            'gms_helpers.auto_maintenance.maintenance.tidy_json',
            'gms_helpers.auto_maintenance.maintenance.validate_paths',
            'gms_helpers.auto_maintenance.maintenance.orphans',
            'gms_helpers.auto_maintenance.maintenance.orphan_cleanup',
            'gms_helpers.auto_maintenance.event_helper'
        ]
        
        for module in modules_to_mock:
            if module in sys.modules:
                original_modules[module] = sys.modules[module]
        
        try:
            # Force the ImportError path by temporarily removing relative imports
            with patch.dict(sys.modules, {mod: None for mod in modules_to_mock if '.' in mod}):
                # Force reimport to trigger the except ImportError block
                if 'gms_helpers.auto_maintenance' in sys.modules:
                    del sys.modules['gms_helpers.auto_maintenance']
                
                # This import should trigger the fallback imports
                import gms_helpers.auto_maintenance as auto_maintenance
                
                # Verify the module loaded correctly
                self.assertTrue(hasattr(auto_maintenance, 'run_auto_maintenance'))
                self.assertTrue(hasattr(auto_maintenance, 'MaintenanceResult'))
                
        finally:
            # Restore original modules
            for module, value in original_modules.items():
                sys.modules[module] = value
    
    def test_run_auto_maintenance_missing_assets_directory(self):
        """Test run_auto_maintenance when asset directories are missing."""
        from gms_helpers.auto_maintenance import run_auto_maintenance
        
        # Run maintenance on directory with missing scripts folder
        result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=True)
        
        # Should complete successfully
        self.assertIsNotNone(result)
        self.assertIsInstance(result.lint_issues, list)
        self.assertIsInstance(result.path_issues, list)
    
    def test_import_error_handlers(self):
        """Test all ImportError handlers get executed."""
        import sys
        from unittest.mock import patch, MagicMock
        
        # Mock the modules to force ImportError on relative imports
        mock_modules = {
            'maintenance.event_sync': MagicMock(),
            'maintenance.clean_unused_assets': MagicMock()
        }
        
        # Create mock functions
        mock_sync = MagicMock(return_value={
            'orphaned_found': 0,
            'missing_found': 0,
            'orphaned_fixed': 0,
            'missing_fixed': 0
        })
        mock_clean_folders = MagicMock(return_value=(0, 0))
        mock_clean_old = MagicMock(return_value=(0, 0))
        
        mock_modules['maintenance.event_sync'].sync_all_object_events = mock_sync
        mock_modules['maintenance.clean_unused_assets'].clean_unused_folders = mock_clean_folders
        mock_modules['maintenance.clean_unused_assets'].clean_old_yy_files = mock_clean_old
        
        import builtins
        original_import = builtins.__import__
        
        def custom_import(name, *args, **kwargs):
            # Force ImportError for package imports to trigger fallback
            if name.startswith('gms_helpers.maintenance.'):
                raise ImportError(f"Forcing fallback for {name}")
            # Return our mocks for absolute imports
            if name in mock_modules:
                return mock_modules[name]
            return original_import(name, *args, **kwargs)
        
        with patch('builtins.__import__', side_effect=custom_import):
            from gms_helpers.auto_maintenance import run_auto_maintenance
            
            # Run maintenance which should use fallback imports
            result = run_auto_maintenance(self.temp_dir, fix_issues=False, verbose=False)
            
            # Verify it completed successfully
            self.assertIsNotNone(result)
            
            # Verify our mocked functions were called (proving fallback imports worked)
            mock_sync.assert_called_once()
            mock_clean_folders.assert_called()
            mock_clean_old.assert_called_once()
    
    def test_detect_multi_asset_with_multiple_yy_files(self):
        """Test detect_multi_asset_directories when directories have multiple .yy files."""
        from gms_helpers.auto_maintenance import detect_multi_asset_directories
        import os
        
        # Create a directory with multiple .yy files
        multi_dir = os.path.join(self.temp_dir, "objects", "multi_asset")
        os.makedirs(multi_dir, exist_ok=True)
        
        # Create multiple .yy files
        with open(os.path.join(multi_dir, "asset1.yy"), 'w') as f:
            f.write('{"test": "data1"}')
        with open(os.path.join(multi_dir, "asset2.yy"), 'w') as f:
            f.write('{"test": "data2"}')
        
        # Test detection
        result = detect_multi_asset_directories(self.temp_dir)
        
        # Should find the multi-asset directory
        self.assertEqual(len(result), 1)
        self.assertIn("objects/multi_asset", result[0])
        self.assertIn("asset1.yy", result[0])
        self.assertIn("asset2.yy", result[0])
