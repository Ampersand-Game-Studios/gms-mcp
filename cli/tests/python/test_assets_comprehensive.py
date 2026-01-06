#!/usr/bin/env python3
"""
Comprehensive test suite for assets.py - Target: 90%+ Coverage
Tests all asset classes, error conditions, edge cases, and integration scenarios.
"""

import unittest
import tempfile
import shutil
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

import sys
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import all asset classes to test
try:
    from gms_helpers.assets import (
        ScriptAsset, ObjectAsset, SpriteAsset, RoomAsset, FolderAsset,
        FontAsset, ShaderAsset, AnimCurveAsset, SoundAsset, PathAsset,
        TileSetAsset, TimelineAsset, SequenceAsset, NoteAsset
    )
    from gms_helpers.base_asset import BaseAsset
    from gms_helpers.utils import generate_uuid, create_dummy_png, ensure_directory, load_json_loose
except ImportError as e:
    print(f"Import error: {e}")
    raise


class TestAssetsComprehensive(unittest.TestCase):
    """Comprehensive test suite for asset classes."""
    
    def setUp(self):
        """Set up test environment with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create basic project structure
        for folder in ['objects', 'scripts', 'sprites', 'rooms', 'folders']:
            (self.project_root / folder).mkdir(exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_folder_structure(self):
        """Create a basic folder structure for testing."""
        folders_dir = self.project_root / "folders"
        folders_dir.mkdir(exist_ok=True)
        
        # Create a test parent folder
        test_folder_path = folders_dir / "TestFolder.yy"
        test_folder_data = {
            "$GMFolder": "",
            "%Name": "TestFolder",
            "folderPath": "folders/TestFolder.yy",
            "name": "TestFolder",
            "resourceType": "GMFolder",
            "resourceVersion": "2.0"
        }
        
        with open(test_folder_path, 'w') as f:
            json.dump(test_folder_data, f, indent=2)
        
        return "folders/TestFolder.yy"
    
    def _create_basic_yyp_file(self):
        """Create a basic .yyp file for tests that require it."""
        yyp_path = self.project_root / "TestProject.yyp"
        yyp_data = {
            "$GMProject": "",
            "%Name": "TestProject",
            "name": "TestProject",
            "resources": [],
            "folders": [],
            "resourceType": "GMProject",
            "resourceVersion": "2.0"
        }
        
        with open(yyp_path, 'w') as f:
            json.dump(yyp_data, f, indent=2)
        
        return yyp_path


class TestBaseAsset(TestAssetsComprehensive):
    """Test BaseAsset abstract class functionality."""
    
    def test_base_asset_is_abstract(self):
        """Test that BaseAsset cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            BaseAsset()
    
    def test_base_asset_abstract_methods(self):
        """Test that BaseAsset requires implementation of abstract methods."""
        # Create a concrete class missing abstract methods
        class IncompleteAsset(BaseAsset):
            kind = "incomplete"
            folder_prefix = "incomplete"
            gm_tag = "GMIncomplete"
        
        with self.assertRaises(TypeError):
            IncompleteAsset()
    
    def test_base_asset_folder_path_normalization(self):
        """Test that get_folder_path normalizes names to lowercase."""
        class TestAsset(BaseAsset):
            kind = "test"
            folder_prefix = "tests"
            gm_tag = "GMTest"
            
            def create_yy_data(self, name, parent_path, **kwargs):
                return {}
            
            def create_stub_files(self, asset_folder, name, **kwargs):
                pass
        
        asset = TestAsset()
        
        # Test case normalization
        path = asset.get_folder_path(self.project_root, "TestAsset")
        expected = self.project_root / "tests" / "testasset"
        self.assertEqual(path, expected)
        
        # Test already lowercase
        path_lower = asset.get_folder_path(self.project_root, "testasset")
        self.assertEqual(path_lower, expected)
    
    def test_base_asset_yy_path_generation(self):
        """Test that get_yy_path generates correct paths."""
        class TestAsset(BaseAsset):
            kind = "test"
            folder_prefix = "tests"
            gm_tag = "GMTest"
            
            def create_yy_data(self, name, parent_path, **kwargs):
                return {}
            
            def create_stub_files(self, asset_folder, name, **kwargs):
                pass
        
        asset = TestAsset()
        asset_folder = self.project_root / "tests" / "testasset"
        
        yy_path = asset.get_yy_path(asset_folder, "TestAsset")
        expected = asset_folder / "TestAsset.yy"
        self.assertEqual(yy_path, expected)
    
    def test_base_asset_validate_name_basic(self):
        """Test basic name validation functionality."""
        class TestAsset(BaseAsset):
            kind = "test"
            folder_prefix = "tests"
            gm_tag = "GMTest"
            
            def create_yy_data(self, name, parent_path, **kwargs):
                return {}
            
            def create_stub_files(self, asset_folder, name, **kwargs):
                pass
        
        asset = TestAsset()
        
        # Valid names
        self.assertTrue(asset.validate_name("valid_name"))
        self.assertTrue(asset.validate_name("ValidName"))
        self.assertTrue(asset.validate_name("valid123"))
        
        # Invalid names
        self.assertFalse(asset.validate_name(""))
        self.assertFalse(asset.validate_name("invalid name"))  # space
        self.assertFalse(asset.validate_name("invalid@name"))  # special char
    
    def test_base_asset_get_parent_name(self):
        """Test parent name extraction from path."""
        class TestAsset(BaseAsset):
            kind = "test"
            folder_prefix = "tests"
            gm_tag = "GMTest"
            
            def create_yy_data(self, name, parent_path, **kwargs):
                return {}
            
            def create_stub_files(self, asset_folder, name, **kwargs):
                pass
        
        asset = TestAsset()
        
        # Test various path formats
        self.assertEqual(asset.get_parent_name("folders/TestFolder.yy"), "TestFolder")
        self.assertEqual(asset.get_parent_name("folders/subfolder/TestFolder.yy"), "TestFolder")
        self.assertEqual(asset.get_parent_name("TestFolder"), "TestFolder")


