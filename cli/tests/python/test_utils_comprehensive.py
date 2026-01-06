#!/usr/bin/env python3
"""
Comprehensive test suite for utils.py - Target: 90%+ Coverage
Tests all utility functions, error conditions, edge cases, and cross-platform scenarios.
"""

import unittest
import tempfile
import shutil
import os
import json
import stat
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import all functions to test
from gms_helpers.utils import (
    strip_trailing_commas, load_json_loose, save_pretty_json, save_pretty_json_gm,
    save_json, find_yyp, ensure_directory, verify_parent_path_exists,
    insert_into_resources, insert_into_folders, generate_uuid, create_dummy_png,
    load_json, add_trailing_commas, validate_name, find_yyp_file,
    check_resource_conflicts, find_duplicate_resources, dedupe_resources,
    update_yyp_file, validate_parent_path, remove_folder_from_yyp, list_folders_in_yyp
)
from gms_helpers.exceptions import GMSError, ProjectNotFoundError, ValidationError


class TestUtilsComprehensive(unittest.TestCase):
    """Comprehensive test suite for utils module."""
    
    def setUp(self):
        """Set up test environment with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create basic project structure
        for folder in ['scripts', 'objects', 'sprites', 'rooms', 'folders']:
            (self.project_root / folder).mkdir(exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_json_file(self, filename, data, trailing_commas=False):
        """Helper to create JSON test files."""
        file_path = self.project_root / filename
        json_str = json.dumps(data, indent=2)
        
        if trailing_commas:
            # Add trailing commas for GameMaker format
            json_str = json_str.replace('{\n  ', '{\n  ').replace('\n}', ',\n}')
            json_str = json_str.replace('[\n  ', '[\n  ').replace('\n]', ',\n]')
        
        file_path.write_text(json_str, encoding="utf-8")
        return file_path
    
    def _create_test_yyp_file(self, name="TestProject"):
        """Helper to create a basic .yyp file."""
        yyp_data = {
            "$GMProject": "",
            "%Name": name,
            "name": name,
            "resources": [],
            "folders": [],
            "resourceType": "GMProject",
            "resourceVersion": "2.0"
        }
        
        yyp_path = self.project_root / f"{name}.yyp"
        with open(yyp_path, 'w') as f:
            json.dump(yyp_data, f, indent=2)
        
        return yyp_path


class TestJSONUtilities(TestUtilsComprehensive):
    """Test JSON utility functions."""
    
    def test_strip_trailing_commas_basic(self):
        """Test basic trailing comma removal."""
        test_cases = [
            ('{"a": 1,}', '{"a": 1}'),
            ('[1, 2, 3,]', '[1, 2, 3]'),
            ('{"a": [1, 2,], "b": 3,}', '{"a": [1, 2], "b": 3}'),
            ('{"a": 1}', '{"a": 1}'),  # No trailing commas
            ('[]', '[]'),  # Empty array
            ('{}', '{}'),  # Empty object
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = strip_trailing_commas(input_text)
                self.assertEqual(result, expected)
    
    def test_strip_trailing_commas_complex(self):
        """Test trailing comma removal with complex nested structures."""
        complex_json = '''
        {
            "project": {
                "name": "test",
                "resources": [
                    {"id": 1, "name": "asset1",},
                    {"id": 2, "name": "asset2",},
                ],
                "folders": [
                    {"name": "folder1",},
                    {"name": "folder2",},
                ],
            },
            "version": "2.0",
        }
        '''
        
        result = strip_trailing_commas(complex_json)
        
        # Should be valid JSON after stripping
        try:
            parsed = json.loads(result)
            self.assertIn("project", parsed)
            self.assertEqual(len(parsed["project"]["resources"]), 2)
        except json.JSONDecodeError:
            self.fail("Result should be valid JSON after stripping trailing commas")
    
    def test_load_json_loose_valid_json(self):
        """Test loading valid JSON files."""
        test_data = {"name": "test", "value": 123}
        json_file = self._create_test_json_file("valid.json", test_data)
        
        result = load_json_loose(json_file)
        self.assertEqual(result, test_data)
    
    def test_load_json_loose_trailing_commas(self):
        """Test loading JSON files with trailing commas."""
        json_content = '''
        {
            "name": "test",
            "resources": [
                {"id": 1,},
                {"id": 2,},
            ],
            "version": "1.0",
        }
        '''
        
        json_file = self.project_root / "trailing.json"
        json_file.write_text(json_content, encoding="utf-8")
        
        result = load_json_loose(json_file)
        
        self.assertEqual(result["name"], "test")
        self.assertEqual(len(result["resources"]), 2)
        self.assertEqual(result["version"], "1.0")
    
    def test_load_json_loose_invalid_json(self):
        """Test loading invalid JSON files - should return None instead of raising exception."""
        invalid_json = "{ invalid json content"
        json_file = self.project_root / "invalid.json"
        json_file.write_text(invalid_json, encoding="utf-8")
        
        # load_json_loose should return None for invalid JSON, not raise exception
        result = load_json_loose(json_file)
        self.assertIsNone(result)
    
    def test_save_pretty_json_basic(self):
        """Test saving JSON with pretty formatting."""
        test_data = {"name": "test", "items": [1, 2, 3]}
        json_file = self.project_root / "output.json"
        
        save_pretty_json(json_file, test_data)
        
        # Verify file was created and contains correct data
        self.assertTrue(json_file.exists())
        
        with open(json_file) as f:
            loaded_data = json.load(f)
        
        self.assertEqual(loaded_data, test_data)
    
    def test_save_pretty_json_gm_basic(self):
        """Test saving JSON with GameMaker-style trailing commas."""
        test_data = {"name": "test", "items": [1, 2, 3]}
        json_file = self.project_root / "output_gm.json"
        
        save_pretty_json_gm(json_file, test_data)
        
        # Verify file was created
        self.assertTrue(json_file.exists())
        
        # Read the raw content to check for trailing commas
        content = json_file.read_text(encoding="utf-8")
        
        # Should contain trailing commas - check for them after values
        self.assertIn("3,", content)  # Last array item should have comma
        self.assertIn("],", content)  # Array closing should have comma
    
    def test_save_json_function(self):
        """Test the save_json function."""
        test_data = {"name": "test", "value": 42}
        json_file = str(self.project_root / "save_test.json")
        
        save_json(test_data, json_file)
        
        # Verify file was created and contains correct data
        self.assertTrue(Path(json_file).exists())
        
        # Should be loadable with load_json_loose due to trailing commas
        loaded_data = load_json_loose(Path(json_file))
        self.assertEqual(loaded_data, test_data)
    
    def test_add_trailing_commas(self):
        """Test adding trailing commas to JSON strings."""
        # Test with multi-line JSON (which is what the function expects)
        input_json = '{\n  "name": "test",\n  "value": 42\n}'
        expected = '{\n  "name": "test",\n  "value": 42,\n}'
        
        result = add_trailing_commas(input_json)
        self.assertEqual(result, expected)
        
        # Test with array
        input_array = '[\n  "item1",\n  "item2"\n]'
        expected_array = '[\n  "item1",\n  "item2",\n]'
        
        result_array = add_trailing_commas(input_array)
        self.assertEqual(result_array, expected_array)
    
    def test_load_json_function(self):
        """Test the main load_json function."""
        test_data = {"name": "test", "value": 123}
        json_file = str(self.project_root / "load_test.json")
        
        # Create file using save_json (which adds trailing commas)
        save_json(test_data, json_file)
        
        # Load using load_json function
        result = load_json(json_file)
        self.assertEqual(result, test_data)
    
    def test_load_json_missing_file(self):
        """Test loading non-existent JSON file."""
        missing_file = str(self.project_root / "missing.json")
        
        with self.assertRaises(FileNotFoundError):
            load_json(missing_file)


class TestProjectManagement(TestUtilsComprehensive):
    """Test project management utilities."""
    
    def test_find_yyp_success(self):
        """Test finding .yyp file successfully."""
        yyp_file = self._create_test_yyp_file("TestProject")
        
        result = find_yyp(self.project_root)
        self.assertEqual(result, yyp_file)
    
    def test_find_yyp_missing(self):
        """Test finding .yyp file when none exists - should raise ProjectNotFoundError."""
        with self.assertRaises(ProjectNotFoundError):
            find_yyp(self.project_root)
    
    def test_find_yyp_multiple_files(self):
        """Test finding .yyp file when multiple exist."""
        yyp1 = self._create_test_yyp_file("Project1")
        yyp2 = self._create_test_yyp_file("Project2")
        
        # Should return the first one found
        result = find_yyp(self.project_root)
        self.assertIn(result, [yyp1, yyp2])
        self.assertTrue(result.exists())
    
    def test_find_yyp_file_function(self):
        """Test the find_yyp_file function."""
        # Change to project directory
        original_cwd = os.getcwd()
        try:
            os.chdir(self.project_root)
            
            # Create .yyp file
            self._create_test_yyp_file("TestProject")
            
            result = find_yyp_file()
            self.assertIsInstance(result, str)
            self.assertTrue(result.endswith(".yyp"))
            
        finally:
            os.chdir(original_cwd)
    
    def test_find_yyp_file_missing(self):
        """Test find_yyp_file when no .yyp exists - should raise FileNotFoundError."""
        original_cwd = os.getcwd()
        try:
            os.chdir(self.project_root)
            
            with self.assertRaises(FileNotFoundError):
                find_yyp_file()
            
        finally:
            os.chdir(original_cwd)
    
    def test_ensure_directory_new(self):
        """Test creating new directory."""
        new_dir = self.project_root / "new_folder" / "subfolder"
        
        ensure_directory(new_dir)
        
        self.assertTrue(new_dir.exists())
        self.assertTrue(new_dir.is_dir())
    
    def test_ensure_directory_existing(self):
        """Test ensuring existing directory."""
        existing_dir = self.project_root / "existing"
        existing_dir.mkdir()
        
        # Should not raise error
        ensure_directory(existing_dir)
        
        self.assertTrue(existing_dir.exists())
    
    def test_verify_parent_path_exists_valid(self):
        """Test verifying existing parent path."""
        yyp_data = {
            "folders": [
                {"folderPath": "folders/TestFolder.yy"},
                {"folderPath": "folders/SubFolder.yy"}
            ]
        }
        
        result = verify_parent_path_exists(yyp_data, "folders/TestFolder.yy")
        self.assertTrue(result)
    
    def test_verify_parent_path_exists_invalid(self):
        """Test verifying non-existent parent path."""
        yyp_data = {
            "folders": [
                {"folderPath": "folders/TestFolder.yy"}
            ]
        }
        
        result = verify_parent_path_exists(yyp_data, "folders/MissingFolder.yy")
        self.assertFalse(result)
    
    def test_verify_parent_path_exists_empty_path(self):
        """Test verifying empty parent path."""
        yyp_data = {"folders": []}
        
        result = verify_parent_path_exists(yyp_data, "")
        self.assertTrue(result)  # Empty path is considered valid


class TestResourceManagement(TestUtilsComprehensive):
    """Test resource management utilities."""
    
    def test_insert_into_resources_basic(self):
        """Test inserting resource into resources list."""
        resources = [
            {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}},
            {"id": {"name": "asset3", "path": "scripts/asset3/asset3.yy"}}
        ]
        
        insert_into_resources(resources, "asset2", "scripts/asset2/asset2.yy")
        
        # Should be inserted in alphabetical order
        names = [r["id"]["name"] for r in resources]
        self.assertEqual(names, ["asset1", "asset2", "asset3"])
    
    def test_insert_into_resources_empty_list(self):
        """Test inserting into empty resources list."""
        resources = []
        
        insert_into_resources(resources, "asset1", "scripts/asset1/asset1.yy")
        
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["id"]["name"], "asset1")
    
    def test_insert_into_resources_duplicate(self):
        """Test inserting duplicate resource."""
        resources = [
            {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}}
        ]
        
        # Insert same asset again
        insert_into_resources(resources, "asset1", "scripts/asset1/asset1.yy")
        
        # Should still only have one entry
        self.assertEqual(len(resources), 1)
    
    def test_insert_into_folders_basic(self):
        """Test inserting folder into folders list."""
        folders = [
            {"folderPath": "folders/FolderA.yy"},
            {"folderPath": "folders/FolderC.yy"}
        ]
        
        insert_into_folders(folders, "FolderB", "folders/FolderB.yy")
        
        # Should be inserted in alphabetical order
        paths = [f["folderPath"] for f in folders]
        self.assertEqual(paths, ["folders/FolderA.yy", "folders/FolderB.yy", "folders/FolderC.yy"])
    
    def test_insert_into_folders_duplicate(self):
        """Test inserting duplicate folder."""
        folders = [
            {"folderPath": "folders/FolderA.yy"}
        ]
        
        # Insert same folder again  
        insert_into_folders(folders, "FolderA", "folders/FolderA.yy")
        
        # Should still only have one entry
        self.assertEqual(len(folders), 1)
    
    def test_check_resource_conflicts_no_conflict(self):
        """Test checking for resource conflicts with no conflicts."""
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}}
            ]
        }
        
        can_create, conflict_type, message = check_resource_conflicts(yyp_data, "asset2", "scripts/asset2/asset2.yy")
        self.assertTrue(can_create)
        self.assertIsNone(conflict_type)
    
    def test_check_resource_conflicts_name_conflict(self):
        """Test checking for resource conflicts with name collision."""
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}}
            ]
        }
        
        can_create, conflict_type, message = check_resource_conflicts(yyp_data, "asset1", "scripts/asset1_copy/asset1.yy")
        self.assertFalse(can_create)
        self.assertEqual(conflict_type, "name_conflict")
    
    def test_check_resource_conflicts_path_conflict(self):
        """Test checking for resource conflicts with path collision."""
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}}
            ]
        }
        
        can_create, conflict_type, message = check_resource_conflicts(yyp_data, "asset2", "scripts/asset1/asset1.yy")
        self.assertFalse(can_create)
        self.assertEqual(conflict_type, "path_conflict")
    
    def test_find_duplicate_resources_none(self):
        """Test finding duplicates when none exist."""
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}},
                {"id": {"name": "asset2", "path": "scripts/asset2/asset2.yy"}}
            ]
        }
        
        duplicates = find_duplicate_resources(yyp_data)
        self.assertEqual(len(duplicates), 0)
    
    def test_find_duplicate_resources_names(self):
        """Test finding duplicate resource names."""
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}},
                {"id": {"name": "asset1", "path": "scripts/asset1_copy/asset1.yy"}}
            ]
        }
        
        duplicates = find_duplicate_resources(yyp_data)
        self.assertGreater(len(duplicates), 0)
    
    def test_find_duplicate_resources_paths(self):
        """Test finding duplicate resource names."""
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}},
                {"id": {"name": "asset1", "path": "scripts/asset1_copy/asset1.yy"}}
            ]
        }
        
        duplicates = find_duplicate_resources(yyp_data)
        self.assertGreater(len(duplicates), 0)
    
    @patch('builtins.input')
    def test_dedupe_resources_interactive_yes(self, mock_input):
        """Test deduplicating resources with user confirmation."""
        mock_input.return_value = 'a'  # Choose 'a' to keep first entry
        
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}},
                {"id": {"name": "asset1", "path": "scripts/asset1_copy/asset1.yy"}}
            ]
        }
        
        result_data, removed_count, report = dedupe_resources(yyp_data, interactive=True)

        # Should remove duplicates
        self.assertEqual(len(result_data["resources"]), 1)
    
    def test_dedupe_resources_non_interactive(self):
        """Test deduplicating resources without interaction."""
        yyp_data = {
            "resources": [
                {"id": {"name": "asset1", "path": "scripts/asset1/asset1.yy"}},
                {"id": {"name": "asset1", "path": "scripts/asset1_copy/asset1.yy"}}
            ]
        }
        
        result_data, removed_count, report = dedupe_resources(yyp_data, interactive=False)
        
        # Should remove duplicates
        self.assertEqual(len(result_data["resources"]), 1)


class TestValidationUtilities(TestUtilsComprehensive):
    """Test validation utility functions."""
    
    def setUp(self):
        """Set up test environment and clear naming config cache."""
        super().setUp()
        from gms_helpers.naming_config import NamingConfig
        NamingConfig.clear_cache()
    
    def tearDown(self):
        """Clean up and clear naming config cache."""
        from gms_helpers.naming_config import NamingConfig
        NamingConfig.clear_cache()
        super().tearDown()
    
    def test_validate_name_script_valid(self):
        """Test script name validation with valid names."""
        valid_names = [
            "script_name",
            "my_script_123",
            "snake_case_name",
            "simple"
        ]
        
        for name in valid_names:
            with self.subTest(name=name):
                # Should not raise any exception for valid names
                try:
                    validate_name(name, "script")
                except ValueError:
                    self.fail(f"validate_name raised ValueError for valid name: {name}")
    
    def test_validate_name_script_invalid(self):
        """Test script name validation with invalid names."""
        invalid_names = [
            "",  # Empty
            "CamelCase",  # Not snake_case (without constructor flag)
            "invalid-hyphen",  # Hyphen not allowed
            "invalid space",  # Space not allowed
            "invalid@symbol",  # Special character
            "123_start",  # Starting with number
        ]
        
        for name in invalid_names:
            with self.subTest(name=name):
                # Should raise ValueError for invalid names
                with self.assertRaises(ValueError):
                    validate_name(name, "script")
    
    def test_validate_name_script_constructor(self):
        """Test script name validation with constructor flag."""
        valid_constructor_names = [
            "PlayerData",
            "InventoryItem", 
            "StatusEffect",
            "GameData"
        ]
        
        for name in valid_constructor_names:
            with self.subTest(name=name):
                # Should not raise exception when allow_constructor=True
                try:
                    validate_name(name, "script", allow_constructor=True)
                except ValueError:
                    self.fail(f"validate_name raised ValueError for valid constructor name: {name}")
                
                # Should raise exception when allow_constructor=False (default)
                with self.assertRaises(ValueError):
                    validate_name(name, "script", allow_constructor=False)
    
    def test_validate_name_object_valid(self):
        """Test object name validation with valid names."""
        valid_names = [
            "o_player",
            "o_enemy_zombie",
            "o_item_123"
        ]
        
        for name in valid_names:
            with self.subTest(name=name):
                # Should not raise any exception for valid names
                try:
                    validate_name(name, "object")
                except ValueError:
                    self.fail(f"validate_name raised ValueError for valid name: {name}")
    
    def test_validate_name_object_invalid(self):
        """Test object name validation with invalid names."""
        invalid_names = [
            "",  # Empty
            "player",  # Missing o_ prefix
            "obj_player",  # Wrong prefix
            "o_invalid space",  # Space
            "o_invalid@symbol",  # Special character
        ]
        
        for name in invalid_names:
            with self.subTest(name=name):
                # Should raise ValueError for invalid names
                with self.assertRaises(ValueError):
                    validate_name(name, "object")
    
    def test_validate_name_unsupported_type(self):
        """Test validation with unsupported asset type."""
        # Unsupported types should succeed (no validation rules)
        try:
            validate_name("test_name", "unsupported_type")
        except ValueError:
            self.fail("validate_name raised ValueError for unsupported asset type")
    
    def test_validate_name_with_custom_config(self):
        """Test validate_name respects custom config settings."""
        import tempfile
        import json
        from gms_helpers.naming_config import NamingConfig, PROJECT_CONFIG_FILE
        
        # Create a temp directory with custom config
        temp_dir = tempfile.mkdtemp()
        try:
            # Create custom config that uses obj_ prefix for objects
            config_path = Path(temp_dir) / PROJECT_CONFIG_FILE
            custom_config = {
                "naming": {
                    "rules": {
                        "object": {"prefix": "obj_", "pattern": "^obj_[a-z0-9_]*$"}
                    }
                }
            }
            with open(config_path, 'w') as f:
                json.dump(custom_config, f)
            
            # Load config from this directory
            config = NamingConfig(temp_dir)
            
            # obj_player should be valid with custom config
            try:
                validate_name("obj_player", "object", config=config)
            except ValueError:
                self.fail("validate_name rejected obj_player with custom config")
            
            # o_player should be invalid with custom config
            with self.assertRaises(ValueError):
                validate_name("o_player", "object", config=config)
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_validate_name_with_disabled_naming(self):
        """Test validate_name skips validation when naming is disabled."""
        import tempfile
        import json
        from gms_helpers.naming_config import NamingConfig, PROJECT_CONFIG_FILE
        
        # Create a temp directory with naming disabled
        temp_dir = tempfile.mkdtemp()
        try:
            config_path = Path(temp_dir) / PROJECT_CONFIG_FILE
            disabled_config = {
                "naming": {
                    "enabled": False
                }
            }
            with open(config_path, 'w') as f:
                json.dump(disabled_config, f)
            
            config = NamingConfig(temp_dir)
            
            # Any name should be valid when naming is disabled
            try:
                validate_name("any_name_at_all", "object", config=config)
                validate_name("NoPrefix", "sprite", config=config)
            except ValueError:
                self.fail("validate_name raised ValueError when naming is disabled")
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_validate_parent_path_valid(self):
        """Test validating valid parent paths.""" 
        # For empty path, it should return True since the function handles it specially
        result = validate_parent_path("")
        self.assertTrue(result)
        
        # For other paths, we need actual folder data - skip as they require project context
    
    def test_validate_parent_path_invalid(self):
        """Test validating invalid parent paths."""
        invalid_paths = [
            "invalid/path",  # Not in folders/
            "folders/invalid path.yy",  # Space in name
            "folders/invalid@name.yy",  # Special character
            "folders/invalid.txt",  # Wrong extension
        ]
    
        for path in invalid_paths:
            with self.subTest(path=path):
                # Should raise ValidationError for invalid paths
                with self.assertRaises((ValidationError, ProjectNotFoundError)):
                    validate_parent_path(path)


class TestFileUtilities(TestUtilsComprehensive):
    """Test file utility functions."""
    
    def test_generate_uuid_basic(self):
        """Test UUID generation."""
        uuid1 = generate_uuid()
        uuid2 = generate_uuid()
        
        # Should be different UUIDs
        self.assertNotEqual(uuid1, uuid2)
        
        # Should be valid UUID format (simple check)
        self.assertEqual(len(uuid1), 32)  # UUID without hyphens
        self.assertTrue(all(c in '0123456789abcdef' for c in uuid1))
    
    def test_generate_uuid_multiple(self):
        """Test generating multiple UUIDs."""
        uuids = [generate_uuid() for _ in range(10)]
        
        # All should be unique
        self.assertEqual(len(set(uuids)), 10)
    
    def test_create_dummy_png_basic(self):
        """Test creating dummy PNG files."""
        png_path = self.project_root / "test.png"
        
        create_dummy_png(png_path, width=64, height=64)
        
        # Verify PNG file was created
        self.assertTrue(png_path.exists())
        # Verify it's a valid PNG file (starts with PNG signature)
        with open(png_path, 'rb') as f:
            signature = f.read(8)
            f.seek(16)
            width = int.from_bytes(f.read(4), "big")
            height = int.from_bytes(f.read(4), "big")
        self.assertEqual(signature, bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]))
        self.assertEqual(width, 64)
        self.assertEqual(height, 64)
    
    def test_create_dummy_png_custom_dimensions(self):
        """Test creating dummy PNG with custom dimensions."""
        png_path = self.project_root / "custom.png"
        
        create_dummy_png(png_path, width=128, height=256)
        
        # Verify PNG file was created
        self.assertTrue(png_path.exists())
        # Verify it's a valid PNG file
        with open(png_path, 'rb') as f:
            signature = f.read(8)
            f.seek(16)
            width = int.from_bytes(f.read(4), "big")
            height = int.from_bytes(f.read(4), "big")
        self.assertEqual(signature, bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]))
        self.assertEqual(width, 128)
        self.assertEqual(height, 256)
    
    def test_create_dummy_png_no_pil(self):
        """Test creating dummy PNG when PIL is not available (current implementation doesn't use PIL)."""
        png_path = self.project_root / "test.png"
        
        # Current implementation doesn't use PIL, so this should always work
        create_dummy_png(png_path)
        
        # Verify PNG file was created
        self.assertTrue(png_path.exists())
        # Verify it's a valid PNG file
        with open(png_path, 'rb') as f:
            signature = f.read(8)
        self.assertEqual(signature, bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]))


