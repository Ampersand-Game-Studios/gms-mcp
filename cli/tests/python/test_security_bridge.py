"""Security regressions for the local bridge and trusted live-reload configuration."""

from __future__ import annotations

import argparse
import contextlib
import asyncio
import json
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gms_helpers import live_reload, live_session
from gms_helpers.bounded_regex import RegexTimeoutError
from gms_helpers.bridge_installer import BridgeInstaller
from gms_helpers.bridge_server import BridgeServer
from gms_helpers.exceptions import ValidationError
from gms_mcp.server.tools import runner


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def server():
    bridge = BridgeServer()
    assert bridge.start()
    yield bridge
    bridge.stop()


def connect(server, token=None):
    client = socket.create_connection((server.host, server.port), timeout=2)
    hello = {"protocol": 2, "token": server.token if token is None else token}
    client.sendall(("HELLO:" + json.dumps(hello) + "\n").encode())
    return client


def test_installed_gml_is_gated_and_reinstallation_upgrades(tmp_path, user_config):
    (tmp_path / "game.yyp").write_text('{"name":"game","resources":[],"Folders":[]}')
    installer = BridgeInstaller(tmp_path)
    assert installer.install()["ok"]
    create_path = tmp_path / "objects/__mcp_bridge/Create_0.gml"
    create_path.write_text('network_connect_raw(socket, "127.0.0.1", 6502);')
    assert installer.install()["ok"]
    create = create_path.read_text()
    before_connect = create[: create.index("network_create_socket")]
    assert 'environment_get_variable("GMS_MCP_BRIDGE_PORT")' in before_connect
    assert 'environment_get_variable("GMS_MCP_BRIDGE_TOKEN")' in before_connect
    assert '_credential == ""' in before_connect and "65535" in before_connect
    assert 'ord("0")' in before_connect and 'ord("9")' in before_connect
    assert '"HELLO:" + json_stringify({protocol: 2, token: _credential})' in create
    assert create.index('"HELLO:"') < create.index('__mcp_log("[MCP]')
    assert "6502" not in create
    events = installer._create_object_asset()[2]
    gml = "\n".join(events.values()) + installer._create_script_asset()[2]
    assert not re.search(r"\b\w*exists\s*\(", gml)
    assert "1048576" in events["Other_68.gml"]
    assert "network_destroy(global.__mcp_socket)" in events["Other_68.gml"]
    assert installer.get_status()["warnings"]
    project = json.loads((tmp_path / "game.yyp").read_text())
    assert len(project["resources"]) == 2 and len(project["Folders"]) == 1


@pytest.mark.parametrize(
    "payload", [b"HELLO:{}\n", b"HELLO:[]\n", b'HELLO:{"token":"wrong"}\n', b"LOG:1|forged\n", b"RSP:cmd_1|forged\n"]
)
def test_unauthenticated_peers_do_not_displace_game(server, payload):
    with connect(server) as game:
        wait_for(lambda: server.is_connected)
        original = server._client_socket
        with socket.create_connection((server.host, server.port), timeout=2) as attacker:
            attacker.sendall(payload)
            assert attacker.recv(1) == b""
        assert server._client_socket is original
        assert server.hello == {"protocol": 2}
        game.sendall(b"LOG:1|real\n")
        wait_for(lambda: server.get_log_count() == 1)
        assert server.get_logs()[0]["message"] == "real"
    wait_for(lambda: not server.is_connected)
    assert server.hello is None


def test_silent_candidate_expires_without_authentication(server):
    server.HELLO_TIMEOUT = 0.05
    server.SOCKET_TIMEOUT = 0.02
    with socket.create_connection((server.host, server.port), timeout=2) as candidate:
        assert candidate.recv(1) == b""
    assert not server.is_connected


def test_session_ports_tokens_and_command_ids_are_unpredictable(server):
    assert server.port > 0 and len(server.token) >= 43
    other = BridgeServer()
    assert other.token != server.token
    with connect(server) as game:
        wait_for(lambda: server.is_connected)
        ids = [server.send_command_async("ping") for _ in range(2)]
        assert len(set(ids)) == 2 and all(len(value) >= 32 and not value.startswith("cmd_") for value in ids)
        assert "token" not in json.dumps(server.get_status())
        game.recv(4096)


