"""
Configurable naming conventions and linting rules for GameMaker projects.

This module provides a per-project configuration system that allows users to
customize asset naming prefixes, validation patterns, and linting behavior.

Configuration Resolution Order:
1. Project config (.gms-mcp.json in project root)
2. Global config (~/.gms-mcp/config.json)
3. Factory defaults (built into this module)
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from copy import deepcopy

# Configuration file names
PROJECT_CONFIG_FILE = ".gms-mcp.json"
GLOBAL_CONFIG_DIR = ".gms-mcp"
GLOBAL_CONFIG_FILE = "config.json"

# Schema version for compatibility checking
CONFIG_SCHEMA_VERSION = "gms-mcp-config-v1"


def _get_factory_defaults() -> Dict[str, Any]:
    """Return the factory default configuration.
    
    These defaults match the original hard-coded behavior of the tool.
    """
    return {
        "$schema": CONFIG_SCHEMA_VERSION,
        "naming": {
            "enabled": True,
            "rules": {
                "object": {
                    "prefix": "o_",
                    "pattern": "^o_[a-z0-9_]*$",
                    "description": "Objects should start with o_ prefix"
                },
                "sprite": {
                    "prefix": "spr_",
                    "pattern": "^spr_[a-z0-9_]*$",
                    "description": "Sprites should start with spr_ prefix"
                },
                "script": {
                    "prefix": "",
                    "pattern": "^[a-z][a-z0-9_]*$",
                    "allow_pascal_constructors": True,
                    "description": "Scripts should be snake_case (constructors can be PascalCase)"
                },
                "room": {
                    "prefix": "r_",
                    "pattern": "^r_[a-z0-9_]*$",
                    "description": "Rooms should start with r_ prefix"
                },
                "font": {
                    "prefix": "fnt_",
                    "pattern": "^fnt_[a-z0-9_]*$",
                    "description": "Fonts should start with fnt_ prefix"
                },
                "shader": {
                    "prefix": ["sh_", "shader_"],
                    "pattern": "^(sh_|shader_)[a-z0-9_]*$",
                    "description": "Shaders should start with sh_ or shader_ prefix"
                },
                "animcurve": {
                    "prefix": ["curve_", "ac_"],
                    "pattern": "^(curve_|ac_)[a-z0-9_]*$",
                    "description": "Animation curves should start with curve_ or ac_ prefix"
                },
                "sound": {
                    "prefix": ["snd_", "sfx_"],
                    "pattern": "^(snd_|sfx_)[a-z0-9_]*$",
                    "description": "Sounds should start with snd_ or sfx_ prefix"
                },
                "path": {
                    "prefix": ["pth_", "path_"],
                    "pattern": "^(pth_|path_)[a-z0-9_]*$",
                    "description": "Paths should start with pth_ or path_ prefix"
                },
                "tileset": {
                    "prefix": ["ts_", "tile_"],
                    "pattern": "^(ts_|tile_)[a-z0-9_]*$",
                    "description": "Tilesets should start with ts_ or tile_ prefix"
                },
                "timeline": {
                    "prefix": ["tl_", "timeline_"],
                    "pattern": "^(tl_|timeline_)[a-z0-9_]*$",
                    "description": "Timelines should start with tl_ or timeline_ prefix"
                },
                "sequence": {
                    "prefix": ["seq_", "sequence_"],
                    "pattern": "^(seq_|sequence_)[a-z0-9_]*$",
                    "description": "Sequences should start with seq_ or sequence_ prefix"
                },
                "note": {
                    "prefix": "",
                    "pattern": "^[a-zA-Z0-9_\\- ]+$",
                    "description": "Notes can contain letters, numbers, underscores, hyphens, and spaces"
                },
                "folder": {
                    "prefix": "",
                    "pattern": "^[a-zA-Z0-9_/ ]+$",
                    "description": "Folders can contain letters, numbers, underscores, slashes, and spaces"
                }
            }
        },
        "linting": {
            "block_on_critical_errors": True,
            "require_inherited_event": True
        }
    }


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence.
    
    Args:
        base: The base dictionary (defaults)
        override: The dictionary with overrides (user config)
        
    Returns:
        A new dictionary with merged values
    """
    result = deepcopy(base)
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    
    return result


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON file, returning None if it doesn't exist or is invalid."""
    if not path.exists():
        return None
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Handle trailing commas (GameMaker style)
        import re
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        
        return json.loads(content)
    except (json.JSONDecodeError, IOError, OSError) as e:
        # Log warning but don't crash - fall back to defaults
        print(f"[WARN] Could not load config from {path}: {e}")
        return None