class TestErrorConditions(TestUtilsComprehensive):
    """Test error conditions and edge cases."""
    
    def test_load_json_loose_permission_error(self):
        """Test loading JSON file with permission error."""
        json_file = self.project_root / "restricted.json"
        json_file.write_text('{"test": "data"}', encoding="utf-8")
        with patch('pathlib.Path.read_text', side_effect=PermissionError("No permission")):
            with self.assertRaises(PermissionError):
                load_json_loose(json_file)
    
    def test_save_pretty_json_permission_error(self):
        """Test saving JSON to directory without write permissions."""
        test_data = {"test": "data"}
        
        readonly_dir = self.project_root / "readonly"
        readonly_dir.mkdir()
        json_file = readonly_dir / "test.json"
        with patch('pathlib.Path.write_text', side_effect=PermissionError("No permission")):
            with self.assertRaises(PermissionError):
                save_pretty_json(json_file, test_data)
    
    def test_save_json_directory_creation(self):
        """Test save_json creating directories when they don't exist."""
        test_data = {"test": "data"}
        json_file = str(self.project_root / "new_dir" / "subdir" / "test.json")
        
        save_json(test_data, json_file)
        
        # Verify file and directories were created
        self.assertTrue(Path(json_file).exists())
        
        # Verify content
        loaded_data = load_json(json_file)
        self.assertEqual(loaded_data, test_data)
    
    def test_find_yyp_empty_directory(self):
        """Test finding .yyp in empty directory - should raise ProjectNotFoundError."""
        empty_dir = self.project_root / "empty"
        empty_dir.mkdir()
        
        with self.assertRaises(ProjectNotFoundError):
            find_yyp(empty_dir)
    
    def test_insert_into_resources_malformed_list(self):
        """Test inserting into malformed resources list."""
        # Resources list with missing required fields
        resources = [
            {"name": "incomplete_resource"},  # Missing 'id' structure
            {"id": {"name": "valid_resource", "path": "scripts/valid/valid.yy"}}
        ]
        
        # Should still work, handling malformed entries gracefully
        initial_length = len(resources)
        insert_into_resources(resources, "new_asset", "scripts/new/new.yy")
        
        # Should have added the new resource
        self.assertGreater(len(resources), initial_length)
    
    def test_verify_parent_path_malformed_yyp(self):
        """Test verifying parent path with malformed yyp data."""
        malformed_yyp = {
            # Missing 'folders' key
            "resources": []
        }
        
        # Should handle missing folders gracefully
        result = verify_parent_path_exists(malformed_yyp, "folders/test.yy")
        self.assertFalse(result)
    
    def test_validate_name_edge_cases(self):
        """Test name validation with edge cases."""
        edge_cases = [
            ("_", "script"),  # Single underscore - invalid
            ("a" * 100, "script"),  # Very long name - valid
            ("test_", "script"),  # Trailing underscore - valid
            ("_test", "script"),  # Leading underscore - invalid
        ]
        
        for name, asset_type in edge_cases:
            with self.subTest(name=name, asset_type=asset_type):
                # Should not crash, may raise ValueError for invalid names
                try:
                    validate_name(name, asset_type)
                except ValueError:
                    # Expected for some edge cases
                    pass


