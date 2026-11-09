from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

from gms_helpers.bundle_assets import bundled_hooks_dir, bundled_skills_dir

from .common import (
    _FORWARDED_ENV_VARS,
    _apply_onboarding_profile_env,
    _apply_safe_profile_env,
    _make_antigravity_server_config,
    _make_server_config,
    _merge_server_entry,
    _parse_json_object_or_raise,
    _redact_config_value,
    _relpath_posix_or_none,
    _report_removed_keys,
    _update_config_text,
    _validate_common_entry,
    _validate_config_destination,
    _write_json,
    _write_json_atomic_with_backup,
    validate_server_name,
)
from ..client_registry import codex_home

if sys.version_info >= (3, 11):
    import tomllib as _toml_parser
else:
    try:
        import tomli as _toml_parser
    except ModuleNotFoundError:
        _toml_parser = None


def _generate_cursor_config(
    *,
    workspace_root: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    gm_project_root: Path | None,
    out_path: Path,
    workspace_scope: bool = True,
    dry_run: bool,
    safe_profile: bool = False,
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
) -> Path:
    gm_rel_posix = _relpath_posix_or_none(gm_project_root, workspace_root)
    config = _make_server_config(
        client="cursor",
        server_name=server_name,
        command=command,
        args=args_prefix,
        gm_project_root_rel_posix=gm_rel_posix,
        safe_profile=safe_profile,
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
    )
    _write_json(out_path, config, dry_run=dry_run, workspace_root=workspace_root if workspace_scope else None)
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
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
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
                onboarding_profile=onboarding_profile,
                toolsets=toolsets,
            )
        else:
            config = _make_server_config(
                client=client,
                server_name=server_name,
                command=command,
                args=args_prefix,
                gm_project_root_rel_posix=gm_rel_posix,
                safe_profile=safe_profile,
                onboarding_profile=onboarding_profile,
                toolsets=toolsets,
            )
        out_path = out_dir / f"{client}.mcp.json"
        _write_json(out_path, config, dry_run=dry_run, workspace_root=workspace_root)
        out_paths.append(out_path)
    return out_paths


def _make_claude_code_plugin_manifest() -> dict:
    """Create the plugin.json manifest for Claude Code."""
    return {
        "name": "gms-mcp",
        "description": "GameMaker Studio MCP tools for asset management, code intelligence, and project maintenance",
        "author": {"name": "Ampersand Game Studios", "url": "https://github.com/Ampersand-Game-Studios/gms-mcp"},
        "repository": "https://github.com/Ampersand-Game-Studios/gms-mcp",
        "license": "MIT",
        "keywords": ["gamemaker", "game-development", "mcp", "assets", "code-intelligence"],
    }


def _make_claude_code_mcp_config(
    *,
    server_name: str,
    command: str,
    args: list[str],
    safe_profile: bool = False,
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
) -> dict:
    """
    Create the .mcp.json config for Claude Code.

    Uses ${CLAUDE_PROJECT_DIR:-.}, which resolves to the active Claude Code
    project and remains valid when Claude invokes the plugin outside a project.
    """
    env: dict[str, str] = {
        "GM_PROJECT_ROOT": "${CLAUDE_PROJECT_DIR:-.}",
        "PYTHONUNBUFFERED": "1",  # Ensure Python output is not buffered
    }

    # Include relevant environment variables from current process
    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_onboarding_profile_env(
        env,
        profile="safe" if safe_profile else onboarding_profile,
        toolsets=toolsets,
    )

    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }


def _build_codex_env(
    gm_project_root: Optional[Path],
    workspace_root: Path,
    *,
    include_project_root: bool = True,
    safe_profile: bool = False,
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
) -> dict[str, str]:
    env: dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
    }

    if not include_project_root and os.environ.get("GMS_MCP_GMS_PATH"):
        env["GMS_MCP_GMS_PATH"] = os.environ["GMS_MCP_GMS_PATH"]
    if include_project_root:
        resolved_workspace = workspace_root.expanduser().resolve()
        resolved_root = (gm_project_root if gm_project_root is not None else workspace_root).expanduser().resolve()
        try:
            relative_root = resolved_root.relative_to(resolved_workspace)
        except ValueError as exc:
            raise ValueError(
                "Codex workspace GM_PROJECT_ROOT must be inside the workspace so the generated config remains portable."
            ) from exc
        env["GM_PROJECT_ROOT"] = relative_root.as_posix() or "."

    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_onboarding_profile_env(
        env,
        profile="safe" if safe_profile else onboarding_profile,
        toolsets=toolsets,
    )

    return env