class TestScriptAsset(TestAssetsComprehensive):
    """Test ScriptAsset class comprehensively."""
    
    def setUp(self):
        super().setUp()
        self.script_asset = ScriptAsset()
        self.parent_path = self._create_test_folder_structure()
    
    def test_script_asset_properties(self):
        """Test ScriptAsset class properties."""
        self.assertEqual(self.script_asset.kind, "script")
        self.assertEqual(self.script_asset.folder_prefix, "scripts")
        self.assertEqual(self.script_asset.gm_tag, "GMScript")
    
    def test_script_create_yy_data_basic(self):
        """Test basic script .yy data creation."""
        yy_data = self.script_asset.create_yy_data("test_script", self.parent_path)
        
        # Verify required fields
        self.assertEqual(yy_data["$GMScript"], "v1")
        self.assertEqual(yy_data["%Name"], "test_script")
        self.assertEqual(yy_data["name"], "test_script")
        self.assertEqual(yy_data["resourceType"], "GMScript")
        self.assertEqual(yy_data["resourceVersion"], "2.0")
        self.assertFalse(yy_data["isCompatibility"])
        self.assertFalse(yy_data["isDnD"])
        
        # Verify parent structure
        self.assertIn("parent", yy_data)
        self.assertEqual(yy_data["parent"]["name"], "TestFolder")
        self.assertEqual(yy_data["parent"]["path"], self.parent_path)
    
    def test_script_create_stub_files(self):
        """Test script stub file creation."""
        asset_folder = self.project_root / "scripts" / "test_script"
        asset_folder.mkdir(parents=True)
        
        self.script_asset.create_stub_files(asset_folder, "test_script")
        
        # Verify GML file was created
        gml_file = asset_folder / "test_script.gml"
        self.assertTrue(gml_file.exists())
        
        # Verify GML content
        content = gml_file.read_text(encoding="utf-8")
        self.assertIn("function test_script()", content)
        self.assertIn("/// test_script()", content)
        self.assertIn("TODO", content)
    
    def test_script_create_stub_files_existing(self):
        """Test script stub file creation when file already exists."""
        asset_folder = self.project_root / "scripts" / "test_script"
        asset_folder.mkdir(parents=True)
        
        # Create existing file
        gml_file = asset_folder / "test_script.gml"
        existing_content = "// Existing content"
        gml_file.write_text(existing_content, encoding="utf-8")
        
        self.script_asset.create_stub_files(asset_folder, "test_script")
        
        # Verify existing content is preserved
        content = gml_file.read_text(encoding="utf-8")
        self.assertEqual(content, existing_content)
    
    def test_script_validate_name(self):
        """Test script name validation rules."""
        # Valid script names (snake_case)
        self.assertTrue(self.script_asset.validate_name("valid_script"))
        self.assertTrue(self.script_asset.validate_name("script_with_numbers_123"))
        self.assertTrue(self.script_asset.validate_name("lowercase"))
        
        # Invalid script names
        self.assertFalse(self.script_asset.validate_name(""))
        self.assertFalse(self.script_asset.validate_name("InvalidCamelCase"))
        self.assertFalse(self.script_asset.validate_name("invalid-hyphen"))
        self.assertFalse(self.script_asset.validate_name("invalid space"))
        self.assertFalse(self.script_asset.validate_name("invalid@symbol"))
    
    def test_script_create_files_integration(self):
        """Test complete script creation workflow."""
        with patch('builtins.print'):  # Suppress print output
            relative_path = self.script_asset.create_files(
                self.project_root, "test_script", self.parent_path
            )
        
        # Verify relative path
        expected_path = "scripts/test_script/test_script.yy"
        self.assertEqual(relative_path, expected_path)
        
        # Verify files were created
        yy_file = self.project_root / "scripts" / "test_script" / "test_script.yy"
        gml_file = self.project_root / "scripts" / "test_script" / "test_script.gml"
        
        self.assertTrue(yy_file.exists())
        self.assertTrue(gml_file.exists())
        
        # Verify .yy file content
        yy_data = load_json_loose(yy_file)
        
        self.assertEqual(yy_data["$GMScript"], "v1")
        self.assertEqual(yy_data["name"], "test_script")
    
    def test_script_create_files_already_exists(self):
        """Test script creation when asset already exists."""
        # Create existing asset
        asset_folder = self.project_root / "scripts" / "test_script"
        asset_folder.mkdir(parents=True)
        yy_file = asset_folder / "test_script.yy"
        yy_file.write_text('{"existing": "data"}', encoding="utf-8")
        
        with patch('builtins.print') as mock_print:
            self.script_asset.create_files(self.project_root, "test_script", self.parent_path)
        
        # Verify skip message was printed
        mock_print.assert_any_call("Asset test_script already exists - skipping .yy creation")
        
        # Verify existing file is preserved
        content = yy_file.read_text(encoding="utf-8")
        self.assertEqual(content, '{"existing": "data"}')


