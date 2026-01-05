#!/usr/bin/env python3
"""
Test suite for room instance management operations.
Tests the room_instance_helper.py functionality for managing instances within GameMaker rooms.
"""

import unittest
import tempfile
import shutil
import sys
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to Python path for imports
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import from the correct locations
from gms_helpers.room_instance_helper import (
    add_instance, remove_instance, list_instances, modify_instance, set_creation_code,
    _find_room_file, _load_room_data, _save_room_data, _find_layer_by_name
)
from gms_helpers.utils import load_json_loose, save_pretty_json, generate_uuid
from gms_helpers.assets import RoomAsset
from gms_helpers.exceptions import AssetNotFoundError, ValidationError
from test_workflow import TempProject  # Import from where it's actually defined


class TestRoomInstanceHelper(unittest.TestCase):
    """Test suite for room instance helper functionality."""

    def setUp(self):
        """Set up test environment."""
        self.temp_project_ctx = TempProject()
        self.project_dir = self.temp_project_ctx.__enter__()

        # Create a test room with basic structure
        self.room_asset = RoomAsset()
        self.room_asset.create_files(self.project_dir, "r_test", "", width=800, height=600)

        # Create basic room data structure with an Instances layer
        self.basic_room_data = {
            "$GMRoom": "v1",
            "%Name": "r_test",
            "name": "r_test",
            "layers": [
                {
                    "__type": "GMRInstanceLayer",
                    "depth": 0,
                    "name": "Instances",
                    "instances": [],
                    "visible": True,
                    "resourceType": "GMRInstanceLayer"
                }
            ],
            "roomSettings": {
                "Width": 800,
                "Height": 600
            },
            "resourceType": "GMRoom",
            "resourceVersion": "2.0"
        }

        # Save the room data
        room_path = Path("rooms/r_test/r_test.yy")
        room_path.parent.mkdir(parents=True, exist_ok=True)
        save_pretty_json(room_path, self.basic_room_data)
        
        # Create a minimal object for testing
        obj_dir = Path("objects/o_player")
        obj_dir.mkdir(parents=True, exist_ok=True)
        obj_data = {
            "$GMObject": "v1",
            "%Name": "o_player",
            "name": "o_player",
            "resourceType": "GMObject",
            "resourceVersion": "2.0"
        }
        with open(obj_dir / "o_player.yy", 'w') as f:
            json.dump(obj_data, f)

    def tearDown(self):
        """Clean up test environment."""
        self.temp_project_ctx.__exit__(None, None, None)

    def test_find_room_file(self):
        """Test finding room files."""
        # Test finding existing room
        room_path = _find_room_file("r_test")
        self.assertTrue(room_path.exists())
        self.assertTrue(str(room_path).endswith("r_test.yy"))

        # Test finding non-existent room raises AssetNotFoundError
        with self.assertRaises(AssetNotFoundError):
            _find_room_file("r_nonexistent")

    def test_load_room_data(self):
        """Test loading room data."""
        room_path = _find_room_file("r_test")
        room_data = _load_room_data(room_path)

        self.assertIsInstance(room_data, dict)
        self.assertEqual(room_data["name"], "r_test")
        self.assertIn("layers", room_data)

    def test_save_room_data(self):
        """Test saving room data."""
        room_path = _find_room_file("r_test")
        room_data = _load_room_data(room_path)

        # Modify the data
        room_data["modified"] = True

        # Save it
        _save_room_data(room_path, room_data)

        # Load it back and verify
        reloaded_data = _load_room_data(room_path)
        self.assertTrue(reloaded_data.get("modified", False))

    def test_find_layer_by_name(self):
        """Test finding layers by name."""
        room_path = _find_room_file("r_test")
        room_data = _load_room_data(room_path)
        
        # Should find existing layer
        layer = _find_layer_by_name(room_data, "Instances")
        self.assertIsNotNone(layer)
        self.assertEqual(layer["name"], "Instances")
        
        # Should raise ValidationError for non-existent layer
        with self.assertRaises(ValidationError):
            _find_layer_by_name(room_data, "NonExistent")

    def test_add_instance_success(self):
        """Test successfully adding instances to a room."""
        # Test adding an instance using library-style API
        result = add_instance("r_test", "o_player", 100.0, 200.0, "Instances")
        self.assertIsNotNone(result)  # Should return instance ID

        # Verify instance was added
        room_path = _find_room_file("r_test")
        room_data = _load_room_data(room_path)
        instances_layer = _find_layer_by_name(room_data, "Instances")
        self.assertIsNotNone(instances_layer)
        self.assertGreater(len(instances_layer.get("instances", [])), 0)

    def test_remove_instance_success(self):
        """Test successfully removing an instance from a room."""
        # First add an instance to remove
        instance_id = add_instance("r_test", "o_player", 100.0, 200.0, "Instances")
        self.assertIsNotNone(instance_id)

        # Now remove it
        result = remove_instance("r_test", instance_id)
        self.assertTrue(result)

        # Verify instance was removed
        room_path = _find_room_file("r_test")
        room_data = _load_room_data(room_path)
        instances_layer = _find_layer_by_name(room_data, "Instances")
        instance_ids = [inst.get("name") for inst in instances_layer.get("instances", [])]
        self.assertNotIn(instance_id, instance_ids)

    def test_list_instances_success(self):
        """Test successfully listing instances in a room."""
        # Add some instances for testing
        add_instance("r_test", "o_player", 100.0, 200.0, "Instances")
        add_instance("r_test", "o_player", 300.0, 400.0, "Instances")

        # List instances
        result = list_instances("r_test")
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_list_instances_with_layer_filter(self):
        """Test listing instances filtered by layer."""
        # Add an instance
        add_instance("r_test", "o_player", 100.0, 200.0, "Instances")

        # List instances with filter
        result = list_instances("r_test", layer_name="Instances")
        self.assertIsInstance(result, list)


class TestRoomInstanceHelperIntegration(unittest.TestCase):
    """Integration tests for room instance helper."""

    def test_function_imports(self):
        """Test that all expected functions can be imported."""
        try:
            from gms_helpers.room_instance_helper import (
                add_instance, remove_instance, list_instances, modify_instance, set_creation_code,
                _find_room_file, _load_room_data, _save_room_data, _find_layer_by_name, main
            )
            # All imports successful
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import room instance helper functions: {e}")

    def test_function_signatures(self):
        """Test that all functions have correct signatures."""
        from gms_helpers.room_instance_helper import add_instance, remove_instance, list_instances

        # Test that functions exist and are callable
        self.assertTrue(callable(add_instance))
        self.assertTrue(callable(remove_instance))
        self.assertTrue(callable(list_instances))

    def test_main_function_exists(self):
        """Test that main function exists for CLI usage."""
        from gms_helpers.room_instance_helper import main
        self.assertTrue(callable(main))


if __name__ == '__main__':
    # Set up test environment
    print("Running Room Instance Helper Tests...")
    print("=" * 50)

    # Run the tests
    unittest.main(verbosity=2)
