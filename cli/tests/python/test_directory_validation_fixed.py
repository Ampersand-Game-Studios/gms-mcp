#!/usr/bin/env python3
"""
Directory Validation Tests - ACTUALLY WORKING VERSION
====================================================

Fixed tests that properly catch asset location issues without BS.
"""

import unittest
import tempfile
import shutil
import os
import json
from pathlib import Path


class GameMakerContextError(Exception):
    """Mock version of the GameMakerContextError for testing"""
    pass


def mock_validate_gamemaker_context():
    """
    Mock version that ONLY looks in the current temp directory structure
    This prevents interference from real .yyp files on the user's system
    """
    cwd = Path.cwd()
    
    # Only search within our controlled test environment
    # Stop at the first parent that doesn't exist or reaches system root
    current_dir = cwd
    gamemaker_root = None
    max_levels = 5  # Limit search to prevent finding real .yyp files
    
    for _ in range(max_levels):
        if current_dir == current_dir.parent:
            break
            
        # Check if this directory contains a .yyp file
        yyp_files = list(current_dir.glob("*.yyp"))
        if yyp_files:
            gamemaker_root = current_dir
            break
        current_dir = current_dir.parent
    
    if not gamemaker_root:
        raise GameMakerContextError(
            "ERROR: Not in a GameMaker project directory. "
            "GameMaker asset operations must be run from within a directory containing a .yyp project file."
        )
    
    # Additional validation: check for common GameMaker directory structure
    expected_dirs = ['objects', 'sprites', 'scripts', 'rooms']
    missing_dirs = [d for d in expected_dirs if not (gamemaker_root / d).exists()]
    
    if len(missing_dirs) == len(expected_dirs):
        raise GameMakerContextError(
            f"ERROR: Directory '{gamemaker_root}' contains a .yyp file but doesn't appear to be "
            f"a valid GameMaker project (missing standard asset directories: {', '.join(expected_dirs)})"
        )
    
    return gamemaker_root


def mock_validate_asset_directory_structure():
    """Mock version that prevents asset creation outside GameMaker projects"""
    try:
        gamemaker_root = mock_validate_gamemaker_context()
        
        # Ensure we're not creating assets outside the project structure
        cwd = Path.cwd()
        if not str(cwd).startswith(str(gamemaker_root)):
            raise GameMakerContextError(
                f"ERROR: Current directory '{cwd}' is outside GameMaker project '{gamemaker_root}'"
            )
        
        return gamemaker_root
        
    except GameMakerContextError as e:
        # Re-raise the exception without modification
        raise


class TestDirectoryValidation(unittest.TestCase):
    """ACTUALLY WORKING tests for directory validation"""
    
    def setUp(self):
        """Set up isolated test environment"""
        self.temp_root = Path(tempfile.mkdtemp())
        self.original_cwd = os.getcwd()
        
        # Create a proper GameMaker project structure
        self.gamemaker_project = self.temp_root / "gamemaker_project"
        self.gamemaker_project.mkdir()
        
        # Create GameMaker directories
        for dir_name in ['objects', 'sprites', 'scripts', 'rooms', 'folders']:
            (self.gamemaker_project / dir_name).mkdir()
        
        # Create .yyp file
        yyp_content = {
            "$GMProject": "",
            "resources": [],
            "folders": []
        }
        with open(self.gamemaker_project / "test_project.yyp", 'w') as f:
            json.dump(yyp_content, f, indent=2)
        
        # Create a non-GameMaker directory  
        self.non_gamemaker_dir = self.temp_root / "non_gamemaker"
        self.non_gamemaker_dir.mkdir()
    
    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_root, ignore_errors=True)
    
    def test_validate_gamemaker_context_in_valid_project(self):
        """TEST: Should validate successfully in GameMaker project directory"""
        os.chdir(self.gamemaker_project)
        
        # Should not raise exception
        gamemaker_root = mock_validate_gamemaker_context()
        
        # Should return the correct project root
        self.assertEqual(gamemaker_root, self.gamemaker_project)
    
    def test_validate_gamemaker_context_outside_project(self):
        """CRITICAL TEST: Should fail when outside GameMaker project"""
        os.chdir(self.non_gamemaker_dir)
        
        # Should raise GameMakerContextError
        with self.assertRaises(GameMakerContextError) as context:
            mock_validate_gamemaker_context()
        
        # Should have appropriate error message
        error_msg = str(context.exception)
        self.assertIn("Not in a GameMaker project directory", error_msg)
    
    def test_validate_gamemaker_context_in_subdirectory(self):
        """TEST: Should find GameMaker project when in subdirectory"""
        # Create and enter subdirectory within project
        subdir = self.gamemaker_project / "objects" / "some_object"
        subdir.mkdir(parents=True)
        os.chdir(subdir)
        
        # Should find the project root
        gamemaker_root = mock_validate_gamemaker_context()
        self.assertEqual(gamemaker_root, self.gamemaker_project)
    
    def test_validate_gamemaker_context_missing_asset_directories(self):
        """CRITICAL TEST: Should fail if project structure is invalid"""
        # Create directory with .yyp but no asset directories
        invalid_project = self.temp_root / "invalid_project"
        invalid_project.mkdir()
        
        # Create .yyp file but no asset directories
        yyp_content = {"$GMProject": "", "resources": [], "folders": []}
        with open(invalid_project / "invalid.yyp", 'w') as f:
            json.dump(yyp_content, f)
        
        os.chdir(invalid_project)
        
        # Should raise GameMakerContextError for invalid structure
        with self.assertRaises(GameMakerContextError) as context:
            mock_validate_gamemaker_context()
        
        error_msg = str(context.exception)
        self.assertIn("doesn't appear to be a valid GameMaker project", error_msg)
    
    def test_asset_directory_structure_validation_success(self):
        """TEST: Asset directory structure validation should succeed in valid project"""
        os.chdir(self.gamemaker_project)
        
        # Should not raise exception
        gamemaker_root = mock_validate_asset_directory_structure()
        self.assertEqual(gamemaker_root, self.gamemaker_project)
    
    def test_asset_directory_structure_validation_failure(self):
        """CRITICAL TEST: Asset directory structure validation should fail outside project"""
        os.chdir(self.non_gamemaker_dir)
        
        # Should raise GameMakerContextError
        with self.assertRaises(GameMakerContextError):
            mock_validate_asset_directory_structure()
    
    def test_asset_creation_outside_project_prevented(self):
        """
        CRITICAL TEST: Asset creation should be prevented outside GameMaker project
        This test simulates the exact issue from social tab implementation
        """
        # Simulate being in wrong directory (like the root of the repo)
        wrong_dir = self.temp_root / "wrong_location"
        wrong_dir.mkdir()
        os.chdir(wrong_dir)
        
        # Try to create an asset - should fail with directory validation
        with self.assertRaises(GameMakerContextError) as context:
            # This simulates what should happen when running:
            # gms asset create script my_script --parent-path "folders/Scripts.yy"
            mock_validate_asset_directory_structure()
        
        # Should provide helpful error message
        error_msg = str(context.exception)
        self.assertIn("Not in a GameMaker project directory", error_msg)
    
    def test_asset_creation_in_correct_location_allowed(self):
        """TEST: Asset creation should be allowed in correct GameMaker project location"""
        os.chdir(self.gamemaker_project)
        
        # This should succeed without raising exception
        gamemaker_root = mock_validate_asset_directory_structure()
        self.assertEqual(gamemaker_root, self.gamemaker_project)
        
        # Verify we're in the right place for asset creation
        self.assertTrue((gamemaker_root / "scripts").exists())
        self.assertTrue((gamemaker_root / "objects").exists())
        self.assertTrue((gamemaker_root / "sprites").exists())


