from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from ..client_registry import CLIENT_ACTIONS, CLIENT_SCOPES, resolve_client_spec
from ..telemetry import should_prompt_for_consent
from .client_configs import (
    _build_claude_plugin_manifest,
    _generate_antigravity_config,
    _generate_claude_code_plugin,
    _generate_codex_config,
    _generate_cursor_config,
    _make_claude_code_mcp_config,
    _read_codex_server_entry,
    _render_codex_privacy_safe_preview,
)
from .common import (
    ConfigState,
    ReadinessResult,
    _collect_standard_check_state,
    _make_antigravity_server_config,
    _make_server_config,
    _normalize_toolsets,
    _print_standard_app_setup_summary,
    _print_standard_check,
    _print_standard_check_json,
    _privacy_safe_path_label,
    _redact_config_value,
    _redact_private_paths,
    _relpath_posix_or_none,
    _validate_common_entry,
    _write_json,
)


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

        require_project_root = not (spec.key == "codex" and scope == "global")
        return _collect_standard_check_state(
            client=spec.key,
            scope=scope,
            config_path=target,
            server_name=server_name,
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
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
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
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
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
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
        )
        print(
            f"[{'DRY-RUN' if dry_run else 'INFO'}] Cursor config {'would be written to' if dry_run else 'written to'}: {_privacy_safe_path_label(target)}"
        )
        if dry_run:
            print(json.dumps(_redact_private_paths(_redact_config_value(payload)), indent=2, sort_keys=True))
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
                onboarding_profile=onboarding_profile,
                toolsets=toolsets,
            )
        except (RuntimeError, ValueError) as exc:
            print(f"[ERROR] Could not generate Codex config: {exc}")
            return 2
        if dry_run:
            print(
                f"[DRY-RUN] Codex config would be {'merged into' if scope == 'global' else 'written to'}: "
                f"{_privacy_safe_path_label(target)}"
            )
            print(
                _render_codex_privacy_safe_preview(
                    merged_text=payload,
                    server_name=server_name,
                    source_label="<generated>",
                )
            )
            print("[DRY-RUN] Final merged target entry (unrelated configuration omitted):")
            print(
                _render_codex_privacy_safe_preview(
                    merged_text=merged,
                    server_name=server_name,
                    source_label="<generated>",
                )
            )
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
                    onboarding_profile=onboarding_profile,
                    toolsets=toolsets,
                )
            except ValueError as exc:
                print(f"[ERROR] Could not generate Antigravity config: {exc}")
                return 2
            if dry_run:
                print(f"[DRY-RUN] Antigravity config would be merged into: {_privacy_safe_path_label(target)}")
                print(json.dumps(_redact_private_paths(_redact_config_value(payload)), indent=2, sort_keys=True))
                print(json.dumps(_redact_private_paths(_redact_config_value(merged)), indent=2, sort_keys=True))
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
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
        )
        _write_json(target, payload, dry_run=dry_run)
        print(
            f"[{'DRY-RUN' if dry_run else 'INFO'}] Antigravity workspace config {'would be written to' if dry_run else 'written to'}: {_privacy_safe_path_label(target)}"
        )
        return 0

    if spec.key == "claude-code":
        plugin_dir = target.parent if target.suffix == ".json" else target
        manifest_payload = _build_claude_plugin_manifest()
        mcp_payload = _make_claude_code_mcp_config(
            server_name=server_name,
            command=command,
            args=args_prefix,
            safe_profile=safe_profile,
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
        )
        _generate_claude_code_plugin(
            plugin_dir=plugin_dir,
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
            dry_run=dry_run,
            include_bundle_assets=False,
            safe_profile=safe_profile,
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
        )
        print(
            f"[{'DRY-RUN' if dry_run else 'INFO'}] Claude Code config {'would be written to' if dry_run else 'written to'}: "
            f"{_privacy_safe_path_label(plugin_dir / '.mcp.json')}"
        )
        if dry_run:
            print(json.dumps(_redact_private_paths(manifest_payload), indent=2, sort_keys=True))
            print(json.dumps(_redact_private_paths(_redact_config_value(mcp_payload)), indent=2, sort_keys=True))
        return 0

    if spec.key == "claude-desktop":
        manifest_payload = _build_claude_plugin_manifest()
        mcp_payload = _make_claude_code_mcp_config(
            server_name=server_name,
            command=command,
            args=args_prefix,
            safe_profile=safe_profile,
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
        )
        _generate_claude_code_plugin(
            plugin_dir=target,
            server_name=server_name,
            command=command,
            args_prefix=args_prefix,
            dry_run=dry_run,
            include_bundle_assets=True,
            safe_profile=safe_profile,
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
        )
        print(
            f"[{'DRY-RUN' if dry_run else 'INFO'}] Claude Desktop plugin {'would be synced to' if dry_run else 'synced to'}: {_privacy_safe_path_label(target)}"
        )
        if dry_run:
            print(json.dumps(_redact_private_paths(manifest_payload), indent=2, sort_keys=True))
            print(json.dumps(_redact_private_paths(_redact_config_value(mcp_payload)), indent=2, sort_keys=True))
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
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
    )
    _write_json(target, payload, dry_run=dry_run)
    print(
        f"[{'DRY-RUN' if dry_run else 'INFO'}] {spec.key} config {'would be written to' if dry_run else 'written to'}: {_privacy_safe_path_label(target)}"
    )
    if dry_run:
        print(json.dumps(_redact_private_paths(_redact_config_value(payload)), indent=2, sort_keys=True))
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
    onboarding_profile: str | None = None,
    toolsets: str | None = None,
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
    if toolsets is not None:
        try:
            toolsets = _normalize_toolsets(toolsets)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            return 2
    if onboarding_profile == "safe" and toolsets not in (None, "core"):
        print("[ERROR] The safe profile only supports the read-only core tool surface.")
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
            onboarding_profile=onboarding_profile,
            toolsets=toolsets,
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
        onboarding_profile=onboarding_profile,
        toolsets=toolsets,
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


