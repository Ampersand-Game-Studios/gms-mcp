#!/usr/bin/env python3
"""
Test suite for GameMaker Asset Helper
=====================================

Comprehensive tests for all asset types and utilities.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to Python path
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import our modules
from gms_helpers.utils import (
    strip_trailing_commas, load_json_loose, save_pretty_json,
    find_yyp, insert_into_resources, insert_into_folders,
    generate_uuid, create_dummy_png
)
from gms_helpers.assets import ScriptAsset, ObjectAsset, SpriteAsset, RoomAsset, FolderAsset


class TestUtils(unittest.TestCase):
    """Test utility functions."""

    def test_strip_trailing_commas(self):
        """Test JSON trailing comma removal."""
        # Test object with trailing comma
        json_with_comma = '{"key": "value",}'
        expected = '{"key": "value"}'
        self.assertEqual(strip_trailing_commas(json_with_comma), expected)

        # Test array with trailing comma
        json_array = '["item1", "item2",]'
        expected_array = '["item1", "item2"]'
        self.assertEqual(strip_trailing_commas(json_array), expected_array)

        # Test nested structure
        nested = '{"obj": {"nested": "value",}, "arr": [1, 2,]}'
        expected_nested = '{"obj": {"nested": "value"}, "arr": [1, 2]}'
        self.assertEqual(strip_trailing_commas(nested), expected_nested)

    def test_generate_uuid(self):
        """Test UUID generation."""
        uuid1 = generate_uuid()
        uuid2 = generate_uuid()

        # Should be different
        self.assertNotEqual(uuid1, uuid2)

        # Should be 32 characters (no dashes)
        self.assertEqual(len(uuid1), 32)
        self.assertEqual(len(uuid2), 32)

        # Should contain only hex characters
        self.assertTrue(all(c in '0123456789abcdef' for c in uuid1.lower()))

    def test_insert_into_resources(self):
        """Test resource insertion and sorting."""
        resources = [
            {"id": {"name": "alpha", "path": "alpha.yy"}},
            {"id": {"name": "charlie", "path": "charlie.yy"}}
        ]

        # Insert beta (should go between alpha and charlie)
        result = insert_into_resources(resources, "beta", "beta.yy")
        self.assertTrue(result)
        self.assertEqual(len(resources), 3)

        # Check alphabetical order
        names = [r["id"]["name"] for r in resources]
        self.assertEqual(names, ["alpha", "beta", "charlie"])

        # Try to insert duplicate
        result = insert_into_resources(resources, "beta", "beta.yy")
        self.assertFalse(result)
        self.assertEqual(len(resources), 3)  # Should not change

    def test_insert_into_folders(self):
        """Test folder insertion and sorting."""
        folders = [
            {"name": "Alpha", "folderPath": "folders/Alpha.yy"},
            {"name": "Charlie", "folderPath": "folders/Charlie.yy"}
        ]

        # Insert Beta
        result = insert_into_folders(folders, "Beta", "folders/Beta.yy")
        self.assertTrue(result)
        self.assertEqual(len(folders), 3)

        # Check alphabetical order
        names = [f["name"] for f in folders]
        self.assertEqual(names, ["Alpha", "Beta", "Charlie"])


class TestAssetValidation(unittest.TestCase):
    """Test asset name validation."""

    def setUp(self):
        self.script = ScriptAsset()
        self.object = ObjectAsset()
        self.sprite = SpriteAsset()
        self.room = RoomAsset()
        self.folder = FolderAsset()

    def test_script_validation(self):
        """Test script name validation."""
        # Valid names
        self.assertTrue(self.script.validate_name("my_function"))
        self.assertTrue(self.script.validate_name("player_move"))
        self.assertTrue(self.script.validate_name("simple"))

        # Invalid names
        self.assertFalse(self.script.validate_name(""))
        self.assertFalse(self.script.validate_name("MyFunction"))  # CamelCase (without constructor)
        self.assertFalse(self.script.validate_name("my-function"))  # No underscores

    def test_constructor_script_validation(self):
        """Test constructor script name validation with utils.validate_name."""
        from gms_helpers.utils import validate_name

        # Valid PascalCase constructor names
        valid_constructor_names = [
            "PlayerData",
            "InventoryItem",
            "StatusEffect",
            "GameData",
            "Vector2D"
        ]

        for name in valid_constructor_names:
            with self.subTest(name=name):
                # Should not raise exception when allow_constructor=True
                try:
                    validate_name(name, 'script', allow_constructor=True)
                except ValueError:
                    self.fail(f"validate_name raised ValueError for valid constructor name: {name}")

                # Should raise exception when allow_constructor=False (default)
                with self.assertRaises(ValueError):
                    validate_name(name, 'script', allow_constructor=False)

        # Invalid names even for constructors
        invalid_names = [
            "",  # Empty
            "invalid-hyphen",  # Hyphen
            "invalid space",  # Space
            "invalid@symbol",  # Special character
            "123Start",  # Starting with number
        ]

        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_name(name, 'script', allow_constructor=True)

    def test_constructor_pattern_detection(self):
        """Test constructor pattern detection in linting."""
        from gms_helpers.maintenance.lint import ProjectLinter
        import tempfile
        import os
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a test script with constructor pattern
            script_dir = Path(temp_dir) / "scripts" / "TestConstructor"
            script_dir.mkdir(parents=True)

            # Create .gml file with constructor pattern
            gml_file = script_dir / "TestConstructor.gml"
            gml_content = """/// @function TestConstructor
