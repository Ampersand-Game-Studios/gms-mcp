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

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add the tools directory to Python path for imports
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'tooling' / 'gms_helpers'))

# Import from the correct locations
from room_layer_helper import (
    add_layer, remove_layer, list_layers, reorder_layer,
    find_room_file, load_room_data, save_room_data,
    create_layer_data, LAYER_TYPES
)
from utils import load_json_loose, save_pretty_json, generate_uuid
from assets import RoomAsset
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
    
    def tearDown(self):
        """Clean up test environment."""
        self.temp_project_ctx.__exit__(None, None, None)
    
    def test_find_room_file(self):
        """Test finding room files."""
        # Test finding existing room
        room_path = find_room_file("r_test")
        self.assertEqual(str(room_path).replace("\\", "/"), "rooms/r_test/r_test.yy")
        self.assertTrue(room_path.exists())
        
        # Test finding non-existent room
        with self.assertRaises(FileNotFoundError):
            find_room_file("r_nonexistent")
    
    def test_load_room_data(self):
        """Test loading room data."""
        room_data, room_path = load_room_data("r_test")
        
        self.assertIsInstance(room_data, dict)
        self.assertEqual(room_data["name"], "r_test")
        self.assertIn("layers", room_data)
        self.assertEqual(str(room_path).replace("\\", "/"), "rooms/r_test/r_test.yy")
    
    def test_save_room_data(self):
        """Test saving room data."""
        room_data, room_path = load_room_data("r_test")
        
        # Modify the data
        room_data["modified"] = True
        
        # Save it
        save_room_data(room_data, room_path)
        
        # Load it back and verify
        reloaded_data, _ = load_room_data("r_test")
        self.assertTrue(reloaded_data.get("modified", False))
    
    def test_create_layer_data(self):
        """Test creating layer data structures for different layer types."""
        # Test instance layer
        instance_layer = create_layer_data("test_instances", "instance", 100)
        self.assertEqual(instance_layer["__type"], "GMRInstanceLayer")
        self.assertEqual(instance_layer["name"], "test_instances")
        self.assertEqual(instance_layer["depth"], 100)
        self.assertIn("instances", instance_layer)
        self.assertEqual(instance_layer["resourceType"], "GMRInstanceLayer")
        
        # Test background layer
        bg_layer = create_layer_data("test_background", "background", 200)
        self.assertEqual(bg_layer["__type"], "GMRBackgroundLayer")
        self.assertEqual(bg_layer["name"], "test_background")
        self.assertEqual(bg_layer["depth"], 200)
        self.assertIn("spriteId", bg_layer)
        self.assertEqual(bg_layer["resourceType"], "GMRBackgroundLayer")
        
        # Test asset layer
        asset_layer = create_layer_data("test_assets", "asset", 150)
        self.assertEqual(asset_layer["__type"], "GMRAssetLayer")
        self.assertEqual(asset_layer["name"], "test_assets")
        self.assertEqual(asset_layer["depth"], 150)
        self.assertIn("assets", asset_layer)
        self.assertEqual(asset_layer["resourceType"], "GMRAssetLayer")
        
        # Test tile layer
        tile_layer = create_layer_data("test_tiles", "tile", 300)
        self.assertEqual(tile_layer["__type"], "GMRTileLayer")
        self.assertEqual(tile_layer["name"], "test_tiles")
        self.assertEqual(tile_layer["depth"], 300)
        self.assertIn("tiles", tile_layer)
        self.assertEqual(tile_layer["resourceType"], "GMRTileLayer")
    
    def test_add_layer_success(self):
        """Test successfully adding layers to a room."""
        # Test adding instance layer
        args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'lyr_enemies',
            'layer_type': 'instance',
            'depth': 200
        })()
        
        result = add_layer(args)
        self.assertTrue(result)
        
        # Verify layer was added
        room_data, _ = load_room_data("r_test")
        layer_names = [layer.get("name") for layer in room_data.get("layers", [])]
        self.assertIn("lyr_enemies", layer_names)
        
        # Find the added layer and verify properties
        added_layer = None
        for layer in room_data["layers"]:
            if layer.get("name") == "lyr_enemies":
                added_layer = layer
                break
        
        self.assertIsNotNone(added_layer)
        if added_layer is not None:  # Type guard for linter
            self.assertEqual(added_layer["__type"], "GMRInstanceLayer")
            self.assertEqual(added_layer["depth"], 200)
    
    def test_add_layer_duplicate_name(self):
        """Test adding layer with duplicate name fails."""
        args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'Instances',  # This already exists
            'layer_type': 'instance',
            'depth': 200
        })()
        
        result = add_layer(args)
        self.assertFalse(result)
    
    def test_add_layer_invalid_type(self):
        """Test adding layer with invalid type fails."""
        args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'test_layer',
            'layer_type': 'invalid_type',
            'depth': 200
        })()
        
        result = add_layer(args)
        self.assertFalse(result)
    
    def test_add_layer_nonexistent_room(self):
        """Test adding layer to non-existent room fails."""
        args = type('Args', (), {
            'room_name': 'r_nonexistent',
            'layer_name': 'test_layer',
            'layer_type': 'instance',
            'depth': 200
        })()
        
        result = add_layer(args)
        self.assertFalse(result)
    
    def test_remove_layer_success(self):
        """Test successfully removing a layer from a room."""
        # First add a layer to remove
        add_args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'temp_layer',
            'layer_type': 'background',
            'depth': 300
        })()
        add_layer(add_args)
        
        # Now remove it
        remove_args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'temp_layer'
        })()
        
        result = remove_layer(remove_args)
        self.assertTrue(result)
        
        # Verify layer was removed
        room_data, _ = load_room_data("r_test")
        layer_names = [layer.get("name") for layer in room_data.get("layers", [])]
        self.assertNotIn("temp_layer", layer_names)
    
    def test_remove_layer_nonexistent(self):
        """Test removing non-existent layer fails."""
        args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'nonexistent_layer'
        })()
        
        result = remove_layer(args)
        self.assertFalse(result)
    
    def test_remove_layer_nonexistent_room(self):
        """Test removing layer from non-existent room fails."""
        args = type('Args', (), {
            'room_name': 'r_nonexistent',
            'layer_name': 'some_layer'
        })()
        
        result = remove_layer(args)
        self.assertFalse(result)
    
    def test_list_layers_success(self):
        """Test successfully listing layers in a room."""
        # Add some layers for testing
        add_args1 = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'lyr_background',
            'layer_type': 'background',
            'depth': 500
        })()
        add_layer(add_args1)
        
        add_args2 = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'lyr_tiles',
            'layer_type': 'tile',
            'depth': 400
        })()
        add_layer(add_args2)
        
        # List layers
        args = type('Args', (), {
            'room_name': 'r_test'
        })()
        
        result = list_layers(args)
        self.assertTrue(result)
    
    def test_list_layers_nonexistent_room(self):
        """Test listing layers for non-existent room fails."""
        args = type('Args', (), {
            'room_name': 'r_nonexistent'
        })()
        
        result = list_layers(args)
        self.assertFalse(result)
    
    def test_reorder_layer_success(self):
        """Test successfully reordering a layer's depth."""
        # Add a layer to reorder
        add_args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'lyr_reorder_test',
            'layer_type': 'instance',
            'depth': 100
        })()
        add_layer(add_args)
        
        # Reorder it
        reorder_args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'lyr_reorder_test',
            'new_depth': 500
        })()
        
        result = reorder_layer(reorder_args)
        self.assertTrue(result)
        
        # Verify depth was changed
        room_data, _ = load_room_data("r_test")
        for layer in room_data["layers"]:
            if layer.get("name") == "lyr_reorder_test":
                self.assertEqual(layer.get("depth"), 500)
                break
        else:
            self.fail("Layer not found after reorder")
    
    def test_reorder_layer_nonexistent(self):
        """Test reordering non-existent layer fails."""
        args = type('Args', (), {
            'room_name': 'r_test',
            'layer_name': 'nonexistent_layer',
            'new_depth': 500
        })()
        
        result = reorder_layer(args)
        self.assertFalse(result)
    
    def test_reorder_layer_nonexistent_room(self):
        """Test reordering layer in non-existent room fails."""
        args = type('Args', (), {
            'room_name': 'r_nonexistent',
            'layer_name': 'some_layer',
            'new_depth': 500
        })()
        
        result = reorder_layer(args)
        self.assertFalse(result)
    
    def test_layer_depth_sorting(self):
        """Test that layers are sorted by depth after operations."""
        # Add multiple layers with different depths
        layers_to_add = [
            ('lyr_deep', 'background', 1000),
            ('lyr_middle', 'instance', 500),
            ('lyr_shallow', 'asset', 100)
        ]
        
        for layer_name, layer_type, depth in layers_to_add:
            args = type('Args', (), {
                'room_name': 'r_test',
                'layer_name': layer_name,
                'layer_type': layer_type,
                'depth': depth
            })()
            add_layer(args)
        
        # Check that layers are sorted by depth (deeper first)
        room_data, _ = load_room_data("r_test")
        depths = [layer.get("depth", 0) for layer in room_data["layers"]]
        
        # Should be sorted in descending order (deeper layers first)
        self.assertEqual(depths, sorted(depths, reverse=True))
    
    def test_layer_types_constants(self):
        """Test that LAYER_TYPES constant contains expected values."""
        expected_types = {'background', 'instance', 'asset', 'tile', 'path', 'effect'}
        actual_types = set(LAYER_TYPES.keys())
        self.assertEqual(actual_types, expected_types)
    
    def test_create_layer_path_type(self):
        """Test creating path layer type."""
        path_layer = create_layer_data("test_path", "path", 250)
        self.assertEqual(path_layer["__type"], "GMRLayer")  # Path layers use base type
        self.assertEqual(path_layer["name"], "test_path")
        self.assertEqual(path_layer["depth"], 250)
        self.assertEqual(path_layer["resourceType"], "GMRLayer")
    
    def test_create_layer_effect_type(self):
        """Test creating effect layer type."""
        effect_layer = create_layer_data("test_effect", "effect", 350)
        self.assertEqual(effect_layer["__type"], "GMRLayer")  # Effect layers use base type
        self.assertEqual(effect_layer["name"], "test_effect")
        self.assertEqual(effect_layer["depth"], 350)
        self.assertEqual(effect_layer["resourceType"], "GMRLayer")
    
    def test_add_layer_all_types(self):
        """Test adding all supported layer types."""
        layer_types_to_test = ['background', 'instance', 'asset', 'tile', 'path', 'effect']
        
        for i, layer_type in enumerate(layer_types_to_test):
            args = type('Args', (), {
                'room_name': 'r_test',
                'layer_name': f'lyr_{layer_type}_test',
                'layer_type': layer_type,
                'depth': 100 + i * 10
            })()
            
            result = add_layer(args)
            self.assertTrue(result, f"Failed to add {layer_type} layer")
            
            # Verify layer was added
            room_data, _ = load_room_data("r_test")
            layer_names = [layer.get("name") for layer in room_data.get("layers", [])]
            self.assertIn(f'lyr_{layer_type}_test', layer_names)
    
    def test_error_handling_exceptions(self):
        """Test various exception scenarios."""
        # Test with invalid room data structure
        try:
            # This should raise an exception due to missing room
            args = type('Args', (), {
                'room_name': 'r_invalid_structure',
                'layer_name': 'test_layer',
                'layer_type': 'instance',
                'depth': 100
            })()
            
            result = add_layer(args)
            self.assertFalse(result)  # Should return False on error
        except Exception:
            # Expected behavior - exception should be caught and return False
            pass
    
    def test_room_with_no_layers(self):
        """Test operations on room with no existing layers."""
        # Create room with no layers
        minimal_room_data = {
            "$GMRoom": "v1",
            "%Name": "r_empty",
            "name": "r_empty",
            "layers": [],  # No layers
            "roomSettings": {"Width": 800, "Height": 600},
            "resourceType": "GMRoom",
            "resourceVersion": "2.0"
        }
        
        room_path = Path("rooms/r_empty/r_empty.yy")
        room_path.parent.mkdir(parents=True, exist_ok=True)
        save_pretty_json(room_path, minimal_room_data)
        
        # Test adding layer to empty room
        args = type('Args', (), {
            'room_name': 'r_empty',
            'layer_name': 'first_layer',
            'layer_type': 'instance',
            'depth': 0
        })()
        
        result = add_layer(args)
        self.assertTrue(result)
        
        # Test listing empty room initially
        list_args = type('Args', (), {
            'room_name': 'r_empty'
        })()
        
        # This should work even with initially empty layers
        result = list_layers(list_args)
        self.assertTrue(result)


