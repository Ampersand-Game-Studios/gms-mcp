"""Regression coverage for process, runtime, installer and diagnostic trust boundaries."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
            telemetry,
            "resolve_state",
            return_value=SimpleNamespace(ci=False, test_env=False, enabled=True, source="config"),
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX trust checks")
def test_default_cache_is_trusted_like_the_ide_and_warns_when_shared(tmp_path, monkeypatch):
    root, runtime, igor = _runtime(tmp_path)
    root.chmod(0o777)
    monkeypatch.delenv("GMS_MCP_RUNTIME_ROOT", raising=False)
    monkeypatch.setattr(runtime_manager.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime_manager, "default_runtime_roots", lambda system=None: [root.absolute()])
    assert runtime_manager.runtime_trust_issue(runtime, igor) is None
    (root / "runtime-2024.14.4.265/bin/igor/linux/x64").mkdir(parents=True)
    (root / "runtime-2024.14.4.265/bin/igor/linux/x64/Igor").write_text("runtime")
    manager = runtime_manager.RuntimeManager(tmp_path)
    assert {runtime.version for runtime in manager.list_installed()} == {"2024.14.4.268", "2024.14.4.265"}
    assert len(manager.exposure_warnings) == 1
    assert str(root) in manager.exposure_warnings[0]
    assert manager.discovery_diagnostics == manager.exposure_warnings


@pytest.mark.skipif(os.name == "nt", reason="POSIX trust checks")
def test_explicit_root_stays_strict_even_when_it_is_the_default_cache(tmp_path, monkeypatch):
    root, runtime, igor = _runtime(tmp_path)
    root.chmod(0o777)
    monkeypatch.setattr(runtime_manager, "default_runtime_roots", lambda system=None: [root.absolute()])
    monkeypatch.setenv("GMS_MCP_RUNTIME_ROOT", str(root))
    assert not runtime_manager.is_default_cache_runtime(runtime)
    assert runtime_manager.runtime_trust_issue(runtime, igor)


@pytest.mark.parametrize("component", ["runtime", "binary"])
def test_default_cache_still_rejects_symlinked_components(tmp_path, monkeypatch, component):
    root, runtime, igor = _runtime(tmp_path)
    monkeypatch.delenv("GMS_MCP_RUNTIME_ROOT", raising=False)
    monkeypatch.setattr(runtime_manager, "default_runtime_roots", lambda system=None: [root.absolute()])
    target = {"runtime": runtime, "binary": igor}[component]
    moved = target.with_name(target.name + "-real")
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=moved.is_dir())
    assert runtime_manager.runtime_trust_issue(runtime, igor) == "runtime component is a symlink or reparse point"


def test_doctor_warns_about_a_shared_runtime_cache(tmp_path):
    from gms_mcp.doctor_checks import _build_runtime_selection_check

    active = runtime_manager.RuntimeInfo("2024.14.4.268", "path", "igor", True, "stable")
    warning = "Other accounts can modify GameMaker's runtime cache at /shared"
    manager = SimpleNamespace(
        list_installed=lambda: [active],
        select=lambda: active,
        get_pinned=lambda: None,
        verify=lambda: {"ok": True},
        discovery_diagnostics=[warning],
        exposure_warnings=[warning],
    )
    with mock.patch("gms_helpers.runtime_manager.RuntimeManager", return_value=manager):
        check = _build_runtime_selection_check(tmp_path)
    assert check.status == "warning"
    assert warning in check.details
    assert "GMS_MCP_RUNTIME_ROOT" in check.recommendation[0]


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
    project_key = hashlib.sha256(str((project / "Game.yyp").resolve()).encode()).hexdigest()[:16]
    artifact = root / "GameMakerStudio2" / project_key / "Game" / ("Game.exe" if target == "Windows" else "Game")
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
    # Windows timestamps can stay equal for back-to-back writes; a real build takes longer.
    info = artifact.stat()
    os.utime(artifact, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
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


def test_trusted_command_lookup_applies_windows_pathext(tmp_path, monkeypatch):
    candidate = tmp_path / "bin" / "gms-mcp"
    executable = str(candidate) + ".EXE"
    tried = []

    def which(name):
        tried.append(name)
        return name if name == executable else None

    monkeypatch.setattr(common.shutil, "which", which)
    monkeypatch.setenv("PATHEXT", os.pathsep.join([".COM", ".EXE"]))
    # Patch the platform only around the lookup: pathlib picks its flavour from os.name.
    monkeypatch.setattr(common.os, "name", "nt")
    try:
        found = common._which_path(candidate)
    finally:
        monkeypatch.undo()
    assert found == executable
    assert tried == [str(candidate) + ".COM", executable]


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
    assert not list(path.parent.glob(path.name + ".bak.*"))
    (backup,) = common._config_backups(path)
    assert json.loads(backup.read_text()) == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


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
    # User-added env survives; installer-owned keys are refreshed.
    assert parsed["mcp_servers"]["gms"]["env"]["OLD"] == "1"
    assert parsed["mcp_servers"]["gms"]["env"]["GM_PROJECT_ROOT"] == "."
    assert 'value = "keep"' in path.read_text()
    (backup,) = common._config_backups(path)
    assert backup.read_text() == original


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
    if os.name != "nt":
        assert stat.S_IMODE(base.stat().st_mode) == 0o700
    else:
        from gms_helpers.windows_security import windows_path_trust_issue

        assert windows_path_trust_issue(base, private=True) is None
    runner.runtime_path = tmp_path / "runtime"
    assert runner._igor_work_root().is_relative_to(base)


@pytest.mark.skipif(os.name == "nt", reason="The legacy wrapper is a POSIX shell script")
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


_FAKE_OPENCLAW = """#!/bin/sh
# Stand-in for the OpenClaw CLI: `mcp set` stores the JSON, `mcp show --json` returns it with env redacted.
store="$OPENCLAW_FAKE_STORE"
if [ "$1 $2" = "mcp set" ]; then printf '%s' "$4" > "$store"; exit 0; fi
if [ "$1 $2" = "mcp show" ]; then
  [ -f "$store" ] || { echo "unknown server $3" >&2; exit 1; }
  sed -E 's/("(PYTHONUNBUFFERED|GM_PROJECT_ROOT)": *)"[^"]*"/\\1"__OPENCLAW_REDACTED__"/g' "$store"; exit 0
