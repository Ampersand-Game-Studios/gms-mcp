#!/usr/bin/env python3
"""Generate MCP client configuration files for the GameMaker MCP server."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import time
from pathlib import Path

from .client_registry import CLIENT_ACTIONS, CLIENT_SCOPES, all_client_names, resolve_client_spec
from .install_support.client_configs import (
    _build_claude_plugin_manifest,
    _build_codex_env,
    _build_codex_env_args,
    _collect_antigravity_check_state,
    _collect_codex_check_state,
    _generate_antigravity_config,
    _generate_claude_code_plugin,
    _generate_codex_config,
    _generate_cursor_config,
    _generate_example_configs,
    _make_antigravity_server_config,
    _make_claude_code_mcp_config,
    _make_codex_mcp_config,
    _make_codex_toml_value,
    _make_backup_path,
    _make_claude_code_plugin_manifest,
    _parse_toml_or_raise,
    _print_antigravity_app_setup_summary,
    _print_antigravity_check,
    _print_antigravity_check_json,
    _print_codex_app_setup_summary,
    _print_codex_check,
    _print_codex_check_json,
    _read_antigravity_server_entry,
    _read_codex_server_entry,
    _render_antigravity_merged_config,
    _render_codex_merged_config,
    _toml_parser,
    _upsert_codex_server_config,
    _validate_antigravity_sections,
    _validate_codex_sections,
    _write_json_atomic_with_backup,
)
from .install_support.common import (
    ConfigState,
    ReadinessResult,
    _apply_safe_profile_env,
    _as_posix_path,
    _collect_standard_check_state,
    _default_antigravity_config_path,
    _default_python_command,
    _detect_gm_project_roots,
    _find_yyp_dirs,
    _looks_secret_flag,
    _looks_secret_key,
    _make_server_config,
    _normalize_config_key,
    _parse_json_object_or_raise,
    _print_standard_app_setup_summary,
    _print_standard_check,
    _print_standard_check_json,
    _redact_args_list,
    _redact_config_value,
    _relpath_posix_or_none,
    _resolve_antigravity_config_path,
    _resolve_json_entry_root,
    _resolve_launcher,
    _resolve_python_command,
    _select_gm_project_root,
    _validate_common_entry,
    _workspace_folder_var,
    _write_json,
)
from .install_support.flow import (
    _collect_client_check_state,
    _install_action_label,
    _maybe_install_openclaw_skills,
    _run_canonical_flow,
    _run_setup_for_client,
    _scope_not_applicable_reason,
    _should_prompt_after_init,
)
from .install_support.naming import (
    HAS_NAMING_CONFIG as _HAS_NAMING_CONFIG,
    PROJECT_CONFIG_FILE,
    create_default_config_file,
    get_factory_defaults,
)
from .install_support.project import _setup_project_config
from .star_cta import HELP_EPILOG, maybe_print_star_cta
from .telemetry import (
    classify_error_family,
    emit_consent_changed,
    maybe_start_background_flush,
    prompt_for_consent,
    queue_event,
    resolve_state,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate MCP client configs for the GameMaker MCP server.",
        epilog=HELP_EPILOG,
    )
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
        "--no-star-ask",
        action="store_true",
        help="Suppress the post-setup GitHub star note for this run.",
    )
    parser.add_argument(
        "--telemetry",
        choices=["inherit", "on", "off"],
        default="inherit",
        help="Telemetry override for this run (default: inherit).",
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
    parser.add_argument(
        "--cursor-global", action="store_true", help="Write Cursor *global* config to ~/.cursor/mcp.json."
    )
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
    parser.add_argument(
        "--vscode", action="store_true", help="Write a VS Code example config to mcp-configs/vscode.mcp.json."
    )
    parser.add_argument(
        "--windsurf", action="store_true", help="Write a Windsurf example config to mcp-configs/windsurf.mcp.json."
    )
    parser.add_argument(
        "--antigravity",
        action="store_true",
        help="Write an Antigravity example config to mcp-configs/antigravity.mcp.json.",
    )
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
    parser.add_argument(
        "--openclaw", action="store_true", help="Write an OpenClaw example config to mcp-configs/openclaw.mcp.json."
    )
    parser.add_argument(
        "--all", action="store_true", help="Generate Cursor config + all example configs (excludes Claude Code global)."
    )

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
    start_time = time.monotonic()

    def _finish(exit_code: int, *, only_checks: bool = False, error_family: str | None = None) -> int:
        event_type, action = _install_action_label(args, only_checks=only_checks)
        duration_ms = int((time.monotonic() - start_time) * 1000)
        state = resolve_state(getattr(args, "telemetry", "inherit"))
        queued = queue_event(
            state=state,
            surface="init",
            event_type=event_type,
            action=action,
            tool_name=action,
            tool_family="init",
            result="ok" if exit_code == 0 else "error",
            error_family=error_family if exit_code != 0 else None,
            duration_ms=duration_ms,
            execution_mode="inline",
        )
        if queued:
            maybe_start_background_flush()
        if _should_prompt_after_init(args=args, only_checks=only_checks, exit_code=exit_code):
            enabled = prompt_for_consent()
            if enabled:
                emit_consent_changed("enable")
        return exit_code

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
        return _finish(
            _run_canonical_flow(
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
            ),
            only_checks=args.action in {"check", "check-json"},
        )

    requested_any = (
        args.cursor
        or args.cursor_global
        or args.claude_code
        or args.claude_code_global
        or args.codex
        or args.codex_global
        or args.codex_dry_run_only
        or args.codex_check
        or args.codex_check_json
        or args.codex_app_setup
        or args.vscode
        or args.windsurf
        or args.antigravity
        or args.antigravity_setup
        or args.antigravity_check
        or args.antigravity_check_json
        or args.antigravity_app_setup
        or args.openclaw
        or args.all
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
        args.codex_check or args.codex_check_json or args.antigravity_check or args.antigravity_check_json
    ) and not (
        args.cursor
        or args.cursor_global
        or args.claude_code
        or args.claude_code_global
        or args.codex
        or args.codex_global
        or args.codex_dry_run_only
        or args.codex_app_setup
        or args.antigravity_app_setup
        or args.vscode
        or args.windsurf
        or args.antigravity
        or args.antigravity_setup
        or args.openclaw
        or args.all
    )
    if only_checks:
        codex_exit = _run_requested_codex_checks()
        antigravity_exit = _run_requested_antigravity_checks()
        if codex_exit != 0:
            return _finish(codex_exit, only_checks=True)
        return _finish(antigravity_exit, only_checks=True)

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
            return _finish(2, error_family=classify_error_family(exc))
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
            return _finish(2, error_family=classify_error_family(exc))
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
            return _finish(2, error_family=classify_error_family(exc))
        print(f"[INFO] Codex app setup global preview target: {codex_global_path}")
        print("[INFO] Codex app setup global final merged payload (preview):")
        print(codex_global_preview.rstrip())

    if args.antigravity_setup:
        try:
            antigravity_path, antigravity_payload, antigravity_merged, antigravity_backup = (
                _generate_antigravity_config(
                    workspace_root=workspace_root,
                    output_path=antigravity_config_path,
                    server_name=args.server_name,
                    command=command,
                    args_prefix=args_prefix,
                    gm_project_root=gm_project_root,
                    safe_profile=antigravity_safe_profile,
                    dry_run=dry_run,
                )
            )
        except ValueError as exc:
            print(f"[ERROR] Could not generate Antigravity config: {exc}")
            return _finish(2, error_family=classify_error_family(exc))
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
                print("[INFO] Applied conservative safety profile: GMS_MCP_ENABLE_DIRECT=0, GMS_MCP_REQUIRE_DRY_RUN=1.")

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
            return _finish(0)
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
            plugin_dir = Path.home() / ".claude" / "plugins" / "gms-mcp" if args.claude_code_global else workspace_root
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
            return _finish(check_exit)
        antigravity_check_exit = _run_requested_antigravity_checks()
        if antigravity_check_exit != 0:
            return _finish(antigravity_check_exit)
        if args.codex_app_setup:
            summary_code = _print_codex_app_setup_summary(workspace_root=workspace_root, server_name=args.server_name)
            if summary_code != 0:
                return _finish(summary_code)
        if args.antigravity_app_setup:
            return _finish(
                _print_antigravity_app_setup_summary(
                    config_path=antigravity_config_path,
                    server_name=args.server_name,
                )
            )
        return _finish(0)

    gm_note = str(gm_project_root) if gm_project_root else "(not selected; defaults to ${workspaceFolder})"
    print("[OK] Wrote MCP config(s):")
    for p in written:
        print(f"  - {p}")
    if gm_candidates and len(gm_candidates) > 1 and gm_project_root is None:
        print("[WARN] Multiple .yyp projects detected; GM_PROJECT_ROOT defaulted to ${workspaceFolder}.")
        print("       Re-run with --gm-project-root <path> (or run interactively to choose).")
    print(f"[INFO] Selected GameMaker project root: {gm_note}")
    print("[INFO] If this is wrong, edit GM_PROJECT_ROOT in the generated config.")
    print("[INFO] Manual local diagnostics: gms-mcp doctor")

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
        return _finish(check_exit)
    antigravity_check_exit = _run_requested_antigravity_checks()
    if antigravity_check_exit != 0:
        return _finish(antigravity_check_exit)
    if args.codex_app_setup:
        summary_code = _print_codex_app_setup_summary(workspace_root=workspace_root, server_name=args.server_name)
        if summary_code != 0:
            return _finish(summary_code)
    if args.antigravity_app_setup:
        summary_code = _print_antigravity_app_setup_summary(
            config_path=antigravity_config_path,
            server_name=args.server_name,
        )
        if summary_code != 0:
            return _finish(summary_code)

    maybe_print_star_cta(no_star_ask=bool(args.no_star_ask))
    return _finish(0)


if __name__ == "__main__":
    raise SystemExit(main())