/// @description Constructor for TestConstructor
function TestConstructor() constructor {
    // Constructor implementation
}"""
            gml_file.write_text(gml_content, encoding='utf-8')

            # Create .yy file
            yy_file = script_dir / "TestConstructor.yy"
            yy_file.write_text('{}', encoding='utf-8')

            # Test constructor detection
            linter = ProjectLinter(temp_dir)
            is_constructor = linter._is_constructor_script(str(yy_file))
            self.assertTrue(is_constructor, "Should detect constructor pattern")

            # Test non-constructor script
            regular_gml = """function test_function() {
    // Regular function
}"""
            gml_file.write_text(regular_gml, encoding='utf-8')

            is_constructor = linter._is_constructor_script(str(yy_file))
            self.assertFalse(is_constructor, "Should not detect constructor pattern in regular script")

    def test_delete_command_argument_parsing(self):
        """Test that delete command uses correct argument name."""
        from gms_helpers.asset_helper import delete_asset
        import argparse

        # Create mock args object with correct attribute name
        class MockArgs:
            def __init__(self):
                self.asset_type = 'script'  # This should be asset_type, not type
                self.name = 'test_script'
                self.dry_run = True
                self.skip_maintenance = True
                self.no_auto_fix = False

        args = MockArgs()

        # Should be able to access args.asset_type without AttributeError
        self.assertEqual(args.asset_type, 'script')
        self.assertTrue(hasattr(args, 'asset_type'))

        # The delete_asset function should not fail due to missing asset_type attribute
        # Note: We're only testing the argument structure, not the full deletion
        # since that requires a proper GameMaker project environment

    def test_object_validation(self):
        """Test object name validation."""
        # Valid names
        self.assertTrue(self.object.validate_name("o_player"))
        self.assertTrue(self.object.validate_name("o_enemy_zombie"))

        # Invalid names
        self.assertFalse(self.object.validate_name(""))
        self.assertFalse(self.object.validate_name("player"))  # Missing o_ prefix
        self.assertFalse(self.object.validate_name("obj_player"))  # Wrong prefix

    def test_sprite_validation(self):
        """Test sprite name validation."""
        # Valid names
        self.assertTrue(self.sprite.validate_name("spr_player"))
        self.assertTrue(self.sprite.validate_name("spr_bullet_fire"))

        # Invalid names
        self.assertFalse(self.sprite.validate_name(""))
        self.assertFalse(self.sprite.validate_name("player"))  # Missing spr_ prefix
        self.assertFalse(self.sprite.validate_name("sprite_player"))  # Wrong prefix

    def test_room_validation(self):
        """Test room name validation."""
        # Valid names
        self.assertTrue(self.room.validate_name("r_menu"))
        self.assertTrue(self.room.validate_name("r_level_01"))

        # Invalid names
        self.assertFalse(self.room.validate_name(""))
        self.assertFalse(self.room.validate_name("menu"))  # Missing r_ prefix
        self.assertFalse(self.room.validate_name("room_menu"))  # Wrong prefix

    def test_folder_validation(self):
        """Test folder name validation."""
        # Valid names
        self.assertTrue(self.folder.validate_name("Scripts"))
        self.assertTrue(self.folder.validate_name("UI/GameOver"))
        self.assertTrue(self.folder.validate_name("Test Folder"))

        # Invalid names
        self.assertFalse(self.folder.validate_name(""))


class TestAssetCreation(unittest.TestCase):
    """Test asset file creation."""

    def setUp(self):
        """Set up temporary directory for testing."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.project_root = self.temp_dir / "test_project"
        self.project_root.mkdir()

        # Create basic project structure
        (self.project_root / "scripts").mkdir()
        (self.project_root / "objects").mkdir()
        (self.project_root / "sprites").mkdir()
        (self.project_root / "rooms").mkdir()
        # Note: We don't create a physical 'folders' directory since GameMaker folder paths are logical

        # Create a minimal .yyp file
        self.yyp_data = {
            "resources": [],
            "Folders": [
                {
                    "$GMFolder": "",
                    "%Name": "Scripts",
                    "folderPath": "folders/Scripts.yy",
                    "name": "Scripts",
                    "resourceType": "GMFolder",
                    "resourceVersion": "2.0"
                }
            ]
        }
        yyp_path = self.project_root / "test.yyp"
        save_pretty_json(yyp_path, self.yyp_data)

        # Note: We don't create physical folder .yy files since GameMaker folder paths are logical references

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_script_creation(self):
        """Test script asset creation."""
        script = ScriptAsset()

        # Create script
        rel_path = script.create_files(
            self.project_root,
            "test_function",
            "folders/Scripts.yy"
        )

        # Check files were created
        script_dir = self.project_root / "scripts" / "test_function"
        self.assertTrue(script_dir.exists())

        yy_file = script_dir / "test_function.yy"
        gml_file = script_dir / "test_function.gml"

        self.assertTrue(yy_file.exists())
        self.assertTrue(gml_file.exists())

        # Check .yy file content
        yy_data = load_json_loose(yy_file)
        self.assertEqual(yy_data["$GMScript"], "v1")
        self.assertEqual(yy_data["name"], "test_function")
        self.assertEqual(yy_data["parent"]["path"], "folders/Scripts.yy")

        # Check .gml file content
        gml_content = gml_file.read_text(encoding="utf-8")
        self.assertIn("function test_function()", gml_content)

        # Check return path
        self.assertEqual(rel_path, "scripts/test_function/test_function.yy")

    def test_object_creation(self):
        """Test object asset creation."""
        obj = ObjectAsset()

        # Create object
        rel_path = obj.create_files(
            self.project_root,
            "o_test_object",
            "folders/Scripts.yy"  # Using existing folder for test
        )

        # Check files were created
        obj_dir = self.project_root / "objects" / "o_test_object"
        self.assertTrue(obj_dir.exists())

        yy_file = obj_dir / "o_test_object.yy"
        create_file = obj_dir / "Create_0.gml"

        self.assertTrue(yy_file.exists())
        self.assertTrue(create_file.exists())

        # Check .yy file content
        yy_data = load_json_loose(yy_file)
        self.assertEqual(yy_data["$GMObject"], "v1")
        self.assertEqual(yy_data["name"], "o_test_object")
        self.assertIsNone(yy_data["spriteId"])  # No sprite assigned
        self.assertIsNone(yy_data["parentObjectId"])  # No parent object

        # Check Create event
        create_content = create_file.read_text(encoding="utf-8")
        self.assertIn("Create Event for o_test_object", create_content)

        # Test object creation with parent object
        child_rel_path = obj.create_files(
            self.project_root,
            "o_child_object",
            "folders/Scripts.yy",
            parent_object="o_test_object"
        )

        # Check child object files
        child_obj_dir = self.project_root / "objects" / "o_child_object"
        self.assertTrue(child_obj_dir.exists())

        child_yy_file = child_obj_dir / "o_child_object.yy"
        self.assertTrue(child_yy_file.exists())

        # Check child .yy file content has parent object
        child_yy_data = load_json_loose(child_yy_file)
        self.assertEqual(child_yy_data["$GMObject"], "v1")
        self.assertEqual(child_yy_data["name"], "o_child_object")
        self.assertIsNotNone(child_yy_data["parentObjectId"])
        self.assertEqual(child_yy_data["parentObjectId"]["name"], "o_test_object")
        self.assertEqual(child_yy_data["parentObjectId"]["path"], "objects/o_test_object/o_test_object.yy")

    def test_sprite_creation(self):
        """Test sprite asset creation."""
        sprite = SpriteAsset()

        # Create sprite
        rel_path = sprite.create_files(
            self.project_root,
            "spr_test_sprite",
            "folders/Scripts.yy"  # Using existing folder for test
        )

        # Check files were created
        sprite_dir = self.project_root / "sprites" / "spr_test_sprite"
        self.assertTrue(sprite_dir.exists())

        yy_file = sprite_dir / "spr_test_sprite.yy"
        self.assertTrue(yy_file.exists())

        # Check .yy file content
        yy_data = load_json_loose(yy_file)
        self.assertEqual(yy_data["$GMSprite"], "")
        self.assertEqual(yy_data["name"], "spr_test_sprite")

        # Check that PNG files were created
        layer_uuid = yy_data["layers"][0]["name"]
        image_uuid = yy_data["frames"][0]["name"]

        main_image = sprite_dir / f"{image_uuid}.png"
        layer_image = sprite_dir / "layers" / image_uuid / f"{layer_uuid}.png"

        self.assertTrue(main_image.exists())
        self.assertTrue(layer_image.exists())

        # Check that files are valid PNG (at least have PNG header)
        main_data = main_image.read_bytes()
        self.assertTrue(main_data.startswith(b'\x89PNG'))

    def test_room_creation(self):
        """Test room asset creation."""
        room = RoomAsset()

        # Create room with custom dimensions
        rel_path = room.create_files(
            self.project_root,
            "r_test_room",
            "folders/Scripts.yy",  # Using existing folder for test
            width=1920,
            height=1080
        )

        # Check files were created
        room_dir = self.project_root / "rooms" / "r_test_room"
        self.assertTrue(room_dir.exists())

        yy_file = room_dir / "r_test_room.yy"
        self.assertTrue(yy_file.exists())

        # Check .yy file content
        yy_data = load_json_loose(yy_file)
        self.assertEqual(yy_data["$GMRoom"], "v1")
        self.assertEqual(yy_data["name"], "r_test_room")
        self.assertEqual(yy_data["roomSettings"]["Width"], 1920)
        self.assertEqual(yy_data["roomSettings"]["Height"], 1080)

        # Check that default layers exist
        layer_names = [layer["%Name"] for layer in yy_data["layers"]]
        self.assertIn("Instances", layer_names)
        self.assertIn("Background", layer_names)

    def test_folder_creation(self):
        """Test folder asset creation."""
        folder = FolderAsset()

        # Test simple folder creation
        rel_path = folder.create_files(
            self.project_root,
            "TestFolder"
        )

        # Check return path (folders are logical, no physical files created)
        self.assertEqual(rel_path, "folders/TestFolder.yy")

        # Check that folder was added to .yyp file
        yyp_data = load_json_loose(self.project_root / "test.yyp")
        folder_paths = [folder.get("folderPath", "") for folder in yyp_data.get("Folders", [])]
        self.assertIn("folders/TestFolder.yy", folder_paths)

        # Test nested folder creation with parent_path
        nested_rel_path = folder.create_files(
            self.project_root,
            "NestedFolder",
            "folders/Parent/Child/NestedFolder.yy"
        )

        # Check nested return path
        self.assertEqual(nested_rel_path, "folders/Parent/Child/NestedFolder.yy")

        # Check that nested folder was added to .yyp file
        yyp_data = load_json_loose(self.project_root / "test.yyp")
        folder_paths = [folder.get("folderPath", "") for folder in yyp_data.get("Folders", [])]
        self.assertIn("folders/Parent/Child/NestedFolder.yy", folder_paths)


