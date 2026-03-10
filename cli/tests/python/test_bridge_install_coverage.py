#!/usr/bin/env python3
"""Coverage tests for bridge_server and gms_mcp.install."""

from __future__ import annotations

import io
import builtins
import json
import os
import queue
import socket
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.bridge_server import BridgeServer
from gms_mcp import install as install_module


def _capture_output(func, *args, **kwargs):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


@contextmanager
def temporary_home(home_dir: Path):
    keys = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
    previous = {key: os.environ.get(key) for key in keys}
    home_str = str(home_dir)
    os.environ["HOME"] = home_str
    os.environ["USERPROFILE"] = home_str
    drive, tail = os.path.splitdrive(home_str)
    if drive:
        os.environ["HOMEDRIVE"] = drive
    if tail:
        os.environ["HOMEPATH"] = tail
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestBridgeServerCoverage(unittest.TestCase):
    def test_start_and_cleanup_failure_paths(self):
        server = BridgeServer(port=6540)
        fake_socket = MagicMock()
        fake_socket.bind.side_effect = OSError("bind fail")
        with patch("socket.socket", return_value=fake_socket):
            result, output = _capture_output(server.start)
        self.assertFalse(result)
        self.assertIn("bind fail", output)

        server._server_socket = MagicMock()
        server._server_socket.close.side_effect = OSError("close fail")
        server._cleanup_server()
        self.assertIsNone(server._server_socket)

    def test_disconnect_receive_send_and_process_message_branches(self):
        server = BridgeServer(port=6541)
        server._connected = True
        callback_called = []
        server._on_disconnect = lambda: callback_called.append("disconnect")
        pending = SimpleNamespace(completed_at=None, error=None)
        server._pending_commands = {"cmd_1": pending}
        server._client_socket = MagicMock()
        server._client_socket.close.side_effect = OSError("close fail")
        server._disconnect_client()
        self.assertEqual(pending.error, "Game disconnected")
        self.assertEqual(callback_called, ["disconnect"])

        server._running = True
        server._connected = True
        recv_socket = MagicMock()
        recv_socket.recv.side_effect = [socket.timeout(), b"", OSError("recv fail")]
        server._client_socket = recv_socket
        _capture_output(server._receive_loop)

        server._running = True
        server._connected = True
        server._client_socket = None
        _capture_output(server._receive_loop)

        server._running = True
        server._connected = True
        server._command_queue = MagicMock()
        server._command_queue.get.side_effect = [queue.Empty(), StopIteration()]
        _result, output = _capture_output(server._send_loop)
        self.assertIn("Send loop error", output)

        server._running = True
        server._connected = True
        server._command_queue = MagicMock()
        server._command_queue.get.side_effect = [("cmd_2", "ping"), StopIteration()]
        server._pending_commands = {"cmd_2": SimpleNamespace(error=None, completed_at=None)}
        server._client_socket = MagicMock()
        server._client_socket.sendall.side_effect = OSError("send fail")
        _result, output = _capture_output(server._send_loop)
        self.assertIn("Send error", output)
        self.assertEqual(server._pending_commands["cmd_2"].error, "send fail")

        server.MAX_LOG_BUFFER = 1
        server._on_log = lambda _entry: (_ for _ in ()).throw(RuntimeError("log callback fail"))
        server._process_message("LOG:hello world")
        self.assertEqual(len(server._log_buffer), 1)
        server._process_message("RSP:cmd_3")
        self.assertEqual(server.get_logs(count=10)[0]["message"], "hello world")

    def test_command_timeout_disconnect_and_async_branches(self):
        server = BridgeServer(port=6542)
        server._connected = True
        with patch("time.sleep", side_effect=lambda _seconds: None), patch(
            "time.time",
            side_effect=[0.0, 0.0, 10.0, 10.0],
        ):
            result = server.send_command("ping", timeout=0.1)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Command timed out")

        server = BridgeServer(port=6543)
        server._connected = True
        time_values = iter([0.0, 0.0, 0.01, 0.02, 0.03])

        def disconnecting_sleep(_seconds):
            server._connected = False

        with patch("time.sleep", side_effect=disconnecting_sleep), patch(
            "time.time",
            side_effect=lambda: next(time_values),
        ):
            result = server.send_command("ping", timeout=0.5)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Game disconnected")

        server = BridgeServer(port=6544)
        server._connected = True
        cmd_id = server.send_command_async("ping")
        self.assertEqual(cmd_id, "cmd_1")
        self.assertIsNotNone(server.get_command_result(cmd_id))

        server._running = True
        server._server_socket = None
        server._server_loop()


