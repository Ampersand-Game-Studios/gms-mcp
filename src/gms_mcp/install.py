#!/usr/bin/env python3
"""
Generate MCP client configuration files for the GameMaker MCP server.

Multi-project model:
- Install the tool once (recommended: `pipx install gms-mcp`)
- Run this per-project/workspace to generate that workspace's MCP config (Cursor primary)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import sys
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .client_registry import (
    CLIENT_ACTIONS,
    CLIENT_SCOPES,
    all_client_names,
    resolve_client_spec,
)

try:
    import tomllib as _toml_parser  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as _toml_parser  # Python 3.10 fallback
    except ModuleNotFoundError:
        _toml_parser = None

# Import naming config for project setup
try:
    from gms_helpers.naming_config import (
        get_factory_defaults,
        create_default_config_file,
        PROJECT_CONFIG_FILE,
    )
    _HAS_NAMING_CONFIG = True
except ImportError:
    _HAS_NAMING_CONFIG = False
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
                }
            },
            "linting": {
                "block_on_critical_errors": True
            }
        }
    
    def create_default_config_file(project_root: Path, overwrite: bool = False) -> Path:
        """Fallback config file creator."""
        config_path = project_root / PROJECT_CONFIG_FILE
        if config_path.exists() and not overwrite:
            raise FileExistsError(f"Config file already exists: {config_path}")
        defaults = get_factory_defaults()
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(defaults, f, indent=2, ensure_ascii=False)
            f.write('\n')
        return config_path


_DEFAULT_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".cursor",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
}

_FORWARDED_ENV_VARS = [
    "GMS_MCP_GMS_PATH",
    "GMS_MCP_DEFAULT_TIMEOUT_SECONDS",
    "GMS_MCP_ENABLE_DIRECT",
]
_SAFE_PROFILE_TIMEOUT_SECONDS = 600


def _as_posix_path(path: Path) -> str:
    return path.as_posix()


def _find_yyp_dirs(workspace_root: Path, max_results: int = 5) -> list[Path]:
    results: list[Path] = []
    ignored = {d.lower() for d in _DEFAULT_IGNORED_DIRS}

    for root, dirs, files in os.walk(workspace_root):
        dirs[:] = [d for d in dirs if d.lower() not in ignored]
        if any(f.lower().endswith(".yyp") for f in files):
            results.append(Path(root))
            if len(results) >= max_results:
                break

    return results


def _detect_gm_project_roots(workspace_root: Path, max_results: int = 50) -> list[Path]:
    candidates: list[Path] = []

    if sorted(workspace_root.glob("*.yyp")):
        candidates.append(workspace_root)

    gm = workspace_root / "gamemaker"
    if gm.exists() and gm.is_dir() and sorted(gm.glob("*.yyp")):
        candidates.append(gm)

    candidates.extend(_find_yyp_dirs(workspace_root, max_results=max_results))

    # Unique + stable order (by relative path)
    uniq: dict[str, Path] = {}
    for p in candidates:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)
        uniq[key] = p

    def _sort_key(p: Path) -> str:
        try:
            return _as_posix_path(p.relative_to(workspace_root))
        except Exception:
            return _as_posix_path(p)

    return sorted(uniq.values(), key=_sort_key)


def _select_gm_project_root(
    *,
    workspace_root: Path,
    requested_root: str | None,
    non_interactive: bool,
) -> tuple[Path | None, list[Path]]:
    """
    Returns (selected_root, all_candidates).
    """
    if requested_root:
        p = Path(requested_root).expanduser()
        if not p.is_absolute():
            p = (workspace_root / p).resolve()
        if p.is_file():
            p = p.parent
        return p, []

    candidates = _detect_gm_project_roots(workspace_root)
    if len(candidates) == 0:
        return None, candidates
    if len(candidates) == 1:
        return candidates[0], candidates

    # Multiple projects found: prompt if interactive, otherwise fall back safely.
    if non_interactive or not (sys.stdin and sys.stdin.isatty()):
        return None, candidates

    print("[WARN] Multiple GameMaker projects (.yyp) detected in this workspace:")
    for i, p in enumerate(candidates, start=1):
        try:
            rel = p.relative_to(workspace_root)
            label = f"./{_as_posix_path(rel)}"
        except Exception:
            label = str(p)
        print(f"  {i}. {label}")
    print("Select which project root to target, or press Enter to skip (defaults to ${workspaceFolder}).")

    while True:
        choice = input("Project number (1..N) or Enter: ").strip()
        if choice == "":
            return None, candidates
        try:
            idx = int(choice)
        except ValueError:
            print("[ERROR] Enter a number or press Enter.")
            continue
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1], candidates
        print("[ERROR] Out of range.")


def _workspace_folder_var(client: str) -> str:
    """Return the workspace/project directory variable for a given client."""
    if client in ("claude-code", "claude-code-global"):
        return "${CLAUDE_PROJECT_DIR}"
    return "${workspaceFolder}"


def _write_json(path: Path, data: dict, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _relpath_posix_or_none(target: Path | None, base: Path) -> str | None:
    if target is None:
        return None
    try:
        rel = target.relative_to(base)
    except ValueError:
        return None
    return _as_posix_path(rel)


def _make_server_config(
    *,
    client: str,
    server_name: str,
    command: str,
    args: list[str],
    gm_project_root_rel_posix: str | None,
    safe_profile: bool = False,
) -> dict:
    workspace_var = _workspace_folder_var(client)
    env: dict[str, str] = {}

    if gm_project_root_rel_posix:
        env["GM_PROJECT_ROOT"] = f"{workspace_var}/{gm_project_root_rel_posix}".replace("//", "/")
    else:
        env["GM_PROJECT_ROOT"] = workspace_var

    # Polish: Auto-detect and write relevant environment variables from current process
    # This helps when running gms-mcp-init from a shell where these are already set.
    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_safe_profile_env(env, enabled=safe_profile)

    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": args,
                "cwd": workspace_var,
                "env": env,
            }
        }
    }


def _default_antigravity_config_path() -> Path:
    return Path.home() / ".gemini" / "antigravity" / "mcp_config.json"


def _resolve_antigravity_config_path(config_path: str | None) -> Path:
    if not config_path:
        return _default_antigravity_config_path()
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _apply_safe_profile_env(env: dict[str, str], *, enabled: bool) -> None:
    if not enabled:
        return
    env["GMS_MCP_ENABLE_DIRECT"] = "0"
    env["GMS_MCP_REQUIRE_DRY_RUN"] = "1"
    timeout = env.get("GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "").strip()
    if timeout:
        try:
            parsed_timeout = int(timeout)
            if parsed_timeout <= 0 or parsed_timeout > _SAFE_PROFILE_TIMEOUT_SECONDS:
                env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = str(_SAFE_PROFILE_TIMEOUT_SECONDS)
        except ValueError:
            env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = str(_SAFE_PROFILE_TIMEOUT_SECONDS)
    else:
        env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = str(_SAFE_PROFILE_TIMEOUT_SECONDS)


@dataclass
class ReadinessResult:
    ready: bool
    problems: list[str]
    not_applicable: bool = False


@dataclass
class ConfigState:
    client: str
    scope: str
    server_name: str
    path: str
    exists: bool
    entry: dict | None
    readiness: ReadinessResult

    def as_dict(self) -> dict:
        return {
            "ok": True,
            "client": self.client,
            "scope": self.scope,
            "server_name": self.server_name,
            "config": {
                "path": self.path,
                "exists": self.exists,
                "entry": self.entry,
            },
            "active": {
                "scope": self.scope,
                "path": self.path,
                "entry": self.entry,
            },
            "ready": self.readiness.ready,
            "problems": self.readiness.problems,
            "not_applicable": self.readiness.not_applicable,
        }


def _validate_common_entry(
    entry: object,
    *,
    require_project_root: bool = True,
    env_required: bool = True,
) -> ReadinessResult:
    if not isinstance(entry, dict):
        return ReadinessResult(ready=False, problems=["Active server entry is missing or not an object."])

    problems: list[str] = []

    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        problems.append("`command` must be a non-empty string.")

    args = entry.get("args")
    if not isinstance(args, list):
        problems.append("`args` must be a list.")

    env = entry.get("env")
    if env_required and not isinstance(env, dict):
        problems.append("`env` must be an object.")
    elif isinstance(env, dict):
        if require_project_root:
            gm_project_root = env.get("GM_PROJECT_ROOT")
            if not isinstance(gm_project_root, str) or not gm_project_root.strip():
                problems.append("`env.GM_PROJECT_ROOT` must be a non-empty string.")
        if env.get("PYTHONUNBUFFERED") != "1":
            problems.append("`env.PYTHONUNBUFFERED` should be \"1\" for unbuffered logs.")

    return ReadinessResult(ready=len(problems) == 0, problems=problems)


def _resolve_json_entry_root(parsed: dict, *, server_name: str, allow_plain_top_level: bool) -> dict | None:
    mcp_servers = parsed.get("mcpServers")
    if isinstance(mcp_servers, dict):
        entry = mcp_servers.get(server_name)
        return entry if isinstance(entry, dict) else None

    if allow_plain_top_level:
        plain_entry = parsed.get(server_name)
        if isinstance(plain_entry, dict):
            return plain_entry

    return None


def _read_json_server_entry(
    *,
    config_path: Path,
    server_name: str,
    allow_plain_top_level: bool,
) -> tuple[dict | None, bool]:
    if not config_path.exists():
        return None, False

    text = config_path.read_text(encoding="utf-8")
    parsed = _parse_json_object_or_raise(text=text, source_label=str(config_path))
    entry = _resolve_json_entry_root(parsed, server_name=server_name, allow_plain_top_level=allow_plain_top_level)
    return entry, True


def _collect_standard_check_state(
    *,
    client: str,
    scope: str,
    config_path: Path,
    server_name: str,
    allow_plain_top_level: bool = False,
    require_project_root: bool = True,
    env_required: bool = True,
    not_applicable_reason: str | None = None,
) -> ConfigState:
    if not_applicable_reason is not None:
        readiness = ReadinessResult(ready=False, problems=[not_applicable_reason], not_applicable=True)
        return ConfigState(
            client=client,
            scope=scope,
            server_name=server_name,
            path=str(config_path),
            exists=False,
            entry=None,
            readiness=readiness,
        )

    entry, exists = _read_json_server_entry(
        config_path=config_path,
        server_name=server_name,
        allow_plain_top_level=allow_plain_top_level,
    )
    readiness = _validate_common_entry(
        entry,
        require_project_root=require_project_root,
        env_required=env_required,
    )
    return ConfigState(
        client=client,
        scope=scope,
        server_name=server_name,
        path=str(config_path),
        exists=exists,
        entry=entry,
        readiness=readiness,
    )


def _print_standard_check(state: ConfigState) -> int:
    print(f"[INFO] {state.client} {state.scope} config: {state.path} ({'exists' if state.exists else 'missing'})")
    if state.entry is None:
        print(f"[INFO] Active server entry '{state.server_name}': not found")
    else:
        print(f"[INFO] Active server entry '{state.server_name}' source: {state.path}")
        print("[INFO] Active server entry payload:")
        print(json.dumps(state.entry, indent=2, sort_keys=True))
    print(f"[INFO] Ready for {state.client}: {'yes' if state.readiness.ready else 'no'}")
    for problem in state.readiness.problems:
        level = "WARN" if not state.readiness.not_applicable else "INFO"
        print(f"[{level}] {problem}")
    return 0


def _print_standard_check_json(state: ConfigState) -> int:
    print(json.dumps(state.as_dict(), indent=2, sort_keys=True))
    return 0


def _print_standard_app_setup_summary(state: ConfigState) -> int:
    print(f"[INFO] {state.client} app readiness summary:")
    print(f"[INFO] Scope: {state.scope}")
    print(f"[INFO] Config path: {state.path}")
    print(f"[INFO] Ready for {state.client}: {'yes' if state.readiness.ready else 'no'}")
    for problem in state.readiness.problems:
        level = "WARN" if not state.readiness.not_applicable else "INFO"
        print(f"[{level}] {problem}")
    return 0


def _make_antigravity_server_config(
    *,
    server_name: str,
    command: str,
    args: list[str],
    workspace_root: Path,
    gm_project_root: Path | None,
    safe_profile: bool,
) -> dict:
    env: dict[str, str] = {
        "GM_PROJECT_ROOT": str(gm_project_root if gm_project_root is not None else workspace_root),
        "PYTHONUNBUFFERED": "1",
    }
    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_safe_profile_env(env, enabled=safe_profile)

    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }


def _resolve_launcher(*, mode: str, python_command: str) -> tuple[str, list[str]]:
    """
    Return (command, args_prefix) for launching the server.
    """
    if mode == "command":
        return "gms-mcp", []
    if mode == "python-module":
        resolved_python = _resolve_python_command(python_command)
        return resolved_python, ["-m", "gms_mcp.bootstrap_server"]
    raise ValueError(f"Unknown mode: {mode}")


def _default_python_command() -> str:
    """
    Return a practical Python command default per host OS.

    On Unix-like systems `python3` is often available while `python` may not be.
    """
    if os.name == "nt":
        return "python"
    if shutil.which("python3"):
        return "python3"
    return "python"


def _resolve_python_command(python_command: str) -> str:
    """
    Resolve a usable Python command for --mode=python-module.

    Keeps caller-provided values when available and falls back to common
    interpreter commands if needed.
    """
    requested = (python_command or "").strip() or _default_python_command()
    if shutil.which(requested):
        return requested

    fallback_candidates: list[str] = []
    if sys.executable:
        fallback_candidates.append(sys.executable)
    fallback_candidates.extend(["python3", "python"])

    for candidate in fallback_candidates:
        if candidate and shutil.which(candidate):
            return candidate

    return requested


def _generate_cursor_config(
    *,
    workspace_root: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    gm_project_root: Path | None,
    out_path: Path,
    dry_run: bool,
    safe_profile: bool = False,
) -> Path:
    gm_rel_posix = _relpath_posix_or_none(gm_project_root, workspace_root)
    config = _make_server_config(
        client="cursor",
        server_name=server_name,
        command=command,
        args=args_prefix,
        gm_project_root_rel_posix=gm_rel_posix,
        safe_profile=safe_profile,
    )
    _write_json(out_path, config, dry_run=dry_run)
    return out_path


def _generate_example_configs(
    *,
    workspace_root: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    gm_project_root: Path | None,
    clients: Iterable[str],
    dry_run: bool,
    safe_profile: bool = False,
) -> list[Path]:
    gm_rel_posix = _relpath_posix_or_none(gm_project_root, workspace_root)

    out_paths: list[Path] = []
    out_dir = workspace_root / "mcp-configs"
    for client in clients:
        if client == "antigravity":
            config = _make_antigravity_server_config(
                server_name=server_name,
                command=command,
                args=args_prefix,
                workspace_root=workspace_root,
                gm_project_root=gm_project_root,
                safe_profile=safe_profile,
            )
        else:
            config = _make_server_config(
                client=client,
                server_name=server_name,
                command=command,
                args=args_prefix,
                gm_project_root_rel_posix=gm_rel_posix,
                safe_profile=safe_profile,
            )
        out_path = out_dir / f"{client}.mcp.json"
        _write_json(out_path, config, dry_run=dry_run)
        out_paths.append(out_path)
    return out_paths


def _get_package_version() -> str:
    """Get the current package version, with fallback."""
    try:
        from importlib.metadata import version
        return version("gms-mcp")
    except Exception:
        return "0.1.0"


def _make_claude_code_plugin_manifest() -> dict:
    """Create the plugin.json manifest for Claude Code."""
    return {
        "name": "gms-mcp",
        "description": "GameMaker Studio MCP tools for asset management, code intelligence, and project maintenance",
        "version": _get_package_version(),
        "author": {
            "name": "Ampersand Game Studios",
            "url": "https://github.com/Ampersand-Game-Studios/gms-mcp"
        },
        "repository": "https://github.com/Ampersand-Game-Studios/gms-mcp",
        "license": "MIT",
        "keywords": ["gamemaker", "game-development", "mcp", "assets", "code-intelligence"]
    }


def _make_claude_code_mcp_config(
    *,
    server_name: str,
    command: str,
    args: list[str],
    safe_profile: bool = False,
) -> dict:
    """
    Create the .mcp.json config for Claude Code.

    Uses ${CLAUDE_PROJECT_DIR} which dynamically resolves to whichever
    project Claude Code is currently open in.
    """
    env: dict[str, str] = {
        "GM_PROJECT_ROOT": "${CLAUDE_PROJECT_DIR}",
        "PYTHONUNBUFFERED": "1",  # Ensure Python output is not buffered
    }

    # Include relevant environment variables from current process
    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_safe_profile_env(env, enabled=safe_profile)

    return {
        server_name: {
            "command": command,
            "args": args,
            "env": env,
        }
    }


def _build_codex_env(
    gm_project_root: Optional[Path],
    workspace_root: Path,
    *,
    include_project_root: bool = True,
    safe_profile: bool = False,
) -> dict[str, str]:
    env: dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
    }

    if include_project_root:
        resolved_root = str(
            gm_project_root if gm_project_root is not None else workspace_root
        )
        env["GM_PROJECT_ROOT"] = resolved_root

    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_safe_profile_env(env, enabled=safe_profile)

    return env


def _build_codex_env_args(env: dict[str, str]) -> str:
    if not env:
        return ""
    return " " + " ".join(
        f"--env {shlex.quote(f'{key}={value}')}" for key, value in env.items()
    )


def _parse_toml_or_raise(*, text: str, source_label: str) -> dict:
    """Parse TOML text and return a dictionary; raise a descriptive error on failure."""
    if _toml_parser is None:
        raise RuntimeError(
            "TOML parser unavailable. Install Python 3.11+ or add dependency 'tomli' for Python 3.10."
        )
    try:
        parsed = _toml_parser.loads(text)
    except Exception as exc:
        raise ValueError(f"Malformed TOML in {source_label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Malformed TOML in {source_label}: root must be a table/object.")
    return parsed


def _validate_codex_sections(
    *,
    parsed: dict,
    source_label: str,
    server_name: str,
) -> None:
    """Validate only the Codex MCP sections we need for safe merges/checks."""
    mcp_servers = parsed.get("mcp_servers")
    if mcp_servers is None:
        return
    if not isinstance(mcp_servers, dict):
        raise ValueError(f"Malformed TOML in {source_label}: [mcp_servers] must be a table.")

    target_entry = mcp_servers.get(server_name)
    if target_entry is None:
        return
    if not isinstance(target_entry, dict):
        raise ValueError(f"Malformed TOML in {source_label}: [mcp_servers.{server_name}] must be a table.")

    env = target_entry.get("env")
    if env is not None and not isinstance(env, dict):
        raise ValueError(
            f"Malformed TOML in {source_label}: [mcp_servers.{server_name}.env] must be a table."
        )


def _render_codex_merged_config(
    *,
    output_path: Path,
    server_name: str,
    server_block: str,
) -> str:
    """
    Return the final merged Codex TOML payload without writing to disk.
    Validates existing TOML and section types before merging.
    """
    if not output_path.exists():
        return server_block + "\n" if not server_block.endswith("\n") else server_block

    existing_text = output_path.read_text(encoding="utf-8")
    parsed = _parse_toml_or_raise(text=existing_text, source_label=str(output_path))
    _validate_codex_sections(parsed=parsed, source_label=str(output_path), server_name=server_name)
    return _upsert_codex_server_config(
        existing_text=existing_text,
        server_name=server_name,
        server_block=server_block,
    )


def _upsert_codex_server_config(
    existing_text: str,
    *,
    server_name: str,
    server_block: str,
) -> str:
    """Return TOML text with the target server block inserted or replaced."""
    server_header = f"[mcp_servers.{server_name}]"
    block_lines = server_block.splitlines()

    if not existing_text.strip():
        return "\n".join(block_lines) + "\n"

    lines = existing_text.splitlines()
    start: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == server_header:
            start = idx
            break

    if start is None:
        if lines and lines[-1].strip() != "":
            return "\n".join(lines + ["", *block_lines]) + "\n"
        return "\n".join(lines + block_lines) + "\n"

    section_prefix = f"[mcp_servers.{server_name}."
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        candidate = lines[idx].strip()
        if (
            candidate.startswith("[")
            and candidate.endswith("]")
            and candidate.startswith("[mcp_servers.")
            and not candidate.startswith(section_prefix)
        ):
            end = idx
            break

    merged = lines[:start] + block_lines + lines[end:]
    return "\n".join(merged) + "\n"


def _make_codex_toml_value(value: object) -> str:
    """Serialize a Python value for inclusion in Codex TOML config."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_make_codex_toml_value(v) for v in value) + "]"
    return json.dumps(value)