class TestObjectAsset(TestAssetsComprehensive):
    """Test ObjectAsset class comprehensively."""
    
    def setUp(self):
        super().setUp()
        self.object_asset = ObjectAsset()
        self.parent_path = self._create_test_folder_structure()
    
    def test_object_asset_properties(self):
        """Test ObjectAsset class properties."""
        self.assertEqual(self.object_asset.kind, "object")
        self.assertEqual(self.object_asset.folder_prefix, "objects")
        self.assertEqual(self.object_asset.gm_tag, "GMObject")
    
    def test_object_create_yy_data_basic(self):
        """Test basic object .yy data creation."""
        yy_data = self.object_asset.create_yy_data("o_test", self.parent_path)
        
        # Verify required fields (v1 is required for Igor compiler compatibility)
        self.assertEqual(yy_data["$GMObject"], "v1")
        self.assertEqual(yy_data["%Name"], "o_test")
        self.assertEqual(yy_data["name"], "o_test")
        self.assertTrue(yy_data["managed"])
        self.assertFalse(yy_data["persistent"])
        
        # Verify default values
        self.assertEqual(yy_data["eventList"], [])
        self.assertEqual(yy_data["overriddenProperties"], [])
        self.assertIsNone(yy_data["parentObjectId"])
        
        # Verify physics defaults
        self.assertEqual(yy_data["physicsAngularDamping"], 0.1)
        self.assertEqual(yy_data["physicsDensity"], 0.5)
        self.assertEqual(yy_data["physicsFriction"], 0.2)
    
    def test_object_create_yy_data_with_sprite(self):
        """Test object creation with sprite reference."""
        yy_data = self.object_asset.create_yy_data(
            "o_test", self.parent_path, sprite_id="spr_test"
        )
        
        # Verify sprite reference
        self.assertIsNotNone(yy_data["spriteId"])
        self.assertEqual(yy_data["spriteId"]["name"], "spr_test")
        self.assertEqual(yy_data["spriteId"]["path"], "sprites/spr_test/spr_test.yy")
    
    def test_object_create_yy_data_with_parent_object(self):
        """Test object creation with parent object inheritance."""
        yy_data = self.object_asset.create_yy_data(
            "o_child", self.parent_path, parent_object="o_parent"
        )
        
        # Verify parent object reference
        self.assertIsNotNone(yy_data["parentObjectId"])
        self.assertEqual(yy_data["parentObjectId"]["name"], "o_parent")
        self.assertEqual(yy_data["parentObjectId"]["path"], "objects/o_parent/o_parent.yy")
    
    def test_object_parent_object_validation_rejects_paths(self):
        """Test that parent_object parameter validation rejects file paths."""
        # Test rejection of full path
        with self.assertRaises(ValueError) as context:
            self.object_asset.create_yy_data(
                "o_child", self.parent_path, parent_object="objects/o_actor/o_actor.yy"
            )
        self.assertIn("expects ONLY the object name", str(context.exception))
        self.assertIn("objects/o_actor/o_actor.yy", str(context.exception))
        
        # Test rejection of path with forward slashes
        with self.assertRaises(ValueError) as context:
            self.object_asset.create_yy_data(
                "o_child", self.parent_path, parent_object="objects/o_actor"
            )
        self.assertIn("expects ONLY the object name", str(context.exception))
        
        # Test rejection of path with backslashes
        with self.assertRaises(ValueError) as context:
            self.object_asset.create_yy_data(
                "o_child", self.parent_path, parent_object="objects\\o_actor\\o_actor.yy"
            )
        self.assertIn("expects ONLY the object name", str(context.exception))
        
        # Test rejection of .yy extension
        with self.assertRaises(ValueError) as context:
            self.object_asset.create_yy_data(
                "o_child", self.parent_path, parent_object="o_actor.yy"
            )
        self.assertIn("expects ONLY the object name", str(context.exception))
    
    def test_object_create_yy_data_with_both_sprite_and_parent(self):
        """Test object creation with both sprite and parent object."""
        yy_data = self.object_asset.create_yy_data(
            "o_complex", self.parent_path, 
            sprite_id="spr_complex", parent_object="o_base"
        )
        
        # Verify both references
        self.assertIsNotNone(yy_data["spriteId"])
        self.assertEqual(yy_data["spriteId"]["name"], "spr_complex")
        
        self.assertIsNotNone(yy_data["parentObjectId"])
        self.assertEqual(yy_data["parentObjectId"]["name"], "o_base")
    
    def test_object_create_stub_files(self):
        """Test object stub file creation."""
        asset_folder = self.project_root / "objects" / "o_test"
        asset_folder.mkdir(parents=True)
        
        # Should create Create_0.gml by default
        self.object_asset.create_stub_files(asset_folder, "o_test")
        
        # Verify Create_0.gml was created
        create_file = asset_folder / "Create_0.gml"
        self.assertTrue(create_file.exists())
        
        # Verify content
        content = create_file.read_text(encoding="utf-8")
        self.assertIn("Create Event for o_test", content)
    
    def test_object_validate_name(self):
        """Test object name validation rules."""
        # Valid object names (with o_ prefix)
        self.assertTrue(self.object_asset.validate_name("o_player"))
        self.assertTrue(self.object_asset.validate_name("o_enemy_zombie"))
        self.assertTrue(self.object_asset.validate_name("o_item_123"))
        
        # Names without o_ prefix should be invalid
        self.assertFalse(self.object_asset.validate_name("object_test"))
        self.assertFalse(self.object_asset.validate_name("test_object"))
        
        # Invalid names
        self.assertFalse(self.object_asset.validate_name(""))
        self.assertFalse(self.object_asset.validate_name("invalid space"))
        self.assertFalse(self.object_asset.validate_name("invalid@symbol"))
        self.assertFalse(self.object_asset.validate_name("invalid-hyphen"))