def _install_action_label(args: argparse.Namespace, *, only_checks: bool = False) -> tuple[str, str]:
    if args.client:
        if args.client == "codex" and args.action in {"check", "check-json"}:
            return "init.codex_check", f"{args.client}.{args.action.replace('-', '_')}"
        return "init.run", f"{args.client}.{args.action.replace('-', '_')}"

    if only_checks and args.codex_check_json:
        return "init.codex_check", "codex.check_json"
    if only_checks and args.codex_check:
        return "init.codex_check", "codex.check"
    if args.codex_app_setup:
        return "init.run", "codex.app_setup"
    if args.antigravity_app_setup:
        return "init.run", "antigravity.app_setup"
    if args.codex_dry_run_only:
        return "init.run", "codex.dry_run_only"
    if args.codex:
        return "init.run", "codex.setup"
    if args.codex_global:
        return "init.run", "codex.global_setup"
    if args.cursor_global:
        return "init.run", "cursor.global_setup"
    if args.cursor:
        return "init.run", "cursor.setup"
    if args.claude_code_global:
        return "init.run", "claude_code.global_setup"
    if args.claude_code:
        return "init.run", "claude_code.setup"
    if args.antigravity_setup:
        return "init.run", "antigravity.setup"
    if args.antigravity_check_json:
        return "init.run", "antigravity.check_json"
    if args.antigravity_check:
        return "init.run", "antigravity.check"
    if args.openclaw:
        return "init.run", "openclaw.setup"
    if args.vscode:
        return "init.run", "vscode.setup"
    if args.windsurf:
        return "init.run", "windsurf.setup"
    if args.all:
        return "init.run", "all"
    return "init.run", "setup"


def _should_prompt_after_init(*, args: argparse.Namespace, only_checks: bool, exit_code: int) -> bool:
    if exit_code != 0:
        return False
    if bool(args.non_interactive) or bool(args.dry_run) or only_checks:
        return False
    return should_prompt_for_consent(cli_override=getattr(args, "telemetry", "inherit"), allow_prompt=True)