def _make_codex_mcp_config(
    *,
    server_name: str,
    command: str,
    args: list[str],
    gm_project_root: Optional[Path],
    workspace_root: Path,
    include_project_root: bool = True,
    safe_profile: bool = False,
) -> str:
    """Create a Codex MCP config block in TOML format."""
    env: dict[str, str] = _build_codex_env(
        gm_project_root=gm_project_root,
        workspace_root=workspace_root,
        include_project_root=include_project_root,
        safe_profile=safe_profile,
    )

    lines = [
        "[mcp_servers.{}]".format(server_name),
        f"command = {_make_codex_toml_value(command)}",
        f"args = {_make_codex_toml_value(args)}",
        "",
        f"[mcp_servers.{server_name}.env]",
    ]

    for key, value in env.items():
        lines.append(f"{key} = {_make_codex_toml_value(value)}")

    return "\n".join(lines)


def _generate_codex_config(
    *,
    workspace_root: Path,
    output_path: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    gm_project_root: Optional[Path],
    dry_run: bool,
    include_project_root: bool = True,
    safe_profile: bool = False,
) -> tuple[Path, str, str]:
    """Generate a Codex config entry for the target server."""
    resolved_root = gm_project_root if gm_project_root is not None else workspace_root
    payload = _make_codex_mcp_config(
        server_name=server_name,
        command=command,
        args=args_prefix,
        gm_project_root=resolved_root,
        workspace_root=workspace_root,
        include_project_root=include_project_root,
        safe_profile=safe_profile,
    )
    merged = _render_codex_merged_config(
        output_path=output_path,
        server_name=server_name,
        server_block=payload,
    )
    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(merged, encoding="utf-8")

    return output_path, payload, merged


