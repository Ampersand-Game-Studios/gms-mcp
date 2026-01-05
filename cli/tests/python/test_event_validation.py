#!/usr/bin/env python3
"""
Test event validation error handling and maintenance failure reporting.
"""

import unittest
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import patch
import sys
import json

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to the path for imports
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.auto_maintenance import (
    run_auto_maintenance,
    MaintenanceResult
)
from gms_helpers.maintenance.event_sync import sync_all_object_events
from gms_helpers.utils import save_pretty_json

class TestEventValidationErrors(unittest.TestCase):
    """Test that event validation errors are properly handled and reported."""

    def setUp(self):
        """Set up temporary directory for testing."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        
        # Create minimal project
        (self.temp_dir / "objects").mkdir()
        (self.temp_dir / "test.yyp").write_text("{}")

    def tearDown(self):
        """Clean up temporary directory."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)

    def test_sync_detects_missing_files(self):
        """Test that sync_all_object_events detects missing GML files."""
        obj_name = "o_missing"
        obj_dir = self.temp_dir / "objects" / obj_name
        obj_dir.mkdir()
        
        # Reference a Create event in .yy but don't create the file
        yy_data = {
            "name": obj_name,
            "eventList": [
                {
                    "resourceType": "GMEvent",
                    "resourceVersion": "1.0",
                    "name": "",
                    "isDnD": False,
                    "eventNum": 0,
                    "eventType": 0,
                    "collisionObjectId": None
                }
            ],
            "resourceType": "GMObject",
            "resourceVersion": "2.0"
        }
        save_pretty_json(obj_dir / f"{obj_name}.yy", yy_data)
        
        # Run sync (dry run)
        stats = sync_all_object_events(str(self.temp_dir), dry_run=True)
        
        self.assertEqual(stats['missing_found'], 1)
        self.assertEqual(stats['missing_created'], 0)

    def test_sync_fixes_missing_files(self):
        """Test that sync_all_object_events creates missing GML files when fix=True."""
        obj_name = "o_fix_me"
        obj_dir = self.temp_dir / "objects" / obj_name
        obj_dir.mkdir()
        
        yy_data = {
            "name": obj_name,
            "eventList": [{"eventType": 0, "eventNum": 0, "resourceType": "GMEvent", "resourceVersion": "1.0"}]
        }
        save_pretty_json(obj_dir / f"{obj_name}.yy", yy_data)
        
        # Run sync (with fix)
        stats = sync_all_object_events(str(self.temp_dir), dry_run=False)
        
        self.assertEqual(stats['missing_created'], 1)
        self.assertTrue((obj_dir / "Create_0.gml").exists())

if __name__ == "__main__":
    unittest.main()