class TestSpriteAsset(TestAssetsComprehensive):
    """Test SpriteAsset class comprehensively."""
    
    def setUp(self):
        super().setUp()
        self.sprite_asset = SpriteAsset()
        self.parent_path = self._create_test_folder_structure()
    
    def test_sprite_asset_properties(self):
        """Test SpriteAsset class properties."""
        self.assertEqual(self.sprite_asset.kind, "sprite")
        self.assertEqual(self.sprite_asset.folder_prefix, "sprites")
        self.assertEqual(self.sprite_asset.gm_tag, "GMSprite")
    
    def test_sprite_create_yy_data_basic(self):
        """Test basic sprite .yy data creation."""
        yy_data = self.sprite_asset.create_yy_data("spr_test", self.parent_path)
        
        # Verify required fields
        self.assertEqual(yy_data["$GMSprite"], "")
        self.assertEqual(yy_data["%Name"], "spr_test")
        self.assertEqual(yy_data["name"], "spr_test")
        self.assertEqual(yy_data["resourceType"], "GMSprite")
        
        # Verify default dimensions
        self.assertEqual(yy_data["width"], 1)
        self.assertEqual(yy_data["height"], 1)
        
        # Verify layers structure
        self.assertIn("layers", yy_data)
        self.assertEqual(len(yy_data["layers"]), 1)
        layer = yy_data["layers"][0]
        self.assertEqual(layer["$GMImageLayer"], "")
        # Layer name is a UUID, not "default"
        self.assertIn("name", layer)
        self.assertEqual(layer["displayName"], "default")
    
    def test_sprite_create_yy_data_custom_dimensions(self):
        """Test sprite creation with custom dimensions."""
        yy_data = self.sprite_asset.create_yy_data(
            "spr_custom", self.parent_path, width=128, height=256
        )
        
        # Sprite dimensions are hardcoded to 1x1 in the current implementation
        # Custom dimensions would need to be set later in GameMaker IDE
        self.assertEqual(yy_data["width"], 1)
        self.assertEqual(yy_data["height"], 1)
    
    def test_sprite_create_yy_data_frame_count(self):
        """Test sprite creation with custom frame count."""
        yy_data = self.sprite_asset.create_yy_data(
            "spr_animated", self.parent_path, frame_count=5
        )
        
        # Verify frames structure - sprite always creates exactly 1 frame
        self.assertIn("frames", yy_data)
        frames = yy_data["frames"]
        self.assertEqual(len(frames), 1)
        
        # Verify frame has correct structure
        frame = frames[0]
        self.assertEqual(frame["$GMSpriteFrame"], "")
        self.assertIn("name", frame)
    
    def test_sprite_create_stub_files(self):
        """Test sprite stub file creation."""
        asset_folder = self.project_root / "sprites" / "spr_test"
        asset_folder.mkdir(parents=True)
        
        # Create a .yy file first (as the stub creation reads from it)
        yy_file = asset_folder / "spr_test.yy"
        yy_data = self.sprite_asset.create_yy_data("spr_test", self.parent_path)
        
        with open(yy_file, 'w') as f:
            json.dump(yy_data, f, indent=2)
        
        # Now create stub files
        self.sprite_asset.create_stub_files(asset_folder, "spr_test")
        
        # Verify some PNG files were created (exact structure depends on implementation)
        png_files = list(asset_folder.glob("*.png"))
        self.assertGreater(len(png_files), 0, "Should create at least one PNG file")
    
    def test_sprite_create_stub_files_custom_dimensions(self):
        """Test sprite stub file creation with custom dimensions."""
        asset_folder = self.project_root / "sprites" / "spr_custom"
        asset_folder.mkdir(parents=True)
        
        # Create a .yy file first (as the stub creation reads from it)
        yy_file = asset_folder / "spr_custom.yy"
        yy_data = self.sprite_asset.create_yy_data("spr_custom", self.parent_path)
        
        with open(yy_file, 'w') as f:
            json.dump(yy_data, f, indent=2)
        
        # Now create stub files (dimensions passed but not used by current implementation)
        self.sprite_asset.create_stub_files(
            asset_folder, "spr_custom", width=128, height=256
        )
        
        # Verify PNG files were created
        png_files = list(asset_folder.glob("*.png"))
        self.assertGreater(len(png_files), 0, "Should create at least one PNG file")
    
    def test_sprite_validate_name(self):
        """Test sprite name validation rules."""
        # Valid sprite names (with spr_ prefix)
        self.assertTrue(self.sprite_asset.validate_name("spr_player"))
        self.assertTrue(self.sprite_asset.validate_name("spr_enemy_idle"))
        self.assertTrue(self.sprite_asset.validate_name("spr_ui_button"))
        
        # Names without spr_ prefix should be invalid
        self.assertFalse(self.sprite_asset.validate_name("sprite_test"))
        self.assertFalse(self.sprite_asset.validate_name("test_sprite"))
        
        # Invalid names
        self.assertFalse(self.sprite_asset.validate_name(""))
        self.assertFalse(self.sprite_asset.validate_name("invalid space"))
        self.assertFalse(self.sprite_asset.validate_name("invalid@symbol"))


