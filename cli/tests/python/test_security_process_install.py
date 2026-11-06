"""Regression coverage for process, runtime, installer and diagnostic trust boundaries."""

from __future__ import annotations

import argparse
import asyncio
import json
import ntpath
import os
import shlex
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from gms_helpers import agent_setup, runtime_manager
from gms_helpers.runner_support.artifacts import RunnerArtifactMixin
from gms_helpers.runner_support.security import private_directory
from gms_mcp import telemetry
from gms_mcp.client_registry import resolve_client_spec
from gms_mcp.install_support import client_configs, common, flow
from gms_mcp.server import debug, direct, log_paths, subprocess_runner


def _direct_secure_probe(_args):
    return {"ok": True, "json_file": json.__file__}


def _plant_shadow_modules(project):
    marker = project / "hijacked"
    payload = (
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\nraise RuntimeError('hijacked')\n"
    )
    (project / "json.py").write_text(payload)
    for package in ("gms_mcp", "gms_helpers"):
        (project / package).mkdir()
        (project / package / "__init__.py").write_text(payload)
    return marker


def test_cli_safe_path_and_approved_root(tmp_path, monkeypatch):
    marker = _plant_shadow_modules(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + ".")
    monkeypatch.delenv("GMS_MCP_PREFER_GMS_EXE", raising=False)
    captured = {}

    async def run(cmd, **kwargs):
        captured.update(kwargs)
        captured["cmd"] = cmd
        return subprocess.run(cmd, cwd=kwargs["cwd"], env=kwargs["env"], capture_output=True, text=True, timeout=15)

    with (
        mock.patch.object(subprocess_runner, "_resolve_project_directory", return_value=tmp_path),
        mock.patch.object(subprocess_runner, "_run_subprocess_async", side_effect=run),
        mock.patch.object(
            subprocess_runner, "_select_gms_executable", side_effect=AssertionError("unrequested lookup")
        ),
    ):
        result = asyncio.run(subprocess_runner._run_cli_async(["--version"], str(tmp_path), persist_logs=False))
    assert result.returncode == 0, result.stderr
    assert "-P" in captured["cmd"]
    assert captured["env"]["GMS_MCP_APPROVED_PROJECT_ROOT"] == str(tmp_path.resolve())
    assert captured["env"]["PYTHONSAFEPATH"] == "1"
    assert not marker.exists()


def test_direct_worker_ignores_project_shadow_packages(tmp_path):
    (tmp_path / "Game.yyp").write_text("{}")
    marker = _plant_shadow_modules(tmp_path)
    with mock.patch.object(direct, "_resolve_project_directory", return_value=tmp_path):
        result = direct._run_direct(_direct_secure_probe, argparse.Namespace(), str(tmp_path), timeout_seconds=15)
    assert result.ok, result.stderr
    assert not marker.exists()


