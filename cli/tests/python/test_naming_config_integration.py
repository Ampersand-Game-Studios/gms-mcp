#!/usr/bin/env python3
"""
Integration tests for the configurable naming conventions system.

These tests verify the full workflow of:
1. Creating a project with custom .gms-mcp.json config
2. Creating assets with non-default prefixes
3. Verifying validation passes with custom rules
4. Verifying linter respects the config
"""

import unittest
import tempfile
import shutil
import json
import os
import sys
from pathlib import Path

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.naming_config import (
    NamingConfig,
    get_config,
    create_default_config_file,
    PROJECT_CONFIG_FILE,
)
from gms_helpers.utils import validate_name
from gms_helpers.maintenance.lint import ProjectLinter


class TestNamingConfigIntegration(unittest.TestCase):
    """Integration tests for configurable naming conventions."""
    
    def setUp(self):
        """Set up test environment with a complete project structure."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a complete GameMaker project structure
        self._create_project_structure()
        
        # Clear config cache for test isolation
        NamingConfig.clear_cache()
        
        # Change to project directory
        self.original_cwd = os.getcwd()
        os.chdir(self.project_root)
    
    def tearDown(self):
        """Clean up test environment."""
        os.chdir(self.original_cwd)
        NamingConfig.clear_cache()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_project_structure(self):
        """Create a minimal GameMaker project structure."""
        # Create standard folders
        for folder in ['objects', 'sprites', 'scripts', 'rooms', 'fonts', 'sounds', 'shaders']:
            (self.project_root / folder).mkdir(exist_ok=True)
        
        # Create a .yyp file
        yyp_data = {
            "$GMProject": "",
            "%Name": "TestProject",
            "name": "TestProject",
            "resources": [],
            "Folders": [],
            "resourceType": "GMProject",
            "resourceVersion": "2.0"
        }
        yyp_path = self.project_root / "TestProject.yyp"
        with open(yyp_path, 'w') as f:
            json.dump(yyp_data, f, indent=2)
    
    def _create_object_asset(self, name: str):
        """Create a minimal object asset for testing."""
        obj_dir = self.project_root / "objects" / name
        obj_dir.mkdir(parents=True, exist_ok=True)
        
        # Create .yy file
        yy_data = {
            "$GMObject": "",
            "%Name": name,
            "name": name,
            "parent": {"name": "Objects", "path": "folders/Objects.yy"},
            "resourceType": "GMObject",
            "resourceVersion": "2.0"
        }
        yy_path = obj_dir / f"{name}.yy"
        with open(yy_path, 'w') as f:
            json.dump(yy_data, f, indent=2)
        
        # Add to .yyp resources
        yyp_path = self.project_root / "TestProject.yyp"
        with open(yyp_path, 'r') as f:
            yyp_data = json.load(f)
        
        yyp_data["resources"].append({
            "id": {"name": name, "path": f"objects/{name}/{name}.yy"}
        })
        
        with open(yyp_path, 'w') as f:
            json.dump(yyp_data, f, indent=2)
    
    def _create_sprite_asset(self, name: str):
        """Create a minimal sprite asset for testing."""
        spr_dir = self.project_root / "sprites" / name
        spr_dir.mkdir(parents=True, exist_ok=True)
        
        yy_data = {
            "$GMSprite": "",
            "%Name": name,
            "name": name,
            "parent": {"name": "Sprites", "path": "folders/Sprites.yy"},
            "resourceType": "GMSprite",
            "resourceVersion": "2.0"
        }
        yy_path = spr_dir / f"{name}.yy"
        with open(yy_path, 'w') as f:
            json.dump(yy_data, f, indent=2)
        
        # Add to .yyp resources
        yyp_path = self.project_root / "TestProject.yyp"
        with open(yyp_path, 'r') as f:
            yyp_data = json.load(f)
        
        yyp_data["resources"].append({
            "id": {"name": name, "path": f"sprites/{name}/{name}.yy"}
        })
        
        with open(yyp_path, 'w') as f:
            json.dump(yyp_data, f, indent=2)

    # =========================================================================
    # Test 1: Custom prefix validation works
    # =========================================================================
    
    def test_custom_prefix_validation(self):
        """Test that assets with non-default prefixes pass validation when configured."""
        # Create custom config with obj_ prefix for objects
        custom_config = {
            "naming": {
                "rules": {
                    "object": {"prefix": "obj_", "pattern": "^obj_[a-z0-9_]*$"}
                }
            }
        }
        config_path = self.project_root / PROJECT_CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(custom_config, f)
        
        # Reload config
        config = NamingConfig(self.project_root)
        
        # Create assets with custom naming
        self._create_object_asset("obj_player")
        
        # Validate - should pass with custom prefix
        try:
            validate_name("obj_player", "object", config=config)
        except ValueError:
            self.fail("validate_name rejected obj_player with custom config")
        
        # Default prefix should now fail
        with self.assertRaises(ValueError):
            validate_name("o_player", "object", config=config)
    
    # =========================================================================
    # Test 2: Linter respects project config
    # =========================================================================
    
    def test_linter_respects_custom_config(self):
        """Test that linter uses project config for naming validation."""
        # Create custom config that uses obj_ prefix
        custom_config = {
            "naming": {
                "enabled": True,
                "rules": {
                    "object": {
                        "prefix": "obj_",
                        "pattern": "^obj_[a-z0-9_]*$",
                        "description": "Objects should use obj_ prefix"
                    }
                }
            }
        }
        config_path = self.project_root / PROJECT_CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(custom_config, f)
        
        # Create object with custom naming
        self._create_object_asset("obj_player")
        
        # Run linter - should not report naming issues for obj_player
        linter = ProjectLinter(str(self.project_root))
        issues = linter.scan_project()
        
        # Filter to naming issues only
        naming_issues = [i for i in issues if i.category == 'naming']
        
        # Should have no naming issues for obj_player
        obj_issues = [i for i in naming_issues if 'obj_player' in str(i)]
        self.assertEqual(len(obj_issues), 0, f"Unexpected naming issues: {obj_issues}")
    
    def test_linter_reports_violations_with_custom_config(self):
        """Test that linter reports violations based on custom config."""
        # First create the object (which creates physical files)
        self._create_object_asset("o_player")
        
        # NOW create custom config that requires obj_ prefix
        # This simulates a project where someone adopts stricter naming later
        # Note: We use raw strings for the pattern to avoid escape issues
        config_path = self.project_root / PROJECT_CONFIG_FILE
        config_content = '''{
  "naming": {
    "enabled": true,
    "rules": {
      "object": {
        "prefix": "obj_",
        "pattern": "^obj_[a-z0-9_]*$",
        "description": "Objects should use obj_ prefix"
      }
    }
  }
}'''
        config_path.write_text(config_content, encoding='utf-8')
        
        # Invalidate cache so linter picks up new config
        NamingConfig.invalidate(self.project_root)
        
        # Run linter
        linter = ProjectLinter(str(self.project_root))
        issues = linter.scan_project()
        
        # Filter to naming issues
        naming_issues = [i for i in issues if i.category == 'naming']
        
        # Should have a naming issue for o_player (violates custom obj_ rule)
        o_player_issues = [i for i in naming_issues if 'o_player' in str(i)]
        self.assertGreater(len(o_player_issues), 0, "Linter should report o_player as violation")
    
    # =========================================================================
    # Test 3: Disabled naming validation
    # =========================================================================
    
    def test_linter_skips_naming_when_disabled(self):
        """Test that linter skips naming validation when disabled."""
        # Create config with naming disabled
        disabled_config = {
            "naming": {
                "enabled": False
            }
        }
        config_path = self.project_root / PROJECT_CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(disabled_config, f)
        
        # Create objects with various "invalid" names
        self._create_object_asset("PlayerController")  # No prefix at all
        self._create_object_asset("badname")  # No prefix
        
        # Run linter
        linter = ProjectLinter(str(self.project_root))
        issues = linter.scan_project()
        
        # Filter to naming issues
        naming_issues = [i for i in issues if i.category == 'naming']
        
        # Should have NO naming issues when disabled
        self.assertEqual(len(naming_issues), 0, f"Naming issues found when disabled: {naming_issues}")
    
    # =========================================================================
    # Test 4: Multiple prefix support
    # =========================================================================
    
    def test_multiple_prefix_support(self):
        """Test that multiple prefixes are all accepted."""
        # Create config with multiple accepted prefixes
        multi_config = {
            "naming": {
                "rules": {
                    "sprite": {
                        "prefix": ["spr_", "sprite_", "s_"],
                        "pattern": "^(spr_|sprite_|s_)[a-z0-9_]*$"
                    }
                }
            }
        }
        config_path = self.project_root / PROJECT_CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(multi_config, f)
        
        config = NamingConfig(self.project_root)
        
        # All these should be valid
        valid_names = ["spr_player", "sprite_player", "s_player"]
        for name in valid_names:
            try:
                validate_name(name, "sprite", config=config)
            except ValueError:
                self.fail(f"validate_name rejected {name} with multi-prefix config")
        
        # This should be invalid
        with self.assertRaises(ValueError):
            validate_name("invalid_sprite", "sprite", config=config)
    
    # =========================================================================
    # Test 5: Config file creation via install
    # =========================================================================
    
    def test_create_default_config_file(self):
        """Test that create_default_config_file works correctly."""
        # Remove any existing config
        config_path = self.project_root / PROJECT_CONFIG_FILE
        if config_path.exists():
            config_path.unlink()
        
        # Create default config
        created_path = create_default_config_file(self.project_root)
        
        self.assertTrue(created_path.exists())
        self.assertEqual(created_path, config_path)
        
        # Verify it's valid JSON with expected structure
        with open(created_path, 'r') as f:
            data = json.load(f)
        
        self.assertIn("naming", data)
        self.assertIn("rules", data["naming"])
        self.assertIn("object", data["naming"]["rules"])
    
    # =========================================================================
    # Test 6: Partial config override
    # =========================================================================
    
    def test_partial_config_override(self):
        """Test that partial config merges correctly with defaults."""
        # Create config that only overrides object prefix
        partial_config = {
            "naming": {
                "rules": {
                    "object": {"prefix": "OBJ_"}
                }
            }
        }
        config_path = self.project_root / PROJECT_CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(partial_config, f)
        
        config = NamingConfig(self.project_root)
        
        # Object should have custom prefix
        obj_rule = config.get_rule("object")
        self.assertEqual(obj_rule["prefix"], "OBJ_")
        
        # Sprite should still have default prefix
        sprite_rule = config.get_rule("sprite")
        self.assertEqual(sprite_rule["prefix"], "spr_")
        
        # Script should still allow constructors by default
        self.assertTrue(config.allows_pascal_constructors("script"))


class TestConfigWithAssetClasses(unittest.TestCase):
    """Test that asset classes respect the naming config."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create minimal .yyp file
        yyp_path = self.project_root / "Test.yyp"
        with open(yyp_path, 'w') as f:
            json.dump({"resources": []}, f)
        
        NamingConfig.clear_cache()
    
    def tearDown(self):
        """Clean up."""
        NamingConfig.clear_cache()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_object_asset_validate_name_uses_config(self):
        """Test ObjectAsset.validate_name uses config."""
        from gms_helpers.assets import ObjectAsset
        
        # Create custom config
        custom_config = {
            "naming": {
                "rules": {
                    "object": {"prefix": "obj_", "pattern": "^obj_[a-z0-9_]*$"}
                }
            }
        }
        config_path = self.project_root / PROJECT_CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(custom_config, f)
        
        # Test validation with config
        os.chdir(self.project_root)
        try:
            obj = ObjectAsset()
            
            # With custom config, obj_ should be valid
            self.assertTrue(obj.validate_name("obj_player"))
            
            # o_ should not match the custom pattern
            self.assertFalse(obj.validate_name("o_player"))
        finally:
            os.chdir(PROJECT_ROOT)
    
    def test_sprite_asset_validate_name_uses_config(self):
        """Test SpriteAsset.validate_name uses config."""
        from gms_helpers.assets import SpriteAsset
        
        # Create custom config
        custom_config = {
            "naming": {
                "rules": {
                    "sprite": {"prefix": "sprite_", "pattern": "^sprite_[a-z0-9_]*$"}
                }
            }
        }
        config_path = self.project_root / PROJECT_CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(custom_config, f)
        
        os.chdir(self.project_root)
        try:
            sprite = SpriteAsset()
            
            # With custom config, sprite_ should be valid
            self.assertTrue(sprite.validate_name("sprite_player"))
            
            # spr_ should not match custom pattern
            self.assertFalse(sprite.validate_name("spr_player"))
        finally:
            os.chdir(PROJECT_ROOT)


if __name__ == "__main__":
    unittest.main()