def _parse_json_object_or_raise(*, text: str, source_label: str) -> dict:
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise ValueError(f"Malformed JSON in {source_label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Malformed JSON in {source_label}: root must be an object.")
    return parsed


def _validate_antigravity_sections(
    *,
    parsed: dict,
    source_label: str,
    server_name: str,
) -> None:
    mcp_servers = parsed.get("mcpServers")
    if mcp_servers is None:
        return
    if not isinstance(mcp_servers, dict):
        raise ValueError(f"Malformed JSON in {source_label}: `mcpServers` must be an object.")

    target_entry = mcp_servers.get(server_name)
    if target_entry is None:
        return
    if not isinstance(target_entry, dict):
        raise ValueError(f"Malformed JSON in {source_label}: `mcpServers.{server_name}` must be an object.")

    env = target_entry.get("env")
    if env is not None and not isinstance(env, dict):
        raise ValueError(
            f"Malformed JSON in {source_label}: `mcpServers.{server_name}.env` must be an object."
        )


def _render_antigravity_merged_config(
    *,
    output_path: Path,
    server_name: str,
    server_entry: dict,
) -> dict:
    if output_path.exists():
        existing_text = output_path.read_text(encoding="utf-8")
        parsed = _parse_json_object_or_raise(text=existing_text, source_label=str(output_path))
        _validate_antigravity_sections(parsed=parsed, source_label=str(output_path), server_name=server_name)
        merged = dict(parsed)
    else:
        merged = {}

    mcp_servers = merged.get("mcpServers")
    if mcp_servers is None:
        mcp_servers = {}
    if not isinstance(mcp_servers, dict):
        raise ValueError(f"Malformed JSON in {output_path}: `mcpServers` must be an object.")
    mcp_servers = dict(mcp_servers)
    mcp_servers[server_name] = server_entry
    merged["mcpServers"] = mcp_servers
    return merged


def _make_backup_path(output_path: Path) -> Path:
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"{output_path.name}.bak.{timestamp}.{os.getpid()}"
    candidate = output_path.with_name(base_name)
    suffix = 1
    while candidate.exists():
        candidate = output_path.with_name(f"{base_name}.{suffix}")
        suffix += 1
    return candidate