def _build_codex_env_args(env: dict[str, str]) -> str:
    if not env:
        return ""
    return " " + " ".join(f"--env {shlex.quote(f'{key}={value}')}" for key, value in env.items())


def _parse_toml_or_raise(*, text: str, source_label: str) -> dict:
    """Parse TOML text and return a dictionary; raise a descriptive error on failure."""
    if _toml_parser is None:
        raise RuntimeError("TOML parser unavailable. Install Python 3.11+ or add dependency 'tomli' for Python 3.10.")
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
        raise ValueError(f"Malformed TOML in {source_label}: [mcp_servers.{server_name}.env] must be a table.")


def _merge_codex_text(
    *,
    existing_text: str | None,
    source_label: str,
    server_name: str,
    server_block: str,
) -> str:
    """Return the final merged Codex TOML payload; validates existing TOML first."""
    if existing_text is None:
        merged = server_block if server_block.endswith("\n") else server_block + "\n"
        _verify_codex_entry(merged_text=merged, server_name=server_name, server_block=server_block)
        return merged
    parsed = _parse_toml_or_raise(text=existing_text, source_label=source_label)
    _validate_codex_sections(parsed=parsed, source_label=source_label, server_name=server_name)
    return _upsert_codex_server_config(
        existing_text=existing_text,
        server_name=server_name,
        server_block=server_block,
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
    existing_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    return _merge_codex_text(
        existing_text=existing_text,
        source_label=str(output_path),
        server_name=server_name,
        server_block=server_block,
    )


def _verify_codex_entry(*, merged_text: str, server_name: str, server_block: str, expected: dict | None = None) -> None:
    """Parse the merged text and confirm it defines exactly the intended server entry."""
    merged = _parse_toml_or_raise(text=merged_text, source_label="merged config")
    if expected is None:
        expected = _parse_toml_or_raise(text=server_block, source_label="generated config")["mcp_servers"][server_name]
    servers = merged.get("mcp_servers")
    if not isinstance(servers, dict) or servers.get(server_name) != expected:
        raise ValueError(f"Merged Codex config does not contain the expected [mcp_servers.{server_name}] entry.")


def _redact_host_paths(value: object) -> object:
    """Replace machine-specific paths in a configuration preview."""
    if isinstance(value, dict):
        return {key: _redact_host_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_host_paths(item) for item in value]
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if stripped.startswith(("/", "\\\\", "~/", "~\\")) or re.match(r"^[A-Za-z]:[\\/]", stripped):
        return "<host-path>"

    option, separator, option_value = value.partition("=")
    option_value = option_value.strip()
    if separator and (
        option_value.startswith(("/", "\\\\", "~/", "~\\")) or re.match(r"^[A-Za-z]:[\\/]", option_value)
    ):
        return f"{option}=<host-path>"
    return value


def _render_codex_privacy_safe_preview(
    *,
    merged_text: str,
    server_name: str,
    source_label: str,
) -> str:
    """Render only the redacted target entry from a final Codex TOML merge."""
    parsed = _parse_toml_or_raise(text=merged_text, source_label=source_label)
    _validate_codex_sections(parsed=parsed, source_label=source_label, server_name=server_name)
    mcp_servers = parsed.get("mcp_servers")
    if not isinstance(mcp_servers, dict) or server_name not in mcp_servers:
        raise ValueError(f"Malformed TOML in {source_label}: target MCP server entry is missing.")

    target_entry = _redact_host_paths(_redact_config_value(mcp_servers[server_name]))
    return json.dumps({"mcp_servers": {server_name: target_entry}}, indent=2, sort_keys=True)


def _upsert_codex_server_config(
    existing_text: str,
    *,
    server_name: str,
    server_block: str,
) -> str:
    """Return TOML text with the target server entry inserted or updated.

    Only installer-owned keys are replaced; other keys in an existing entry and
    full-line comments inside its tables are kept.
    """
    validate_server_name(server_name)
    before = _parse_toml_or_raise(text=existing_text, source_label="existing config")
    generated = _parse_toml_or_raise(text=server_block, source_label="generated config")["mcp_servers"][server_name]
    existing_servers = before.get("mcp_servers")
    existing_entry = existing_servers.get(server_name) if isinstance(existing_servers, dict) else None
    if isinstance(existing_entry, dict):
        entry, removed = _merge_server_entry(existing_entry, generated)
        _report_removed_keys(server_name, removed)
        block = _render_toml_tables(("mcp_servers", server_name), entry)
    else:
        entry, block = generated, server_block.strip()
    lines = existing_text.splitlines()
    kept = []
    own_comments = []
    own_section = False
    for line in lines:
        match = re.match(r"^\s*(\[\[?.+?\]\]?)(?:\s*#.*)?\s*$", line)
        if match:
            header = _parse_toml_or_raise(text=match.group(1), source_label="table header")
            servers = header.get("mcp_servers", {})
            own_section = set(header) == {"mcp_servers"} and set(servers) == {server_name}
        if not own_section:
            kept.append(line)
        elif line.lstrip().startswith("#"):
            own_comments.append(line)
    merged = "\n".join([*kept, "", *own_comments, block]).strip() + "\n"
    _verify_codex_entry(merged_text=merged, server_name=server_name, server_block=server_block, expected=entry)
    after = _parse_toml_or_raise(text=merged, source_label="merged config")
    for parsed in (before, after):
        servers = parsed.get("mcp_servers")
        if isinstance(servers, dict):
            servers.pop(server_name, None)
            if not servers:
                parsed.pop("mcp_servers")
    if before != after:
        raise ValueError("Config merge changed unrelated TOML tables")
    return merged


def _make_codex_toml_value(value: object) -> str:
    """Serialize a Python value for inclusion in Codex TOML config."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value in (float("inf"), float("-inf")):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_make_codex_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(f"{_toml_key(key)} = {_make_codex_toml_value(item)}" for key, item in value.items())
        return "{ " + items + " }" if items else "{}"
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    # JSON string escapes are valid TOML basic-string escapes; DEL must be escaped too.
    return json.dumps(value).replace("\x7f", "\\u007f")


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _render_toml_tables(path: tuple[str, ...], table: dict) -> str:
    """Render a table and its sub-tables as standard TOML table sections."""
    header = "[" + ".".join(_toml_key(part) for part in path) + "]"
    lines = [header]
    nested = []
    for key, value in table.items():
        if isinstance(value, dict):
            nested.append((key, value))
        else:
            lines.append(f"{_toml_key(key)} = {_make_codex_toml_value(value)}")
    sections = ["\n".join(lines)]
    sections.extend(_render_toml_tables((*path, key), value) for key, value in nested)
    return "\n\n".join(sections)


def _make_codex_mcp_config(
    *,
    server_name: str,
    command: str,
    args: list[str],
    gm_project_root: Optional[Path],
    workspace_root: Path,
    include_project_root: bool = True,
    safe_profile: bool = False,
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
) -> str:
    """Create a Codex MCP config block in TOML format.

    Workspace configs use a relative GM_PROJECT_ROOT, so they pin ``cwd`` to the
    workspace root that the relative path is resolved from.
    """
    validate_server_name(server_name)
    env: dict[str, str] = _build_codex_env(
        gm_project_root=gm_project_root,
        workspace_root=workspace_root,
        include_project_root=include_project_root,
        safe_profile=safe_profile,
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
    )

    lines = [
        "[mcp_servers.{}]".format(server_name),
        f"command = {_make_codex_toml_value(command)}",
        f"args = {_make_codex_toml_value(args)}",
    ]
    if include_project_root:
        lines.append(f"cwd = {_make_codex_toml_value(workspace_root.expanduser().resolve().as_posix())}")
    lines += ["", f"[mcp_servers.{server_name}.env]"]

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
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
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
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
    )
    _validate_config_destination(output_path, workspace_root if include_project_root else None)
    merged, _backup = _update_config_text(
        output_path=output_path,
        render=lambda existing_text: _merge_codex_text(
            existing_text=existing_text,
            source_label=str(output_path),
            server_name=server_name,
            server_block=payload,
        ),
        dry_run=dry_run,
    )
    if not dry_run and output_path.read_text(encoding="utf-8") != merged:
        raise OSError("Written Codex config failed verification")

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
        raise ValueError(f"Malformed JSON in {source_label}: `mcpServers.{server_name}.env` must be an object.")


def _render_antigravity_merged_config(
    *,
    output_path: Path,
    server_name: str,
    server_entry: dict,
) -> dict:
    existing_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    return _merge_antigravity_config(
        existing_text=existing_text, output_path=output_path, server_name=server_name, server_entry=server_entry
    )


def _merge_antigravity_config(
    *,
    existing_text: str | None,
    output_path: Path,
    server_name: str,
    server_entry: dict,
) -> dict:
    if existing_text is not None:
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
    mcp_servers[server_name], removed = _merge_server_entry(mcp_servers.get(server_name), server_entry)
    _report_removed_keys(server_name, removed)
    merged["mcpServers"] = mcp_servers
    return merged


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
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
) -> tuple[Path, dict, dict, Path | None]:
    payload = _make_antigravity_server_config(
        server_name=server_name,
        command=command,
        args=args_prefix,
        workspace_root=workspace_root,
        gm_project_root=gm_project_root,
        safe_profile=safe_profile,
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
    )
    server_entry = payload["mcpServers"][server_name]
    merged_holder: dict = {}

    def render(existing_text: str | None) -> str:
        merged_holder["merged"] = _merge_antigravity_config(
            existing_text=existing_text, output_path=output_path, server_name=server_name, server_entry=server_entry
        )
        return json.dumps(merged_holder["merged"], indent=2) + "\n"

    _text, backup_path = _update_config_text(output_path=output_path, render=render, dry_run=dry_run)
    return output_path, payload, merged_holder["merged"], backup_path


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
            problems.append('`env.PYTHONUNBUFFERED` should be "1" for unbuffered logs.')

    return len(problems) == 0, problems


def _print_antigravity_check(*, config_path: Path, server_name: str) -> int:
    try:
        state = _collect_antigravity_check_state(config_path=config_path, server_name=server_name)
    except ValueError as exc:
        print(f"[ERROR] Antigravity config check failed: {exc}")
        return 2

    print(
        f"[INFO] Antigravity config: {state['config']['path']} ({'exists' if state['config']['exists'] else 'missing'})"
    )
    entry = state["config"]["entry"]
    if entry is None:
        print(f"[INFO] Active server entry '{server_name}': not found")
        return 0

    ready, problems = _antigravity_entry_readiness(entry)
    print(f"[INFO] Active server entry '{server_name}' source: {state['config']['path']}")
    print("[INFO] Active server entry payload:")
    print(json.dumps(_redact_config_value(entry), indent=2, sort_keys=True))
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
    print(json.dumps(_redact_config_value(state), indent=2, sort_keys=True))
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
    global_path = codex_home() / "config.toml"

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

    local_entry_redacted = _redact_config_value(local_entry)
    global_entry_redacted = _redact_config_value(global_entry)
    active_entry_redacted = _redact_config_value(active_entry)

    return {
        "ok": True,
        "client": "codex",
        "server_name": server_name,
        "workspace": {
            "path": str(local_path),
            "exists": local_path.exists(),
            "entry": local_entry_redacted,
        },
        "global": {
            "path": str(global_path),
            "exists": global_path.exists(),
            "entry": global_entry_redacted,
        },
        "active": {
            "scope": active_scope,
            "path": active_path,
            "entry": active_entry_redacted,
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
        print(json.dumps(_redact_config_value(active_entry), indent=2, sort_keys=True))

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

    print(json.dumps(_redact_config_value(state), indent=2, sort_keys=True))
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


def _copy_tree(*, source: Path, destination: Path, dry_run: bool, written: list[Path]) -> None:
    if not source.exists():
        return
    if source.resolve() == destination.resolve():
        return
    _validate_config_destination(destination)

    for item in sorted(source.rglob("*")):
        rel = item.relative_to(source)
        target = destination / rel
        if item.is_symlink():
            raise ValueError(f"Refusing to copy bundled asset symlink: {rel.as_posix()}")
        # Never write through a link planted inside the destination tree.
        _validate_config_destination(target, destination)
        if item.is_dir():
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)
            continue
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        written.append(target)


def _build_claude_plugin_manifest() -> dict:
    manifest = _make_claude_code_plugin_manifest()
    manifest["name"] = manifest.get("name") or "gms-mcp"
    return manifest


def _render_claude_hook_server_name(*, hooks_manifest_path: Path, server_name: str, dry_run: bool) -> None:
    """Bind bundled MCP hook matchers to the configured plugin server name."""
    if dry_run or not hooks_manifest_path.is_file():
        return
    payload = _parse_json_object_or_raise(
        text=hooks_manifest_path.read_text(encoding="utf-8"),
        source_label=str(hooks_manifest_path),
    )
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        raise ValueError(f"Malformed Claude hooks manifest: {hooks_manifest_path}")

    source_prefix = "mcp__plugin_gms-mcp_gms__"
    target_prefix = f"mcp__plugin_gms-mcp_{re.escape(server_name)}__"
    replacements = 0
    for event_name in ("PostToolUse", "PostToolUseFailure"):
        groups = hooks.get(event_name)
        if not isinstance(groups, list):
            raise ValueError(f"Malformed Claude hooks manifest: missing {event_name} groups")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("matcher"), str):
                continue
            matcher = group["matcher"]
            if source_prefix in matcher:
                group["matcher"] = matcher.replace(source_prefix, target_prefix)
                replacements += 1
    if replacements != 2:
        raise ValueError(f"Claude hooks manifest did not contain both expected GMS MCP matchers: {hooks_manifest_path}")
    _write_json(hooks_manifest_path, payload, dry_run=False)


def _check_plugin_manifest_ownership(manifest_path: Path, *, force: bool) -> None:
    """Refuse to rewrite a .claude-plugin/plugin.json that another plugin owns."""
    if force or not manifest_path.exists():
        return
    existing = _parse_json_object_or_raise(
        text=manifest_path.read_text(encoding="utf-8"), source_label=str(manifest_path)
    )
    if existing.get("name") != _make_claude_code_plugin_manifest()["name"]:
        raise ValueError(
            f"{manifest_path} belongs to another plugin ({existing.get('name')!r}); "
            "re-run with --force to replace it with the gms-mcp manifest."
        )


def _generate_claude_code_plugin(
    *,
    plugin_dir: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    dry_run: bool,
    include_bundle_assets: bool = False,
    safe_profile: bool = False,
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
    force: bool = False,
) -> list[Path]:
    """
    Generate Claude plugin files with MCP server configuration.

    This creates files for BOTH Claude Desktop (GUI) and Claude Code (CLI),
    but they are used differently:

    - Claude Desktop: Uses ~/.claude/plugins/ with plugin.json manifest (global)
    - Claude Code CLI: Uses per-project .mcp.json files (project-scoped)

    The same file structure works for both, but the discovery mechanism differs.

    Existing files are validated before anything is written, so a malformed or
    foreign file leaves the plugin untouched instead of half-installed.

    Creates:
      plugin_dir/
      ├── .claude-plugin/
      │   └── plugin.json   # For Claude Desktop only
      └── .mcp.json         # For Claude Code CLI (or Claude Desktop)
    """
    validate_server_name(server_name)
    written: list[Path] = []
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    mcp_config_path = plugin_dir / ".mcp.json"
    manifest = _build_claude_plugin_manifest()
    mcp_config = _make_claude_code_mcp_config(
        server_name=server_name,
        command=command,
        args=args_prefix,
        safe_profile=safe_profile,
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
    )

    _check_plugin_manifest_ownership(manifest_path, force=force)
    # Validate both targets (dry-run parses existing files) before copying assets.
    _write_json(manifest_path, manifest, dry_run=True)
    _write_json(mcp_config_path, mcp_config, dry_run=True)

    if include_bundle_assets:
        _copy_tree(
            source=bundled_hooks_dir(),
            destination=plugin_dir / "hooks",
            dry_run=dry_run,
            written=written,
        )
        _copy_tree(
            source=bundled_skills_dir(),
            destination=plugin_dir / "skills",
            dry_run=dry_run,
            written=written,
        )
        _render_claude_hook_server_name(
            hooks_manifest_path=plugin_dir / "hooks" / "hooks.json",
            server_name=server_name,
            dry_run=dry_run,
        )

    _write_json(manifest_path, manifest, dry_run=dry_run)
    written.append(manifest_path)
    _write_json(mcp_config_path, mcp_config, dry_run=dry_run)
    written.append(mcp_config_path)

    return written


# OpenClaw keeps saved MCP servers under `mcp.servers` in ~/.openclaw/openclaw.json (JSON5,
# shared with all other OpenClaw settings), so global setup goes through its own CLI rather
# than rewriting that file.
OPENCLAW_REDACTED = "__OPENCLAW_REDACTED__"
_OPENCLAW_TIMEOUT_SECONDS = 60


def _openclaw_cli() -> str:
    executable = shutil.which("openclaw")
    if not executable:
        raise RuntimeError(
            "The OpenClaw CLI (`openclaw`) was not found on PATH. Install OpenClaw, "
            "or pass --config-path to write a JSON file instead."
        )
    return executable


def _make_openclaw_server_entry(
    *,
    server_name: str,
    command: str,
    args_prefix: list[str],
    workspace_root: Path,
    gm_project_root: Path | None,
    safe_profile: bool,
    onboarding_profile: str | None,
    toolsets: str | None,
) -> dict:
    # OpenClaw does not expand ${workspaceFolder}, so paths are absolute.
    payload = _make_antigravity_server_config(
        server_name=server_name,
        command=command,
        args=args_prefix,
        workspace_root=workspace_root.resolve(),
        gm_project_root=gm_project_root.resolve() if gm_project_root is not None else None,
        safe_profile=safe_profile,
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
    )
    entry = payload["mcpServers"][server_name]
    return {**entry, "cwd": str(workspace_root.resolve())}


def _run_openclaw_mcp(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_openclaw_cli(), "mcp", *args],
        capture_output=True,
        text=True,
        timeout=_OPENCLAW_TIMEOUT_SECONDS,
        check=False,
    )


def _set_openclaw_server(*, server_name: str, entry: dict) -> None:
    validate_server_name(server_name)
    result = _run_openclaw_mcp(["set", server_name, json.dumps(entry)])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
        raise RuntimeError(
            f"`openclaw mcp set {server_name}` failed: {detail}. "
            "OpenClaw only changes saved servers while its Gateway is stopped; stop it and retry."
        )


def _read_openclaw_server_entry(*, server_name: str) -> dict | None:
    validate_server_name(server_name)
    result = _run_openclaw_mcp(["show", server_name, "--json"])
    if result.returncode != 0:
        return None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"`openclaw mcp show {server_name} --json` did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        return None
    if "command" in parsed or "url" in parsed:
        return parsed
    nested = parsed.get(server_name)
    return nested if isinstance(nested, dict) else None


def _validate_openclaw_entry(entry: object):
    # `openclaw mcp show` hides env values, so a redacted PYTHONUNBUFFERED only proves it is set.
    if isinstance(entry, dict) and isinstance(entry.get("env"), dict):
        env = dict(entry["env"])
        if env.get("PYTHONUNBUFFERED") == OPENCLAW_REDACTED:
            env["PYTHONUNBUFFERED"] = "1"
        entry = {**entry, "env": env}
    return _validate_common_entry(entry, require_project_root=True, env_required=True)
