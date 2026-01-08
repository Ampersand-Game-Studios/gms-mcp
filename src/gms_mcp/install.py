#!/usr/bin/env python3
"""
Generate MCP client configuration files for the GameMaker MCP server.

Multi-project model:
- Install the tool once (recommended: `pipx install gms-mcp`)
- Run this per-project/workspace to generate that workspace's MCP config (Cursor primary)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

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
) -> dict:
    workspace_var = _workspace_folder_var(client)
    env: dict[str, str] = {}

    if gm_project_root_rel_posix:
        env["GM_PROJECT_ROOT"] = f"{workspace_var}/{gm_project_root_rel_posix}".replace("//", "/")
    else:
        env["GM_PROJECT_ROOT"] = workspace_var

    # Polish: Auto-detect and write relevant environment variables from current process
    # This helps when running gms-mcp-init from a shell where these are already set.
    for env_var in ["GMS_MCP_GMS_PATH", "GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "GMS_MCP_ENABLE_DIRECT"]:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val

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


def _resolve_launcher(*, mode: str, python_command: str) -> tuple[str, list[str]]:
    """
    Return (command, args_prefix) for launching the server.
    """
    if mode == "command":
        return "gms-mcp", []
    if mode == "python-module":
        return python_command, ["-m", "gms_mcp.bootstrap_server"]
    raise ValueError(f"Unknown mode: {mode}")


def _generate_cursor_config(
    *,
    workspace_root: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    gm_project_root: Path | None,
    out_path: Path,
    dry_run: bool,
) -> Path:
    gm_rel_posix = _relpath_posix_or_none(gm_project_root, workspace_root)
    config = _make_server_config(
        client="cursor",
        server_name=server_name,
        command=command,
        args=args_prefix,
        gm_project_root_rel_posix=gm_rel_posix,
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
) -> list[Path]:
    gm_rel_posix = _relpath_posix_or_none(gm_project_root, workspace_root)

    out_paths: list[Path] = []
    out_dir = workspace_root / "mcp-configs"
    for client in clients:
        config = _make_server_config(
            client=client,
            server_name=server_name,
            command=command,
            args=args_prefix,
            gm_project_root_rel_posix=gm_rel_posix,
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
    for env_var in ["GMS_MCP_GMS_PATH", "GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "GMS_MCP_ENABLE_DIRECT"]:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val

    return {
        server_name: {
            "command": command,
            "args": args,
            "env": env,
        }
    }


def _generate_claude_code_plugin(
    *,
    plugin_dir: Path,
    server_name: str,
    command: str,
    args_prefix: list[str],
    dry_run: bool,
) -> list[Path]:
    """
    Generate a Claude Code plugin with MCP server configuration.

    Creates:
      plugin_dir/
      ├── .claude-plugin/
      │   └── plugin.json
      └── .mcp.json
    """
    written: list[Path] = []

    # Create plugin manifest
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_path = manifest_dir / "plugin.json"
    manifest = _make_claude_code_plugin_manifest()
    _write_json(manifest_path, manifest, dry_run=dry_run)
    written.append(manifest_path)

    # Create MCP server config
    mcp_config_path = plugin_dir / ".mcp.json"
    mcp_config = _make_claude_code_mcp_config(
        server_name=server_name,
        command=command,
        args=args_prefix,
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
        default="python",
        help="Python command to use when --mode=python-module (default: python).",
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

    parser.add_argument("--cursor", action="store_true", help="Write Cursor workspace config to .cursor/mcp.json.")
    parser.add_argument("--cursor-global", action="store_true", help="Write Cursor *global* config to ~/.cursor/mcp.json.")
    parser.add_argument("--claude-code", action="store_true", help="Write Claude Code plugin to current workspace (.claude-plugin/).")
    parser.add_argument(
        "--claude-code-global",
        action="store_true",
        help="Install Claude Code plugin globally to ~/.claude/plugins/gms-mcp/. "
             "Works across all projects using ${CLAUDE_PROJECT_DIR}.",
    )
    parser.add_argument("--vscode", action="store_true", help="Write a VS Code example config to mcp-configs/vscode.mcp.json.")
    parser.add_argument("--windsurf", action="store_true", help="Write a Windsurf example config to mcp-configs/windsurf.mcp.json.")
    parser.add_argument("--antigravity", action="store_true", help="Write an Antigravity example config to mcp-configs/antigravity.mcp.json.")
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

    requested_any = (
        args.cursor or args.cursor_global or
        args.claude_code or args.claude_code_global or
        args.vscode or args.windsurf or args.antigravity or args.all
    )
    if not requested_any:
        args.cursor = True

    if args.all:
        args.cursor = True
        args.vscode = True
        args.windsurf = True
        args.antigravity = True
        # Note: --all does NOT include claude-code-global since it's a global install

    command, args_prefix = _resolve_launcher(mode=args.mode, python_command=args.python)

    if args.mode == "command":
        if shutil.which(command) is None:
            print(
                "[WARN] 'gms-mcp' not found on PATH. Config will still be written, but the client may fail to start it.\n"
                "       Recommended: `pipx install gms-mcp` (or use --mode=python-module)."
            )

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
            )
        )

    if args.claude_code:
        # Workspace-local Claude Code plugin
        written.extend(
            _generate_claude_code_plugin(
                plugin_dir=workspace_root,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                dry_run=dry_run,
            )
        )

    if args.claude_code_global:
        # Global Claude Code plugin - uses ${CLAUDE_PROJECT_DIR} for dynamic project detection
        claude_plugins_dir = Path.home() / ".claude" / "plugins" / "gms-mcp"
        written.extend(
            _generate_claude_code_plugin(
                plugin_dir=claude_plugins_dir,
                server_name=args.server_name,
                command=command,
                args_prefix=args_prefix,
                dry_run=dry_run,
            )
        )
        if not dry_run:
            print(f"[INFO] Claude Code plugin installed to: {claude_plugins_dir}")
            print("       The plugin will be available after restarting Claude Code.")

    example_clients: list[str] = []
    if args.vscode:
        example_clients.append("vscode")
    if args.windsurf:
        example_clients.append("windsurf")
    if args.antigravity:
        example_clients.append("antigravity")
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
            )
        )

    if dry_run:
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
            print(json.dumps(_make_claude_code_plugin_manifest(), indent=2))
            print(f"\n[DRY-RUN] {plugin_dir / '.mcp.json'}:")
            mcp_config = _make_claude_code_mcp_config(
                server_name=args.server_name,
                command=command,
                args=args_prefix,
            )
            print(json.dumps(mcp_config, indent=2))
            print()
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
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