def test_telemetry_spawn_uses_safe_package_path(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", ".")
    with (
        mock.patch.object(
            telemetry, "resolve_state", return_value=SimpleNamespace(ci=False, test_env=False, enabled=True)
        ),
        mock.patch.object(telemetry, "count_spool_events", return_value=1),
        mock.patch.object(telemetry.subprocess, "Popen") as popen,
    ):
        assert telemetry.maybe_start_background_flush(force=True)
    args, kwargs = popen.call_args
    assert "-P" in args[0]
    assert kwargs["env"]["PYTHONSAFEPATH"] == "1"
    assert kwargs["env"]["PYTHONPATH"] == str(Path(telemetry.__file__).resolve().parents[1])


def _runtime(tmp_path, name="2024.14.4.268"):
    root = tmp_path / "runtimes"
    runtime = root / f"runtime-{name}"
    igor = runtime / "bin/igor/linux/x64/Igor"
    igor.parent.mkdir(parents=True)
    igor.write_text("runtime")
    return root, runtime, igor


@pytest.mark.skipif(os.name == "nt", reason="POSIX trust checks")
@pytest.mark.parametrize("component", ["runtime", "binary", "parent"])
def test_discovery_rejects_writable_runtime_components(tmp_path, monkeypatch, component):
    root, runtime, igor = _runtime(tmp_path)
    {"runtime": runtime, "binary": igor, "parent": igor.parent}[component].chmod(0o777)
    monkeypatch.setenv("GMS_MCP_RUNTIME_ROOT", str(root))
    monkeypatch.setattr(runtime_manager.platform, "system", lambda: "Linux")
    manager = runtime_manager.RuntimeManager(tmp_path)
    assert manager.list_installed() == []
    assert "Skipped untrusted runtime" in manager.discovery_diagnostics[0]


@pytest.mark.skipif(os.name == "nt", reason="POSIX trust checks")
@pytest.mark.parametrize("ancestor", ["root", "cache_parent"])
def test_runtime_rejects_replaceable_cache_ancestors(tmp_path, ancestor):
    root, runtime, igor = _runtime(tmp_path)
    (root if ancestor == "root" else tmp_path).chmod(0o777)
    assert runtime_manager.runtime_trust_issue(runtime, igor)


@pytest.mark.skipif(os.name == "nt", reason="POSIX trust checks")
def test_shared_root_requires_sticky_protection_and_trusted_owner(tmp_path):
    root, runtime, igor = _runtime(tmp_path)
    root.chmod(0o1777)
    assert runtime_manager.runtime_trust_issue(runtime, igor) is None
    original = Path.lstat

    def foreign_owner(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == runtime:
            return SimpleNamespace(st_mode=info.st_mode, st_uid=os.getuid() + 1000)
        return info

    with mock.patch.object(Path, "lstat", foreign_owner):
        assert runtime_manager.runtime_trust_issue(runtime, igor)


@pytest.mark.skipif(os.name == "nt", reason="POSIX trust checks")
def test_sticky_runtime_component_is_still_untrusted(tmp_path):
    _, runtime, igor = _runtime(tmp_path)
    igor.parent.chmod(0o1777)
    assert runtime_manager.runtime_trust_issue(runtime, igor)


@pytest.mark.parametrize("component", ["runtime", "binary", "parent", "root"])
def test_runtime_symlinks_are_untrusted(tmp_path, component):
    root, runtime, igor = _runtime(tmp_path)
    target = {"runtime": runtime, "binary": igor, "parent": igor.parent, "root": root}[component]
    moved = target.with_name(target.name + "-real")
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=moved.is_dir())
    assert runtime_manager.runtime_trust_issue(runtime, igor)


def test_discovery_only_scans_known_cache_families(tmp_path):
    for name in ("GameMakerStudio2", "GameMakerStudio2-LTS2026", "GameMakerStudio2-malicious"):
        (tmp_path / name / "Cache/runtimes").mkdir(parents=True)
    roots = runtime_manager._runtime_roots(tmp_path)
    assert {path.parents[1].name for path in roots} == {"GameMakerStudio2", "GameMakerStudio2-LTS2026"}


def test_exact_recorded_version_precedes_newest(tmp_path):
    (tmp_path / "game.yyp").write_text('{"MetaData":{"IDEVersion":"2024.14.4.268"}}')
    manager = runtime_manager.RuntimeManager(tmp_path)
    exact = runtime_manager.RuntimeInfo("2024.14.4.268", "exact", "igor", True, "stable")
    newer = runtime_manager.RuntimeInfo("2024.99.0.1", "newer", "igor", True, "stable")
    with mock.patch.object(manager, "list_installed", return_value=[newer, exact]):
        assert manager.select() == exact


@pytest.mark.skipif(os.name == "nt", reason="POSIX private directory checks")
def test_private_build_directory_refuses_unsafe_existing_paths(tmp_path):
    private = private_directory(tmp_path / "build")
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    private.chmod(0o777)
    with pytest.raises(OSError):
        private_directory(private)
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises(OSError):
        private_directory(link)
    private.chmod(0o700)
    with mock.patch("gms_helpers.runner_support.security.os.getuid", return_value=private.stat().st_uid + 1):
        with pytest.raises(OSError):
            private_directory(private)


def test_log_directory_chmod_failure_is_not_ignored(tmp_path):
    with mock.patch.object(Path, "chmod", side_effect=PermissionError("denied")):
        with pytest.raises(PermissionError):
            log_paths._make_private_directory(tmp_path / "logs")


@pytest.mark.parametrize("target", ["Windows", "Linux"])
@pytest.mark.parametrize("returncode,fresh,expected", [(1, True, False), (0, False, False), (0, True, True)])
def test_launch_requires_success_and_current_build_artifact(tmp_path, target, returncode, fresh, expected):
    from gms_helpers.runner import GameMakerRunner

    project = tmp_path / "project"
    project.mkdir()
    (project / "Game.yyp").write_text("{}")
    runner = GameMakerRunner(project)
    root = tmp_path / "private"
    artifact = root / "GameMakerStudio2/Game" / ("Game.exe" if target == "Windows" else "Game")
    artifact.parent.mkdir(parents=True)
    artifact.write_text("old")
    process = mock.Mock(returncode=returncode)

    def build(_cmd):
        if fresh:
            artifact.write_text("new output")
        return process

    with (
        mock.patch("gms_helpers.runner_support.execution.GameMakerMachineLock"),
        mock.patch.object(runner, "_system_temp_root", return_value=root),
        mock.patch.object(runner, "_build_platform_action_command", return_value=["Igor"]),
        mock.patch.object(runner, "_run_igor_command", side_effect=build),
        mock.patch.object(runner, "_wait_for_igor_idle"),
        mock.patch.object(runner, "_stream_igor_output", return_value=[]),
        mock.patch.object(runner, "_start_game_process") as launch,
        mock.patch.object(runner._session_manager, "create_session"),
    ):
        runner._run_project_ide_temp_approach(target, background=True)
    assert launch.called is expected


def test_artifact_freshness_rejects_symlinks(tmp_path):
    artifact = tmp_path / "Game"
    artifact.write_text("old")
    baseline = RunnerArtifactMixin._artifact_fingerprints(tmp_path)
    assert not RunnerArtifactMixin._artifact_is_fresh(artifact, baseline)
    artifact.write_text("fresh")
    assert RunnerArtifactMixin._artifact_is_fresh(artifact, baseline)
    link = tmp_path / "link"
    link.symlink_to(artifact)
    assert not RunnerArtifactMixin._artifact_is_fresh(link, baseline)


def test_windows_system_helpers_are_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    with mock.patch.object(
        subprocess_runner.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="")
    ) as run:
        subprocess_runner._resolve_gms_candidates_windows()
    assert run.call_args.args[0] == [ntpath.join("C:/Windows", "System32", "where.exe"), "$PATH:gms"]
    assert ntpath.isabs(subprocess_runner._windows_system_executable("taskkill.exe"))