class NamingConfig:
    """Configuration manager for naming conventions and linting rules.
    
    This class handles loading, merging, and accessing configuration for
    asset naming conventions. It supports per-project configuration with
    fallback to global and factory defaults.
    
    Usage:
        config = NamingConfig(project_root="/path/to/project")
        rule = config.get_rule("object")
        if rule:
            prefix = rule.get("prefix", "")
            pattern = rule.get("pattern")
    """
    
    # Class-level cache: project_root_str -> NamingConfig instance
    _cache: Dict[str, "NamingConfig"] = {}
    
    def __init__(self, project_root: Optional[Union[str, Path]] = None):
        """Initialize the config manager.
        
        Args:
            project_root: Path to the GameMaker project root (directory with .yyp).
                         If None, uses current working directory.
        """
        if project_root is None:
            project_root = Path.cwd()
        elif isinstance(project_root, str):
            project_root = Path(project_root)
        
        self.project_root = project_root.resolve()
        self._config: Dict[str, Any] = {}
        self._loaded = False
        self._load()
    
    def _load(self) -> None:
        """Load configuration from all sources and merge."""
        # Start with factory defaults
        config = _get_factory_defaults()
        
        # Try to load global config
        global_config_path = Path.home() / GLOBAL_CONFIG_DIR / GLOBAL_CONFIG_FILE
        global_config = _load_json_file(global_config_path)
        if global_config:
            config = _deep_merge(config, global_config)
        
        # Try to load project config (takes precedence)
        project_config_path = self.project_root / PROJECT_CONFIG_FILE
        project_config = _load_json_file(project_config_path)
        if project_config:
            config = _deep_merge(config, project_config)
        
        self._config = config
        self._loaded = True
    
    def reload(self) -> None:
        """Force reload of configuration from disk."""
        self._load()
    
    @property
    def naming_enabled(self) -> bool:
        """Check if naming validation is enabled."""
        return self._config.get("naming", {}).get("enabled", True)
    
    def get_rule(self, asset_type: str) -> Optional[Dict[str, Any]]:
        """Get the naming rule for a specific asset type.
        
        Args:
            asset_type: The type of asset (e.g., 'object', 'sprite', 'script')
            
        Returns:
            The rule dictionary, or None if no rule exists for this type.
            Rule dictionary may contain:
            - prefix: str or List[str] - Required prefix(es)
            - pattern: str - Regex pattern for validation
            - allow_pascal_constructors: bool - For scripts only
            - description: str - Human-readable description
        """
        rules = self._config.get("naming", {}).get("rules", {})
        return rules.get(asset_type)
    
    def get_prefixes(self, asset_type: str) -> List[str]:
        """Get the valid prefixes for an asset type as a list.
        
        Args:
            asset_type: The type of asset
            
        Returns:
            List of valid prefixes (may be empty)
        """
        rule = self.get_rule(asset_type)
        if not rule:
            return []
        
        prefix = rule.get("prefix", "")
        if isinstance(prefix, list):
            return prefix
        elif prefix:
            return [prefix]
        return []
    
    def get_pattern(self, asset_type: str) -> Optional[str]:
        """Get the regex pattern for an asset type.
        
        Args:
            asset_type: The type of asset
            
        Returns:
            The regex pattern string, or None
        """
        rule = self.get_rule(asset_type)
        if rule:
            return rule.get("pattern")
        return None
    
    def allows_pascal_constructors(self, asset_type: str) -> bool:
        """Check if PascalCase constructor names are allowed.
        
        Args:
            asset_type: The type of asset (only relevant for 'script')
            
        Returns:
            True if PascalCase constructors are allowed
        """
        rule = self.get_rule(asset_type)
        if rule:
            return rule.get("allow_pascal_constructors", False)
        return False
    
    def get_linting_option(self, option: str, default: Any = None) -> Any:
        """Get a linting configuration option.
        
        Args:
            option: The option name (e.g., 'block_on_critical_errors')
            default: Default value if option is not set
            
        Returns:
            The option value
        """
        return self._config.get("linting", {}).get(option, default)
    
    @property
    def raw_config(self) -> Dict[str, Any]:
        """Get the raw merged configuration dictionary."""
        return deepcopy(self._config)
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize the current config to JSON string."""
        return json.dumps(self._config, indent=indent, ensure_ascii=False)
    
    @classmethod
    def get_cached(cls, project_root: Optional[Union[str, Path]] = None) -> "NamingConfig":
        """Get a cached config instance for the given project root.
        
        This avoids reloading config files on every validation call.
        
        Args:
            project_root: Path to project root, or None for cwd
            
        Returns:
            Cached NamingConfig instance
        """
        if project_root is None:
            project_root = Path.cwd()
        elif isinstance(project_root, str):
            project_root = Path(project_root)
        
        key = str(project_root.resolve())
        
        if key not in cls._cache:
            cls._cache[key] = cls(project_root)
        
        return cls._cache[key]
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear the config cache. Useful for testing."""
        cls._cache.clear()
    
    @classmethod
    def invalidate(cls, project_root: Optional[Union[str, Path]] = None) -> None:
        """Invalidate cached config for a specific project.
        
        Args:
            project_root: Path to project root to invalidate
        """
        if project_root is None:
            project_root = Path.cwd()
        elif isinstance(project_root, str):
            project_root = Path(project_root)
        
        key = str(project_root.resolve())
        cls._cache.pop(key, None)