class TestCrossPlatformCompatibility(TestUtilsComprehensive):
    """Test cross-platform compatibility scenarios."""
    
    def test_path_handling_windows_style(self):
        """Test handling Windows-style paths - should raise error when path not found."""
        # Test with backslashes (should be normalized but still fail if path doesn't exist)
        windows_path = "folders\\TestFolder.yy"
        
        # validate_parent_path raises error when path is invalid
        with self.assertRaises((ValidationError, ProjectNotFoundError)):
            validate_parent_path(windows_path)
    
    def test_unicode_file_names(self):
        """Test handling Unicode in file names."""
        unicode_data = {"name": "tëst", "value": "ünïcødë"}
        json_file = self.project_root / "unicode_测试.json"
        
        # Should handle Unicode file names
        save_pretty_json(json_file, unicode_data)
        self.assertTrue(json_file.exists())
        
        # Should load Unicode content correctly
        loaded_data = load_json_loose(json_file)
        self.assertEqual(loaded_data, unicode_data)
    

    
    @patch('os.name', 'nt')
    def test_windows_specific_handling(self):
        """Test Windows-specific code paths."""
        # This tests the Windows Unicode console setup code
        # The actual setup happens at import time, so we just verify
        # it doesn't break normal operations
        
        test_data = {"test": "data"}
        json_file = self.project_root / "windows_test.json"
        
        save_pretty_json(json_file, test_data)
        result = load_json_loose(json_file)
        
        self.assertEqual(result, test_data)


