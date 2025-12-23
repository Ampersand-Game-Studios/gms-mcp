#!/usr/bin/env python3
"""
Test event validation error handling and maintenance failure reporting.

This module ensures that event validation errors are properly detected, reported,
and block asset creation when appropriate. It prevents the regression where
event errors were silently ignored in maintenance failure output.
"""

import unittest
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import patch
import sys

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to the path for imports
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.auto_maintenance import (
    run_auto_maintenance,
    validate_asset_creation_safe,
    handle_maintenance_failure,
    MaintenanceResult
)
from gms_helpers.event_helper import ValidationReport
from gms_helpers.utils import save_pretty_json


class TestEventValidationErrors(unittest.TestCase):
    """Test that event validation errors are properly handled and reported."""

    def setUp(self):
        """Set up temporary directory for testing."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cwd = os.getcwd()

    def tearDown(self):
        """Clean up temporary directory."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)

    def _create_synthetic_bad_object(self, obj_name: str = "o_bad", missing_events: list = None):
        """
        Create a synthetic object with event validation errors for testing.

        Args:
            obj_name: Name of the object to create
            missing_events: List of event tuples (event_type, event_num) that should be
                          referenced in .yy but have missing GML files

        Returns:
            Path to the created object directory
        """
        if missing_events is None:
            missing_events = [(0, 0)]  # Create event by default

        # Create project structure
        project_data = {
            "$GMProject": "",
            "%Name": "test",
            "name": "test",
            "resourceType": "GMProject",
            "resourceVersion": "2.0",
            "resources": [
                {
                    "id": {
                        "name": obj_name,
                        "path": f"objects/{obj_name}/{obj_name}.yy"
                    }
                }
            ],
            "Folders": [
                {
                    "$GMFolder": "",
                    "%Name": "Objects",
                    "folderPath": "folders/Objects.yy",
                    "name": "Objects",
                    "resourceType": "GMFolder",
                    "resourceVersion": "2.0"
                }
            ]
        }

        save_pretty_json(self.temp_dir / "test.yyp", project_data)

        # Create object directory
        obj_dir = self.temp_dir / "objects" / obj_name
        obj_dir.mkdir(parents=True)

        # Create object .yy file with event references
        event_list = []
        for event_type, event_num in missing_events:
            event_list.append({
                "$GMEvent": "v1",
                "%Name": "",
                "collisionObjectId": None,
                "eventNum": event_num,
                "eventType": event_type,
                "isDnD": False,
                "name": "",
                "resourceType": "GMEvent",
                "resourceVersion": "2.0"
            })

        obj_data = {
            "$GMObject": "",
            "%Name": obj_name,
            "eventList": event_list,
            "managed": True,
            "name": obj_name,
            "overriddenProperties": [],
            "parent": {
                "name": "Objects",
                "path": "folders/Objects.yy"
            },
            "parentObjectId": None,
            "persistent": False,
            "physicsAngularDamping": 0.1,
            "physicsDensity": 0.5,
            "physicsFriction": 0.2,
            "physicsGroup": 1,
            "physicsKinematic": False,
            "physicsLinearDamping": 0.1,
            "physicsObject": False,
            "physicsRestitution": 0.1,
            "physicsSensor": False,
            "physicsShape": 1,
            "physicsShapePoints": [],
            "physicsStartAwake": True,
            "properties": [],
            "resourceType": "GMObject",
            "resourceVersion": "2.0",
            "solid": False,
            "spriteId": None,
            "spriteMaskId": None,
            "visible": True
        }

        save_pretty_json(obj_dir / f"{obj_name}.yy", obj_data)

        # Intentionally do NOT create the GML files to trigger validation errors

        return obj_dir

    def _copy_test_fixture(self, fixture_name: str):
        """Copy a test fixture to the temp directory and change to it."""
        fixture_path = Path(__file__).parent / "test_fixtures" / fixture_name
        if not fixture_path.exists():
            self.skipTest(f"Test fixture {fixture_name} not found")

        # Copy fixture to temp directory
        for item in fixture_path.iterdir():
            if item.is_dir():
                shutil.copytree(item, self.temp_dir / item.name)
            else:
                shutil.copy2(item, self.temp_dir / item.name)

        # Change to temp directory
        os.chdir(self.temp_dir)

    def test_event_error_blocks_asset_creation(self):
        """Test that event validation errors block asset creation and are properly reported."""
        # Create synthetic bad object instead of relying on fixture
        os.chdir(self.temp_dir)
        self._create_synthetic_bad_object("o_bad", [(0, 0)])  # Missing Create_0.gml

        # Run maintenance manually in dry-run mode (fix_issues=False)
        result = run_auto_maintenance(".", fix_issues=False, verbose=False)

        # Verify that event sync stats were populated
        self.assertTrue(hasattr(result, 'event_sync_stats'), "Expected event_sync_stats to be populated")
        self.assertTrue(result.event_sync_stats, "Expected event_sync_stats to have data")

        # Verify missing files were detected
        missing_found = result.event_sync_stats.get('missing_found', 0)
        self.assertGreater(missing_found, 0, "Expected missing GML files to be detected")

        # Verify that validation considers this unsafe
        self.assertFalse(validate_asset_creation_safe(result),
                        "Asset creation should be blocked due to event sync issues")

        # Test that the failure handler surfaces event sync issues
        with patch('builtins.print') as mock_print:
            handle_maintenance_failure("Test operation", result)

            # Capture all print calls as a single string
            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)

            # Verify event sync errors are displayed
            self.assertIn("Event sync", printed_output,
                         "Event sync issues should appear in failure output")
            self.assertIn("missing GML file", printed_output,
                         "Missing GML file error should be displayed")

            # Verify total count is correct (should be > 0 now)
            self.assertIn("Total critical issues: 1", printed_output,
                         "Total critical issues should be 1")

    def test_event_error_only_scenario(self):
        """Test scenario where ONLY event errors exist (no lint/path/missing issues)."""
        # Create synthetic bad object
        os.chdir(self.temp_dir)
        self._create_synthetic_bad_object("o_bad", [(0, 0)])

        # Run maintenance
        result = run_auto_maintenance(".", fix_issues=False, verbose=False)

        # Verify this is truly an "event-only" error scenario
        self.assertEqual(len(result.lint_issues), 0, "Should have no lint issues")
        self.assertEqual(len(result.path_issues), 0, "Should have no path issues")
        self.assertEqual(len(result.missing_assets), 0, "Should have no missing assets")

        # Check for event sync issues (new system)
        if hasattr(result, 'event_sync_stats') and result.event_sync_stats:
            missing_found = result.event_sync_stats.get('missing_found', 0)
            self.assertGreater(missing_found, 0, "Should have event sync issues")

        # Verify it still blocks asset creation
        self.assertFalse(validate_asset_creation_safe(result))

    def test_multiple_event_errors(self):
        """Test that multiple event errors are all displayed."""
        os.chdir(self.temp_dir)
        # Create object with multiple missing events
        self._create_synthetic_bad_object("o_multi_bad", [(0, 0), (3, 0), (8, 0)])  # Create, Step, Draw

        result = run_auto_maintenance(".", fix_issues=False, verbose=False)

        # Verify multiple missing files were detected
        if hasattr(result, 'event_sync_stats') and result.event_sync_stats:
            missing_found = result.event_sync_stats.get('missing_found', 0)
            self.assertEqual(missing_found, 3, "Should detect 3 missing GML files")

        with patch('builtins.print') as mock_print:
            handle_maintenance_failure("Multi-error test", result)

            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)

            # Should show event sync issues
            self.assertIn("Event sync", printed_output)
            self.assertIn("3 missing GML file", printed_output)
            self.assertIn("Total critical issues: 3", printed_output)

    def test_mixed_error_scenario(self):
        """Test that event errors are shown alongside other types of errors."""
        # Create a scenario with multiple error types
        os.chdir(self.temp_dir)
        self._create_synthetic_bad_object("o_bad", [(0, 0)])

        # Manually add some other issues to the result
        result = run_auto_maintenance(".", fix_issues=False, verbose=False)

        # Add a fake missing asset to simulate mixed errors
        result.missing_assets.append(("fake/path.yy", "script"))

        with patch('builtins.print') as mock_print:
            handle_maintenance_failure("Mixed errors test", result)

            printed_output = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)

            # Should show both event sync issues and missing assets
            self.assertIn("Event sync", printed_output, "Event sync error should be shown")
            self.assertIn("Missing script: fake/path.yy", printed_output, "Missing asset should be shown")
            self.assertIn("Total critical issues: 2", printed_output, "Should count both types of errors")

    def test_clean_project_passes_validation(self):
        """Test that a clean project with no errors passes validation."""
        # Create a minimal clean project
        clean_project = {
            "$GMProject": "",
            "%Name": "clean_test",
            "name": "clean_test",
            "resourceType": "GMProject",
            "resourceVersion": "2.0",
            "resources": [],
            "Folders": []
        }

        os.chdir(self.temp_dir)
        save_pretty_json(self.temp_dir / "clean_test.yyp", clean_project)

        # Create minimal directory structure
        (self.temp_dir / "objects").mkdir()
        (self.temp_dir / "scripts").mkdir()
        (self.temp_dir / "sprites").mkdir()

        result = run_auto_maintenance(".", fix_issues=False, verbose=False)

        # Should pass validation
        self.assertTrue(validate_asset_creation_safe(result),
                       "Clean project should pass asset creation validation")
        self.assertEqual(len(result.event_issues), 0, "Clean project should have no event issues")