def _write_json_atomic_with_backup(*, output_path: Path, payload: dict) -> Path | None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Path | None = None
    if output_path.exists():
        backup_path = _make_backup_path(output_path)
        shutil.copy2(output_path, backup_path)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(output_path.parent),
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        os.replace(temp_path, output_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return backup_path


def _generate_antigravity_config(
    *,
    workspace_root: Path,
    output_path: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    gm_project_root: Path | None,
    safe_profile: bool,
    dry_run: bool,
) -> tuple[Path, dict, dict, Path | None]:
    payload = _make_antigravity_server_config(
        server_name=server_name,
        command=command,
        args=args_prefix,
        workspace_root=workspace_root,
        gm_project_root=gm_project_root,
        safe_profile=safe_profile,
    )
    server_entry = payload["mcpServers"][server_name]
    merged = _render_antigravity_merged_config(
        output_path=output_path,
        server_name=server_name,
        server_entry=server_entry,
    )

    backup_path: Path | None = None
    if not dry_run:
        backup_path = _write_json_atomic_with_backup(output_path=output_path, payload=merged)

    return output_path, payload, merged, backup_path


def _read_antigravity_server_entry(
    *,
    config_path: Path,
    server_name: str,
) -> tuple[dict | None, str | None]:
    if not config_path.exists():
        return None, None
    text = config_path.read_text(encoding="utf-8")
    parsed = _parse_json_object_or_raise(text=text, source_label=str(config_path))
    _validate_antigravity_sections(parsed=parsed, source_label=str(config_path), server_name=server_name)
    mcp_servers = parsed.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return None, str(config_path)
    entry = mcp_servers.get(server_name)
    if isinstance(entry, dict):
        return entry, str(config_path)
    return None, str(config_path)


def _collect_antigravity_check_state(*, config_path: Path, server_name: str) -> dict:
    entry, _ = _read_antigravity_server_entry(config_path=config_path, server_name=server_name)
    return {
        "server_name": server_name,
        "config": {
            "path": str(config_path),
            "exists": config_path.exists(),
            "entry": entry,
        },
    }


def _antigravity_entry_readiness(entry: object) -> tuple[bool, list[str]]:
    problems: list[str] = []
    if not isinstance(entry, dict):
        return False, ["Active server entry is missing or not an object."]

    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        problems.append("`command` must be a non-empty string.")

    args = entry.get("args")
    if not isinstance(args, list):
        problems.append("`args` must be a list.")

    env = entry.get("env")
    if not isinstance(env, dict):
        problems.append("`env` must be an object.")
    else:
        gm_project_root = env.get("GM_PROJECT_ROOT")
        if not isinstance(gm_project_root, str) or not gm_project_root.strip():
            problems.append("`env.GM_PROJECT_ROOT` must be a non-empty string.")
        if env.get("PYTHONUNBUFFERED") != "1":
            problems.append("`env.PYTHONUNBUFFERED` should be \"1\" for unbuffered logs.")

    return len(problems) == 0, problems


def _print_antigravity_check(*, config_path: Path, server_name: str) -> int:
    try:
        state = _collect_antigravity_check_state(config_path=config_path, server_name=server_name)
    except ValueError as exc:
        print(f"[ERROR] Antigravity config check failed: {exc}")
        return 2

    print(
        f"[INFO] Antigravity config: {state['config']['path']} "
        f"({'exists' if state['config']['exists'] else 'missing'})"
    )
    entry = state["config"]["entry"]
    if entry is None:
        print(f"[INFO] Active server entry '{server_name}': not found")
        return 0

    ready, problems = _antigravity_entry_readiness(entry)
    print(f"[INFO] Active server entry '{server_name}' source: {state['config']['path']}")
    print("[INFO] Active server entry payload:")
    print(json.dumps(entry, indent=2, sort_keys=True))
    print(f"[INFO] Ready for Antigravity: {'yes' if ready else 'no'}")
    for problem in problems:
        print(f"[WARN] {problem}")
    return 0


def _print_antigravity_check_json(*, config_path: Path, server_name: str) -> int:
    """Print Antigravity config discovery + active server entry as machine-readable JSON."""
    try:
        state = _collect_antigravity_check_state(config_path=config_path, server_name=server_name)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2

    ready, problems = _antigravity_entry_readiness(state["config"]["entry"])
    state["ok"] = True
    state["ready"] = ready
    state["problems"] = problems
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def _print_antigravity_app_setup_summary(*, config_path: Path, server_name: str) -> int:
    """Print a compact readiness summary for Antigravity usage."""
    try:
        state = _collect_antigravity_check_state(config_path=config_path, server_name=server_name)
    except ValueError as exc:
        print(f"[ERROR] Antigravity app setup summary failed: {exc}")
        return 2

    ready, problems = _antigravity_entry_readiness(state["config"]["entry"])
    print("[INFO] Antigravity app readiness summary:")
    print(f"[INFO] Config path: {state['config']['path']}")
    print(f"[INFO] Ready for Antigravity: {'yes' if ready else 'no'}")
    for problem in problems:
        print(f"[WARN] {problem}")
    return 0


def _read_codex_server_entry(
    *,
    config_path: Path,
    server_name: str,
) -> tuple[dict | None, str | None]:
    """Read and validate a Codex config, returning the server entry if present."""
    if not config_path.exists():
        return None, None

    text = config_path.read_text(encoding="utf-8")
    parsed = _parse_toml_or_raise(text=text, source_label=str(config_path))
    _validate_codex_sections(parsed=parsed, source_label=str(config_path), server_name=server_name)
    mcp_servers = parsed.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        return None, None
    entry = mcp_servers.get(server_name)
    if isinstance(entry, dict):
        return entry, str(config_path)
    return None, str(config_path)


def _collect_codex_check_state(*, workspace_root: Path, server_name: str) -> dict:
    """
    Collect Codex config discovery state for text and JSON check outputs.
    Active precedence: workspace .codex/mcp.toml, then ~/.codex/config.toml.
    """
    local_path = workspace_root / ".codex" / "mcp.toml"
    global_path = Path.home() / ".codex" / "config.toml"

    local_entry, _ = _read_codex_server_entry(config_path=local_path, server_name=server_name)
    global_entry, _ = _read_codex_server_entry(config_path=global_path, server_name=server_name)

    active_scope = "none"
    active_path: str | None = None
    active_entry = None
    if local_entry is not None:
        active_scope = "workspace"
        active_path = str(local_path)
        active_entry = local_entry
    elif global_entry is not None:
        active_scope = "global"
        active_path = str(global_path)
        active_entry = global_entry

    readiness = _validate_common_entry(
        active_entry,
        require_project_root=active_scope != "global",
        env_required=True,
    )

    return {
        "ok": True,
        "client": "codex",
        "server_name": server_name,
        "workspace": {
            "path": str(local_path),
            "exists": local_path.exists(),
            "entry": local_entry,
        },
        "global": {
            "path": str(global_path),
            "exists": global_path.exists(),
            "entry": global_entry,
        },
        "active": {
            "scope": active_scope,
            "path": active_path,
            "entry": active_entry,
        },
        "ready": readiness.ready,
        "problems": readiness.problems,
        "not_applicable": False,
    }


def _codex_entry_readiness(entry: object) -> tuple[bool, list[str]]:
    """Validate that an active Codex MCP server entry has required fields."""
    result = _validate_common_entry(entry, require_project_root=False, env_required=True)
    return result.ready, result.problems


def _print_codex_check(*, workspace_root: Path, server_name: str) -> int:
    """
    Print Codex config discovery status and the active server entry.
    Active precedence: workspace .codex/mcp.toml, then ~/.codex/config.toml.
    """
    try:
        state = _collect_codex_check_state(workspace_root=workspace_root, server_name=server_name)
    except (RuntimeError, ValueError) as exc:
        print(f"[ERROR] Codex config check failed: {exc}")
        return 2

    print(
        f"[INFO] Codex workspace config: {state['workspace']['path']} "
        f"({'exists' if state['workspace']['exists'] else 'missing'})"
    )
    print(
        f"[INFO] Codex global config: {state['global']['path']} "
        f"({'exists' if state['global']['exists'] else 'missing'})"
    )

    active_entry = state["active"]["entry"]
    if active_entry is None:
        print(f"[INFO] Active server entry '{server_name}': not found")
    else:
        print(f"[INFO] Active server entry '{server_name}' source: {state['active']['path']}")
        print("[INFO] Active server entry payload:")
        print(json.dumps(active_entry, indent=2, sort_keys=True))

    print(f"[INFO] Ready for Codex: {'yes' if state.get('ready') else 'no'}")
    for problem in state.get("problems", []):
        print(f"[WARN] {problem}")
    return 0


def _print_codex_check_json(*, workspace_root: Path, server_name: str) -> int:
    """Print Codex config discovery + active server entry as machine-readable JSON."""
    try:
        state = _collect_codex_check_state(workspace_root=workspace_root, server_name=server_name)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2

    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def _print_codex_app_setup_summary(*, workspace_root: Path, server_name: str) -> int:
    """Print a compact readiness summary for Codex app usage."""
    try:
        state = _collect_codex_check_state(workspace_root=workspace_root, server_name=server_name)
    except (RuntimeError, ValueError) as exc:
        print(f"[ERROR] Codex app setup summary failed: {exc}")
        return 2

    print("[INFO] Codex app readiness summary:")
    print(f"[INFO] Active scope: {state['active']['scope']}")
    if state["active"]["path"]:
        print(f"[INFO] Active config path: {state['active']['path']}")
    print(f"[INFO] Ready for Codex app: {'yes' if state.get('ready') else 'no'}")
    for problem in state.get("problems", []):
        print(f"[WARN] {problem}")
    return 0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _copy_tree(*, source: Path, destination: Path, dry_run: bool, written: list[Path]) -> None:
    if not source.exists():
        return
    if source.resolve() == destination.resolve():
        return

    for item in source.rglob("*"):
        rel = item.relative_to(source)
        target = destination / rel
        if item.is_dir():
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)
            continue
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        written.append(target)


def _build_claude_plugin_manifest(
    *,
    server_name: str,
    command: str,
    args_prefix: list[str],
) -> dict:
    manifest = _make_claude_code_plugin_manifest()
    template_path = _repo_root() / ".claude-plugin" / "plugin.json"
    if template_path.exists():
        try:
            parsed = _parse_json_object_or_raise(
                text=template_path.read_text(encoding="utf-8"),
                source_label=str(template_path),
            )
            manifest.update(parsed)
        except Exception:
            pass

    manifest["name"] = manifest.get("name") or "gms-mcp"
    manifest["mcpServers"] = {
        server_name: {
            "command": command,
            "args": args_prefix,
            "env": {},
        }
    }
    return manifest


def _generate_claude_code_plugin(
    *,
    plugin_dir: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    dry_run: bool,
    include_bundle_assets: bool = False,
    safe_profile: bool = False,
) -> list[Path]:
    """
    Generate Claude plugin files with MCP server configuration.

    This creates files for BOTH Claude Desktop (GUI) and Claude Code (CLI),
    but they are used differently:

    - Claude Desktop: Uses ~/.claude/plugins/ with plugin.json manifest (global)
    - Claude Code CLI: Uses per-project .mcp.json files (project-scoped)

    The same file structure works for both, but the discovery mechanism differs.

    Creates:
      plugin_dir/
      ├── .claude-plugin/
      │   └── plugin.json   # For Claude Desktop only
      └── .mcp.json         # For Claude Code CLI (or Claude Desktop)
    """
    written: list[Path] = []

    if include_bundle_assets:
        _copy_tree(
            source=_repo_root() / "hooks",
            destination=plugin_dir / "hooks",
            dry_run=dry_run,
            written=written,
        )
        _copy_tree(
            source=_repo_root() / "skills",
            destination=plugin_dir / "skills",
            dry_run=dry_run,
            written=written,
        )

    # Create plugin manifest
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_path = manifest_dir / "plugin.json"
    manifest = _build_claude_plugin_manifest(
        server_name=server_name,
        command=command,
        args_prefix=args_prefix,
    )
    _write_json(manifest_path, manifest, dry_run=dry_run)
    written.append(manifest_path)

    # Create MCP server config
    mcp_config_path = plugin_dir / ".mcp.json"
    mcp_config = _make_claude_code_mcp_config(
        server_name=server_name,
        command=command,
        args=args_prefix,
        safe_profile=safe_profile,
    )
    _write_json(mcp_config_path, mcp_config, dry_run=dry_run)
    written.append(mcp_config_path)

    return written