def test_replaced_connection_threads_cannot_touch_new_game(server):
    first = connect(server)
    wait_for(lambda: server.is_connected)
    previous_receiver = server._receive_thread
    previous_socket = server._client_socket
    with connect(server) as second:
        wait_for(lambda: server._client_socket is not previous_socket)
        previous_receiver.join(timeout=1)
        assert not previous_receiver.is_alive()
        assert server.is_connected
        command_id = server.send_command_async("ping")
        assert f"CMD:{command_id}|ping\n".encode() in second.recv(4096)
        second.sendall(f"RSP:{command_id}|pong\n".encode())
        wait_for(lambda: server.get_command_result(command_id).success)
    first.close()


@pytest.mark.parametrize("terminated", [True, False])
def test_oversized_lines_disconnect(server, terminated):
    server.MAX_LINE_BYTES = 100
    with connect(server) as game:
        wait_for(lambda: server.is_connected)
        game.sendall(b"LOG:1|" + b"a" * 120 + (b"\n" if terminated else b""))
        wait_for(lambda: not server.is_connected)
        assert server.get_logs() == []
        assert server.hello is None


def test_byte_framing_preserves_split_utf8_and_enforces_log_byte_budget(server):
    server.MAX_LOG_BYTES = 20
    with connect(server) as game:
        wait_for(lambda: server.is_connected)
        game.sendall(b"LOG:1|\xc3")
        time.sleep(0.02)
        game.sendall(b"\xa9\n\x00LOG:2|second\n")
        wait_for(lambda: server.get_log_count() == 2)
        assert server.get_logs()[0]["message"] == "é"
        game.sendall(b"LOG:3|123456789012345\n")
        wait_for(lambda: server.get_logs()[-1]["timestamp"] == "3")
        assert server._log_bytes <= 20
        assert len(server.get_logs()) == 1
        server.clear_logs()
        assert server._log_bytes == 0


@pytest.fixture
def user_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_dir = home / ".gms-mcp"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return config_dir / "config.json"


@pytest.mark.parametrize("action", ["start", "stop", "status"])
def test_project_commands_are_ignored_with_migration_warning(tmp_path, user_config, monkeypatch, action):
    (tmp_path / ".gms-mcp.json").write_text(json.dumps({"live_reload": {action: ["/bin/sh", "-c", "exit 99"]}}))
    run = MagicMock(side_effect=AssertionError("untrusted command executed"))
    monkeypatch.setattr(live_reload.subprocess, "run", run)
    monkeypatch.setattr(live_reload.subprocess, "Popen", run)
    if action == "status":
        result = live_reload.status(tmp_path)
        assert not result["configured"]
        warning = result["warnings"][0]
    else:
        with pytest.raises(live_reload.LiveReloadError) as error:
            getattr(live_reload, action)(tmp_path)
        warning = str(error.value)
    assert "Ignored project" in warning and "~/.gms-mcp/config.json" in warning
    run.assert_not_called()


@pytest.mark.parametrize("action", ["start", "stop", "status"])
def test_only_user_commands_execute(tmp_path, user_config, action):
    user_config.write_text(
        json.dumps({"live_reload": {action: [sys.executable, "-I", "-c", "print('{\"trusted\":true}')"]}})
    )
    (tmp_path / ".gms-mcp.json").write_text(json.dumps({"live_reload": {action: ["/bin/sh", "-c", "exit 99"]}}))
    if action == "start":
        (tmp_path / ".gms_mcp").mkdir()
        (tmp_path / ".gms_mcp/live_reload.log").write_text("earlier run\n")
    result = getattr(live_reload, action)(tmp_path)
    assert result["ok"] and result["warnings"]
    if action == "status":
        assert result["status"] == {"trusted": True}
    if action == "start":
        assert (tmp_path / ".gms_mcp/live_reload.log").read_text().startswith("earlier run\n")


@pytest.mark.parametrize("value", ["/etc/passwd", "../outside.json", "C:\\secret.json", "nested/../../outside"])
def test_status_paths_must_be_project_relative(tmp_path, user_config, value):
    (tmp_path / ".gms-mcp.json").write_text(json.dumps({"live_reload": {"status_file": value}}))
    with pytest.raises(ValidationError, match="relative|traversal|escapes"):
        live_reload.status(tmp_path)


def test_status_symlink_cannot_escape_project(tmp_path, user_config):
    (tmp_path / "status.json").symlink_to(tmp_path.parent / "outside-secret.json")
    user_config.write_text('{"live_reload":{"status_file":"status.json"}}')
    with pytest.raises(ValidationError, match="escapes"):
        live_reload.status(tmp_path)


