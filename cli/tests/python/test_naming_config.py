#!/usr/bin/env python3
"""
Comprehensive test suite for naming_config.py

Tests configurable naming conventions, config loading, merging, and validation.
"""

import unittest
import tempfile
import shutil
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.naming_config import (
    NamingConfig,
    get_config,
    get_factory_defaults,
    create_default_config_file,
    validate_config,
    PROJECT_CONFIG_FILE,
    GLOBAL_CONFIG_DIR,
    GLOBAL_CONFIG_FILE,
    _deep_merge,
)


class TestNamingConfigBase(unittest.TestCase):
    """Base class with common setup/teardown."""
    
    def setUp(self):
        """Set up test environment with temporary directories."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a minimal project structure
        (self.project_root / "test.yyp").write_text('{"resources":[]}')
        
        # Clear the config cache before each test
        NamingConfig.clear_cache()
    
    def tearDown(self):
        """Clean up test environment."""
        NamingConfig.clear_cache()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_config_file(self, config_data: dict, path: Path = None):
        """Helper to create a config file."""
        if path is None:
            path = self.project_root / PROJECT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
        return path


class TestFactoryDefaults(TestNamingConfigBase):
    """Test factory default configuration."""
    
    def test_default_config_loads(self):
        """Verify factory defaults load correctly."""
        defaults = get_factory_defaults()
        
        self.assertIn("$schema", defaults)
        self.assertIn("naming", defaults)
        self.assertIn("linting", defaults)
        
        # Check naming section
        naming = defaults["naming"]
        self.assertTrue(naming.get("enabled", False))
        self.assertIn("rules", naming)
        
        # Check that key asset types are present
        rules = naming["rules"]
        expected_types = ["object", "sprite", "script", "room", "font", "shader"]
        for asset_type in expected_types:
            self.assertIn(asset_type, rules, f"Missing rule for {asset_type}")
    
    def test_default_object_prefix(self):
        """Verify default object prefix is o_."""
        defaults = get_factory_defaults()
        object_rule = defaults["naming"]["rules"]["object"]
        self.assertEqual(object_rule["prefix"], "o_")
    
    def test_default_sprite_prefix(self):
        """Verify default sprite prefix is spr_."""
        defaults = get_factory_defaults()
        sprite_rule = defaults["naming"]["rules"]["sprite"]
        self.assertEqual(sprite_rule["prefix"], "spr_")
    
    def test_default_script_allows_constructors(self):
        """Verify scripts allow PascalCase constructors by default."""
        defaults = get_factory_defaults()
        script_rule = defaults["naming"]["rules"]["script"]
        self.assertTrue(script_rule.get("allow_pascal_constructors", False))


class TestConfigLoading(TestNamingConfigBase):
    """Test configuration loading from files."""
    
    def test_loads_without_config_file(self):
        """Config loads factory defaults when no config file exists."""
        config = NamingConfig(self.project_root)
        
        self.assertTrue(config.naming_enabled)
        self.assertIsNotNone(config.get_rule("object"))
    
    def test_project_config_overrides_defaults(self):
        """Project config merges with and overrides defaults."""
        # Create project config with custom object prefix
        project_config = {
            "naming": {
                "rules": {
                    "object": {"prefix": "obj_", "pattern": "^obj_[a-z0-9_]*$"}
                }
            }
        }
        self._create_config_file(project_config)
        
        config = NamingConfig(self.project_root)
        
        # Object should have custom prefix
        object_rule = config.get_rule("object")
        self.assertEqual(object_rule["prefix"], "obj_")
        
        # Sprite should still have default prefix
        sprite_rule = config.get_rule("sprite")
        self.assertEqual(sprite_rule["prefix"], "spr_")
    
    def test_global_config_fallback(self):
        """Global config used when project config missing."""
        # Create global config
        global_config_dir = Path.home() / GLOBAL_CONFIG_DIR
        global_config_path = global_config_dir / GLOBAL_CONFIG_FILE
        
        try:
            global_config_dir.mkdir(parents=True, exist_ok=True)
            global_config = {
                "naming": {
                    "rules": {
                        "object": {"prefix": "OBJ_"}
                    }
                }
            }
            with open(global_config_path, 'w') as f:
                json.dump(global_config, f)
            
            # No project config, should use global
            config = NamingConfig(self.project_root)
            object_rule = config.get_rule("object")
            self.assertEqual(object_rule["prefix"], "OBJ_")
            
        finally:
            # Clean up global config
            if global_config_path.exists():
                global_config_path.unlink()
            try:
                global_config_dir.rmdir()
            except OSError:
                pass  # Directory not empty or doesn't exist
    
    def test_partial_config_merge(self):
        """User can override single rule, rest use defaults."""
        # Only override font prefix
        project_config = {
            "naming": {
                "rules": {
                    "font": {"prefix": "font_"}
                }
            }
        }
        self._create_config_file(project_config)
        
        config = NamingConfig(self.project_root)
        
        # Font should have custom prefix
        font_rule = config.get_rule("font")
        self.assertEqual(font_rule["prefix"], "font_")
        
        # Other rules should still have defaults
        self.assertEqual(config.get_rule("object")["prefix"], "o_")
        self.assertEqual(config.get_rule("sprite")["prefix"], "spr_")
        self.assertEqual(config.get_rule("room")["prefix"], "r_")


class TestNamingEnabled(TestNamingConfigBase):
    """Test naming.enabled flag behavior."""
    
    def test_naming_enabled_by_default(self):
        """Naming is enabled by default."""
        config = NamingConfig(self.project_root)
        self.assertTrue(config.naming_enabled)
    
    def test_disabled_naming_skips_validation(self):
        """When naming.enabled is False, naming_enabled returns False."""
        project_config = {
            "naming": {
                "enabled": False
            }
        }
        self._create_config_file(project_config)
        
        config = NamingConfig(self.project_root)
        self.assertFalse(config.naming_enabled)


class TestPrefixHandling(TestNamingConfigBase):
    """Test prefix configuration handling."""
    
    def test_custom_prefix_single(self):
        """Single prefix string works."""
        project_config = {
            "naming": {
                "rules": {
                    "object": {"prefix": "obj_"}
                }
            }
        }
        self._create_config_file(project_config)
        
        config = NamingConfig(self.project_root)
        prefixes = config.get_prefixes("object")
        
        self.assertEqual(prefixes, ["obj_"])
    
    def test_custom_prefix_array(self):
        """Array of prefixes works."""
        project_config = {
            "naming": {
                "rules": {
                    "shader": {"prefix": ["shd_", "shader_", "sh_"]}
                }
            }
        }
        self._create_config_file(project_config)
        
        config = NamingConfig(self.project_root)
        prefixes = config.get_prefixes("shader")
        
        self.assertEqual(prefixes, ["shd_", "shader_", "sh_"])
    
    def test_empty_prefix(self):
        """Empty prefix returns empty list."""
        project_config = {
            "naming": {
                "rules": {
                    "script": {"prefix": ""}
                }
            }
        }
        self._create_config_file(project_config)
        
        config = NamingConfig(self.project_root)
        prefixes = config.get_prefixes("script")
        
        self.assertEqual(prefixes, [])


class TestPatternHandling(TestNamingConfigBase):
    """Test pattern configuration handling."""
    
    def test_custom_pattern_regex(self):
        """Custom regex pattern is stored correctly."""
        project_config = {
            "naming": {
                "rules": {
                    "object": {"pattern": "^[A-Z][a-zA-Z0-9]*$"}
                }
            }
        }
        self._create_config_file(project_config)
        
        config = NamingConfig(self.project_root)
        pattern = config.get_pattern("object")
        
        self.assertEqual(pattern, "^[A-Z][a-zA-Z0-9]*$")
    
    def test_get_pattern_for_unknown_type(self):
        """get_pattern returns None for unknown asset type."""
        config = NamingConfig(self.project_root)
        pattern = config.get_pattern("unknown_asset_type")
        
        self.assertIsNone(pattern)


class TestConfigCaching(TestNamingConfigBase):
    """Test configuration caching behavior."""
    
    def test_config_caching(self):
        """Same project root returns cached config."""
        config1 = get_config(self.project_root)
        config2 = get_config(self.project_root)
        
        # Should be the same instance
        self.assertIs(config1, config2)
    
    def test_different_projects_different_configs(self):
        """Different project roots get different configs."""
        other_dir = tempfile.mkdtemp()
        try:
            (Path(other_dir) / "other.yyp").write_text('{}')
            
            config1 = get_config(self.project_root)
            config2 = get_config(other_dir)
            
            # Should be different instances
            self.assertIsNot(config1, config2)
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)
    
    def test_cache_clear(self):
        """Cache can be cleared."""
        config1 = get_config(self.project_root)
        NamingConfig.clear_cache()
        config2 = get_config(self.project_root)
        
        # Should be different instances after cache clear
        self.assertIsNot(config1, config2)
    
    def test_invalidate_specific_project(self):
        """Can invalidate cache for specific project."""
        config1 = get_config(self.project_root)
        NamingConfig.invalidate(self.project_root)
        config2 = get_config(self.project_root)
        
        # Should be different instances
        self.assertIsNot(config1, config2)


class TestInvalidConfig(TestNamingConfigBase):
    """Test handling of invalid configuration files."""
    
    def test_invalid_config_json(self):
        """Graceful fallback on malformed JSON."""
        config_path = self.project_root / PROJECT_CONFIG_FILE
        config_path.write_text("{ invalid json }", encoding='utf-8')
        
        # Should not raise, should fall back to defaults
        config = NamingConfig(self.project_root)
        
        # Should still work with defaults
        self.assertTrue(config.naming_enabled)
        self.assertIsNotNone(config.get_rule("object"))
    
    def test_config_with_trailing_commas(self):
        """Config files with trailing commas are handled."""
        config_path = self.project_root / PROJECT_CONFIG_FILE
        config_path.write_text('{"naming": {"enabled": true,},}', encoding='utf-8')
        
        # Should handle trailing commas gracefully
        config = NamingConfig(self.project_root)
        self.assertTrue(config.naming_enabled)


class TestCreateConfigFile(TestNamingConfigBase):
    """Test config file creation."""
    
    def test_create_default_config_file(self):
        """create_default_config_file creates valid config."""
        config_path = create_default_config_file(self.project_root)
        
        self.assertTrue(config_path.exists())
        
        # Load and verify it's valid JSON
        with open(config_path, 'r') as f:
            data = json.load(f)
        
        self.assertIn("naming", data)
        self.assertIn("rules", data["naming"])
    
    def test_create_config_file_no_overwrite(self):
        """create_default_config_file raises if file exists and overwrite=False."""
        # Create a config file first
        create_default_config_file(self.project_root)
        
        # Should raise FileExistsError
        with self.assertRaises(FileExistsError):
            create_default_config_file(self.project_root, overwrite=False)
    
    def test_create_config_file_with_overwrite(self):
        """create_default_config_file overwrites when overwrite=True."""
        # Create a config file with custom content
        config_path = self.project_root / PROJECT_CONFIG_FILE
        config_path.write_text('{"custom": true}')
        
        # Overwrite with defaults
        create_default_config_file(self.project_root, overwrite=True)
        
        # Should have default content now
        with open(config_path, 'r') as f:
            data = json.load(f)
        
        self.assertIn("naming", data)
        self.assertNotIn("custom", data)


class TestValidateConfig(TestNamingConfigBase):
    """Test config validation."""
    
    def test_validate_valid_config(self):
        """Valid config returns no errors."""
        config = get_factory_defaults()
        errors = validate_config(config)
        
        self.assertEqual(errors, [])
    
    def test_validate_invalid_pattern(self):
        """Invalid regex pattern is detected."""
        config = {
            "naming": {
                "rules": {
                    "object": {"pattern": "[invalid(regex"}
                }
            }
        }
        errors = validate_config(config)
        
        self.assertTrue(any("regex" in e.lower() for e in errors))
    
    def test_validate_invalid_prefix_type(self):
        """Invalid prefix type is detected."""
        config = {
            "naming": {
                "rules": {
                    "object": {"prefix": 123}  # Should be string or list
                }
            }
        }
        errors = validate_config(config)
        
        self.assertTrue(any("prefix" in e.lower() for e in errors))


class TestDeepMerge(unittest.TestCase):
    """Test the _deep_merge helper function."""
    
    def test_simple_merge(self):
        """Simple dict merge works."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        
        self.assertEqual(result, {"a": 1, "b": 3, "c": 4})
    
    def test_nested_merge(self):
        """Nested dict merge works."""
        base = {"outer": {"inner1": 1, "inner2": 2}}
        override = {"outer": {"inner2": 3, "inner3": 4}}
        result = _deep_merge(base, override)
        
        self.assertEqual(result, {"outer": {"inner1": 1, "inner2": 3, "inner3": 4}})
    
    def test_merge_does_not_modify_original(self):
        """Merge does not modify original dicts."""
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        
        _deep_merge(base, override)
        
        # Original should be unchanged
        self.assertEqual(base, {"a": {"b": 1}})
        self.assertEqual(override, {"a": {"c": 2}})


