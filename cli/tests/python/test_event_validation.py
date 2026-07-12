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

from gms_helpers.auto_maintenance import run_auto_maintenance, MaintenanceResult
from gms_helpers.maintenance.event_sync import sync_all_object_events
from gms_helpers.utils import load_json_loose, save_pretty_json


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
                    "collisionObjectId": None,
                }
            ],
            "resourceType": "GMObject",
            "resourceVersion": "2.0",
        }
        save_pretty_json(obj_dir / f"{obj_name}.yy", yy_data)

        # Run sync (dry run)
        stats = sync_all_object_events(str(self.temp_dir), dry_run=True)

        self.assertEqual(stats["missing_found"], 1)
        self.assertEqual(stats["missing_created"], 0)

    def test_sync_fixes_missing_files(self):
        """Test that sync_all_object_events creates missing GML files when fix=True."""
        obj_name = "o_fix_me"
        obj_dir = self.temp_dir / "objects" / obj_name
        obj_dir.mkdir()

        yy_data = {
            "name": obj_name,
            "eventList": [{"eventType": 0, "eventNum": 0, "resourceType": "GMEvent", "resourceVersion": "1.0"}],
        }
        save_pretty_json(obj_dir / f"{obj_name}.yy", yy_data)

        # Run sync (with fix)
        stats = sync_all_object_events(str(self.temp_dir), dry_run=False)

        self.assertEqual(stats["missing_created"], 1)
        self.assertTrue((obj_dir / "Create_0.gml").exists())

    def test_sync_round_trips_collision_event_filenames_and_references(self):
        target_name = "o_wall"
        target_dir = self.temp_dir / "objects" / target_name
        target_dir.mkdir()
        (target_dir / f"{target_name}.yy").write_text(
            json.dumps({"name": target_name, "resourceType": "GMObject"}),
            encoding="utf-8",
        )
        (self.temp_dir / "test.yyp").write_text(
            json.dumps(
                {
                    "resources": [
                        {
                            "id": {
                                "name": target_name,
                                "path": f"objects/{target_name}/{target_name}.yy",
                            }
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        owner_name = "o_collision_owner"
        owner_dir = self.temp_dir / "objects" / owner_name
        owner_dir.mkdir()
        owner_path = owner_dir / f"{owner_name}.yy"
        collision_reference = {
            "name": target_name,
            "path": f"objects/{target_name}/{target_name}.yy",
        }
        owner_path.write_text(
            json.dumps(
                {
                    "name": owner_name,
                    "eventList": [
                        {
                            "eventType": 4,
                            "eventNum": 0,
                            "collisionObjectId": collision_reference,
                            "resourceType": "GMEvent",
                            "resourceVersion": "2.0",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        missing_stats = sync_all_object_events(str(self.temp_dir), dry_run=False)
        collision_path = owner_dir / "Collision_o_wall.gml"
        self.assertEqual(missing_stats["missing_created"], 1)
        self.assertTrue(collision_path.exists())

        owner_path.write_text(json.dumps({"name": owner_name, "eventList": []}), encoding="utf-8")
        orphan_stats = sync_all_object_events(str(self.temp_dir), dry_run=False)
        restored = load_json_loose(owner_path)
        self.assertEqual(orphan_stats["orphaned_fixed"], 1)
        self.assertEqual(restored["eventList"][0]["collisionObjectId"], collision_reference)


if __name__ == "__main__":
    unittest.main()
