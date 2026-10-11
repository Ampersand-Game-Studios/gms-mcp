"""Per-project settings read from ``.gms-mcp.json`` (next to the ``.yyp``).

``naming_config`` owns the ``naming`` and ``linting`` sections. Everything else a project
wants to tell the tools about itself lives here, so conventions belong to the project and
are never hard-coded in gms-mcp:

    {
      "verification": {"post_mutation": "off"},
      "build":   {"igor_attempts": 30, "max_parallel_builds": 4, "jobs": 4},
      "test":    {"timeout_seconds": 120, "prelude_file": "tools/test_prelude.gml"},
      "conventions": {
        "default_parents": {"script": "folders/Scripts.yy"},
        "allow_root_assets": ["__agent_*"]
      },
      "bridge":  {"port": 6502},
      "live_reload": {"start": ["gms-fire", "start"], "stop": ["gms-fire", "stop"],
                      "status": ["gms-fire", "status", "--json"]}
    }

Resolution order for one setting: environment variable (when the setting has one),
project file, ``~/.gms-mcp/config.json``, built-in default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .naming_config import GLOBAL_CONFIG_DIR, GLOBAL_CONFIG_FILE, PROJECT_CONFIG_FILE, _deep_merge, _load_json_file

DEFAULTS: dict[str, Any] = {
    "verification": {
        # None keeps the server default ("smart": compile after structural edits).
        "post_mutation": None,
    },
    "build": {
        # Igor's project loader in runtime 2026.0.0.23 aborts at random with
        # System.AccessViolationException; each abort is retried up to this many times.
        "igor_attempts": 10,
        "max_parallel_builds": 4,
        "jobs": 4,
        "runtime_version": None,
    },
    "test": {
        "script_name": "__agent_test",
        "timeout_seconds": 120,
        "result_marker": "[TEST_RESULT]",
        "line_marker": "[TEST]",
        "started_marker": "[TEST_SAVE_DIR]",
        "screenshot_prefix": "__agent_shot_",
        # Optional project-relative GML file replacing the built-in test prelude.
        "prelude_file": None,
        "runtime_error_patterns": [
            "ERROR in action number",
            "ERROR in",
            "FATAL ERROR",
            "############################################################################################",
        ],
    },
    "conventions": {
        "default_parents": {},
        "allow_root_assets": [],
    },
    "bridge": {"port": 6502},
    "live_reload": {"start": None, "stop": None, "status": None, "status_file": None},
}

# Settings an operator may force for one server process without editing the project.
_ENVIRONMENT_OVERRIDES: dict[str, tuple[str, type]] = {
    "build.igor_attempts": ("GMS_MCP_SNAPSHOT_IGOR_ATTEMPTS", int),
    "build.max_parallel_builds": ("GMS_MCP_MAX_PARALLEL_BUILDS", int),
    "build.jobs": ("GMS_MCP_IGOR_JOBS", int),
    "bridge.port": ("GMS_MCP_BRIDGE_PORT", int),
}


def load_project_config(project_root: str | Path) -> dict[str, Any]:
    """Return defaults merged with the global and project configuration files."""
    config = _deep_merge({}, DEFAULTS)
    global_config = _load_json_file(Path.home() / GLOBAL_CONFIG_DIR / GLOBAL_CONFIG_FILE)
    if isinstance(global_config, dict):
        config = _deep_merge(config, global_config)
    project_config = _load_json_file(Path(project_root) / PROJECT_CONFIG_FILE)
    if isinstance(project_config, dict):
        config = _deep_merge(config, project_config)
    return config


def project_setting(project_root: str | Path, dotted_key: str, default: Any = None) -> Any:
    """Read one setting such as ``"build.igor_attempts"``."""
    override = _ENVIRONMENT_OVERRIDES.get(dotted_key)
    if override is not None:
        raw = os.environ.get(override[0], "").strip()
        if raw:
            try:
                return override[1](raw)
            except ValueError:
                pass
    value: Any = load_project_config(project_root)
    for part in dotted_key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return default if value is None else value


def configured_post_mutation_verification(project_root: str | Path) -> str | None:
    """Project-level default for compile-after-mutation (``off``, ``smart`` or ``always``)."""
    value = project_setting(project_root, "verification.post_mutation")
    if isinstance(value, bool):
        return "always" if value else "off"
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None