class TestConfigManagerMethods(TestNamingConfigBase):
    """Test NamingConfig helper methods."""
    
    def test_allows_pascal_constructors(self):
        """allows_pascal_constructors returns correct value."""
        config = NamingConfig(self.project_root)
        
        # Scripts should allow constructors by default
        self.assertTrue(config.allows_pascal_constructors("script"))
        
        # Other types should not
        self.assertFalse(config.allows_pascal_constructors("object"))
    
    def test_get_linting_option(self):
        """get_linting_option returns correct values."""
        config = NamingConfig(self.project_root)
        
        # Default linting options
        self.assertTrue(config.get_linting_option("block_on_critical_errors"))
        
        # Non-existent option returns default
        self.assertEqual(config.get_linting_option("nonexistent", "default"), "default")
    
    def test_raw_config(self):
        """raw_config returns a copy of the config."""
        config = NamingConfig(self.project_root)
        raw = config.raw_config
        
        # Should be a dict
        self.assertIsInstance(raw, dict)
        
        # Modifying raw should not affect config
        raw["test"] = "value"
        self.assertNotIn("test", config.raw_config)
    
    def test_to_json(self):
        """to_json returns valid JSON string."""
        config = NamingConfig(self.project_root)
        json_str = config.to_json()
        
        # Should be valid JSON
        data = json.loads(json_str)
        self.assertIn("naming", data)
    
    def test_reload(self):
        """reload() reloads config from disk."""
        config = NamingConfig(self.project_root)
        
        # Initial state - uses defaults
        self.assertEqual(config.get_rule("object")["prefix"], "o_")
        
        # Create a config file with different settings
        project_config = {
            "naming": {
                "rules": {
                    "object": {"prefix": "obj_"}
                }
            }
        }
        self._create_config_file(project_config)
        
        # Reload
        config.reload()
        
        # Should now have new settings
        self.assertEqual(config.get_rule("object")["prefix"], "obj_")


if __name__ == "__main__":
    unittest.main()