def _setup_project_config(
    *,
    gm_project_root: Path,
    non_interactive: bool,
    skip_config: bool,
    use_defaults: bool,
    dry_run: bool,
) -> Optional[Path]:
    """
    Set up the .gms-mcp.json configuration file for naming conventions.
    
    Args:
        gm_project_root: Path to the GameMaker project directory
        non_interactive: If True, never prompt for input
        skip_config: If True, skip config setup entirely
        use_defaults: If True, create config with defaults (no prompts)
        dry_run: If True, don't write any files
        
    Returns:
        Path to created config file, or None if skipped
    """
    if skip_config:
        return None
    
    config_path = gm_project_root / PROJECT_CONFIG_FILE
    
    # Check if config already exists
    if config_path.exists():
        print(f"[INFO] Project config already exists: {config_path}")
        return config_path
    
    # Determine whether to create config
    should_create = use_defaults
    
    if not should_create and not non_interactive and sys.stdin and sys.stdin.isatty():
        # Interactive mode - ask user
        print("\n" + "=" * 60)
        print("NAMING CONVENTIONS CONFIGURATION")
        print("=" * 60)
        print("\nThe GMS-MCP tool can enforce naming conventions for assets.")
        print("Default prefixes:")
        print("  - Objects:  o_       (e.g., o_player)")
        print("  - Sprites:  spr_     (e.g., spr_player)")
        print("  - Rooms:    r_       (e.g., r_main)")
        print("  - Scripts:  snake_case (constructors can be PascalCase)")
        print("\nYou can customize these in the config file after creation.")
        print("")
        
        while True:
            choice = input("Create .gms-mcp.json config file? [Y/n]: ").strip().lower()
            if choice in ("", "y", "yes"):
                should_create = True
                break
            elif choice in ("n", "no"):
                should_create = False
                break
            else:
                print("[ERROR] Please enter Y or N.")
    elif not should_create and non_interactive:
        # Non-interactive mode without --use-defaults: skip by default
        print("[INFO] Skipping config file creation (non-interactive mode).")
        print("       Use --use-defaults to create config with default settings.")
        return None
    
    if not should_create:
        print("[INFO] Skipping config file creation.")
        return None
    
    if dry_run:
        print(f"[DRY-RUN] Would create: {config_path}")
        return config_path
    
    try:
        created_path = create_default_config_file(gm_project_root, overwrite=False)
        print(f"[OK] Created project config: {created_path}")
        print("     Edit this file to customize naming conventions.")
        return created_path
    except FileExistsError:
        print(f"[INFO] Config file already exists: {config_path}")
        return config_path
    except Exception as e:
        print(f"[WARN] Could not create config file: {e}")
        return None


def _scope_not_applicable_reason(*, client: str, scope: str) -> str | None:
    spec = resolve_client_spec(client)
    if scope == "workspace" and not spec.workspace_supported:
        return f"Client '{spec.key}' does not support workspace scope."
    if scope == "global" and not spec.global_supported:
        return f"Client '{spec.key}' does not support global scope."
    return None


def _collect_client_check_state(
    *,
    client: str,
    scope: str,
    workspace_root: Path,
    server_name: str,
    config_path_override: str | None,
) -> ConfigState:
    spec = resolve_client_spec(client)
    not_applicable_reason = _scope_not_applicable_reason(client=spec.key, scope=scope)
    if not_applicable_reason is not None:
        fallback_path = str(workspace_root)
        if config_path_override:
            override_path = Path(config_path_override).expanduser()
            if not override_path.is_absolute():
                override_path = (workspace_root / override_path).resolve()
            fallback_path = str(override_path)
        elif scope == "workspace" and spec.workspace_relpath:
            fallback_path = str(workspace_root / spec.workspace_relpath)
        elif scope == "global" and spec.global_relpath:
            fallback_path = str(Path.home() / spec.global_relpath)
        return ConfigState(
            client=spec.key,
            scope=scope,
            server_name=server_name,
            path=fallback_path,
            exists=False,
            entry=None,
            readiness=ReadinessResult(ready=False, problems=[not_applicable_reason], not_applicable=True),
        )

    target = spec.resolve_path(workspace_root=workspace_root, scope=scope, override=config_path_override)
    try:
        if spec.key == "codex":
            entry, _ = _read_codex_server_entry(config_path=target, server_name=server_name)
            readiness = _validate_common_entry(
                entry,
                require_project_root=scope != "global",
                env_required=True,
            )
            return ConfigState(
                client=spec.key,
                scope=scope,
                server_name=server_name,
                path=str(target),
                exists=target.exists(),
                entry=entry,
                readiness=readiness,
            )

        if spec.key == "claude-desktop":
            plugin_dir = target
            mcp_path = plugin_dir / ".mcp.json"
            state = _collect_standard_check_state(
                client=spec.key,
                scope=scope,
                config_path=mcp_path,
                server_name=server_name,
                allow_plain_top_level=True,
                require_project_root=True,
                env_required=True,
                not_applicable_reason=not_applicable_reason,
            )
            if not state.readiness.not_applicable:
                manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
                hooks_dir = plugin_dir / "hooks"
                skills_dir = plugin_dir / "skills"
                if not manifest_path.exists():
                    state.readiness.problems.append("Claude plugin manifest is missing (.claude-plugin/plugin.json).")
                if not hooks_dir.exists():
                    state.readiness.problems.append("Claude plugin hooks directory is missing.")
                if not skills_dir.exists():
                    state.readiness.problems.append("Claude plugin skills directory is missing.")
                state.readiness.ready = len(state.readiness.problems) == 0
                state.exists = mcp_path.exists() or manifest_path.exists()
                state.path = str(plugin_dir)
            return state

        allow_plain = spec.key == "claude-code"
        require_project_root = not (spec.key == "codex" and scope == "global")
        return _collect_standard_check_state(
            client=spec.key,
            scope=scope,
            config_path=target,
            server_name=server_name,
            allow_plain_top_level=allow_plain,
            require_project_root=require_project_root,
            env_required=True,
            not_applicable_reason=not_applicable_reason,
        )
    except (RuntimeError, ValueError) as exc:
        return ConfigState(
            client=spec.key,
            scope=scope,
            server_name=server_name,
            path=str(target),
            exists=target.exists(),
            entry=None,
            readiness=ReadinessResult(ready=False, problems=[str(exc)]),
        )