fi
exit 2
"""


def _openclaw_global_flow(tmp_path, action, *, dry_run=False):
    return flow._run_canonical_flow(
        client="openclaw",
        scope="global",
        action=action,
        workspace_root=tmp_path / "workspace",
        gm_project_root=tmp_path / "workspace",
        server_name="gms",
        command="server",
        args_prefix=["--stdio"],
        dry_run=dry_run,
        safe_profile=False,
        config_path_override=None,
        openclaw_install_skills=False,
        openclaw_skills_project=False,
    )


def test_openclaw_global_setup_saves_through_openclaw_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "workspace").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "openclaw"
    fake.write_text(_FAKE_OPENCLAW)
    fake.chmod(0o755)
    store = tmp_path / "saved.json"
    monkeypatch.setenv("OPENCLAW_FAKE_STORE", str(store))
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]))

    _openclaw_global_flow(tmp_path, "check")
    assert "Ready for openclaw: no" in capsys.readouterr().out
    assert _openclaw_global_flow(tmp_path, "setup") == 0

    saved = json.loads(store.read_text())
    workspace = str((tmp_path / "workspace").resolve())
    assert saved["command"] == "server"
    assert saved["args"] == ["--stdio"]
    assert saved["cwd"] == workspace
    assert saved["env"]["GM_PROJECT_ROOT"] == workspace
    assert saved["env"]["PYTHONUNBUFFERED"] == "1"
    assert not (tmp_path / "home" / ".openclaw").exists()

    capsys.readouterr()
    assert _openclaw_global_flow(tmp_path, "check-json") == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True


def test_openclaw_global_setup_without_cli_fails_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert _openclaw_global_flow(tmp_path, "setup") == 2
    assert "`openclaw`" in capsys.readouterr().out
    assert not (tmp_path / "home" / ".openclaw").exists()


def _yyp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "game").mkdir(parents=True)
    (workspace / "game" / "game.yyp").write_text("{}")
    return workspace


def test_codex_dry_run_only_never_prompts_or_queues_telemetry(tmp_path, monkeypatch):
    from gms_mcp import install

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    workspace = _yyp_workspace(tmp_path)
    with (
        mock.patch.object(install, "queue_event") as queue,
        mock.patch.object(install, "maybe_start_background_flush") as flush,
        mock.patch.object(install, "prompt_for_consent") as prompt,
        mock.patch.object(flow, "should_prompt_for_consent", return_value=True),
    ):
        assert install.main(["--workspace-root", str(workspace), "--codex-dry-run-only"]) == 0
        assert install.main(["--workspace-root", str(workspace), "--dry-run", "--cursor"]) == 0
    queue.assert_not_called()
    flush.assert_not_called()
    prompt.assert_not_called()
    assert not (tmp_path / "home" / ".gms-mcp").exists()
    assert not (workspace / ".codex").exists()


@pytest.mark.parametrize("name", ["GMS Local", "gms.local", "gms]x", ""])
def test_server_name_must_be_a_bare_toml_key(tmp_path, name):
    from gms_mcp import install

    with pytest.raises(SystemExit) as exited:
        install.main(["--workspace-root", str(tmp_path), "--server-name", name, "--dry-run", "--codex"])
    assert exited.value.code == 2
    with pytest.raises(ValueError, match="Invalid server name"):
        client_configs._make_codex_mcp_config(
            server_name=name, command="gms-mcp", args=[], gm_project_root=None, workspace_root=tmp_path
        )


def test_config_replace_refuses_concurrent_external_edit(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text('{"mcpServers": {}}')

    def render(existing):
        path.write_text('{"mcpServers": {"edited": {}}, "changed": true}')
        return '{"mcpServers": {"gms": {}}}\n'

    with pytest.raises(RuntimeError, match="changed while"):
        common._update_config_text(output_path=path, render=render, dry_run=False)
    assert json.loads(path.read_text())["changed"] is True


def test_config_lock_serializes_installers(tmp_path):
    path = tmp_path / "mcp.json"
    with common._config_lock(path):
        with pytest.raises(RuntimeError, match="Another gms-mcp installer"):
            with common._config_lock(path, timeout=0.1):
                pass


def test_python_module_launcher_probes_interpreter(tmp_path):
    broken = tmp_path / "python-without-gms"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)
    with pytest.raises(ValueError, match="cannot import gms_mcp"):
        common._resolve_launcher(mode="python-module", python_command=str(broken))
    assert common._default_python_command() == sys.executable


def test_python_module_default_does_not_warn(tmp_path, capsys):
    from gms_mcp import install

    workspace = _yyp_workspace(tmp_path)
    assert install.main(["--workspace-root", str(workspace), "--mode", "python-module", "--dry-run"]) == 0
    assert "not found; using" not in capsys.readouterr().out


def test_command_mode_writes_absolute_launcher_when_on_path(tmp_path, monkeypatch):
    binary = tmp_path / "bin" / "gms-mcp"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary.parent))
    command, args = common._resolve_launcher(mode="command", python_command="")
    assert command == str(binary)
    assert args == []


def test_explicit_project_root_is_resolved_and_validated(tmp_path):
    workspace = _yyp_workspace(tmp_path)
    selected, _ = common._select_gm_project_root(
        workspace_root=workspace, requested_root="game/game.yyp", non_interactive=True
    )
    assert selected == (workspace / "game").resolve()
    (workspace / "empty").mkdir()
    with pytest.raises(ValueError, match="containing a .yyp"):
        common._select_gm_project_root(workspace_root=workspace, requested_root="empty", non_interactive=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.yyp").write_text("{}")
    with pytest.raises(ValueError, match="inside the workspace"):
        common._select_gm_project_root(workspace_root=workspace, requested_root=str(outside), non_interactive=True)
    link = tmp_path / "workspace-link"
    link.symlink_to(workspace, target_is_directory=True)
    selected, _ = common._select_gm_project_root(
        workspace_root=workspace.resolve(), requested_root=str(link / "game"), non_interactive=True
    )
    assert common._relpath_posix_or_none(selected, link) == "game"


def test_existing_entry_keeps_user_settings_and_reports_removed_keys(tmp_path, capsys):
    path = tmp_path / "mcp.json"
    existing = {
        "mcpServers": {
            "gms": {
                "command": "old",
                "args": ["--old"],
                "disabled": False,
                "env": {"GMS_MCP_GMS_PATH": "/opt/gms", "GM_PROJECT_ROOT": "/pinned", "PYTHONUNBUFFERED": "1"},
            }
        }
    }
    path.write_text(json.dumps(existing))
    common._write_json(
        path, {"mcpServers": {"gms": {"command": "new", "args": [], "env": {"PYTHONUNBUFFERED": "1"}}}}, dry_run=False
    )
    entry = json.loads(path.read_text())["mcpServers"]["gms"]
    assert entry == {
        "command": "new",
        "args": [],
        "disabled": False,
        "env": {"GMS_MCP_GMS_PATH": "/opt/gms", "PYTHONUNBUFFERED": "1"},
    }
    assert "env.GM_PROJECT_ROOT" in capsys.readouterr().out


def test_codex_merge_keeps_user_keys_and_comments(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[mcp_servers.gms]\n# keep me\ncommand = "old"\nstartup_timeout_sec = 30\n'
        '[mcp_servers.gms.env]\nGMS_MCP_GMS_PATH = "/opt/gms"\nGM_PROJECT_ROOT = "/pinned"\n'
    )
    client_configs._generate_codex_config(
        workspace_root=tmp_path,
        output_path=path,
        server_name="gms",
        command="new",
        args_prefix=[],
        gm_project_root=None,
        dry_run=False,
        include_project_root=False,
    )
    text = path.read_text()
    entry = tomllib.loads(text)["mcp_servers"]["gms"]
    assert entry["command"] == "new"
    assert entry["startup_timeout_sec"] == 30
    assert entry["env"]["GMS_MCP_GMS_PATH"] == "/opt/gms"
    assert "GM_PROJECT_ROOT" not in entry["env"]
    assert "# keep me" in text


def test_backups_live_outside_workspace_with_bounded_rotation(tmp_path, private_installer_state):
    path = tmp_path / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text("{}")
    for index in range(common._BACKUPS_KEPT_PER_CONFIG + 3):
        common._write_json(path, {"mcpServers": {"gms": {"command": str(index)}}}, dry_run=False)
    backups = common._config_backups(path)
    assert len(backups) == common._BACKUPS_KEPT_PER_CONFIG
    assert all(backup.is_relative_to(private_installer_state) for backup in backups)
    assert sorted(item.name for item in path.parent.iterdir()) == ["mcp.json"]


def test_replaced_config_keeps_file_mode(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text("{}")
    path.chmod(0o640)
    common._write_json(path, {"mcpServers": {"gms": {"command": "gms-mcp"}}}, dry_run=False)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_dry_run_rejects_malformed_existing_config(tmp_path, capsys):
    target = tmp_path / ".cursor" / "mcp.json"
    target.parent.mkdir()
    target.write_text('{"mcpServers": {}, // comment\n}')
    result = flow._run_setup_for_client(
        client="cursor",
        scope="workspace",
        workspace_root=tmp_path,
        gm_project_root=None,
        server_name="gms",
        command="gms-mcp",
        args_prefix=[],
        dry_run=True,
        safe_profile=False,
        config_path_override=None,
    )
    assert result == 2
    assert "Malformed JSON" in capsys.readouterr().out


def test_claude_desktop_install_validates_before_copying_assets(tmp_path, capsys):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / ".mcp.json").write_text("not json")
    result = flow._run_setup_for_client(
        client="claude-desktop",
        scope="global",
        workspace_root=tmp_path,
        gm_project_root=None,
        server_name="gms",
        command="gms-mcp",
        args_prefix=[],
        dry_run=False,
        safe_profile=False,
        config_path_override=str(plugin_dir),
    )
    assert result == 2
    assert sorted(item.name for item in plugin_dir.iterdir()) == [".mcp.json"]


def test_bundle_copy_refuses_symlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "real.txt").write_text("x")
    (source / "link.txt").symlink_to(source / "real.txt")
    with pytest.raises(ValueError, match="symlink"):
        client_configs._copy_tree(source=source, destination=tmp_path / "dest", dry_run=False, written=[])


def test_foreign_plugin_manifest_requires_force(tmp_path):
    manifest = tmp_path / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text('{"name": "my-own-plugin"}')
    kwargs = dict(plugin_dir=tmp_path, server_name="gms", command="gms-mcp", args_prefix=[], dry_run=False)
    with pytest.raises(ValueError, match="--force"):
        client_configs._generate_claude_code_plugin(**kwargs)
    assert json.loads(manifest.read_text()) == {"name": "my-own-plugin"}
    client_configs._generate_claude_code_plugin(**kwargs, force=True)
    assert json.loads(manifest.read_text())["name"] == "gms-mcp"


def test_client_global_paths_and_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    assert resolve_client_spec("codex").global_path() == tmp_path / "codex-home" / "config.toml"
    monkeypatch.delenv("CODEX_HOME")
    assert resolve_client_spec("codex").global_path() == tmp_path / ".codex" / "config.toml"
    assert resolve_client_spec("windsurf").global_path() == tmp_path / ".codeium" / "windsurf" / "mcp_config.json"
    assert resolve_client_spec("vscode").global_path().parts[-2:] == ("User", "mcp.json")
    vscode = common._make_server_config(
        client="vscode", server_name="gms", command="gms-mcp", args=[], gm_project_root_rel_posix=None
    )
    assert list(vscode) == ["servers"]
    assert vscode["servers"]["gms"]["type"] == "stdio"