@pytest.mark.parametrize("parent_link", [False, True])
def test_live_reload_log_never_follows_symlinks(tmp_path, user_config, parent_link):
    user_config.write_text(json.dumps({"live_reload": {"start": [sys.executable, "-c", "print('trusted')"]}}))
    directory = tmp_path / ".gms_mcp"
    if parent_link:
        target = tmp_path / "other"
        target.mkdir()
        directory.symlink_to(target, target_is_directory=True)
    else:
        directory.mkdir()
        target = tmp_path / "valuable.log"
        target.write_text("keep")
        (directory / "live_reload.log").symlink_to(target)
    with pytest.raises(ValidationError, match="Unsafe|symlink"):
        live_reload.start(tmp_path)
    if not parent_link:
        assert target.read_text() == "keep"


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("background", [False, True])
def test_gm_run_passes_only_owned_bridge_credentials(tmp_path, monkeypatch, failure, background):
    registered = {}
    mcp = SimpleNamespace(tool=lambda: lambda function: registered.setdefault(function.__name__, function))
    runner.register(mcp, object)
    bridge = MagicMock(port=43210, token="private-session-token", is_connected=True, hello={})
    bridge.start.return_value = not failure
    monkeypatch.setattr(runner, "_resolve_repo_root", lambda _: tmp_path)
    monkeypatch.setattr(runner, "_resolve_project_directory", lambda _: tmp_path)
    monkeypatch.setattr(runner, "_ensure_cli_on_sys_path", lambda _: None)
    monkeypatch.setattr("gms_helpers.bridge_installer.is_bridge_installed", lambda _: True)
    factory = MagicMock(return_value=bridge)
    monkeypatch.setattr("gms_helpers.bridge_server.get_bridge_server", factory)
    captured = []

    async def execute(_callable, handler, args, *_rest):
        assert handler is runner.handle_runner_run
        captured.append(args.bridge_environment)
        if background:
            return True, "", "", {"ok": True}, None, 0
        return SimpleNamespace(as_dict=lambda: {"ok": True})

    monkeypatch.setattr(runner, "_run_direct_thread_shielded", execute)
    result = asyncio.run(registered["gm_run"](background=background, project_root=str(tmp_path)))
    assert result["bridge_enabled"] is (not failure)
    assert factory.call_args.kwargs["port"] == 0
    assert captured == (
        [{}] if failure else [{"GMS_MCP_BRIDGE_PORT": "43210", "GMS_MCP_BRIDGE_TOKEN": "private-session-token"}]
    )
    if failure:
        assert result["bridge_error"]
    assert "private-session-token" not in json.dumps(result)


def test_launch_worker_removes_inherited_credentials(monkeypatch):
    monkeypatch.setenv("GMS_MCP_BRIDGE_PORT", "6666")
    monkeypatch.setenv("GMS_MCP_BRIDGE_TOKEN", "untrusted")

    def launch(_args):
        return json.loads(
            subprocess.check_output(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    'import os,json;print(json.dumps({k:v for k,v in os.environ.items() if k.startswith("GMS_MCP_BRIDGE_")}))',
                ]
            )
        )

    monkeypatch.setattr("gms_helpers.commands.runner_commands.handle_runner_run", launch)
    assert runner.handle_runner_run(argparse.Namespace(bridge_environment={})) == {}
    approved = {"GMS_MCP_BRIDGE_PORT": "43210", "GMS_MCP_BRIDGE_TOKEN": "owned"}
    assert runner.handle_runner_run(argparse.Namespace(bridge_environment=approved)) == approved