# Module-level convenience functions

def get_config(project_root: Optional[Union[str, Path]] = None) -> NamingConfig:
    """Get the naming config for a project (cached).
    
    This is the primary entry point for accessing configuration.
    
    Args:
        project_root: Path to project root, or None for cwd
        
    Returns:
        NamingConfig instance
    """
    return NamingConfig.get_cached(project_root)


def get_factory_defaults() -> Dict[str, Any]:
    """Get a copy of the factory default configuration."""
    return _get_factory_defaults()


def create_default_config_file(
    project_root: Union[str, Path],
    overwrite: bool = False
) -> Path:
    """Create a default .gms-mcp.json config file in the project root.
    
    Args:
        project_root: Path to the project root directory
        overwrite: If True, overwrite existing config file
        
    Returns:
        Path to the created config file
        
    Raises:
        FileExistsError: If config file exists and overwrite is False
    """
    if isinstance(project_root, str):
        project_root = Path(project_root)
    
    config_path = project_root / PROJECT_CONFIG_FILE
    
    if config_path.exists() and not overwrite:
        raise FileExistsError(f"Config file already exists: {config_path}")
    
    defaults = _get_factory_defaults()
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(defaults, f, indent=2, ensure_ascii=False)
        f.write('\n')
    
    # Invalidate cache for this project
    NamingConfig.invalidate(project_root)
    
    return config_path


def validate_config(config_data: Dict[str, Any]) -> List[str]:
    """Validate a configuration dictionary.
    
    Args:
        config_data: The configuration to validate
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    # Check schema version
    schema = config_data.get("$schema", "")
    if schema and not schema.startswith("gms-mcp-config-"):
        errors.append(f"Unknown schema version: {schema}")
    
    # Check naming section
    naming = config_data.get("naming", {})
    if not isinstance(naming, dict):
        errors.append("'naming' must be a dictionary")
    else:
        rules = naming.get("rules", {})
        if not isinstance(rules, dict):
            errors.append("'naming.rules' must be a dictionary")
        else:
            for asset_type, rule in rules.items():
                if not isinstance(rule, dict):
                    errors.append(f"Rule for '{asset_type}' must be a dictionary")
                    continue
                
                # Validate pattern is valid regex
                pattern = rule.get("pattern")
                if pattern:
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        errors.append(f"Invalid regex pattern for '{asset_type}': {e}")
                
                # Validate prefix type
                prefix = rule.get("prefix")
                if prefix is not None:
                    if not isinstance(prefix, (str, list)):
                        errors.append(f"Prefix for '{asset_type}' must be string or list")
                    elif isinstance(prefix, list):
                        for p in prefix:
                            if not isinstance(p, str):
                                errors.append(f"Prefix list for '{asset_type}' must contain only strings")
                                break
    
    # Check linting section
    linting = config_data.get("linting", {})
    if not isinstance(linting, dict):
        errors.append("'linting' must be a dictionary")
    
    return errors