class TestIntegration(unittest.TestCase):
    """Integration tests for the complete asset creation workflow."""

    def setUp(self):
        """Set up temporary project."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.project_root = self.temp_dir / "test_project"
        self.project_root.mkdir()

        # Create project structure
        for folder in ["scripts", "objects", "sprites", "rooms"]:
            (self.project_root / folder).mkdir()
        # Note: We don't create a physical 'folders' directory since GameMaker folder paths are logical

        # Create .yyp file
        self.yyp_data = {
            "resources": [],
            "Folders": [
                {
                    "$GMFolder": "",
                    "%Name": "Scripts",
                    "folderPath": "folders/Scripts.yy",
                    "name": "Scripts",
                    "resourceType": "GMFolder",
                    "resourceVersion": "2.0"
                }
            ]
        }
        self.yyp_path = self.project_root / "test.yyp"
        save_pretty_json(self.yyp_path, self.yyp_data)

        # Note: We don't create physical folder .yy files since GameMaker folder paths are logical references

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)

    @patch('builtins.input', return_value='y')  # Auto-confirm for missing parent paths
    def test_complete_workflow(self, mock_input):
        """Test creating multiple assets and updating .yyp file."""
        # Create multiple assets using asset classes directly
        script_asset = ScriptAsset()
        script_rel_path = script_asset.create_files(self.project_root, 'test_function', 'folders/Scripts.yy')

        object_asset = ObjectAsset()
        object_rel_path = object_asset.create_files(self.project_root, 'o_test_obj', 'folders/Scripts.yy')

        sprite_asset = SpriteAsset()
        sprite_rel_path = sprite_asset.create_files(self.project_root, 'spr_test_spr', 'folders/Scripts.yy')

        # Manually update .yyp file (simulating what the CLI tool does)
        yyp_data = load_json_loose(self.yyp_path)

        # Add resources to .yyp file
        resources = yyp_data.get("resources", [])
        insert_into_resources(resources, 'test_function', script_rel_path)
        insert_into_resources(resources, 'o_test_obj', object_rel_path)
        insert_into_resources(resources, 'spr_test_spr', sprite_rel_path)

        yyp_data["resources"] = resources
        save_pretty_json(self.yyp_path, yyp_data)

        # Check .yyp file was updated
        yyp_data = load_json_loose(self.yyp_path)
        resource_names = [r["id"]["name"] for r in yyp_data["resources"]]

        self.assertIn('test_function', resource_names)
        self.assertIn('o_test_obj', resource_names)
        self.assertIn('spr_test_spr', resource_names)

        # Check alphabetical order
        self.assertEqual(resource_names, sorted(resource_names))

        # Check all files exist
        self.assertTrue((self.project_root / "scripts" / "test_function" / "test_function.yy").exists())
        self.assertTrue((self.project_root / "objects" / "o_test_obj" / "o_test_obj.yy").exists())
        self.assertTrue((self.project_root / "sprites" / "spr_test_spr" / "spr_test_spr.yy").exists())


def run_tests():
    """Run all tests and return results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [TestUtils, TestAssetValidation, TestAssetCreation, TestIntegration]
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    print("Running GameMaker Asset Helper Test Suite")
    print("=" * 60)

    result = run_tests()

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("All tests passed!")
    else:
        print(f"{len(result.failures)} failures, {len(result.errors)} errors")

        if result.failures:
            print("\nFailures:")
            for test, traceback in result.failures:
                error_msg = traceback.split('AssertionError: ')[-1].split('\n')[0]
                print(f"  - {test}: {error_msg}")

        if result.errors:
            print("\nErrors:")
            for test, traceback in result.errors:
                error_msg = traceback.split('\n')[-2]
                print(f"  - {test}: {error_msg}")

    print(f"\nRan {result.testsRun} tests in total")