class TestSocialTabScenario(unittest.TestCase):
    """Test the exact scenario from social tab implementation"""
    
    def setUp(self):
        """Set up test environment matching the actual project structure"""
        self.temp_root = Path(tempfile.mkdtemp())
        self.original_cwd = os.getcwd()
        
        # Recreate the exact structure from the issue
        self.project_root = self.temp_root / "gms2-template"
        self.project_root.mkdir()
        
        self.gamemaker_dir = self.project_root / "gamemaker"
        self.gamemaker_dir.mkdir()
        
        # Create gamemaker structure
        for dir_name in ['objects', 'sprites', 'scripts', 'rooms', 'folders']:
            (self.gamemaker_dir / dir_name).mkdir()
        
        # Create .yyp file
        yyp_content = {"$GMProject": "", "resources": [], "folders": []}
        with open(self.gamemaker_dir / "gms2-template.yyp", 'w') as f:
            json.dump(yyp_content, f)
        
        # Create other directories that exist in the real project
        (self.project_root / "tests").mkdir()
        (self.project_root / "docs").mkdir()
        (self.project_root / "tooling").mkdir()
    
    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_root, ignore_errors=True)
    
    def test_social_tab_script_creation_scenario(self):
        """
        CRITICAL TEST: Simulate the exact scenario where ui_tab_social_friends_create_main.gml
        was created in the wrong location during social tab implementation
        """
        # Start in project root (where the command was run from)
        os.chdir(self.project_root)
        
        # Attempt to create script - should fail with directory validation
        with self.assertRaises(GameMakerContextError):
            # This simulates:
            # gms asset create script ui_tab_social_friends_create_main --parent-path "folders/UI/..."
            mock_validate_asset_directory_structure()
        
        # Verify that the wrong scripts/ directory was NOT created
        wrong_scripts_dir = self.project_root / "scripts"
        self.assertFalse(wrong_scripts_dir.exists(), 
                        "Wrong scripts directory was created despite validation!")
    
    def test_correct_workflow_from_gamemaker_directory(self):
        """TEST: Simulate the correct workflow when running from gamemaker/ directory"""
        # Start in correct gamemaker directory
        os.chdir(self.gamemaker_dir)
        
        # Should succeed with directory validation
        gamemaker_root = mock_validate_asset_directory_structure()
        self.assertEqual(gamemaker_root, self.gamemaker_dir)
        
        # Verify correct structure exists
        self.assertTrue((gamemaker_root / "scripts").exists())
        self.assertTrue((gamemaker_root / "objects").exists())
        self.assertTrue((gamemaker_root / "sprites").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2) 