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
    _event_to_filename, _filename_to_event,
    add_event, remove_event, list_events, main
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
        self.yy_path.write_text(json.dumps({"name": "o_test", "eventList": []}))
        
        # Create fake .yyp
        (self.test_dir / "test.yyp").write_text("{}")

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

if __name__ == "__main__":
    unittest.main()