class TestInstallCoverage(unittest.TestCase):
    def test_project_root_selection_and_common_helpers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "game.yyp").touch()
            nested = workspace / "nested"
            nested.mkdir()
            selected, candidates = install_module._select_gm_project_root(
                workspace_root=workspace,
                requested_root="nested/..",
                non_interactive=True,
            )
            self.assertEqual(selected.resolve(), workspace.resolve())
            self.assertEqual(candidates, [])

        entry = install_module._resolve_json_entry_root(
            {"mcpServers": {"gms": {"command": "cmd"}}, "plain": {}},
            server_name="gms",
            allow_plain_top_level=False,
        )
        self.assertEqual(entry["command"], "cmd")
        self.assertIsNone(
            install_module._resolve_json_entry_root({"gms": {"command": "cmd"}}, server_name="gms", allow_plain_top_level=False)
        )
        self.assertEqual(
            install_module._resolve_json_entry_root({"gms": {"command": "cmd"}}, server_name="gms", allow_plain_top_level=True)["command"],
            "cmd",
        )

        env = {}
        install_module._apply_safe_profile_env(env, enabled=True)
        self.assertEqual(env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"], "600")
        self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "0")
        self.assertEqual(env["GMS_MCP_REQUIRE_DRY_RUN"], "1")

        env = {"GMS_MCP_DEFAULT_TIMEOUT_SECONDS": "9999"}
        install_module._apply_safe_profile_env(env, enabled=True)
        self.assertEqual(env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"], "600")

        env = {"GMS_MCP_DEFAULT_TIMEOUT_SECONDS": "bad"}
        install_module._apply_safe_profile_env(env, enabled=True)
        self.assertEqual(env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"], "600")

        result = install_module._validate_common_entry({"command": "", "args": "bad", "env": {}}, require_project_root=True)
        self.assertFalse(result.ready)
        self.assertGreater(len(result.problems), 1)

        state = install_module._collect_standard_check_state(
            client="cursor",
            scope="workspace",
            config_path=Path("/tmp/missing.json"),
            server_name="gms",
            not_applicable_reason="not applicable",
        )
        self.assertTrue(state.readiness.not_applicable)

        print_result, output = _capture_output(install_module._print_standard_check, state)
        self.assertEqual(print_result, 0)
        self.assertIn("not found", output)
        _print_json, json_output = _capture_output(install_module._print_standard_check_json, state)
        self.assertIn('"not_applicable": true', json_output.lower())
        _summary, summary_output = _capture_output(install_module._print_standard_app_setup_summary, state)
        self.assertIn("readiness summary", summary_output)

        with self.assertRaises(ValueError):
            install_module._resolve_launcher(mode="unknown", python_command="python")

    def test_antigravity_and_codex_helper_branches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "config.json"
            output_path.write_text(json.dumps({"mcpServers": {"old": {"command": "old"}}}), encoding="utf-8")
            merged = install_module._render_antigravity_merged_config(
                output_path=output_path,
                server_name="gms",
                server_entry={"command": "cmd", "args": [], "env": {"GM_PROJECT_ROOT": "/tmp", "PYTHONUNBUFFERED": "1"}},
            )
            self.assertIn("gms", merged["mcpServers"])

            backup = install_module._write_json_atomic_with_backup(output_path=output_path, payload={"mcpServers": {}})
            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())

            malformed = Path(temp_dir) / "bad.json"
            malformed.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                install_module._parse_json_object_or_raise(text="[]", source_label=str(malformed))

            with self.assertRaises(ValueError):
                install_module._validate_antigravity_sections(parsed={"mcpServers": []}, source_label="bad", server_name="gms")

            with self.assertRaises(ValueError):
                install_module._validate_codex_sections(parsed={"mcp_servers": []}, source_label="bad", server_name="gms")

            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            output_toml = workspace / ".codex" / "mcp.toml"
            output_toml.parent.mkdir(parents=True)
            output_toml.write_text("[mcp_servers]\ngms = []\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                install_module._render_codex_merged_config(
                    output_path=output_toml,
                    server_name="gms",
                    server_block='[mcp_servers.gms]\ncommand = "cmd"\nargs = []\n',
                )

    def test_setup_project_config_and_openclaw_skill_branches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_path = project_root / install_module.PROJECT_CONFIG_FILE

            result, output = _capture_output(
                install_module._setup_project_config,
                gm_project_root=project_root,
                non_interactive=True,
                skip_config=False,
                use_defaults=False,
                dry_run=False,
            )
            self.assertIsNone(result)
            self.assertIn("Skipping config file creation", output)

            result, output = _capture_output(
                install_module._setup_project_config,
                gm_project_root=project_root,
                non_interactive=True,
                skip_config=False,
                use_defaults=True,
                dry_run=True,
            )
            self.assertEqual(result, config_path)
            self.assertIn("Would create", output)

            config_path.write_text("{}", encoding="utf-8")
            result, output = _capture_output(
                install_module._setup_project_config,
                gm_project_root=project_root,
                non_interactive=True,
                skip_config=False,
                use_defaults=True,
                dry_run=False,
            )
            self.assertEqual(result, config_path)
            self.assertIn("already exists", output)

        with patch("gms_mcp.install.resolve_client_spec") as resolve_spec:
            resolve_spec.return_value = SimpleNamespace(key="client", workspace_supported=False, global_supported=True)
            self.assertIn("does not support workspace", install_module._scope_not_applicable_reason(client="client", scope="workspace"))

        real_import = builtins.__import__

        def _failing_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "gms_helpers.commands.skills_commands":
                raise ImportError("missing skills module")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=_failing_import):
            result, output = _capture_output(
                install_module._maybe_install_openclaw_skills,
                enable=True,
                project_scope=True,
                workspace_root=PROJECT_ROOT,
            )
        self.assertEqual(result, 0)
        self.assertIn("Could not load OpenClaw skills installer", output)

        fake_module = SimpleNamespace(handle_skills_install=lambda _args: {"success": False})
        with patch.dict(sys.modules, {"gms_helpers.commands.skills_commands": fake_module}):
            result, output = _capture_output(
                install_module._maybe_install_openclaw_skills,
                enable=True,
                project_scope=True,
                workspace_root=PROJECT_ROOT,
            )
        self.assertEqual(result, 2)
        self.assertIn("skills install failed", output)

    def test_run_canonical_and_main_branches(self):
        with patch("gms_mcp.install.CLIENT_ACTIONS", ["setup"]), patch("gms_mcp.install.CLIENT_SCOPES", ["workspace"]):
            result, output = _capture_output(
                install_module._run_canonical_flow,
                client="cursor",
                scope="workspace",
                action="bad",
                workspace_root=PROJECT_ROOT,
                gm_project_root=None,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
                safe_profile=False,
                config_path_override=None,
                openclaw_install_skills=False,
                openclaw_skills_project=False,
            )
        self.assertEqual(result, 2)
        self.assertIn("Unsupported action", output)

        with patch("gms_mcp.install.CLIENT_ACTIONS", ["setup", "check"]), patch("gms_mcp.install.CLIENT_SCOPES", ["workspace"]):
            result, output = _capture_output(
                install_module._run_canonical_flow,
                client="cursor",
                scope="global",
                action="setup",
                workspace_root=PROJECT_ROOT,
                gm_project_root=None,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
                safe_profile=False,
                config_path_override=None,
                openclaw_install_skills=False,
                openclaw_skills_project=False,
            )
        self.assertEqual(result, 2)
        self.assertIn("Unsupported scope", output)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "game.yyp").touch()
            with patch("gms_mcp.install._print_codex_check", return_value=0), patch(
                "gms_mcp.install._print_antigravity_check",
                return_value=0,
            ):
                result = install_module.main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--codex-check",
                        "--antigravity-check",
                    ]
                )
            self.assertEqual(result, 0)

    def test_interactive_project_selection_and_config_setup_branches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            candidates = [workspace / "game_a", workspace / "game_b"]
            for candidate in candidates:
                candidate.mkdir()

            fake_stdin = SimpleNamespace(isatty=lambda: True)
            with patch("gms_mcp.install._detect_gm_project_roots", return_value=candidates), patch.object(
                install_module.sys,
                "stdin",
                fake_stdin,
            ), patch("builtins.input", side_effect=["bad", "9", "2"]):
                selected, output = _capture_output(
                    install_module._select_gm_project_root,
                    workspace_root=workspace,
                    requested_root=None,
                    non_interactive=False,
                )
            self.assertEqual(selected[0], candidates[1])
            self.assertEqual(selected[1], candidates)
            self.assertIn("Enter a number", output)
            self.assertIn("Out of range", output)

            with patch("gms_mcp.install._detect_gm_project_roots", return_value=candidates), patch.object(
                install_module.sys,
                "stdin",
                fake_stdin,
            ), patch("builtins.input", return_value=""):
                selected, _output = _capture_output(
                    install_module._select_gm_project_root,
                    workspace_root=workspace,
                    requested_root=None,
                    non_interactive=False,
                )
            self.assertIsNone(selected[0])

            with patch.object(install_module.sys, "stdin", fake_stdin), patch("builtins.input", side_effect=["maybe", "n"]):
                result, output = _capture_output(
                    install_module._setup_project_config,
                    gm_project_root=workspace,
                    non_interactive=False,
                    skip_config=False,
                    use_defaults=False,
                    dry_run=False,
                )
            self.assertIsNone(result)
            self.assertIn("Please enter Y or N", output)
            self.assertIn("Skipping config file creation.", output)

            config_path = workspace / install_module.PROJECT_CONFIG_FILE
            with patch.object(install_module.sys, "stdin", fake_stdin), patch("builtins.input", return_value="y"), patch(
                "gms_mcp.install.create_default_config_file",
                return_value=config_path,
            ):
                result, output = _capture_output(
                    install_module._setup_project_config,
                    gm_project_root=workspace,
                    non_interactive=False,
                    skip_config=False,
                    use_defaults=False,
                    dry_run=False,
                )
            self.assertEqual(result, config_path)
            self.assertIn("Created project config", output)

            with patch.object(install_module.sys, "stdin", fake_stdin), patch("builtins.input", return_value="y"), patch(
                "gms_mcp.install.create_default_config_file",
                side_effect=FileExistsError("exists"),
            ):
                result, output = _capture_output(
                    install_module._setup_project_config,
                    gm_project_root=workspace,
                    non_interactive=False,
                    skip_config=False,
                    use_defaults=False,
                    dry_run=False,
                )
            self.assertEqual(result, config_path)
            self.assertIn("already exists", output)

            with patch.object(install_module.sys, "stdin", fake_stdin), patch("builtins.input", return_value="y"), patch(
                "gms_mcp.install.create_default_config_file",
                side_effect=RuntimeError("boom"),
            ):
                result, output = _capture_output(
                    install_module._setup_project_config,
                    gm_project_root=workspace,
                    non_interactive=False,
                    skip_config=False,
                    use_defaults=False,
                    dry_run=False,
                )
            self.assertIsNone(result)
            self.assertIn("Could not create config file: boom", output)

    def test_collect_client_check_state_special_cases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            home_dir = Path(temp_dir) / "home"
            with temporary_home(home_dir):
                plugin_dir = home_dir / ".claude" / "plugins" / "gms-mcp"
                plugin_dir.mkdir(parents=True)
                (plugin_dir / ".mcp.json").write_text(
                    json.dumps(
                        {
                            "mcpServers": {
                                "gms": {
                                    "command": "gms-mcp",
                                    "args": [],
                                    "env": {
                                        "GM_PROJECT_ROOT": "/tmp/project",
                                        "PYTHONUNBUFFERED": "1",
                                    },
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                state = install_module._collect_client_check_state(
                    client="claude-desktop",
                    scope="global",
                    workspace_root=workspace,
                    server_name="gms",
                    config_path_override=None,
                )
            self.assertFalse(state.readiness.ready)
            self.assertTrue(any("manifest" in problem for problem in state.readiness.problems))
            self.assertTrue(any("hooks" in problem for problem in state.readiness.problems))
            self.assertTrue(any("skills" in problem for problem in state.readiness.problems))

        fake_spec = SimpleNamespace(
            key="fake",
            workspace_supported=False,
            global_supported=False,
            workspace_relpath="configs/workspace.json",
            global_relpath=".fake/config.json",
            resolve_path=lambda **_kwargs: Path("/tmp/unused"),
        )
        with patch("gms_mcp.install.resolve_client_spec", return_value=fake_spec), patch(
            "gms_mcp.install._scope_not_applicable_reason",
            return_value="not applicable",
        ):
            state = install_module._collect_client_check_state(
                client="fake",
                scope="workspace",
                workspace_root=Path("/tmp/workspace"),
                server_name="gms",
                config_path_override="custom/config.json",
            )
        self.assertTrue(state.readiness.not_applicable)
        self.assertTrue(state.path.endswith("custom/config.json"))

        with patch("gms_mcp.install.resolve_client_spec", return_value=fake_spec), patch(
            "gms_mcp.install._scope_not_applicable_reason",
            return_value="not applicable",
        ):
            state = install_module._collect_client_check_state(
                client="fake",
                scope="workspace",
                workspace_root=Path("/tmp/workspace"),
                server_name="gms",
                config_path_override=None,
            )
        self.assertTrue(state.path.endswith("configs/workspace.json"))

        with patch("gms_mcp.install.resolve_client_spec", return_value=fake_spec), patch(
            "gms_mcp.install._scope_not_applicable_reason",
            return_value="not applicable",
        ):
            with temporary_home(Path(tempfile.mkdtemp())):
                state = install_module._collect_client_check_state(
                    client="fake",
                    scope="global",
                    workspace_root=Path("/tmp/workspace"),
                    server_name="gms",
                    config_path_override=None,
                )
        self.assertIn(".fake/config.json", state.path)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with patch("gms_mcp.install._read_codex_server_entry", side_effect=ValueError("bad codex config")):
                state = install_module._collect_client_check_state(
                    client="codex",
                    scope="workspace",
                    workspace_root=workspace,
                    server_name="gms",
                    config_path_override=None,
                )
        self.assertFalse(state.readiness.ready)
        self.assertEqual(state.readiness.problems, ["bad codex config"])

    def test_run_setup_for_client_branch_matrix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            gm_project_root = workspace / "gamemaker"
            gm_project_root.mkdir()

            with patch("gms_mcp.install._generate_cursor_config"), patch(
                "gms_mcp.install._make_server_config",
                return_value={"mcpServers": {"gms": {"command": "gms-mcp"}}},
            ):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="cursor",
                    scope="workspace",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=["--flag"],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 0)
            self.assertIn("Cursor config would be written to", output)

            with patch("gms_mcp.install._generate_codex_config", side_effect=ValueError("bad codex")):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="codex",
                    scope="workspace",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 2)
            self.assertIn("Could not generate Codex config", output)

            with patch(
                "gms_mcp.install._generate_codex_config",
                return_value=(workspace / ".codex" / "mcp.toml", "payload", "merged\n"),
            ):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="codex",
                    scope="workspace",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=False,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 0)
            self.assertIn("Codex config updated", output)

            with patch("gms_mcp.install._generate_antigravity_config", side_effect=ValueError("bad antigravity")):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="antigravity",
                    scope="global",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 2)
            self.assertIn("Could not generate Antigravity config", output)

            with patch(
                "gms_mcp.install._generate_antigravity_config",
                return_value=(
                    Path("/tmp/antigravity.json"),
                    {"mcpServers": {"gms": {"command": "gms-mcp"}}},
                    {"mcpServers": {"gms": {"command": "gms-mcp"}}},
                    None,
                ),
            ):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="antigravity",
                    scope="global",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 0)
            self.assertIn("Antigravity config would be merged into", output)

            with patch("gms_mcp.install._write_json"), patch(
                "gms_mcp.install._make_antigravity_server_config",
                return_value={"mcpServers": {"gms": {"command": "gms-mcp"}}},
            ):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="antigravity",
                    scope="workspace",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 0)
            self.assertIn("Antigravity workspace config would be written to", output)

            with patch("gms_mcp.install._generate_claude_code_plugin"), patch(
                "gms_mcp.install._build_claude_plugin_manifest",
                return_value={"name": "gms"},
            ), patch(
                "gms_mcp.install._make_claude_code_mcp_config",
                return_value={"gms": {"command": "gms-mcp"}},
            ):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="claude-code",
                    scope="workspace",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 0)
            self.assertIn("Claude Code config would be written to", output)

            with patch("gms_mcp.install._generate_claude_code_plugin"), patch(
                "gms_mcp.install._build_claude_plugin_manifest",
                return_value={"name": "gms"},
            ), patch(
                "gms_mcp.install._make_claude_code_mcp_config",
                return_value={"gms": {"command": "gms-mcp"}},
            ):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="claude-desktop",
                    scope="global",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 0)
            self.assertIn("Claude Desktop plugin would be synced to", output)

            with patch("gms_mcp.install._write_json"), patch(
                "gms_mcp.install._make_server_config",
                return_value={"mcpServers": {"gms": {"command": "gms-mcp"}}},
            ):
                result, output = _capture_output(
                    install_module._run_setup_for_client,
                    client="vscode",
                    scope="workspace",
                    workspace_root=workspace,
                    gm_project_root=gm_project_root,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    dry_run=True,
                    safe_profile=False,
                    config_path_override=None,
                )
            self.assertEqual(result, 0)
            self.assertIn("vscode config would be written to", output)

    def test_canonical_flow_and_main_branch_matrix(self):
        state = install_module.ConfigState(
            client="openclaw",
            scope="workspace",
            server_name="gms",
            path="/tmp/config",
            exists=True,
            entry={"command": "gms-mcp"},
            readiness=install_module.ReadinessResult(ready=True, problems=[]),
        )

        with patch("gms_mcp.install._collect_client_check_state", return_value=state), patch(
            "gms_mcp.install._print_standard_check",
            return_value=11,
        ):
            result = install_module._run_canonical_flow(
                client="openclaw",
                scope="workspace",
                action="check",
                workspace_root=PROJECT_ROOT,
                gm_project_root=None,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
                safe_profile=False,
                config_path_override=None,
                openclaw_install_skills=False,
                openclaw_skills_project=False,
            )
        self.assertEqual(result, 11)

        with patch("gms_mcp.install._collect_client_check_state", return_value=state), patch(
            "gms_mcp.install._print_standard_check_json",
            return_value=12,
        ):
            result = install_module._run_canonical_flow(
                client="openclaw",
                scope="workspace",
                action="check-json",
                workspace_root=PROJECT_ROOT,
                gm_project_root=None,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
                safe_profile=False,
                config_path_override=None,
                openclaw_install_skills=False,
                openclaw_skills_project=False,
            )
        self.assertEqual(result, 12)

        with patch("gms_mcp.install._run_setup_for_client", return_value=2):
            result = install_module._run_canonical_flow(
                client="openclaw",
                scope="workspace",
                action="app-setup",
                workspace_root=PROJECT_ROOT,
                gm_project_root=None,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
                safe_profile=False,
                config_path_override=None,
                openclaw_install_skills=False,
                openclaw_skills_project=False,
            )
        self.assertEqual(result, 2)

        with patch("gms_mcp.install._run_setup_for_client", return_value=0), patch(
            "gms_mcp.install.resolve_client_spec",
            return_value=SimpleNamespace(key="openclaw"),
        ), patch(
            "gms_mcp.install._maybe_install_openclaw_skills",
            return_value=2,
        ):
            result = install_module._run_canonical_flow(
                client="openclaw",
                scope="workspace",
                action="app-setup",
                workspace_root=PROJECT_ROOT,
                gm_project_root=None,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
                safe_profile=False,
                config_path_override=None,
                openclaw_install_skills=True,
                openclaw_skills_project=True,
            )
        self.assertEqual(result, 2)

        with patch("gms_mcp.install._run_setup_for_client", return_value=0), patch(
            "gms_mcp.install.resolve_client_spec",
            return_value=SimpleNamespace(key="openclaw"),
        ), patch(
            "gms_mcp.install._maybe_install_openclaw_skills",
            return_value=0,
        ), patch(
            "gms_mcp.install._collect_client_check_state",
            return_value=state,
        ), patch(
            "gms_mcp.install._print_standard_check",
            return_value=0,
        ), patch(
            "gms_mcp.install._print_standard_app_setup_summary",
            return_value=13,
        ):
            result = install_module._run_canonical_flow(
                client="openclaw",
                scope="workspace",
                action="app-setup",
                workspace_root=PROJECT_ROOT,
                gm_project_root=None,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
                safe_profile=False,
                config_path_override=None,
                openclaw_install_skills=True,
                openclaw_skills_project=True,
            )
        self.assertEqual(result, 13)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "project.yyp").touch()

            with patch("gms_mcp.install._select_gm_project_root", return_value=(None, [])), patch(
                "gms_mcp.install._resolve_launcher",
                return_value=("python3", ["-m", "gms_mcp.bootstrap_server"]),
            ), patch(
                "gms_mcp.install._run_canonical_flow",
                return_value=7,
            ) as mock_flow:
                result, output = _capture_output(
                    install_module.main,
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "antigravity",
                        "--scope",
                        "global",
                        "--action",
                        "setup",
                        "--mode",
                        "python-module",
                        "--python",
                        "missing-python",
                    ],
                )
            self.assertEqual(result, 7)
            self.assertIn("not found; using 'python3' instead", output)
            self.assertTrue(mock_flow.call_args.kwargs["safe_profile"])

            with patch("gms_mcp.install._select_gm_project_root", return_value=(None, [])), patch(
                "gms_mcp.install._resolve_launcher",
                return_value=("gms-mcp", []),
            ), patch("gms_mcp.install.shutil.which", return_value=None), patch(
                "gms_mcp.install._generate_cursor_config",
                return_value=workspace / ".cursor" / "mcp.json",
            ):
                result, output = _capture_output(
                    install_module.main,
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--dry-run",
                    ],
                )
            self.assertEqual(result, 0)
            self.assertIn("'gms-mcp' not found on PATH", output)
            self.assertIn(".cursor/mcp.json", output)

            with patch("gms_mcp.install._select_gm_project_root", return_value=(None, [])), patch(
                "gms_mcp.install._resolve_launcher",
                return_value=("gms-mcp", []),
            ), patch("gms_mcp.install._print_codex_check_json", return_value=5):
                result = install_module.main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--codex-check-json",
                    ]
                )
            self.assertEqual(result, 5)

            with patch("gms_mcp.install._select_gm_project_root", return_value=(None, [])), patch(
                "gms_mcp.install._resolve_launcher",
                return_value=("gms-mcp", []),
            ), patch("gms_mcp.install._print_antigravity_check_json", return_value=6):
                result = install_module.main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--antigravity-check-json",
                    ]
                )
            self.assertEqual(result, 6)

            with patch("gms_mcp.install._select_gm_project_root", return_value=(None, [])), patch(
                "gms_mcp.install._resolve_launcher",
                return_value=("gms-mcp", []),
            ), patch(
                "gms_mcp.install._generate_cursor_config",
                return_value=workspace / ".cursor" / "mcp.json",
            ), patch(
                "gms_mcp.install._generate_example_configs",
                return_value=[
                    workspace / "mcp-configs" / "vscode.mcp.json",
                    workspace / "mcp-configs" / "windsurf.mcp.json",
                    workspace / "mcp-configs" / "antigravity.mcp.json",
                    workspace / "mcp-configs" / "openclaw.mcp.json",
                ],
            ):
                result, output = _capture_output(
                    install_module.main,
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--all",
                        "--dry-run",
                    ],
                )
            self.assertEqual(result, 0)
            self.assertIn("vscode.mcp.json", output)
            self.assertIn("openclaw.mcp.json", output)


if __name__ == "__main__":
    unittest.main()