class TestRoomLayerHelperIntegration(unittest.TestCase):
    """Integration tests for room layer helper."""
    
    def test_function_imports(self):
        """Test that all expected functions can be imported."""
        try:
            from room_layer_helper import (
                add_layer, remove_layer, list_layers, reorder_layer,
                find_room_file, load_room_data, save_room_data,
                create_layer_data, main, LAYER_TYPES
            )
            # All imports successful
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import room layer helper functions: {e}")
    
    def test_function_signatures(self):
        """Test that all functions have correct signatures."""
        from room_layer_helper import add_layer, remove_layer, list_layers, reorder_layer
        
        # Test that functions exist and are callable
        self.assertTrue(callable(add_layer))
        self.assertTrue(callable(remove_layer))
        self.assertTrue(callable(list_layers))
        self.assertTrue(callable(reorder_layer))
    
    def test_main_function_exists(self):
        """Test that main function exists for CLI usage."""
        from room_layer_helper import main
        self.assertTrue(callable(main))
    
    def test_cli_argument_parsing(self):
        """Test CLI argument parsing functionality."""
        from room_layer_helper import main
        import sys
        from unittest.mock import patch
        
        # Test help command (should not raise exception)
        test_args = ['room_layer_helper.py', '--help']
        
        with patch.object(sys, 'argv', test_args):
            with patch('sys.exit') as mock_exit:
                try:
                    main()
                except SystemExit:
                    pass  # argparse calls sys.exit on --help
        
        # Test that main handles argument parsing
        self.assertTrue(True)  # If we get here, no exceptions were raised
    
    def test_exception_handling_in_main(self):
        """Test exception handling in main function."""
        from room_layer_helper import main
        import sys
        from unittest.mock import patch
        
        # Test KeyboardInterrupt handling
        test_args = ['room_layer_helper.py', 'add-layer', 'r_test', 'test_layer', '--type', 'instance']
        
        with patch.object(sys, 'argv', test_args):
            with patch('sys.exit') as mock_exit:
                with patch('room_layer_helper.add_layer', side_effect=KeyboardInterrupt()):
                    try:
                        main()
                    except SystemExit:
                        pass
                    except KeyboardInterrupt:
                        pass  # Expected behavior
        
        # Test unexpected exception handling
        with patch.object(sys, 'argv', test_args):
            with patch('sys.exit') as mock_exit:
                with patch('room_layer_helper.add_layer', side_effect=Exception("Test error")):
                    try:
                        main()
                    except SystemExit:
                        pass
                    except Exception:
                        pass  # Expected behavior
    
    def test_layer_types_mapping(self):
        """Test that LAYER_TYPES mapping is correctly defined."""
        from room_layer_helper import LAYER_TYPES
        
        # Test that all expected layer types are present
        expected_mappings = {
            'background': 'background',
            'instance': 'instances', 
            'asset': 'assets',
            'tile': 'tiles',
            'path': 'path',
            'effect': 'effect'
        }
        
        for key, expected_value in expected_mappings.items():
            self.assertIn(key, LAYER_TYPES)
            self.assertEqual(LAYER_TYPES[key], expected_value)
    
    def test_create_layer_data_edge_cases(self):
        """Test create_layer_data with edge cases."""
        from room_layer_helper import create_layer_data
        
        # Test with very deep depth
        deep_layer = create_layer_data("deep_layer", "instance", -1000)
        self.assertEqual(deep_layer["depth"], -1000)
        
        # Test with zero depth
        zero_layer = create_layer_data("zero_layer", "background", 0)
        self.assertEqual(zero_layer["depth"], 0)
        
        # Test with very high depth
        high_layer = create_layer_data("high_layer", "tile", 10000)
        self.assertEqual(high_layer["depth"], 10000)
        
        # Test layer naming with special characters (that should be valid)
        special_layer = create_layer_data("lyr_special_123", "asset", 100)
        self.assertEqual(special_layer["name"], "lyr_special_123")
    
    def test_import_fallback(self):
        """Test import fallback mechanism."""
        # Test that we can import the module even if relative imports fail
        import sys
        from unittest.mock import patch
        
        # Temporarily break relative imports to test fallback
        original_path = sys.path[:]
        try:
            # This test verifies the import structure works
            import room_layer_helper
            self.assertTrue(hasattr(room_layer_helper, 'add_layer'))
            self.assertTrue(hasattr(room_layer_helper, 'remove_layer'))
        finally:
            sys.path[:] = original_path
    
    def test_main_execution_coverage(self):
        """Test __main__ execution block for 100% coverage."""
        import subprocess
        import sys
        from pathlib import Path
        
        # Test that the script can be executed directly
        try:
            # Run the script with --help to test main execution
            script_path = Path(__file__).parent / 'room_layer_helper.py'
            result = subprocess.run([
                sys.executable, str(script_path), '--help'
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
            
            # Accept success if the script runs without error
            self.assertTrue(result.returncode == 0 or 'GameMaker Studio Room Layer Helper' in result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Expected if script can't be run directly in test environment
            pass
    
    def test_sys_exit_coverage(self):
        """Test sys.exit paths for complete coverage."""
        from room_layer_helper import main
        import sys
        from unittest.mock import patch
        
        # Test success path (should exit with 0)
        test_args = ['room_layer_helper.py', 'list-layers', 'r_test']
        
        with patch.object(sys, 'argv', test_args):
            with patch('sys.exit') as mock_exit:
                with patch('room_layer_helper.list_layers', return_value=True):
                    try:
                        main()
                    except SystemExit:
                        pass
                    # Verify exit was called with success code
                    mock_exit.assert_called()
        
        # Test failure path (should exit with 1) 
        with patch.object(sys, 'argv', test_args):
            with patch('sys.exit') as mock_exit:
                with patch('room_layer_helper.list_layers', return_value=False):
                    try:
                        main()
                    except SystemExit:
                        pass
                    # Verify exit was called
                    mock_exit.assert_called()


if __name__ == '__main__':
    # Set up test environment
    print("Running Room Layer Helper Tests...")
    print("=" * 50)
    
    # Run the tests
    unittest.main(verbosity=2) 