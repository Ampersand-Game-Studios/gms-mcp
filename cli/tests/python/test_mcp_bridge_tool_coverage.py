#!/usr/bin/env python3
"""Coverage-oriented tests for MCP bridge tool wrappers."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_mcp.server.tools import bridge


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class TestBridgeToolWrappers(unittest.TestCase):
    def setUp(self):
        self.mcp = FakeMCP()
        bridge.register(self.mcp, object)

    def call_tool(self, tool_name: str, **kwargs):
        return asyncio.run(self.mcp.tools[tool_name](**kwargs))

    def test_install_uninstall_and_status_branches(self):
        with patch("gms_helpers.bridge_installer.install_bridge", return_value={"ok": True, "message": "installed"}):
            result = self.call_tool("gm_bridge_install", port=6510, project_root="/tmp/project")
        self.assertTrue(result["ok"])

        with patch("gms_helpers.bridge_installer.install_bridge", side_effect=RuntimeError("install boom")):
            result = self.call_tool("gm_bridge_install", port=6511, project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Installation failed", result["message"])

        with patch("gms_helpers.bridge_installer.uninstall_bridge", side_effect=RuntimeError("uninstall boom")):
            result = self.call_tool("gm_bridge_uninstall", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Uninstallation failed", result["message"])

        with patch("gms_helpers.bridge_installer.get_bridge_status", return_value={"installed": True}), patch(
            "gms_helpers.bridge_server.get_bridge_server",
            return_value=None,
        ):
            result = self.call_tool("gm_bridge_status", project_root="/tmp/project")
        self.assertTrue(result["ok"])
        self.assertFalse(result["server_running"])
        self.assertFalse(result["game_connected"])

        with patch("gms_helpers.bridge_installer.get_bridge_status", side_effect=RuntimeError("status boom")):
            result = self.call_tool("gm_bridge_status", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Status check failed", result["message"])

    def test_enable_one_shot_error_branches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)

            with patch("gms_mcp.server.tools.bridge._resolve_project_directory", return_value=project_root):
                result = self.call_tool("gm_bridge_enable_one_shot", project_root=str(project_root))
            self.assertFalse(result["ok"])
            self.assertIn("No .yyp found", result["error"])

            yyp_path = project_root / "game.yyp"
            yyp_path.write_text("{}", encoding="utf-8")
            with patch("gms_mcp.server.tools.bridge._resolve_project_directory", return_value=project_root), patch(
                "gms_helpers.utils.load_json_loose",
                return_value={},
            ):
                result = self.call_tool("gm_bridge_enable_one_shot", project_root=str(project_root))
            self.assertFalse(result["ok"])
            self.assertIn("Could not determine startup room", result["error"])

            yyp_data = {
                "resources": [
                    {"id": {"name": "r_start", "path": "rooms/r_start/r_start.yy"}},
                ]
            }
            with patch("gms_mcp.server.tools.bridge._resolve_project_directory", return_value=project_root), patch(
                "gms_helpers.utils.load_json_loose",
                return_value=yyp_data,
            ):
                result = self.call_tool("gm_bridge_enable_one_shot", project_root=str(project_root))
            self.assertFalse(result["ok"])
            self.assertIn("Startup room file not found", result["error"])

            room_dir = project_root / "rooms" / "r_start"
            room_dir.mkdir(parents=True)
            room_file = room_dir / "r_start.yy"
            room_file.write_text("{}", encoding="utf-8")
            with patch("gms_mcp.server.tools.bridge._resolve_project_directory", return_value=project_root), patch(
                "gms_helpers.utils.load_json_loose",
                return_value={"RoomOrderNodes": [{"roomId": {"name": "r_start"}}]},
            ), patch(
                "gms_helpers.bridge_installer.install_bridge",
                return_value={"ok": False, "error": "install failed"},
            ):
                result = self.call_tool("gm_bridge_enable_one_shot", project_root=str(project_root))
            self.assertFalse(result["ok"])
            self.assertEqual(result["install"]["error"], "install failed")

    def test_enable_one_shot_success_paths_patch_creation_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            yyp_path = project_root / "game.yyp"
            yyp_path.write_text("{}", encoding="utf-8")
            room_dir = project_root / "rooms" / "r_start"
            room_dir.mkdir(parents=True)
            room_file = room_dir / "r_start.yy"
            room_file.write_text("{}", encoding="utf-8")

            yyp_data = {"RoomOrderNodes": [{"roomId": {"name": "r_start"}}]}
            room_without_layer = {"layers": [], "instanceCreationOrder": None}
            with patch("gms_mcp.server.tools.bridge._resolve_project_directory", return_value=project_root), patch(
                "gms_helpers.utils.load_json_loose",
                side_effect=[yyp_data, room_without_layer, room_without_layer, room_without_layer],
            ), patch(
                "gms_helpers.bridge_installer.install_bridge",
                return_value={"ok": True},
            ), patch(
                "gms_helpers.room_layer_helper.add_layer",
            ) as mock_add_layer, patch(
                "gms_helpers.room_instance_helper.add_instance",
                return_value="inst_bridge",
            ), patch(
                "gms_helpers.utils.save_json_loose",
            ) as mock_save:
                result = self.call_tool("gm_bridge_enable_one_shot", project_root=str(project_root))
            self.assertTrue(result["ok"])
            mock_add_layer.assert_called_once_with("r_start", "Instances", "instance", 0)
            mock_save.assert_called_once()

            room_with_string_order = {
                "layers": [{"name": "Instances", "resourceType": "GMRInstanceLayer", "instances": []}],
                "instanceCreationOrder": ["inst_existing"],
            }
            with patch("gms_mcp.server.tools.bridge._resolve_project_directory", return_value=project_root), patch(
                "gms_helpers.utils.load_json_loose",
                side_effect=[yyp_data, room_with_string_order, room_with_string_order, room_with_string_order],
            ), patch(
                "gms_helpers.bridge_installer.install_bridge",
                return_value={"ok": True},
            ), patch(
                "gms_helpers.room_layer_helper.add_layer",
            ) as mock_add_layer, patch(
                "gms_helpers.room_instance_helper.add_instance",
                return_value="inst_bridge_2",
            ), patch(
                "gms_helpers.utils.save_json_loose",
            ) as mock_save:
                result = self.call_tool("gm_bridge_enable_one_shot", project_root=str(project_root))
            self.assertTrue(result["ok"])
            mock_add_layer.assert_not_called()
            saved_payload = mock_save.call_args.args[1]
            self.assertEqual(saved_payload["instanceCreationOrder"][-1], "inst_bridge_2")

    def test_run_logs_and_run_command_branches(self):
        with patch("gms_helpers.bridge_server.get_bridge_server", return_value=None):
            result = self.call_tool("gm_run_logs", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Bridge server not running", result["error"])

        disconnected_server = SimpleNamespace(is_connected=False)
        with patch("gms_helpers.bridge_server.get_bridge_server", return_value=disconnected_server):
            result = self.call_tool("gm_run_logs", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Game not connected", result["error"])

        connected_server = SimpleNamespace(
            is_connected=True,
            get_logs=lambda count=50: [{"message": "hello"}][:count],
            get_log_count=lambda: 1,
        )
        with patch("gms_helpers.bridge_server.get_bridge_server", return_value=connected_server):
            result = self.call_tool("gm_run_logs", lines=5, project_root="/tmp/project")
        self.assertTrue(result["ok"])
        self.assertEqual(result["log_count"], 1)

        with patch("gms_helpers.bridge_server.get_bridge_server", side_effect=RuntimeError("log boom")):
            result = self.call_tool("gm_run_logs", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Failed to get logs", result["message"])

        with patch("gms_helpers.bridge_server.get_bridge_server", return_value=None):
            result = self.call_tool("gm_run_command", command="ping", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Bridge server not running", result["error"])

        with patch("gms_helpers.bridge_server.get_bridge_server", return_value=disconnected_server):
            result = self.call_tool("gm_run_command", command="ping", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Game not connected", result["error"])

        command_server = SimpleNamespace(
            is_connected=True,
            send_command=lambda command, timeout=5.0: SimpleNamespace(success=True, result=f"ok:{command}", error=None),
        )
        with patch("gms_helpers.bridge_server.get_bridge_server", return_value=command_server):
            result = self.call_tool("gm_run_command", command="ping", timeout=1.0, project_root="/tmp/project")
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "ok:ping")

        failing_server = SimpleNamespace(
            is_connected=True,
            send_command=lambda command, timeout=5.0: SimpleNamespace(success=False, result=None, error="failed"),
        )
        with patch("gms_helpers.bridge_server.get_bridge_server", return_value=failing_server):
            result = self.call_tool("gm_run_command", command="ping", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "failed")

        with patch("gms_helpers.bridge_server.get_bridge_server", side_effect=RuntimeError("command boom")):
            result = self.call_tool("gm_run_command", command="ping", project_root="/tmp/project")
        self.assertFalse(result["ok"])
        self.assertIn("Failed to send command", result["message"])


if __name__ == "__main__":
    unittest.main()