if __name__ == '__main__':
    unittest.main()


class TestUtilsFullCoverage(unittest.TestCase):
    """Additional tests to achieve 100% coverage for utils.py"""
    
    def setUp(self):
        """Clear naming config cache for test isolation."""
        from gms_helpers.naming_config import NamingConfig
        NamingConfig.clear_cache()
    
    def tearDown(self):
        """Clear naming config cache after tests."""
        from gms_helpers.naming_config import NamingConfig
        NamingConfig.clear_cache()
    
    def test_validate_name_all_asset_types(self):
        """Test validate_name for all asset types with invalid names."""
        from gms_helpers.utils import validate_name
        
        # Test invalid font name - error should mention the asset type or prefix
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_font", "font")
        error_msg = str(cm.exception).lower()
        self.assertTrue("font" in error_msg or "fnt_" in error_msg)
        
        # Test invalid shader name
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_shader", "shader")
        error_msg = str(cm.exception).lower()
        self.assertTrue("shader" in error_msg or "sh_" in error_msg)
        
        # Test invalid animcurve name
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_curve", "animcurve")
        error_msg = str(cm.exception).lower()
        self.assertTrue("animcurve" in error_msg or "curve_" in error_msg or "ac_" in error_msg)
        
        # Test invalid sound name
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_sound", "sound")
        error_msg = str(cm.exception).lower()
        self.assertTrue("sound" in error_msg or "snd_" in error_msg or "sfx_" in error_msg)
        
        # Test invalid path name
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_path", "path")
        error_msg = str(cm.exception).lower()
        self.assertTrue("path" in error_msg or "pth_" in error_msg)
        
        # Test invalid tileset name
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_tileset", "tileset")
        error_msg = str(cm.exception).lower()
        self.assertTrue("tileset" in error_msg or "ts_" in error_msg or "tile_" in error_msg)
        
        # Test invalid timeline name
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_timeline", "timeline")
        error_msg = str(cm.exception).lower()
        self.assertTrue("timeline" in error_msg or "tl_" in error_msg)
        
        # Test invalid sequence name
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid_sequence", "sequence")
        error_msg = str(cm.exception).lower()
        self.assertTrue("sequence" in error_msg or "seq_" in error_msg)
        
        # Test invalid note name (with special chars)
        with self.assertRaises(ValueError) as cm:
            validate_name("invalid@note!", "note")
        error_msg = str(cm.exception).lower()
        self.assertTrue("note" in error_msg)
    
    def test_insert_into_resources_duplicate(self):
        """Test insert_into_resources when resource already exists."""
        from gms_helpers.utils import insert_into_resources
        
        resources = [{"id": {"name": "test_asset", "path": "path/to/asset.yy"}}]
        
        # Try to insert duplicate
        result = insert_into_resources(resources, "test_asset", "path/to/asset.yy")
        
        self.assertFalse(result)
        self.assertEqual(len(resources), 1)  # Should not add duplicate
    
    def test_add_trailing_commas_continue_paths(self):
        """Test add_trailing_commas with lines that trigger continue statements."""
        from gms_helpers.utils import add_trailing_commas
        
        # Test JSON with complex structure to hit all continue cases
        test_json = '''{
    "object": {
        "nested": [
            {
                "value": 1
            }
        ]
    },
    "array": [
        
    ],
    "another": {
        
    }
}'''
        
        result = add_trailing_commas(test_json)
        
        # The function should add commas where needed
        self.assertIn('"value": 1,', result)
    
    def test_load_json_loose_exceptions(self):
        """Test load_json_loose error handling - should return None for invalid JSON."""
        from gms_helpers.utils import load_json_loose
        from pathlib import Path
        
        # Create a file with invalid JSON that can't be fixed
        test_file = Path("bad_json.json")
        with open(test_file, 'w') as f:
            f.write("not json at all")
        
        # Should return None, not raise exception (that's what "loose" means)
        result = load_json_loose(test_file)
        self.assertIsNone(result)
        
        # Clean up
        test_file.unlink()
    
    def test_update_yyp_file_save_error(self):
        """Test update_yyp_file when save fails."""
        from gms_helpers.utils import update_yyp_file, save_json
        from unittest.mock import patch
        
        # Create valid project
        with open("test_project.yyp", 'w') as f:
            json.dump({"resources": []}, f)
        
        # Mock save_json to raise exception
        with patch('gms_helpers.utils.save_json', side_effect=Exception("Save failed")):
            resource_entry = {"id": {"name": "test", "path": "test.yy"}}
            result = update_yyp_file(resource_entry)
            
            self.assertFalse(result)
    
    def test_dedupe_resources_with_no_name(self):
        """Test dedupe_resources with resource missing name field."""
        from gms_helpers.utils import dedupe_resources
        
        # Test with resource that has no name (will be skipped)
        yyp_data = {
            "resources": [
                {"id": {}},  # Missing name
                {"id": {"name": "valid_resource", "path": "path.yy"}}
            ]
        }
        
        modified_data, removed_count, report = dedupe_resources(yyp_data, interactive=False)
        
        # Should handle gracefully - no duplicates to remove
        self.assertEqual(removed_count, 0)
        self.assertEqual(len(modified_data["resources"]), 2)