def test_path_lookup_excludes_cwd_and_relative_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", str(tmp_path), "relative", str(tmp_path / "bin")]))
    assert subprocess_runner._safe_lookup_path() == str(tmp_path / "bin")


@pytest.mark.parametrize(
    "client", ["cursor", "claude-code", "vscode", "windsurf", "openclaw", "antigravity", "generic"]
)
def test_json_writes_merge_and_backup(tmp_path, client):
    spec = resolve_client_spec(client)
    path = spec.resolve_path(workspace_root=tmp_path, scope="workspace", override=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = {"mcpServers": {"other": {"token": "secret"}}, "theme": "dark"}
    path.write_text(json.dumps(original))
    common._write_json(path, {"mcpServers": {"gms": {"command": "server"}}}, dry_run=False, workspace_root=tmp_path)
    merged = json.loads(path.read_text())
    assert merged["theme"] == "dark"
    assert merged["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert merged["mcpServers"]["gms"]["command"] == "server"
    assert json.loads(next(path.parent.glob(path.name + ".bak.*")).read_text()) == original


@pytest.mark.parametrize(
    "header", ['[projects."/tmp/game"]', "[tui]", "[sandbox_workspace_write]", "[mcp_servers.other]"]
)
def test_codex_merge_preserves_unrelated_tables_with_backup(tmp_path, header):
    path = tmp_path / ".codex/config.toml"
    path.parent.mkdir()
    original = '[mcp_servers.gms]\ncommand = "old"\n[mcp_servers.gms.env]\nOLD = "1"\n' + header + '\nvalue = "keep"\n'
    path.write_text(original)
    client_configs._generate_codex_config(
        workspace_root=tmp_path,
        output_path=path,
        server_name="gms",
        command="new",
        args_prefix=[],
        gm_project_root=tmp_path,
        dry_run=False,
    )
    parsed = tomllib.loads(path.read_text())
    assert parsed["mcp_servers"]["gms"]["command"] == "new"
    assert "OLD" not in parsed["mcp_servers"]["gms"]["env"]
    assert 'value = "keep"' in path.read_text()
    assert next(path.parent.glob("config.toml.bak.*")).read_text() == original


def test_config_destinations_refuse_links_and_workspace_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".cursor").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        common._write_json(workspace / ".cursor/mcp.json", {}, dry_run=False, workspace_root=workspace)
    with pytest.raises(ValueError, match="inside"):
        common._write_json(outside / "escape.json", {}, dry_run=False, workspace_root=workspace)
    destination = outside / "mcp.json"
    destination.write_text('{"keep":true}')
    link = workspace / "mcp.json"
    link.symlink_to(destination)
    with pytest.raises(ValueError):
        client_configs._write_json_atomic_with_backup(output_path=link, payload={})
    assert json.loads(destination.read_text()) == {"keep": True}


def test_workspace_configs_omit_host_specific_executable(monkeypatch, tmp_path):
    monkeypatch.setenv("GMS_MCP_GMS_PATH", "/host/secret/gms")
    configs = [
        common._make_server_config(
            client="cursor", server_name="gms", command="gms-mcp", args=[], gm_project_root_rel_posix=None
        ),
        client_configs._make_claude_code_mcp_config(server_name="gms", command="gms-mcp", args=[]),
    ]
    for config in configs:
        assert "GMS_MCP_GMS_PATH" not in config["mcpServers"]["gms"]["env"]
    assert "GMS_MCP_GMS_PATH" not in client_configs._build_codex_env(tmp_path, tmp_path)


def test_python_module_config_uses_safe_path():
    _command, args = common._resolve_launcher(mode="python-module", python_command=sys.executable)
    assert args == ["-P", "-m", "gms_mcp.bootstrap_server"]


def test_dry_run_does_not_write_or_create_backups(tmp_path):
    common._write_json(tmp_path / "new/config.json", {}, dry_run=True, workspace_root=tmp_path)
    client_configs._generate_codex_config(
        workspace_root=tmp_path,
        output_path=tmp_path / ".codex/config.toml",
        server_name="gms",
        command="server",
        args_prefix=[],
        gm_project_root=tmp_path,
        dry_run=True,
    )
    assert list(tmp_path.iterdir()) == []


def test_antigravity_preview_omits_other_servers(tmp_path, capsys):
    path = tmp_path / "antigravity.json"
    path.write_text(
        json.dumps({"mcpServers": {"other": {"command": "SENSITIVE_OTHER_SERVER", "env": {"TOKEN": "other-secret"}}}})
    )
    result = flow._run_setup_for_client(
        client="antigravity",
        scope="global",
        workspace_root=tmp_path,
        gm_project_root=tmp_path,
        server_name="gms",
        command="server",
        args_prefix=["--token", "target-secret"],
        dry_run=True,
        safe_profile=False,
        config_path_override=str(path),
    )
    assert result == 0
    preview = capsys.readouterr().out
    for secret in ("other-secret", "SENSITIVE_OTHER_SERVER", "target-secret"):
        assert secret not in preview
    assert "REDACTED" in preview


def test_alias_is_printed_as_quoted_data_and_never_executed(tmp_path, capsys):
    root = tmp_path / "with ' quotes $(touch owned)"
    root.mkdir()
    (root / "gms.py").touch()
    with (
        mock.patch.object(agent_setup, "__file__", str(root / "agent_setup.py")),
        mock.patch.object(os, "system", side_effect=AssertionError("shell execution")),
    ):
        assert agent_setup.setup_bash_alias()
    line = next(line.strip() for line in capsys.readouterr().out.splitlines() if line.strip().startswith("alias gms="))
    alias = shlex.split(line)[1].partition("=")[2]
    assert shlex.split(alias) == [
        "env",
        f"PYTHONPATH={root.parent}",
        agent_setup._preferred_python_command(),
        "-P",
        "-m",
        "gms_helpers.gms",
    ]
    assert not (tmp_path / "owned").exists()


def test_debug_logging_requires_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("GMS_MCP_DEBUG_LOG", raising=False)
    monkeypatch.delenv("GMS_MCP_READ_ONLY", raising=False)
    path = tmp_path / "debug.log"
    with mock.patch.object(debug, "_get_debug_log_path", return_value=path) as lookup:
        debug._dbg("test", "test", "test", {})
        lookup.assert_not_called()
        monkeypatch.setenv("GMS_MCP_DEBUG_LOG", "1")
        debug._dbg("test", "test", "test", {"password": "never-log"})
    assert "never-log" not in path.read_text()
    assert "REDACTED" in path.read_text()


def test_child_logs_redact_secrets_and_host_paths(tmp_path):
    log = tmp_path / "child.log"
    script = "import sys; print('token=private-token'); print('Authorization: Bearer private-bearer', file=sys.stderr); print('/Users/private/file')"
    with mock.patch.object(subprocess_runner, "_new_log_path", return_value=log):
        result = asyncio.run(
            subprocess_runner._run_subprocess_async(
                [sys.executable, "-P", "-c", script],
                cwd=tmp_path,
                env=os.environ.copy(),
                timeout_seconds=10,
                heartbeat_seconds=0,
                tool_name="security",
            )
        )
    assert result.ok
    text = log.read_text()
    assert "private-token" not in text
    assert "private-bearer" not in text
    assert "/Users/private" not in text
    assert "private-token" in result.stdout


def test_runner_work_base_is_private_and_per_user(tmp_path, monkeypatch):
    from gms_helpers.runner import GameMakerRunner

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "Game.yyp").write_text("{}")
    monkeypatch.setattr(Path, "home", lambda: home)
    runner = GameMakerRunner(project)
    base = runner._system_temp_root()
    assert base == home / ".gms-mcp/build"
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    runner.runtime_path = tmp_path / "runtime"
    assert runner._igor_work_root().is_relative_to(base)


