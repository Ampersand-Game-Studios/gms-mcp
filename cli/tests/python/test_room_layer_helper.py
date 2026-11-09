#!/usr/bin/env python3
"""
Test suite for room layer management operations.
Tests the room_layer_helper.py functionality for managing layers within GameMaker rooms.
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
from gms_helpers.room_layer_helper import (
    add_layer,
    remove_layer,
    list_layers,
    reorder_layer,
    _find_room_file,
    _load_room_data,
    _save_room_data,
    create_layer_data,
    LAYER_TYPES,
)
from gms_helpers.utils import load_json_loose, save_pretty_json, generate_uuid
from gms_helpers.assets import RoomAsset
from gms_helpers.exceptions import AssetNotFoundError, ValidationError
from test_workflow import TempProject  # Import from where it's actually defined


class TestRoomLayerHelper(unittest.TestCase):
    """Test suite for room layer helper functionality."""

    def setUp(self):
        """Set up test environment."""
        self.temp_project_ctx = TempProject()
        self.project_dir = self.temp_project_ctx.__enter__()

        # Create a test room with basic structure
        self.room_asset = RoomAsset()
        self.room_asset.create_files(self.project_dir, "r_test", "", width=800, height=600)

        # Create basic room data structure
        self.basic_room_data = {
            "$GMRoom": "v1",
            "%Name": "r_test",
            "name": "r_test",
            "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
            "layers": [
                {
                    "__type": "GMRInstanceLayer",
                    "depth": 0,
                    "name": "Instances",
                    "instances": [],
                    "visible": True,
                    "resourceType": "GMRInstanceLayer",
                }
            ],
            "roomSettings": {"Width": 800, "Height": 600},
            "resourceType": "GMRoom",
            "resourceVersion": "2.0",
        }

        # Save the room data
        room_path = Path("rooms/r_test/r_test.yy")
        room_path.parent.mkdir(parents=True, exist_ok=True)
        save_pretty_json(room_path, self.basic_room_data)
        yyp_path = self.project_dir / "test.yyp"
        yyp_data = load_json_loose(yyp_path)
        yyp_data["resources"] = [{"id": {"name": "r_test", "path": "rooms/r_test/r_test.yy"}}]
        save_pretty_json(yyp_path, yyp_data)

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

    def test_create_layer_data(self):
        """Test creating layer data structures for different layer types."""
        # Test instance layer - signature is (name, layer_type, depth)
        instance_layer = create_layer_data("test_instances", "instance", 100)
        self.assertEqual(instance_layer["name"], "test_instances")
        self.assertEqual(instance_layer["depth"], 100)
        self.assertIn("instances", instance_layer)

        # Test background layer
        bg_layer = create_layer_data("test_background", "background", 200)
        self.assertEqual(bg_layer["name"], "test_background")
        self.assertEqual(bg_layer["depth"], 200)

    def test_add_layer_success(self):
        """Test successfully adding layers to a room."""
        # Test adding instance layer using library-style API
        result = add_layer("r_test", "lyr_enemies", "instance", 200)
        self.assertTrue(result)

        # Verify layer was added
        room_path = _find_room_file("r_test")
        room_data = _load_room_data(room_path)
        layer_names = [layer.get("name") for layer in room_data.get("layers", [])]
        self.assertIn("lyr_enemies", layer_names)

    def test_add_layer_duplicate_name(self):
        """Test adding layer with duplicate name raises ValidationError."""
        # Add a layer first
        add_layer("r_test", "test_duplicate", "instance", 100)

        # Try to add another layer with the same name - should raise ValidationError
        with self.assertRaises(ValidationError):
            add_layer("r_test", "test_duplicate", "instance", 200)

    def test_add_layer_rejects_room_name_path_traversal(self):
        """Room names must not be able to mutate .yy files outside the project."""
        base = self.project_dir / "traversal_case"
        project_dir = base / "workspace" / "project"
        outside_room_dir = project_dir.parent / "victim"
        outside_room_file = base / "victim.yy"
        outside_room_data = {
            "$GMRoom": "v1",
            "%Name": "victim",
            "name": "victim",
            "layers": [],
            "resourceType": "GMRoom",
            "resourceVersion": "2.0",
        }

        project_dir.mkdir(parents=True)
        (project_dir / "rooms").mkdir()
        (project_dir / "test.yyp").write_text("{}")
        outside_room_dir.mkdir(parents=True)
        outside_room_file.write_text(json.dumps(outside_room_data), encoding="utf-8")

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with self.assertRaises(ValidationError):
                add_layer("../../victim", "escaped", "instance", 0)
        finally:
            os.chdir(old_cwd)

        self.assertEqual(json.loads(outside_room_file.read_text(encoding="utf-8"))["layers"], [])

    def test_remove_layer_success(self):
        """Test successfully removing a layer from a room."""
        # First add a layer to remove
        add_layer("r_test", "temp_layer", "background", 300)

        # Now remove it
        result = remove_layer("r_test", "temp_layer")
        self.assertTrue(result)

        # Verify layer was removed
        room_path = _find_room_file("r_test")
        room_data = _load_room_data(room_path)
        layer_names = [layer.get("name") for layer in room_data.get("layers", [])]
        self.assertNotIn("temp_layer", layer_names)

    def test_remove_layer_nonexistent(self):
        """Test removing non-existent layer raises AssetNotFoundError."""
        with self.assertRaises(AssetNotFoundError):
            remove_layer("r_test", "nonexistent_layer")

    def test_list_layers_success(self):
        """Test successfully listing layers in a room."""
        # Add some layers for testing
        add_layer("r_test", "lyr_background", "background", 500)
        add_layer("r_test", "lyr_assets", "asset", 400)

        # List layers
        result = list_layers("r_test")
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_layers_stay_in_ascending_depth_order(self):
        add_layer("r_test", "lyr_back", "background", 500)
        add_layer("r_test", "lyr_front", "instance", -100)
        add_layer("r_test", "lyr_top", "instance")
        data = _load_room_data(_find_room_file("r_test"))
        self.assertEqual(
            [(layer["name"], layer["depth"]) for layer in data["layers"]],
            [("lyr_top", -200), ("lyr_front", -100), ("Instances", 0), ("lyr_back", 500)],
        )
        self.assertTrue(data["layers"][1]["userdefinedDepth"])
        self.assertFalse(data["layers"][0]["userdefinedDepth"])

    def test_reorder_sorts_nested_siblings_ascending(self):
        room_path = _find_room_file("r_test")
        data = _load_room_data(room_path)
        children = [create_layer_data(name, "instance", depth) for name, depth in (("a", 0), ("b", 10), ("c", 20))]
        data["layers"].append({"name": "Folder", "resourceType": "GMRLayer", "depth": 900, "layers": children})
        _save_room_data(room_path, data)
        self.assertTrue(reorder_layer("r_test", "a", 15))
        folder = _load_room_data(room_path)["layers"][-1]
        self.assertEqual([layer["name"] for layer in folder["layers"]], ["b", "a", "c"])
        self.assertTrue(folder["layers"][1]["userdefinedDepth"])

    def test_tile_layer_needs_tileset_and_covers_the_room(self):
        with self.assertRaises(ValidationError):
            add_layer("r_test", "lyr_tiles", "tile", 400)
        tileset_dir = Path("tilesets/ts_ground")
        tileset_dir.mkdir(parents=True)
        save_pretty_json(
            tileset_dir / "ts_ground.yy",
            {"$GMTileSet": "v1", "name": "ts_ground", "resourceType": "GMTileSet", "tileWidth": 32, "tileHeight": 48},
        )
        yyp_path = self.project_dir / "test.yyp"
        yyp_data = load_json_loose(yyp_path)
        yyp_data["resources"].append({"id": {"name": "ts_ground", "path": "tilesets/ts_ground/ts_ground.yy"}})
        save_pretty_json(yyp_path, yyp_data)
        self.assertTrue(add_layer("r_test", "lyr_tiles", "tile", 400, tileset_name="ts_ground"))
        layer = next(l for l in _load_room_data(_find_room_file("r_test"))["layers"] if l["name"] == "lyr_tiles")
        self.assertEqual(layer["tilesetId"]["name"], "ts_ground")
        self.assertEqual(
            {key: layer["tiles"][key] for key in ("SerialiseWidth", "SerialiseHeight", "TileDataFormat")},
            {"SerialiseWidth": 25, "SerialiseHeight": 13, "TileDataFormat": 1},
        )
        self.assertEqual(layer["tiles"]["TileCompressedData"], [-325, -2147483648])

    def test_remove_layer_removes_instance_creation_code(self):
        room_path = _find_room_file("r_test")
        data = _load_room_data(room_path)
        data["layers"][0]["instances"] = [{"name": "inst_a"}, {"objectId": None}]
        data["instanceCreationOrder"] = [{"name": "inst_a", "path": "rooms/r_test/r_test.yy"}]
        _save_room_data(room_path, data)
        code = room_path.parent / "InstanceCreationCode_inst_a.gml"
        code.write_text("hp = 1;", encoding="utf-8")
        self.assertTrue(remove_layer("r_test", "Instances"))
        self.assertFalse(code.exists())
        self.assertEqual(_load_room_data(room_path)["instanceCreationOrder"], [])

    def test_legacy_room_format_is_refused(self):
        room_path = _find_room_file("r_test")
        data = _load_room_data(room_path)
        del data["$GMRoom"]
        data["resourceVersion"] = "1.0"
        _save_room_data(room_path, data)
        with self.assertRaisesRegex(ValidationError, "pre-2023"):
            add_layer("r_test", "lyr_new", "instance", 0)

    def test_module_cli_runs_through_the_project_transaction(self):
        from unittest.mock import patch
        import sys as _sys
        from gms_helpers import room_layer_helper

        with (
            patch.object(
                _sys, "argv", ["room_layer_helper", "reorder-layer", "r_test", "Instances", "--new-depth", "5"]
            ),
            patch("gms_helpers.gms._execute_project_command", return_value=True) as execute,
        ):
            self.assertTrue(room_layer_helper.main())
        args = execute.call_args.args[0]
        self.assertEqual((args.category, args.room_category, args.layer_action), ("room", "layer", "reorder"))

    def test_layer_types_constants(self):
        """Test that LAYER_TYPES constant contains expected values."""
        expected_types = {"background", "instance", "asset", "tile", "path", "effect"}
        actual_types = set(LAYER_TYPES.keys())
        self.assertEqual(actual_types, expected_types)


class TestRoomLayerHelperIntegration(unittest.TestCase):
    """Integration tests for room layer helper."""

    def test_function_imports(self):
        """Test that all expected functions can be imported."""
        try:
            from gms_helpers.room_layer_helper import (
                add_layer,
                remove_layer,
                list_layers,
                reorder_layer,
                _find_room_file,
                _load_room_data,
                _save_room_data,
                create_layer_data,
                main,
                LAYER_TYPES,
            )

            # All imports successful
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import room layer helper functions: {e}")

    def test_function_signatures(self):
        """Test that all functions have correct signatures."""
        from gms_helpers.room_layer_helper import add_layer, remove_layer, list_layers, reorder_layer

        # Test that functions exist and are callable
        self.assertTrue(callable(add_layer))
        self.assertTrue(callable(remove_layer))
        self.assertTrue(callable(list_layers))
        self.assertTrue(callable(reorder_layer))

    def test_main_function_exists(self):
        """Test that main function exists for CLI usage."""
        from gms_helpers.room_layer_helper import main

        self.assertTrue(callable(main))

    def test_layer_types_mapping(self):
        """Test that LAYER_TYPES mapping is correctly defined."""
        from gms_helpers.room_layer_helper import LAYER_TYPES

        # Test that all expected layer types are present
        expected_keys = {"background", "instance", "asset", "tile", "path", "effect"}

        for key in expected_keys:
            self.assertIn(key, LAYER_TYPES)

    def test_create_layer_data_edge_cases(self):
        """Test create_layer_data with edge cases."""
        from gms_helpers.room_layer_helper import create_layer_data

        # Test with very deep depth - signature is (name, layer_type, depth)
        deep_layer = create_layer_data("deep_layer", "instance", -1000)
        self.assertEqual(deep_layer["depth"], -1000)

        # Test with zero depth
        zero_layer = create_layer_data("zero_layer", "background", 0)
        self.assertEqual(zero_layer["depth"], 0)

        # Test with very high depth
        high_layer = create_layer_data("high_layer", "asset", 10000)
        self.assertEqual(high_layer["depth"], 10000)

        # A tile layer cannot exist without a tileset and grid
        with self.assertRaises(ValidationError):
            create_layer_data("tiles", "tile", 0)


if __name__ == "__main__":
    # Set up test environment
    print("Running Room Layer Helper Tests...")
    print("=" * 50)

    # Run the tests
    unittest.main(verbosity=2)