class TestRoomAsset(TestAssetsComprehensive):
    """Test RoomAsset class comprehensively."""
    
    def setUp(self):
        super().setUp()
        self.room_asset = RoomAsset()
        self.parent_path = self._create_test_folder_structure()
    
    def test_room_asset_properties(self):
        """Test RoomAsset class properties."""
        self.assertEqual(self.room_asset.kind, "room")
        self.assertEqual(self.room_asset.folder_prefix, "rooms")
        self.assertEqual(self.room_asset.gm_tag, "GMRoom")
    
    def test_room_create_yy_data_basic(self):
        """Test basic room .yy data creation."""
        yy_data = self.room_asset.create_yy_data("r_test", self.parent_path)
        
        # Verify required fields
        self.assertEqual(yy_data["$GMRoom"], "v1")
        self.assertEqual(yy_data["%Name"], "r_test")
        self.assertEqual(yy_data["name"], "r_test")
        self.assertEqual(yy_data["resourceType"], "GMRoom")
        
        # Verify default room settings
        self.assertFalse(yy_data["isDnd"])  # Default is False
        # Note: volume field may not exist in this room implementation
        
        # Verify room dimensions (default)
        self.assertEqual(yy_data["roomSettings"]["Width"], 1024)
        self.assertEqual(yy_data["roomSettings"]["Height"], 768)
        
        # Verify layer structure exists
        self.assertIn("layers", yy_data)
        self.assertIn("instanceCreationOrder", yy_data)
        self.assertEqual(yy_data["inheritLayers"], False)
    
    def test_room_create_yy_data_custom_dimensions(self):
        """Test room creation with custom dimensions."""
        yy_data = self.room_asset.create_yy_data(
            "r_custom", self.parent_path, width=800, height=600
        )
        
        # Verify custom dimensions
        self.assertEqual(yy_data["roomSettings"]["Width"], 800)
        self.assertEqual(yy_data["roomSettings"]["Height"], 600)
    
    def test_room_create_stub_files(self):
        """Test room stub file creation (should do nothing)."""
        asset_folder = self.project_root / "rooms" / "r_test"
        asset_folder.mkdir(parents=True)
        
        # Should not create any files
        self.room_asset.create_stub_files(asset_folder, "r_test")
        
        # Verify no additional files were created
        files = list(asset_folder.iterdir())
        self.assertEqual(len(files), 0)
    
    def test_room_validate_name(self):
        """Test room name validation rules."""
        # Valid room names (with r_ prefix)
        self.assertTrue(self.room_asset.validate_name("r_main_menu"))
        self.assertTrue(self.room_asset.validate_name("r_game_level_1"))
        self.assertTrue(self.room_asset.validate_name("r_test_room"))
        
        # Names without r_ prefix should be invalid
        self.assertFalse(self.room_asset.validate_name("room_test"))
        self.assertFalse(self.room_asset.validate_name("test_room"))
        
        # Invalid names
        self.assertFalse(self.room_asset.validate_name(""))
        self.assertFalse(self.room_asset.validate_name("invalid space"))
        self.assertFalse(self.room_asset.validate_name("invalid@symbol"))