@pytest.mark.parametrize("enabled", [True, False])
def test_live_session_launch_environment_is_explicit(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("GMS_MCP_BRIDGE_PORT", "6666")
    monkeypatch.setenv("GMS_MCP_BRIDGE_TOKEN", "untrusted")
    popen = MagicMock()
    monkeypatch.setattr(live_session.subprocess, "Popen", popen)
    credentials = {"GMS_MCP_BRIDGE_PORT": "43210", "GMS_MCP_BRIDGE_TOKEN": "owned"} if enabled else {}
    live_session._launch_game(tmp_path / "runner", tmp_path, tmp_path / "game.ios", tmp_path, credentials)
    environment = popen.call_args.kwargs["env"]
    assert {key: value for key, value in environment.items() if key.startswith("GMS_MCP_BRIDGE_")} == credentials


def test_game_log_uses_bounded_regex(tmp_path, monkeypatch):
    path = tmp_path / "debug.txt"
    path.write_text("ok\naaaa!\nerror one\n")
    monkeypatch.setattr(live_session, "_require_session", lambda _: SimpleNamespace(debug_log=path, alive=True))
    assert live_session.game_log(tmp_path, pattern="error")["lines"] == ["error one"]
    with pytest.raises(live_session.LiveSessionError, match="not a valid"):
        live_session.game_log(tmp_path, pattern="[")

    def timeout(*_args, **_kwargs):
        raise RegexTimeoutError("deadline exceeded")

    monkeypatch.setattr(live_session, "search_many", timeout)
    with pytest.raises(live_session.LiveSessionError, match="timed out"):
        live_session.game_log(tmp_path, pattern="(a+)+$")


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("external", [True, False])
def test_live_session_start_passes_credentials_only_after_bind(tmp_path, monkeypatch, enabled, external):
    from gms_helpers import snapshot_build

    root = tmp_path / "project"
    root.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    save = tmp_path / "save"
    save.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    process = SimpleNamespace(pid=4242, poll=lambda: None)
    bridge = SimpleNamespace(
        start=MagicMock(return_value=enabled),
        stop=lambda: None,
        port=43210 if enabled else 0,
        token="owned-token",
        is_connected=enabled,
        hello={} if enabled else None,
    )
    monkeypatch.setattr(live_session, "_SESSIONS", {})
    monkeypatch.setattr(live_session, "BridgeServer", lambda **_kwargs: bridge)
    monkeypatch.setattr(
        snapshot_build,
        "snapshot_compile",
        lambda *_args, **_kwargs: (
            {"ok": True, "label": "test"},
            SimpleNamespace(ok=True, game_archive=tmp_path / "game.zip"),
            work,
            None,
        ),
    )
    monkeypatch.setattr(snapshot_build, "runs_directory", lambda *_args: run_dir)
    monkeypatch.setattr(snapshot_build, "require_mac_runner", lambda _: tmp_path / "runner")
    monkeypatch.setattr(
        live_session,
        "prepare_mac_runtime",
        lambda *_args: SimpleNamespace(
            staging=staging, runner=tmp_path / "runner", save_dir=save, bundle_id="test.game"
        ),
    )
    monkeypatch.setattr(snapshot_build, "stage_game_archive", lambda *_args: (staging, staging / "game.ios"))
    monkeypatch.setattr(snapshot_build, "clear_stale_screenshots", lambda *_args: None)
    launched = MagicMock(return_value=(process, staging / "debug.txt"))
    monkeypatch.setattr(live_session, "_launch_game", launched)
    monkeypatch.setattr(live_session.threading, "Thread", MagicMock())
    manager = MagicMock()
    manager.return_value.create_session.return_value.run_id = "owned-run"
    monkeypatch.setattr(live_session, "RunSessionManager", manager)
    monkeypatch.setattr(
        "gms_helpers.runner.GameMakerRunner._snapshot_macos_processes",
        lambda _: {4242: SimpleNamespace(command="owned runner", started="owned birth")},
    )
    environment = {"GMS_MCP_BRIDGE_PORT": "43210", "GMS_MCP_BRIDGE_TOKEN": "owned-token"} if enabled else {}
    with live_session.bridge_launch_environment(environment) if external else contextlib.nullcontext():
        result = live_session._start(
            root, label="test", lock=MagicMock(), label_lock=MagicMock(), connect_timeout_seconds=0
        )
    assert result["bridge_enabled"] is enabled
    assert launched.call_args.args[-1] == environment
    assert bridge.start.call_count == (0 if external else 1)
    assert result["status"] == ("RUNNING" if enabled else "RUNNING_WITHOUT_BRIDGE")
    assert "owned-token" not in json.dumps(result)


@pytest.mark.parametrize("payload", [b"LOG:1|forged\n", b"HELLO:{}\n", b'HELLO:{"token":"wrong"}\n'])
def test_authentication_rejection_preserves_active_socket_without_network(monkeypatch, payload):
    server = BridgeServer()
    server._running = True
    server._connected = True
    active = server._client_socket = MagicMock()
    server.hello = {"protocol": 2}
    candidate = MagicMock()
    candidate.recv.return_value = payload
    listener = server._server_socket = MagicMock()
    listener.accept.side_effect = [(candidate, ("127.0.0.1", 1)), OSError("listener stopped")]
    server._server_loop()
    assert server._client_socket is active and server.is_connected
    assert server.hello == {"protocol": 2}
    candidate.close.assert_called_once()
    active.close.assert_not_called()


def test_byte_framing_and_caps_without_network():
    server = BridgeServer()
    server._running = server._connected = True
    server.MAX_LINE_BYTES = 20
    server.MAX_LOG_BYTES = 10
    client = server._client_socket = MagicMock()
    client.recv.side_effect = [b"LOG:1|\xc3", b"\xa9\n\x00LOG:2|12345\n", b"LOG:3|abcdef\n", b"x" * 21]
    server._receive_loop(client)
    assert [(entry["timestamp"], entry["message"]) for entry in server.get_logs()] == [("3", "abcdef")]
    assert server._log_bytes <= 10 and not server.is_connected and server.hello is None
    client.close.assert_called_once()


def test_stale_connection_loops_never_use_replacement_socket():
    import queue

    server = BridgeServer()
    server._running = server._connected = True
    current = server._client_socket = MagicMock()
    old = MagicMock()
    server._receive_loop(old)
    server._send_loop(old, queue.Queue())
    old.recv.assert_not_called()
    current.sendall.assert_not_called()
    current.close.assert_not_called()
    assert server.is_connected


def test_hello_authentication_and_deadline_without_network(monkeypatch):
    server = BridgeServer()
    server._running = True
    client = MagicMock()
    hello = ("HELLO:" + json.dumps({"token": server.token, "protocol": 2}) + "\nLOG:1|ready\n").encode()
    client.recv.side_effect = [hello[:9], hello[9:]]
    metadata, remaining = server._read_hello(client)
    assert metadata == {"protocol": 2} and remaining == b"LOG:1|ready\n"
    client.recv.side_effect = socket.timeout()
    monkeypatch.setattr("gms_helpers.bridge_server.time.monotonic", MagicMock(side_effect=[0, 0, 4]))
    with pytest.raises(ValueError, match="timed out"):
        server._read_hello(client)


def test_ephemeral_binding_token_rotation_and_random_ids_without_network(monkeypatch):
    listener = MagicMock()
    listener.getsockname.return_value = ("127.0.0.1", 43210)
    monkeypatch.setattr("gms_helpers.bridge_server.socket.socket", lambda *_args: listener)
    monkeypatch.setattr("gms_helpers.bridge_server.threading.Thread", MagicMock())
    server = BridgeServer()
    assert server.start()
    listener.bind.assert_called_with(("127.0.0.1", 0))
    assert server.port == 43210
    token = server.token
    server._connected = True
    ids = [server.send_command_async("ping") for _ in range(2)]
    assert len(set(ids)) == 2 and all(len(value) >= 32 and not value.startswith("cmd_") for value in ids)
    server.stop()
    assert server.start() and server.token != token
    listener.bind.assert_called_with(("127.0.0.1", 0))
    server.stop()


@pytest.mark.parametrize("action", ["status", "start", "stop"])
def test_mcp_live_reload_ignores_project_commands_and_preserves_warning(tmp_path, user_config, monkeypatch, action):
    from gms_mcp.server.tools import live_reload as tools

    (tmp_path / ".gms-mcp.json").write_text(
        json.dumps({"live_reload": {action: [sys.executable, "-c", "raise SystemExit(99)"]}})
    )
    registered = {}
    tools.register(
        SimpleNamespace(tool=lambda: lambda function: registered.setdefault(function.__name__, function)), object
    )
    monkeypatch.setattr(tools, "_resolve_project_directory", lambda _: tmp_path)
    execute = MagicMock(side_effect=AssertionError("Project command must never execute"))
    monkeypatch.setattr(live_reload.subprocess, "run", execute)
    monkeypatch.setattr(live_reload.subprocess, "Popen", execute)
    result = registered[f"gm_live_reload_{action}"](project_root=str(tmp_path))
    assert result["warnings"] and "~/.gms-mcp/config.json" in " ".join(result["warnings"])
    if action == "status":
        assert result["ok"] and not result["configured"]
    else:
        assert not result["ok"] and result["error_type"] == "LiveReloadError"
    execute.assert_not_called()


def test_mcp_live_reload_invalid_project_returns_structured_failure(monkeypatch):
    from gms_mcp.server.tools import live_reload as tools

    registered = {}
    tools.register(
        SimpleNamespace(tool=lambda: lambda function: registered.setdefault(function.__name__, function)), object
    )
    monkeypatch.setattr(tools, "_resolve_project_directory", MagicMock(side_effect=ValueError("Invalid project")))
    result = registered["gm_live_reload_start"](project_root="unavailable")
    assert not result["ok"] and result["warnings"] == [] and result["error_type"] == "ValueError"