def _run_setup_for_client(
    *,
    client: str,
    scope: str,
    workspace_root: Path,
    gm_project_root: Path | None,
    server_name: str,
    command: str,
    args_prefix: list[str],
    dry_run: bool,
    safe_profile: bool,
    config_path_override: str | None,
) -> int:
    spec = resolve_client_spec(client)
    not_applicable_reason = _scope_not_applicable_reason(client=spec.key, scope=scope)
    if not_applicable_reason is not None:
        print(f"[INFO] {not_applicable_reason}")
        return 0

    target = spec.resolve_path(workspace_root=workspace_root, scope=scope, override=config_path_override)

    if spec.key == "cursor":
        gm_rel_posix = _relpath_posix_or_none(gm_project_root if scope == "workspace" else None, workspace_root)
        payload = _make_server_config(
            client=spec.key,
            server_name=server_name,
            command=command,
            args=args_prefix,
            gm_project_root_rel_posix=gm_rel_posix,
            safe_profile=safe_profile,
        )
        _generate_cursor_config(
            workspace_root=workspace_root,
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
            gm_project_root=gm_project_root if scope == "workspace" else None,
            out_path=target,
            dry_run=dry_run,
            safe_profile=safe_profile,
        )
        print(f"[{'DRY-RUN' if dry_run else 'INFO'}] Cursor config {'would be written to' if dry_run else 'written to'}: {target}")
        if dry_run:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if spec.key == "codex":
        try:
            _, payload, merged = _generate_codex_config(
                workspace_root=workspace_root,
                output_path=target,
                server_name=server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=gm_project_root,
                dry_run=dry_run,
                include_project_root=scope == "workspace",
                safe_profile=safe_profile,
            )
        except (RuntimeError, ValueError) as exc:
            print(f"[ERROR] Could not generate Codex config: {exc}")
            return 2
        if dry_run:
            print(f"[DRY-RUN] Codex config would be {'merged into' if scope == 'global' else 'written to'}: {target}")
            print(payload)
            print("[DRY-RUN] Final merged payload:")
            print(merged.rstrip())
        else:
            print(f"[INFO] Codex config updated: {target}")
        return 0

    if spec.key == "antigravity":
        if scope == "global":
            try:
                _, payload, merged, _ = _generate_antigravity_config(
                    workspace_root=workspace_root,
                    output_path=target,
                    server_name=server_name,
                    command=command,
                    args_prefix=args_prefix,
                    gm_project_root=gm_project_root,
                    safe_profile=safe_profile,
                    dry_run=dry_run,
                )
            except ValueError as exc:
                print(f"[ERROR] Could not generate Antigravity config: {exc}")
                return 2
            if dry_run:
                print(f"[DRY-RUN] Antigravity config would be merged into: {target}")
                print(json.dumps(payload, indent=2, sort_keys=True))
                print(json.dumps(merged, indent=2, sort_keys=True))
            else:
                print(f"[INFO] Antigravity config updated: {target}")
            return 0

        payload = _make_antigravity_server_config(
            server_name=server_name,
            command=command,
            args=args_prefix,
            workspace_root=workspace_root,
            gm_project_root=gm_project_root,
            safe_profile=safe_profile,
        )
        _write_json(target, payload, dry_run=dry_run)
        print(f"[{'DRY-RUN' if dry_run else 'INFO'}] Antigravity workspace config {'would be written to' if dry_run else 'written to'}: {target}")
        return 0

    if spec.key == "claude-code":
        plugin_dir = target.parent if target.suffix == ".json" else target
        manifest_payload = _build_claude_plugin_manifest(
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
        )
        mcp_payload = _make_claude_code_mcp_config(
            server_name=server_name,
            command=command,
            args=args_prefix,
            safe_profile=safe_profile,
        )
        _generate_claude_code_plugin(
            plugin_dir=plugin_dir,
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
            dry_run=dry_run,
            include_bundle_assets=False,
            safe_profile=safe_profile,
        )
        print(f"[{'DRY-RUN' if dry_run else 'INFO'}] Claude Code config {'would be written to' if dry_run else 'written to'}: {plugin_dir / '.mcp.json'}")
        if dry_run:
            print(json.dumps(manifest_payload, indent=2, sort_keys=True))
            print(json.dumps(mcp_payload, indent=2, sort_keys=True))
        return 0

    if spec.key == "claude-desktop":
        manifest_payload = _build_claude_plugin_manifest(
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
        )
        mcp_payload = _make_claude_code_mcp_config(
            server_name=server_name,
            command=command,
            args=args_prefix,
            safe_profile=safe_profile,
        )
        _generate_claude_code_plugin(
            plugin_dir=target,
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
            dry_run=dry_run,
            include_bundle_assets=True,
            safe_profile=safe_profile,
        )
        print(f"[{'DRY-RUN' if dry_run else 'INFO'}] Claude Desktop plugin {'would be synced to' if dry_run else 'synced to'}: {target}")
        if dry_run:
            print(json.dumps(manifest_payload, indent=2, sort_keys=True))
            print(json.dumps(mcp_payload, indent=2, sort_keys=True))
        return 0

    # Generic JSON-style path for vscode/windsurf/openclaw/generic and future clients.
    gm_rel_posix = _relpath_posix_or_none(gm_project_root, workspace_root)
    payload = _make_server_config(
        client=spec.key,
        server_name=server_name,
        command=command,
        args=args_prefix,
        gm_project_root_rel_posix=gm_rel_posix,
        safe_profile=safe_profile,
    )
    _write_json(target, payload, dry_run=dry_run)
    print(f"[{'DRY-RUN' if dry_run else 'INFO'}] {spec.key} config {'would be written to' if dry_run else 'written to'}: {target}")
    if dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _maybe_install_openclaw_skills(*, enable: bool, project_scope: bool, workspace_root: Path) -> int:
    if not enable:
        return 0
    try:
        from types import SimpleNamespace
        from gms_helpers.commands.skills_commands import handle_skills_install
    except Exception as exc:
        print(f"[WARN] Could not load OpenClaw skills installer: {exc}")
        return 0

    previous_cwd = Path.cwd()
    try:
        os.chdir(workspace_root)
        result = handle_skills_install(
            SimpleNamespace(
                openclaw=True,
                project=project_scope,
                force=False,
            )
        )
    finally:
        os.chdir(previous_cwd)
    if not result.get("success", False):
        print("[ERROR] OpenClaw skills install failed during app setup.")
        return 2
    return 0