class TestFolderAsset(TestAssetsComprehensive):
    """Test FolderAsset class comprehensively."""
    
    def setUp(self):
        super().setUp()
        self.folder_asset = FolderAsset()
    
    def test_folder_asset_properties(self):
        """Test FolderAsset class properties."""
        self.assertEqual(self.folder_asset.kind, "folder")
    
    def test_folder_get_folder_path(self):
        """Test folder path generation for folder assets."""
        path = self.folder_asset.get_folder_path(self.project_root, "TestFolder")
        # FolderAsset overrides get_folder_path to return just the project root
        expected = self.project_root
        self.assertEqual(path, expected)
    
    def test_folder_get_yy_path(self):
        """Test .yy file path generation for folders."""
        asset_folder = self.project_root / "folders"
        
        # FolderAsset overrides get_yy_path and raises NotImplementedError
        with self.assertRaises(NotImplementedError):
            self.folder_asset.get_yy_path(asset_folder, "TestFolder")
    
    def test_folder_create_yy_data_basic(self):
        """Test basic folder .yy data creation."""
        yy_data = self.folder_asset.create_yy_data("TestFolder")
        
        # Verify required fields
        self.assertEqual(yy_data["$GMFolder"], "")
        self.assertEqual(yy_data["%Name"], "TestFolder")
        self.assertEqual(yy_data["name"], "TestFolder")
        self.assertEqual(yy_data["resourceType"], "GMFolder")
        self.assertEqual(yy_data["resourceVersion"], "2.0")
        self.assertEqual(yy_data["folderPath"], "folders/TestFolder.yy")
    
    def test_folder_create_yy_data_with_parent(self):
        """Test folder creation with parent path."""
        yy_data = self.folder_asset.create_yy_data(
            "SubFolder", parent_path="folders/ParentFolder.yy"
        )
        
        # FolderAsset constructs nested path when parent_path ends with .yy
        self.assertEqual(yy_data["folderPath"], "folders/ParentFolder/SubFolder.yy")
    
    def test_folder_create_stub_files(self):
        """Test folder stub file creation (should do nothing)."""
        asset_folder = self.project_root / "folders"
        
        # Should not create any files
        self.folder_asset.create_stub_files(asset_folder, "TestFolder")
        
        # Verify behavior doesn't create unexpected files
        # (This method should be a no-op)
    
    def test_folder_create_files_integration(self):
        """Test complete folder creation workflow."""
        # Create basic .yyp file first (required for folder operations)
        self._create_basic_yyp_file()
        
        with patch('builtins.print'):  # Suppress print output
            relative_path = self.folder_asset.create_files(
                self.project_root, "TestFolder"
            )
        
        # Verify relative path was returned
        self.assertIsInstance(relative_path, str)
        self.assertIn("TestFolder", relative_path)
        
        # Check if folder was added to .yyp file (folders are logical only, no physical files)
        yyp_file = self.project_root / "TestProject.yyp"
        self.assertTrue(yyp_file.exists(), "Project .yyp file should exist")
        
        yyp_data = load_json_loose(yyp_file)
        folders = yyp_data.get("Folders", [])
        
        # Check if TestFolder was added to the Folders array
        folder_names = [folder.get("name", "") for folder in folders]
        self.assertIn("TestFolder", folder_names, "TestFolder should be in the .yyp Folders list")
        
        # Find the TestFolder entry and verify its structure
        test_folder = next((f for f in folders if f.get("name") == "TestFolder"), None)
        self.assertIsNotNone(test_folder, "TestFolder entry should exist in Folders array")
        if test_folder:
            self.assertEqual(test_folder["$GMFolder"], "")
            self.assertEqual(test_folder["name"], "TestFolder")
            self.assertEqual(test_folder["folderPath"], "folders/TestFolder.yy")
    
    def test_folder_validate_name(self):
        """Test folder name validation rules."""
        # Valid folder names (can contain spaces and various characters)
        self.assertTrue(self.folder_asset.validate_name("Valid Folder"))
        self.assertTrue(self.folder_asset.validate_name("Test_Folder"))
        self.assertTrue(self.folder_asset.validate_name("Folder123"))
        self.assertTrue(self.folder_asset.validate_name("Folder/Subfolder"))
        
        # Invalid names
        self.assertFalse(self.folder_asset.validate_name(""))
        self.assertFalse(self.folder_asset.validate_name("Invalid@Folder"))  # @ not allowed
        self.assertFalse(self.folder_asset.validate_name("Invalid#Folder"))  # # not allowed


