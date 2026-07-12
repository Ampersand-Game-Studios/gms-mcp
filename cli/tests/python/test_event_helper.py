#!/usr/bin/env python3
"""
Unit tests for refactored event_helper.py
"""

import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, Mock
import unittest
import sys
import os

# Add src directory to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.event_helper import (
    _event_to_filename,
    _filename_to_event,
    add_event,
    duplicate_event,
    list_events,
    main,
    remove_event,
)
from gms_helpers.exceptions import AssetNotFoundError, ValidationError
from gms_helpers.utils import load_json_loose


class TestEventHelper(unittest.TestCase):
    """Test suite for refactored event helper functions."""

    def test_event_to_filename(self):
        """Test event type/num to filename conversion."""
        self.assertEqual(_event_to_filename(0, 0), "Create_0.gml")
        self.assertEqual(_event_to_filename(1, 0), "Destroy_0.gml")
        self.assertEqual(_event_to_filename(3, 2), "Step_2.gml")
        self.assertEqual(_event_to_filename(8, 64), "Draw_64.gml")

    def test_filename_to_event(self):
        """Test filename to event type/num conversion."""
        self.assertEqual(_filename_to_event("Create_0.gml"), (0, 0))
        self.assertEqual(_filename_to_event("Step_2.gml"), (3, 2))
        self.assertEqual(_filename_to_event("Draw_64.gml"), (8, 64))

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create minimal project structure
        (self.test_dir / "objects" / "o_test").mkdir(parents=True)
        self.yy_path = self.test_dir / "objects" / "o_test" / "o_test.yy"
        self.yy_path.write_text(json.dumps({"name": "o_test", "eventList": [], "resourceType": "GMObject"}))

        resources = [{"id": {"name": "o_test", "path": "objects/o_test/o_test.yy"}}]
        for target in ("o_enemy", "o_wall"):
            target_dir = self.test_dir / "objects" / target
            target_dir.mkdir(parents=True)
            (target_dir / f"{target}.yy").write_text(
                json.dumps({"name": target, "eventList": [], "resourceType": "GMObject"}),
                encoding="utf-8",
            )
            resources.append({"id": {"name": target, "path": f"objects/{target}/{target}.yy"}})

        # Create fake .yyp
        (self.test_dir / "test.yyp").write_text(json.dumps({"resources": resources}))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_add_event_success(self):
        """Test adding an event successfully."""
        result = add_event("o_test", "create")
        self.assertTrue(result)

        # Verify file created
        self.assertTrue((self.test_dir / "objects" / "o_test" / "Create_0.gml").exists())

        # Verify .yy updated
        data = load_json_loose(self.yy_path)
        self.assertEqual(len(data["eventList"]), 1)
        self.assertEqual(data["eventList"][0]["eventType"], 0)

    def test_add_event_invalid_spec(self):
        """Test adding an event with invalid specification."""
        with self.assertRaises(ValidationError):
            add_event("o_test", "invalid_type")

    def test_add_event_rejects_object_name_path_traversal(self):
        """Object names must not be able to target event files outside the project."""
        base = self.test_dir / "traversal_case"
        project_dir = base / "workspace" / "project"
        outside_object_dir = project_dir.parent / "victim"
        outside_object_file = base / "victim.yy"

        project_dir.mkdir(parents=True)
        (project_dir / "objects").mkdir()
        (project_dir / "test.yyp").write_text("{}")
        outside_object_dir.mkdir(parents=True)
        outside_object_file.write_text(json.dumps({"name": "victim", "eventList": []}), encoding="utf-8")

        os.chdir(project_dir)
        with self.assertRaises(ValidationError):
            add_event("../../victim", "create")

        self.assertEqual(json.loads(outside_object_file.read_text(encoding="utf-8"))["eventList"], [])
        self.assertFalse((outside_object_dir / "Create_0.gml").exists())

    def test_remove_event_success(self):
        """Test removing an event successfully."""
        # Add first
        add_event("o_test", "step")
        self.assertTrue((self.test_dir / "objects" / "o_test" / "Step_0.gml").exists())

        # Remove
        result = remove_event("o_test", "step")
        self.assertTrue(result)
        self.assertFalse((self.test_dir / "objects" / "o_test" / "Step_0.gml").exists())

        data = load_json_loose(self.yy_path)
        self.assertEqual(len(data["eventList"]), 0)

    def test_list_events(self):
        """Test listing events."""
        add_event("o_test", "create")
        add_event("o_test", "step")

        events = list_events("o_test")
        self.assertEqual(len(events), 2)
        filenames = [e["filename"] for e in events]
        self.assertIn("Create_0.gml", filenames)
        self.assertIn("Step_0.gml", filenames)

    def test_collision_event_round_trip(self):
        self.assertTrue(add_event("o_test", "collision:o_wall"))
        collision_file = self.test_dir / "objects" / "o_test" / "Collision_o_wall.gml"
        self.assertTrue(collision_file.exists())

        data = load_json_loose(self.yy_path)
        event = data["eventList"][0]
        self.assertEqual(event["eventType"], 4)
        self.assertEqual(event["eventNum"], 0)
        self.assertEqual(
            event["collisionObjectId"],
            {"name": "o_wall", "path": "objects/o_wall/o_wall.yy"},
        )

        listed = list_events("o_test")
        self.assertEqual(listed[0]["filename"], "Collision_o_wall.gml")
        self.assertEqual(listed[0]["collision_object"], "o_wall")

        self.assertTrue(remove_event("o_test", "collision:o_wall"))
        self.assertFalse(collision_file.exists())
        self.assertEqual(load_json_loose(self.yy_path)["eventList"], [])

    def test_collision_event_rejects_numeric_and_missing_targets(self):
        with self.assertRaises(ValidationError):
            add_event("o_test", "collision:0")
        with self.assertRaises(AssetNotFoundError):
            add_event("o_test", "collision:o_missing")
        self.assertFalse((self.test_dir / "objects" / "o_test" / "Collision_o_missing.gml").exists())

    def test_collision_event_duplicate_uses_target_spec_and_reference(self):
        add_event("o_test", "collision:o_enemy", template="// shared collision\n")
        self.assertTrue(duplicate_event("o_test", "collision:o_enemy", "collision:o_wall"))

        duplicated = self.test_dir / "objects" / "o_test" / "Collision_o_wall.gml"
        self.assertEqual(duplicated.read_text(encoding="utf-8"), "// shared collision\n")
        entries = load_json_loose(self.yy_path)["eventList"]
        wall_event = next(event for event in entries if event["collisionObjectId"]["name"] == "o_wall")
        self.assertEqual(
            wall_event["collisionObjectId"],
            {"name": "o_wall", "path": "objects/o_wall/o_wall.yy"},
        )


if __name__ == "__main__":
    unittest.main()