def test_legacy_shell_wrapper_treats_paths_as_data(tmp_path, monkeypatch):
    from gms_helpers import install

    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    package = tmp_path / "with ' quotes $(touch owned)" / "gms_helpers"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "gms.py").write_text("import sys\nprint(sys.argv[1:])\n")
    monkeypatch.setattr(install, "__file__", str(package / "install.py"))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(install.platform, "system", lambda: "Linux")
    assert install.install_gms_command()
    result = subprocess.run(
        ["/bin/sh", str(home / ".local/bin/gms"), "literal argument"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "literal argument" in result.stdout
    assert not (tmp_path / "owned").exists()


def test_workspace_setup_rejects_escaping_override(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = flow._run_setup_for_client(
        client="cursor",
        scope="workspace",
        workspace_root=workspace,
        gm_project_root=workspace,
        server_name="gms",
        command="server",
        args_prefix=[],
        dry_run=False,
        safe_profile=False,
        config_path_override="../escape.json",
    )
    assert result == 2
    assert not (tmp_path / "escape.json").exists()


def test_bootstrap_default_does_not_collect_host_diagnostics(monkeypatch):
    from gms_mcp import bootstrap_server

    monkeypatch.delenv("GMS_MCP_DEBUG_LOG", raising=False)
    server = SimpleNamespace(main=lambda: 0)
    with (
        mock.patch.dict(sys.modules, {"gms_mcp.gamemaker_mcp_server": server}),
        mock.patch.object(bootstrap_server, "_dbg") as log,
        mock.patch.object(bootstrap_server, "queue_event", return_value=False),
        mock.patch.object(bootstrap_server, "resolve_state"),
    ):
        assert bootstrap_server.main() == 0
    assert not any("cwd" in call.args[3] or "argv" in call.args[3] for call in log.call_args_list)


def test_doctor_reports_skipped_untrusted_runtimes(tmp_path):
    from gms_mcp.doctor_checks import _build_runtime_selection_check

    manager = SimpleNamespace(
        list_installed=lambda: [],
        select=lambda: None,
        get_pinned=lambda: None,
        verify=lambda: {"ok": False},
        discovery_diagnostics=["Skipped untrusted runtime runtime-9: untrusted owner"],
    )
    with mock.patch("gms_helpers.runtime_manager.RuntimeManager", return_value=manager):
        check = _build_runtime_selection_check(tmp_path)
    assert check.status == "error"
    assert check.details == manager.discovery_diagnostics


def test_python_launcher_uses_absolute_path_without_cwd_lookup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    planted = tmp_path / "python3"
    planted.write_text("#!/bin/sh\nexit 99\n")
    planted.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(tmp_path), str(Path(sys.executable).parent)]))
    resolved = common._resolve_python_command("python3")
    assert Path(resolved).is_absolute()
    assert Path(resolved) != planted


def test_app_setup_dry_run_does_not_install_skills(tmp_path):
    with mock.patch.object(flow, "_maybe_install_openclaw_skills", return_value=0) as skills:
        result = flow._run_canonical_flow(
            client="openclaw",
            scope="workspace",
            action="app-setup",
            workspace_root=tmp_path,
            gm_project_root=tmp_path,
            server_name="gms",
            command="server",
            args_prefix=[],
            dry_run=True,
            safe_profile=False,
            config_path_override=None,
            openclaw_install_skills=True,
            openclaw_skills_project=True,
        )
    assert result == 0
    assert skills.call_args.kwargs["enable"] is False
    assert list(tmp_path.iterdir()) == []