class TestFontAsset(TestAssetsComprehensive):
    """Test FontAsset class comprehensively."""
    
    def setUp(self):
        super().setUp()
        self.font_asset = FontAsset()
        self.parent_path = self._create_test_folder_structure()
    
    def test_font_asset_properties(self):
        """Test FontAsset class properties."""
        self.assertEqual(self.font_asset.kind, "font")
        self.assertEqual(self.font_asset.folder_prefix, "fonts")
        self.assertEqual(self.font_asset.gm_tag, "GMFont")
    
    def test_font_create_yy_data_basic(self):
        """Test basic font .yy data creation."""
        yy_data = self.font_asset.create_yy_data("fnt_test", self.parent_path)
        
        # Verify required fields
        self.assertEqual(yy_data["$GMFont"], "")
        self.assertEqual(yy_data["%Name"], "fnt_test")
        self.assertEqual(yy_data["name"], "fnt_test")
        self.assertEqual(yy_data["resourceType"], "GMFont")
        
        # Verify default font settings
        self.assertEqual(yy_data["fontName"], "Arial")
        self.assertEqual(yy_data["size"], 12)
        self.assertFalse(yy_data["bold"])  # Default is False
        self.assertFalse(yy_data["italic"])
        
        # Verify character range
        self.assertEqual(yy_data["first"], 0)
        self.assertEqual(yy_data["last"], 0)
        
        # Verify sample text exists
        self.assertIn("sampleText", yy_data)
        self.assertIn("abcdef", yy_data["sampleText"])
    
    def test_font_create_yy_data_custom_settings(self):
        """Test font creation with custom settings."""
        yy_data = self.font_asset.create_yy_data(
            "fnt_custom", self.parent_path, 
            font_name="Times New Roman", size=16, bold=False, italic=True
        )
        
        # Verify custom settings
        self.assertEqual(yy_data["fontName"], "Times New Roman")
        self.assertEqual(yy_data["size"], 16)
        self.assertFalse(yy_data["bold"])
        self.assertTrue(yy_data["italic"])
    
    def test_font_create_stub_files(self):
        """Test font stub file creation."""
        asset_folder = self.project_root / "fonts" / "fnt_test"
        asset_folder.mkdir(parents=True)
        
        # The create_stub_files method actually creates a file, not just calls the function
        # Let's test that the PNG file gets created
        self.font_asset.create_stub_files(asset_folder, "fnt_test")
        
        # Verify PNG file was created
        png_file = asset_folder / "fnt_test.png"
        self.assertTrue(png_file.exists())
    
    def test_font_validate_name(self):
        """Test font name validation rules."""
        # Valid font names (with fnt_ prefix)
        self.assertTrue(self.font_asset.validate_name("fnt_arial"))
        self.assertTrue(self.font_asset.validate_name("fnt_ui_text"))
        self.assertTrue(self.font_asset.validate_name("fnt_game_hud"))
        
        # Names without fnt_ prefix should be invalid
        self.assertFalse(self.font_asset.validate_name("font_test"))
        self.assertFalse(self.font_asset.validate_name("test_font"))
        
        # Invalid names
        self.assertFalse(self.font_asset.validate_name(""))
        self.assertFalse(self.font_asset.validate_name("invalid space"))
        self.assertFalse(self.font_asset.validate_name("invalid@symbol"))


class TestErrorConditions(TestAssetsComprehensive):
    """Test error conditions and edge cases across all asset classes."""
    
    def test_asset_creation_with_invalid_parent_path(self):
        """Test asset creation with invalid parent paths."""
        script_asset = ScriptAsset()
        
        # Test with empty parent path
        yy_data = script_asset.create_yy_data("test_script", "")
        self.assertEqual(yy_data["parent"]["path"], "")
        self.assertEqual(yy_data["parent"]["name"], "")
        
        # Test with malformed parent path
        yy_data = script_asset.create_yy_data("test_script", "invalid/path")
        self.assertEqual(yy_data["parent"]["path"], "invalid/path")
        self.assertEqual(yy_data["parent"]["name"], "path")
    
    def test_asset_creation_with_missing_directories(self):
        """Test asset creation when directories don't exist."""
        script_asset = ScriptAsset()
        parent_path = self._create_test_folder_structure()
        
        # Remove the scripts directory
        shutil.rmtree(self.project_root / "scripts", ignore_errors=True)
        
        with patch('builtins.print'):  # Suppress print output
            # Should still work - ensure_directory creates missing dirs
            relative_path = script_asset.create_files(
                self.project_root, "test_script", parent_path
            )
        
        # Verify files were created despite missing directory
        yy_file = self.project_root / "scripts" / "test_script" / "test_script.yy"
        self.assertTrue(yy_file.exists())
    
    def test_asset_creation_with_json_save_error(self):
        """Test asset creation when JSON saving fails."""
        # Test that the method handles file system errors gracefully by mocking save function
        script_asset = ScriptAsset()
        parent_path = self._create_test_folder_structure()
        
        # Mock the save_pretty_json_gm function to raise an exception
        with patch('gms_helpers.base_asset.save_pretty_json_gm', side_effect=PermissionError("Mocked permission error")):
            with self.assertRaises(PermissionError):
                script_asset.create_files(self.project_root, "test_script", parent_path)
    
    def test_sprite_creation_with_zero_frame_count(self):
        """Test sprite creation with zero frame count."""
        sprite_asset = SpriteAsset()
        parent_path = self._create_test_folder_structure()
        
        yy_data = sprite_asset.create_yy_data("spr_test", parent_path, frame_count=0)
        
        # Should create at least one frame
        self.assertIn("frames", yy_data)
        frames = yy_data["frames"]
        self.assertGreaterEqual(len(frames), 1)
    
    def test_sprite_creation_with_negative_dimensions(self):
        """Test sprite creation with negative dimensions."""
        sprite_asset = SpriteAsset()
        parent_path = self._create_test_folder_structure()
        
        yy_data = sprite_asset.create_yy_data(
            "spr_test", parent_path, width=-10, height=-20
        )
        
        # Sprite dimensions are hardcoded, not affected by kwargs
        self.assertEqual(yy_data["width"], 1)  # Hardcoded default
        self.assertEqual(yy_data["height"], 1)  # Hardcoded default
    
    def test_object_creation_with_nonexistent_sprite(self):
        """Test object creation with reference to nonexistent sprite."""
        object_asset = ObjectAsset()
        parent_path = self._create_test_folder_structure()
        
        yy_data = object_asset.create_yy_data(
            "o_test", parent_path, sprite_id="spr_nonexistent"
        )
        
        # Should still create reference (validation happens elsewhere)
        self.assertIsNotNone(yy_data["spriteId"])
        self.assertEqual(yy_data["spriteId"]["name"], "spr_nonexistent")
        self.assertEqual(yy_data["spriteId"]["path"], "sprites/spr_nonexistent/spr_nonexistent.yy")
    
    def test_room_creation_with_invalid_dimensions(self):
        """Test room creation with invalid dimensions."""
        room_asset = RoomAsset()
        parent_path = self._create_test_folder_structure()
        
        yy_data = room_asset.create_yy_data(
            "r_test", parent_path, width=0, height=-100
        )
        
        # Room accepts any values passed in kwargs, no validation
        self.assertEqual(yy_data["roomSettings"]["Width"], 0)    # Accepts invalid value
        self.assertEqual(yy_data["roomSettings"]["Height"], -100) # Accepts invalid value


