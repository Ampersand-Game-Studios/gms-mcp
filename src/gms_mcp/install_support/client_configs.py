from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from .common import (
    _FORWARDED_ENV_VARS,
    _apply_safe_profile_env,
    _make_antigravity_server_config,
    _make_server_config,
    _parse_json_object_or_raise,
    _redact_config_value,
    _relpath_posix_or_none,
    _validate_common_entry,
    _write_json,
)

try:
    import tomllib as _toml_parser
except ModuleNotFoundError:
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
        resolved_root = str(gm_project_root if gm_project_root is not None else workspace_root)
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
        raise ValueError(f"Malformed JSON in {source_label}: `mcpServers.{server_name}.env` must be an object.")


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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

