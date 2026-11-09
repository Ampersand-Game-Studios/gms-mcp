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
      "live_reload": {"status_file": ".gms-fire/status.json"}
    }

Resolution order for one setting: environment variable (when the setting has one),
project file, ``~/.gms-mcp/config.json``, built-in default. Live-reload executable
commands are an exception: they are read only from the user configuration.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .exceptions import ValidationError
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


# Settings whose default is None, with the types a configured value may have.
_NULLABLE_TYPES: dict[str, tuple[type, ...]] = {
    "verification.post_mutation": (bool, str),
    "build.runtime_version": (str,),
    "test.prelude_file": (str,),
    "live_reload.status_file": (str,),
}
# live_reload.start/stop/status are commands that live_reload validates itself (user config only).
# Numeric settings that may be fractional; every other numeric default is a positive integer.
_FRACTIONAL_SETTINGS = {"test.timeout_seconds"}


def _type_name(value: Any) -> str:
    return "null" if value is None else type(value).__name__


def _checked_value(source: Path, key: str, default: Any, value: Any) -> Any:
    """Return ``value`` coerced to the type of ``default``; raise a ValidationError naming the setting."""

    def invalid(expected: str) -> ValidationError:
        return ValidationError(
            f"{key} in {source} must be {expected}, not {value!r} ({_type_name(value)}). "
            "Fix or remove the setting; see documentation/CONFIGURATION.md.",
            details={"setting": key, "file": str(source), "value": value},
        )

    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise invalid("an object")
        return {
            child: _checked_value(source, f"{key}.{child}", default[child], child_value)
            if child in default
            else child_value
            for child, child_value in value.items()
        }
    if value is None:
        return None
    if default is None:
        allowed = _NULLABLE_TYPES.get(key)
        if allowed is not None and not isinstance(value, allowed):
            raise invalid(" or ".join(t.__name__ for t in allowed) + " or null")
        return value
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise invalid("true or false")
        return value
    if isinstance(default, (int, float)):
        fractional = key in _FRACTIONAL_SETTINGS
        expected = "a positive number" if fractional else "a positive whole number"
        number: Any = value
        if isinstance(value, str):
            try:
                number = float(value.strip()) if fractional else int(value.strip())
            except ValueError:
                raise invalid(expected) from None
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise invalid(expected)
        if not fractional:
            if isinstance(number, float) and not number.is_integer():
                raise invalid(expected)
            number = int(number)
        if number <= 0:
            raise invalid(expected)
        return number
    if isinstance(default, str):
        if not isinstance(value, str):
            raise invalid("a string")
        return value
    if isinstance(default, list):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise invalid("a list of strings")
        return value
    return value


def _checked_config(source: Path, data: Any) -> dict[str, Any] | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValidationError(f"{source} must contain a JSON object, not {_type_name(data)}.")
    return {
        key: _checked_value(source, key, DEFAULTS[key], value) if key in DEFAULTS else value
        for key, value in data.items()
    }


def load_project_config(project_root: str | Path) -> dict[str, Any]:
    """Return defaults merged with the global and project configuration files.

    Values for the settings in ``DEFAULTS`` are checked against the default's type (numeric
    strings such as ``"30"`` are accepted for numbers); a wrong type raises ``ValidationError``
    naming the setting and the file instead of failing later inside a tool.
    """
    config = _deep_merge({}, DEFAULTS)
    for source in (Path.home() / GLOBAL_CONFIG_DIR / GLOBAL_CONFIG_FILE, Path(project_root) / PROJECT_CONFIG_FILE):
        checked = _checked_config(source, _load_json_file(source))
        if checked is not None:
            config = _deep_merge(config, checked)
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


def global_setting(dotted_key: str, default: Any = None) -> Any:
    """Read only the user-owned configuration, without project or environment overrides."""
    source = Path.home() / GLOBAL_CONFIG_DIR / GLOBAL_CONFIG_FILE
    value: Any = _checked_config(source, _load_json_file(source))
    for part in dotted_key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return default if value is None else value


def project_live_reload_command_warnings(project_root: str | Path) -> list[str]:
    """Explain ignored executable commands supplied by an untrusted project."""
    config = _load_json_file(Path(project_root) / PROJECT_CONFIG_FILE)
    live_reload = config.get("live_reload", {}) if isinstance(config, dict) else {}
    ignored = [key for key in ("start", "stop", "status") if isinstance(live_reload, dict) and key in live_reload]
    if not ignored:
        return []
    return [
        "Ignored project live_reload commands (" + ", ".join(ignored) + ") in .gms-mcp.json. "
        "Move trusted commands to the user config ~/.gms-mcp/config.json under live_reload."
    ]