def _run_canonical_flow(
    *,
    client: str,
    scope: str,
    action: str,
    workspace_root: Path,
    gm_project_root: Path | None,
    server_name: str,
    command: str,
    args_prefix: list[str],
    dry_run: bool,
    safe_profile: bool,
    config_path_override: str | None,
    openclaw_install_skills: bool,
    openclaw_skills_project: bool,
) -> int:
    if action not in CLIENT_ACTIONS:
        print(f"[ERROR] Unsupported action '{action}'.")
        return 2
    if scope not in CLIENT_SCOPES:
        print(f"[ERROR] Unsupported scope '{scope}'.")
        return 2

    if action == "setup":
        return _run_setup_for_client(
            client=client,
            scope=scope,
            workspace_root=workspace_root,
            gm_project_root=gm_project_root,
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
            dry_run=dry_run,
            safe_profile=safe_profile,
            config_path_override=config_path_override,
        )

    if action == "check":
        state = _collect_client_check_state(
            client=client,
            scope=scope,
            workspace_root=workspace_root,
            server_name=server_name,
            config_path_override=config_path_override,
        )
        return _print_standard_check(state)

    if action == "check-json":
        state = _collect_client_check_state(
            client=client,
            scope=scope,
            workspace_root=workspace_root,
            server_name=server_name,
            config_path_override=config_path_override,
        )
        return _print_standard_check_json(state)

    # app-setup
    setup_code = _run_setup_for_client(
        client=client,
        scope=scope,
        workspace_root=workspace_root,
        gm_project_root=gm_project_root,
        server_name=server_name,
        command=command,
        args_prefix=args_prefix,
        dry_run=dry_run,
        safe_profile=safe_profile,
        config_path_override=config_path_override,
    )
    if setup_code != 0:
        return setup_code

    if resolve_client_spec(client).key == "openclaw":
        skills_code = _maybe_install_openclaw_skills(
            enable=openclaw_install_skills,
            project_scope=openclaw_skills_project,
            workspace_root=workspace_root,
        )
        if skills_code != 0:
            return skills_code

    state = _collect_client_check_state(
        client=client,
        scope=scope,
        workspace_root=workspace_root,
        server_name=server_name,
        config_path_override=config_path_override,
    )
    _print_standard_check(state)
    return _print_standard_app_setup_summary(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate MCP client configs for the GameMaker MCP server.")
    parser.add_argument("--workspace-root", default=".", help="Workspace root where configs should be written.")
    parser.add_argument("--server-name", default="gms", help="MCP server name in the config (default: gms).")
    parser.add_argument(
        "--mode",
        choices=["command", "python-module"],
        default="command",
        help="How configs should launch the server: 'command' (gms-mcp on PATH) or 'python-module'.",
    )
    parser.add_argument(
        "--python",
        default=_default_python_command(),
        help="Python command to use when --mode=python-module (default: python3 on Unix, python on Windows).",
    )
    parser.add_argument(
        "--gm-project-root",
        default=None,
        help="Explicit GameMaker project directory (folder containing a .yyp). Overrides auto-detection.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never prompt (safe for CI/agents). If multiple .yyp are found, defaults to ${workspaceFolder}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written, but do not write any files.",
    )
    parser.add_argument(
        "--client",
        choices=all_client_names(),
        default=None,
        help="Canonical client selector for parity workflows.",
    )
    parser.add_argument(
        "--scope",
        choices=CLIENT_SCOPES,
        default="workspace",
        help="Canonical scope selector: workspace or global.",
    )
    parser.add_argument(
        "--action",
        choices=CLIENT_ACTIONS,
        default="setup",
        help="Canonical action selector: setup/check/check-json/app-setup.",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Optional explicit config path for canonical --client flows.",
    )

    parser.add_argument("--cursor", action="store_true", help="Write Cursor workspace config to .cursor/mcp.json.")
    parser.add_argument("--cursor-global", action="store_true", help="Write Cursor *global* config to ~/.cursor/mcp.json.")
    parser.add_argument(
        "--claude-code",
        action="store_true",
        help="Write .mcp.json for Claude Code CLI (per-project). "
             "NOTE: For Claude Code CLI, run this in each GameMaker project. "
             "Claude Code CLI does not support global MCP configs.",
    )
    parser.add_argument(
        "--claude-code-global",
        action="store_true",
        help="Install plugin for Claude Desktop GUI (NOT Claude Code CLI) to ~/.claude/plugins/gms-mcp/. "
             "This is for the desktop app only. For the CLI, use --claude-code per-project instead.",
    )
    parser.add_argument(
        "--codex",
        action="store_true",
        help="Write a Codex configuration snippet to .codex/mcp.toml in the workspace root.",
    )
    parser.add_argument(
        "--codex-global",
        action="store_true",
        help="Write Codex server config into ~/.codex/config.toml (global merge).",
    )
    parser.add_argument(
        "--codex-dry-run-only",
        action="store_true",
        help="Print final merged Codex payloads for workspace and global targets without writing files.",
    )
    parser.add_argument(
        "--codex-check",
        action="store_true",
        help="Print detected Codex config paths and the active server entry.",
    )
    parser.add_argument(
        "--codex-check-json",
        action="store_true",
        help="Print detected Codex config paths and active server entry as JSON.",
    )
    parser.add_argument(
        "--codex-app-setup",
        action="store_true",
        help="One-shot Codex app setup: write workspace config, preview global merge, then run check + readiness summary.",
    )
    parser.add_argument("--vscode", action="store_true", help="Write a VS Code example config to mcp-configs/vscode.mcp.json.")
    parser.add_argument("--windsurf", action="store_true", help="Write a Windsurf example config to mcp-configs/windsurf.mcp.json.")
    parser.add_argument("--antigravity", action="store_true", help="Write an Antigravity example config to mcp-configs/antigravity.mcp.json.")
    parser.add_argument(
        "--antigravity-setup",
        action="store_true",
        help="Merge server config into Antigravity global config (~/.gemini/antigravity/mcp_config.json).",
    )
    parser.add_argument(
        "--antigravity-check",
        action="store_true",
        help="Print detected Antigravity config path and active server entry readiness.",
    )
    parser.add_argument(
        "--antigravity-check-json",
        action="store_true",
        help="Print detected Antigravity config path and active server entry as JSON.",
    )
    parser.add_argument(
        "--antigravity-app-setup",
        action="store_true",
        help="One-shot Antigravity setup: merge global config, then run check + readiness summary.",
    )
    parser.add_argument(
        "--antigravity-config-path",
        default=None,
        help="Override Antigravity config path (used by --antigravity-setup and --antigravity-check).",
    )
    parser.add_argument(
        "--safe-profile",
        action="store_true",
        help="Apply conservative env defaults to generated configs (disable direct mode, require dry-run for destructive tools).",
    )
    parser.add_argument(
        "--openclaw-install-skills",
        action="store_true",
        help="For canonical openclaw app-setup, also install bundled skills.",
    )
    parser.add_argument(
        "--openclaw-skills-project",
        action="store_true",
        help="When --openclaw-install-skills is used, install OpenClaw skills at workspace scope.",
    )
    parser.add_argument("--openclaw", action="store_true", help="Write an OpenClaw example config to mcp-configs/openclaw.mcp.json.")
    parser.add_argument("--all", action="store_true", help="Generate Cursor config + all example configs (excludes Claude Code global).")
    
    # Naming convention config options
    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="Skip creating .gms-mcp.json naming config file.",
    )
    parser.add_argument(
        "--use-defaults",
        action="store_true",
        help="Create .gms-mcp.json with default naming conventions (no prompts).",
    )

    args = parser.parse_args(argv)

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    dry_run = bool(args.dry_run)
    gm_project_root, gm_candidates = _select_gm_project_root(
        workspace_root=workspace_root,
        requested_root=args.gm_project_root,
        non_interactive=bool(args.non_interactive),
    )

    command, args_prefix = _resolve_launcher(mode=args.mode, python_command=args.python)
    if args.mode == "python-module" and command != args.python:
        print(f"[WARN] Python command '{args.python}' not found; using '{command}' instead.")

    if args.mode == "command" and shutil.which(command) is None:
        print(
            "[WARN] 'gms-mcp' not found on PATH. Config will still be written, but the client may fail to start it.\n"
            "       Recommended: `pipx install gms-mcp` (or use --mode=python-module)."
        )

    if args.client:
        spec = resolve_client_spec(args.client)
        canonical_safe_profile = bool(
            args.safe_profile
            or (spec.key == "antigravity" and args.scope == "global" and args.action in ("setup", "app-setup"))
        )
        return _run_canonical_flow(
            client=spec.key,
            scope=args.scope,
            action=args.action,
            workspace_root=workspace_root,
            gm_project_root=gm_project_root,
            server_name=args.server_name,
            command=command,
            args_prefix=args_prefix,
            dry_run=dry_run,
            safe_profile=canonical_safe_profile,
            config_path_override=args.config_path,
            openclaw_install_skills=bool(args.openclaw_install_skills),
            openclaw_skills_project=bool(args.openclaw_skills_project),
        )

    requested_any = (
        args.cursor or args.cursor_global or
        args.claude_code or args.claude_code_global or
        args.codex or args.codex_global or
        args.codex_dry_run_only or args.codex_check or args.codex_check_json or args.codex_app_setup or
        args.vscode or args.windsurf or args.antigravity or args.antigravity_setup or args.antigravity_check or
        args.antigravity_check_json or args.antigravity_app_setup or
        args.openclaw or args.all
    )
    if not requested_any:
        args.cursor = True

    if args.codex_app_setup:
        args.codex = True
        args.codex_check = True

    if args.antigravity_app_setup:
        args.antigravity_setup = True
        args.antigravity_check = True

    if args.codex_dry_run_only:
        # Explicit preview mode: show Codex final merged payloads only.
        args.codex = True
        args.codex_global = True
        args.cursor = False
        args.cursor_global = False
        args.claude_code = False
        args.claude_code_global = False
        args.vscode = False
        args.windsurf = False
        args.antigravity = False
        args.antigravity_setup = False
        args.antigravity_check = False
        args.antigravity_check_json = False
        args.antigravity_app_setup = False
        args.openclaw = False
        args.all = False
        dry_run = True

    def _run_requested_codex_checks() -> int:
        check_exit = 0
        if args.codex_check:
            code = _print_codex_check(workspace_root=workspace_root, server_name=args.server_name)
            if code != 0:
                check_exit = code
        if args.codex_check_json:
            code = _print_codex_check_json(workspace_root=workspace_root, server_name=args.server_name)
            if code != 0 and check_exit == 0:
                check_exit = code
        return check_exit

    antigravity_config_path = _resolve_antigravity_config_path(args.antigravity_config_path)
    antigravity_safe_profile = bool(args.safe_profile or args.antigravity_setup)

    def _run_requested_antigravity_checks() -> int:
        check_exit = 0
        if args.antigravity_check:
            code = _print_antigravity_check(
                config_path=antigravity_config_path,
                server_name=args.server_name,
            )
            if code != 0:
                check_exit = code
        if args.antigravity_check_json:
            code = _print_antigravity_check_json(
                config_path=antigravity_config_path,
                server_name=args.server_name,
            )
            if code != 0 and check_exit == 0:
                check_exit = code
        return check_exit

    only_checks = (
        (args.codex_check or args.codex_check_json or args.antigravity_check or args.antigravity_check_json)
        and not (
            args.cursor or args.cursor_global or
            args.claude_code or args.claude_code_global or
            args.codex or args.codex_global or
            args.codex_dry_run_only or
            args.codex_app_setup or
            args.antigravity_app_setup or
            args.vscode or args.windsurf or args.antigravity or args.antigravity_setup or args.openclaw or args.all
        )
    )
    if only_checks:
        codex_exit = _run_requested_codex_checks()
        antigravity_exit = _run_requested_antigravity_checks()
        if codex_exit != 0:
            return codex_exit
        return antigravity_exit

    if args.all:
        args.cursor = True
        args.vscode = True
        args.windsurf = True
        args.antigravity = True
        args.openclaw = True
        # Note: --all does NOT include claude-code-global since it's a global install

    written: list[Path] = []

    if args.cursor:
        written.append(
            _generate_cursor_config(
                workspace_root=workspace_root,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=gm_project_root,
                out_path=workspace_root / ".cursor" / "mcp.json",
                dry_run=dry_run,
                safe_profile=bool(args.safe_profile),
            )
        )

    if args.cursor_global:
        # Global config should be multi-workspace safe: default GM_PROJECT_ROOT to ${workspaceFolder}
        # and let project discovery happen per workspace.
        written.append(
            _generate_cursor_config(
                workspace_root=workspace_root,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=None,
                out_path=Path.home() / ".cursor" / "mcp.json",
                dry_run=dry_run,
                safe_profile=bool(args.safe_profile),
            )
        )

    if args.claude_code:
        # Per-project .mcp.json for Claude Code CLI
        written.extend(
            _generate_claude_code_plugin(
                plugin_dir=workspace_root,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                dry_run=dry_run,
                include_bundle_assets=False,
                safe_profile=bool(args.safe_profile),
            )
        )
        if not dry_run:
            print(f"[INFO] Created .mcp.json for Claude Code CLI (per-project config)")
            print(f"[INFO] When you open Claude Code in this directory, it will auto-discover the MCP server.")
            print(f"[INFO] You'll be prompted to approve it on first use.")
            print(f"[INFO] To use in other GameMaker projects: copy .mcp.json or re-run this command.")

    if args.claude_code_global:
        # Global plugin for Claude Desktop GUI (NOT Claude Code CLI)
        claude_plugins_dir = Path.home() / ".claude" / "plugins" / "gms-mcp"
        written.extend(
            _generate_claude_code_plugin(
                plugin_dir=claude_plugins_dir,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                dry_run=dry_run,
                include_bundle_assets=True,
                safe_profile=bool(args.safe_profile),
            )
        )
        if not dry_run:
            print(f"[INFO] Claude Desktop plugin installed to: {claude_plugins_dir}")
            print("       This is for Claude Desktop GUI app, NOT Claude Code CLI.")
            print("       The plugin will be available after restarting Claude Desktop.")
            print("       For Claude Code CLI, use --claude-code (per-project) instead.")

    if args.codex:
        try:
            codex_path, codex_payload, codex_merged = _generate_codex_config(
                workspace_root=workspace_root,
                output_path=workspace_root / ".codex" / "mcp.toml",
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=gm_project_root,
                dry_run=dry_run,
                include_project_root=True,
                safe_profile=bool(args.safe_profile),
            )
        except (RuntimeError, ValueError) as exc:
            print(f"[ERROR] Could not generate Codex workspace config: {exc}")
            return 2
        written.append(codex_path)

        if dry_run:
            print(f"[DRY-RUN] Codex config would be written to: {codex_path}")
            print("[DRY-RUN] Codex config payload:")
            print(codex_payload)
            if args.codex_dry_run_only:
                print("[DRY-RUN] Codex final merged payload:")
                print(codex_merged.rstrip())
        else:
            print(f"[INFO] Codex config written to: {codex_path}")
            print("       This is a workspace-scoped config file.")
            command_line = " ".join(
                [
                    "codex mcp add",
                    shlex.quote(args.server_name),
                    "--",
                    shlex.quote(command),
                ]
                + [shlex.quote(item) for item in args_prefix]
            )
            command_line += _build_codex_env_args(
                _build_codex_env(
                    gm_project_root,
                    workspace_root,
                    safe_profile=bool(args.safe_profile),
                )
            )
            print(f"[INFO] Registering command: {command_line}")

    if args.codex_global:
        codex_global_path = Path.home() / ".codex" / "config.toml"
        try:
            codex_global_path, codex_global_payload, codex_global_merged = _generate_codex_config(
                workspace_root=workspace_root,
                output_path=codex_global_path,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=gm_project_root,
                dry_run=dry_run,
                include_project_root=False,
                safe_profile=bool(args.safe_profile),
            )
        except (RuntimeError, ValueError) as exc:
            print(f"[ERROR] Could not generate Codex global config: {exc}")
            return 2
        written.append(codex_global_path)

        if dry_run:
            print(f"[DRY-RUN] Codex global config would be merged into: {codex_global_path}")
            print("[DRY-RUN] Codex global payload:")
            print(codex_global_payload)
            if args.codex_dry_run_only:
                print("[DRY-RUN] Codex global final merged payload:")
                print(codex_global_merged.rstrip())
        else:
            print(f"[INFO] Codex global config updated: {codex_global_path}")
            print("       Server entry is merged into [mcp_servers] without a fixed GM_PROJECT_ROOT.")

    codex_global_preview_only = args.codex_app_setup and not args.codex_global and not args.codex_dry_run_only
    if codex_global_preview_only:
        codex_global_path = Path.home() / ".codex" / "config.toml"
        try:
            _, _, codex_global_preview = _generate_codex_config(
                workspace_root=workspace_root,
                output_path=codex_global_path,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=gm_project_root,
                dry_run=True,
                include_project_root=False,
                safe_profile=bool(args.safe_profile),
            )
        except (RuntimeError, ValueError) as exc:
            print(f"[ERROR] Could not preview Codex global config merge: {exc}")
            return 2
        print(f"[INFO] Codex app setup global preview target: {codex_global_path}")
        print("[INFO] Codex app setup global final merged payload (preview):")
        print(codex_global_preview.rstrip())

    if args.antigravity_setup:
        try:
            antigravity_path, antigravity_payload, antigravity_merged, antigravity_backup = _generate_antigravity_config(
                workspace_root=workspace_root,
                output_path=antigravity_config_path,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=gm_project_root,
                safe_profile=antigravity_safe_profile,
                dry_run=dry_run,
            )
        except ValueError as exc:
            print(f"[ERROR] Could not generate Antigravity config: {exc}")
            return 2
        written.append(antigravity_path)
        if dry_run:
            print(f"[DRY-RUN] Antigravity config would be merged into: {antigravity_path}")
            print("[DRY-RUN] Antigravity payload:")
            print(json.dumps(antigravity_payload, indent=2, sort_keys=True))
            print("[DRY-RUN] Antigravity final merged payload:")
            print(json.dumps(antigravity_merged, indent=2, sort_keys=True))
        else:
            print(f"[INFO] Antigravity config updated: {antigravity_path}")
            if antigravity_backup is not None:
                print(f"[INFO] Antigravity backup created: {antigravity_backup}")
            if antigravity_safe_profile:
                print(
                    "[INFO] Applied conservative safety profile: "
                    "GMS_MCP_ENABLE_DIRECT=0, GMS_MCP_REQUIRE_DRY_RUN=1."
                )

    example_clients: list[str] = []
    if args.vscode:
        example_clients.append("vscode")
    if args.windsurf:
        example_clients.append("windsurf")
    if args.antigravity:
        example_clients.append("antigravity")
    if args.openclaw:
        example_clients.append("openclaw")
    if example_clients:
        written.extend(
            _generate_example_configs(
                workspace_root=workspace_root,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                gm_project_root=gm_project_root,
                clients=example_clients,
                dry_run=dry_run,
                safe_profile=bool(args.safe_profile),
            )
        )

    if dry_run:
        if args.codex_dry_run_only:
            print("[DRY-RUN] Codex dry-run-only mode complete. No files were written.")
            return 0
        print("[DRY-RUN] No files were written.")
        print("[DRY-RUN] Target paths:")
        for p in written:
            print(f"  - {p}")
        if args.cursor:
            cursor_path = workspace_root / ".cursor" / "mcp.json"
            gm_rel_posix = _relpath_posix_or_none(gm_project_root, workspace_root)
            payload = _make_server_config(
                client="cursor",
                server_name=args.server_name,
                command=command,
                args=args_prefix,
                gm_project_root_rel_posix=gm_rel_posix,
                safe_profile=bool(args.safe_profile),
            )
            print(f"\n[DRY-RUN] {cursor_path}:\n{json.dumps(payload, indent=2)}\n")
        if args.claude_code or args.claude_code_global:
            plugin_dir = (
                Path.home() / ".claude" / "plugins" / "gms-mcp"
                if args.claude_code_global
                else workspace_root
            )
            print(f"\n[DRY-RUN] Claude Code plugin would be created at: {plugin_dir}")
            print(f"[DRY-RUN] {plugin_dir / '.claude-plugin' / 'plugin.json'}:")
            print(
                json.dumps(
                    _build_claude_plugin_manifest(
                        server_name=args.server_name,
                        command=command,
                        args_prefix=args_prefix,
                    ),
                    indent=2,
                )
            )
            print(f"\n[DRY-RUN] {plugin_dir / '.mcp.json'}:")
            mcp_config = _make_claude_code_mcp_config(
                server_name=args.server_name,
                command=command,
                args=args_prefix,
                safe_profile=bool(args.safe_profile),
            )
            print(json.dumps(mcp_config, indent=2))
            print()
        check_exit = _run_requested_codex_checks()
        if check_exit != 0:
            return check_exit
        antigravity_check_exit = _run_requested_antigravity_checks()
        if antigravity_check_exit != 0:
            return antigravity_check_exit
        if args.codex_app_setup:
            summary_code = _print_codex_app_setup_summary(workspace_root=workspace_root, server_name=args.server_name)
            if summary_code != 0:
                return summary_code
        if args.antigravity_app_setup:
            return _print_antigravity_app_setup_summary(
                config_path=antigravity_config_path,
                server_name=args.server_name,
            )
        return 0

    gm_note = str(gm_project_root) if gm_project_root else "(not selected; defaults to ${workspaceFolder})"
    print("[OK] Wrote MCP config(s):")
    for p in written:
        print(f"  - {p}")
    if gm_candidates and len(gm_candidates) > 1 and gm_project_root is None:
        print("[WARN] Multiple .yyp projects detected; GM_PROJECT_ROOT defaulted to ${workspaceFolder}.")
        print("       Re-run with --gm-project-root <path> (or run interactively to choose).")
    print(f"[INFO] Selected GameMaker project root: {gm_note}")
    print("[INFO] If this is wrong, edit GM_PROJECT_ROOT in the generated config.")
    
    # Set up project naming config if we have a project root
    if gm_project_root:
        config_path = _setup_project_config(
            gm_project_root=gm_project_root,
            non_interactive=bool(args.non_interactive),
            skip_config=bool(args.skip_config),
            use_defaults=bool(args.use_defaults),
            dry_run=dry_run,
        )
        if config_path:
            written.append(config_path)

    check_exit = _run_requested_codex_checks()
    if check_exit != 0:
        return check_exit
    antigravity_check_exit = _run_requested_antigravity_checks()
    if antigravity_check_exit != 0:
        return antigravity_check_exit
    if args.codex_app_setup:
        summary_code = _print_codex_app_setup_summary(workspace_root=workspace_root, server_name=args.server_name)
        if summary_code != 0:
            return summary_code
    if args.antigravity_app_setup:
        return _print_antigravity_app_setup_summary(
            config_path=antigravity_config_path,
            server_name=args.server_name,
        )
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
