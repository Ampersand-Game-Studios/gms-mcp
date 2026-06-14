from __future__ import annotations

import json
from pathlib import Path

try:
    from gms_helpers.naming_config import (
        PROJECT_CONFIG_FILE,
        create_default_config_file,
        get_factory_defaults,
    )

    HAS_NAMING_CONFIG = True
except ImportError:  # pragma: no cover
    HAS_NAMING_CONFIG = False
    PROJECT_CONFIG_FILE = ".gms-mcp.json"

    def get_factory_defaults():
        """Fallback factory defaults if gms_helpers not available."""
        return {
            "$schema": "gms-mcp-config-v1",
            "naming": {
                "enabled": True,
                "rules": {
                    "object": {"prefix": "o_", "pattern": "^o_[a-z0-9_]*$"},
                    "sprite": {"prefix": "spr_", "pattern": "^spr_[a-z0-9_]*$"},
                    "script": {"prefix": "", "pattern": "^[a-z][a-z0-9_]*$", "allow_pascal_constructors": True},
                    "room": {"prefix": "r_", "pattern": "^r_[a-z0-9_]*$"},
                },
            },
            "linting": {"block_on_critical_errors": True},
        }

    def create_default_config_file(project_root: Path, overwrite: bool = False) -> Path:
        """Fallback config file creator."""
        config_path = project_root / PROJECT_CONFIG_FILE
        if config_path.exists() and not overwrite:
            raise FileExistsError(f"Config file already exists: {config_path}")
        defaults = get_factory_defaults()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(defaults, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return config_path