class TestMaintenanceResultEventHandling(unittest.TestCase):
    """Test MaintenanceResult class event handling."""

    def test_event_issues_affect_has_errors_flag(self):
        """Test that event issues properly set the has_errors flag."""
        result = MaintenanceResult()

        # Initially no errors
        self.assertFalse(result.has_errors)

        # Add event issues with errors
        validation_with_errors = ValidationReport(
            errors=["Test error"],
            warnings=[],
            missing_files=["missing.gml"],
            orphan_files=[],
            duplicates=[]
        )

        result.add_event_issues("test_object", validation_with_errors)

        # Should now have errors
        self.assertTrue(result.has_errors, "Event validation errors should set has_errors flag")

    def test_event_warnings_affect_has_warnings_flag(self):
        """Test that event warnings properly set the has_warnings flag."""
        result = MaintenanceResult()

        # Initially no warnings
        self.assertFalse(result.has_warnings)

        # Add event issues with warnings only
        validation_with_warnings = ValidationReport(
            errors=[],
            warnings=["Test warning"],
            missing_files=[],
            orphan_files=["orphan.gml"],
            duplicates=[]
        )

        result.add_event_issues("test_object", validation_with_warnings)

        # Should now have warnings
        self.assertTrue(result.has_warnings, "Event validation warnings should set has_warnings flag")


if __name__ == '__main__':
    unittest.main()