class TestAssetIntegrationScenarios(TestAssetsComprehensive):
    """Test integration scenarios and complex asset interactions."""
    
    def test_multiple_asset_creation_sequence(self):
        """Test creating multiple related assets in sequence."""
        parent_path = self._create_test_folder_structure()
        
        # Create sprite first
        sprite_asset = SpriteAsset()
        with patch('builtins.print'):
            sprite_path = sprite_asset.create_files(
                self.project_root, "spr_player", parent_path
            )
        
        # Create object that uses the sprite
        object_asset = ObjectAsset()
        with patch('builtins.print'):
            object_path = object_asset.create_files(
                self.project_root, "o_player", parent_path, sprite_id="spr_player"
            )
        
        # Create script for the object
        script_asset = ScriptAsset()
        with patch('builtins.print'):
            script_path = script_asset.create_files(
                self.project_root, "player_init", parent_path
            )
        
        # Verify all files were created
        self.assertTrue((self.project_root / sprite_path).exists())
        self.assertTrue((self.project_root / object_path).exists())
        self.assertTrue((self.project_root / script_path).exists())
        
        # Verify object references sprite correctly
        object_yy_file = self.project_root / object_path
        object_data = load_json_loose(object_yy_file)
        
        self.assertEqual(object_data["spriteId"]["name"], "spr_player")
    
    def test_nested_folder_creation(self):
        """Test creating nested folder structures."""
        folder_asset = FolderAsset()
        
        # Create basic .yyp file first (required for folder operations)
        self._create_basic_yyp_file()
        
        with patch('builtins.print'):
            # Create parent folder
            parent_path = folder_asset.create_files(
                self.project_root, "UI"
            )
            
            # Create child folder
            child_path = folder_asset.create_files(
                self.project_root, "Buttons", parent_path=parent_path
            )
        
        # Verify both operations returned valid paths
        self.assertIsInstance(parent_path, str)
        self.assertIsInstance(child_path, str)
        self.assertIn("UI", parent_path)
        self.assertIn("Buttons", child_path)
        
        # Check if folders were added to .yyp file (folders are logical only, no physical files)
        yyp_file = self.project_root / "TestProject.yyp"
        self.assertTrue(yyp_file.exists(), "Project .yyp file should exist")
        
        yyp_data = load_json_loose(yyp_file)
        folders = yyp_data.get("Folders", [])
        folder_paths = [folder.get("folderPath", "") for folder in folders]
        
        # Check if both UI and Buttons folders were added to the .yyp file
        self.assertIn(parent_path, folder_paths, f"UI folder should be in .yyp Folders list: {folder_paths}")
        self.assertIn(child_path, folder_paths, f"Buttons folder should be in .yyp Folders list: {folder_paths}")
    
    def test_asset_creation_with_unicode_names(self):
        """Test asset creation with Unicode characters in names."""
        from gms_helpers.naming_config import NamingConfig
        NamingConfig.clear_cache()
        
        script_asset = ScriptAsset()
        parent_path = self._create_test_folder_structure()
        
        # Test with Unicode characters - default config pattern does NOT allow Unicode
        # This is the intended stricter behavior for the default naming conventions
        unicode_name = "test_script_é_ñ"
        
        # With default config, Unicode names should fail validation
        # (pattern ^[a-z][a-z0-9_]*$ only allows ASCII)
        self.assertFalse(script_asset.validate_name(unicode_name))
        
        # Valid ASCII names should still work
        ascii_name = "test_script_valid"
        self.assertTrue(script_asset.validate_name(ascii_name))
    
    def test_asset_creation_performance_stress(self):
        """Test creating many assets rapidly."""
        script_asset = ScriptAsset()
        parent_path = self._create_test_folder_structure()
        
        with patch('builtins.print'):  # Suppress output for performance
            # Create 10 scripts rapidly
            for i in range(10):
                script_name = f"test_script_{i}"
                relative_path = script_asset.create_files(
                    self.project_root, script_name, parent_path
                )
                
                # Verify each was created
                yy_file = self.project_root / relative_path
                self.assertTrue(yy_file.exists())


if __name__ == '__main__':
    unittest.main()
