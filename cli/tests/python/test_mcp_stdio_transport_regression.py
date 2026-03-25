#!/usr/bin/env python3
"""Regression tests for MCP stdio transport safety."""

from __future__ import annotations

import asyncio
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _unwrap_call_tool(result):
    content = getattr(result, "structuredContent", None)
    if isinstance(content, dict) and "result" in content:
        return content["result"]
    raise AssertionError(f"Unexpected call_tool return type: {type(result)} ({result!r})")


class _BridgePeer:
    def __init__(self, port: int):
        self.port = port
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        sock.connect(("127.0.0.1", self.port))
        sock.sendall(b"LOG:1|hello from test\n")
        self._socket = sock
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _serve(self) -> None:
        if self._socket is None:
            return

        buffer = ""
        while not self._stop.is_set():
            try:
                data = self._socket.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            if not data:
                break

            buffer += data.decode("utf-8", errors="replace").replace("\x00", "")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line or not line.startswith("CMD:"):
                    continue

                content = line[4:]
                if "|" in content:
                    cmd_id, command = content.split("|", 1)
                else:
                    cmd_id, command = content, ""
                result = "pong" if command == "ping" else f"ok:{command}"

                try:
                    self._socket.sendall(f"RSP:{cmd_id}|{result}\n".encode("utf-8"))
                except OSError:
                    return


class TestMCPStdioTransportRegression(unittest.TestCase):
    def test_bridge_enabled_background_run_keeps_transport_alive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "TestProject.yyp").write_text('{"resources": []}', encoding="utf-8")

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                bridge_port = probe.getsockname()[1]

            server_script = textwrap.dedent(
                f"""
                import sys
                from pathlib import Path
                from unittest.mock import patch

                repo_root = Path({str(PROJECT_ROOT)!r})
                src_root = repo_root / "src"
                if str(src_root) not in sys.path:
                    sys.path.insert(0, str(src_root))

                from gms_helpers.bridge_server import BridgeServer

                _servers = {{}}

                def _get_bridge_server(project_root, create=True):
                    key = str(Path(project_root).resolve())
                    if key not in _servers and create:
                        _servers[key] = BridgeServer(port={bridge_port})
                    return _servers.get(key)

                def _stop_bridge_server(project_root):
                    key = str(Path(project_root).resolve())
                    server = _servers.pop(key, None)
                    if server:
                        server.stop()

                patches = [
                    patch("gms_helpers.bridge_installer.is_bridge_installed", return_value=True),
                    patch("gms_helpers.bridge_installer.get_bridge_status", return_value={{"installed": True}}),
                    patch("gms_helpers.bridge_server.get_bridge_server", side_effect=_get_bridge_server),
                    patch("gms_helpers.bridge_server.stop_bridge_server", side_effect=_stop_bridge_server),
                    patch("gms_helpers.utils.validate_working_directory", return_value=None),
                    patch(
                        "gms_helpers.commands.runner_commands.handle_runner_run",
                        return_value={{
                            "ok": True,
                            "background": True,
                            "pid": 1234,
                            "run_id": "run-test",
                            "message": "Game started in background",
                        }},
                    ),
                ]
                for active_patch in patches:
                    active_patch.start()

                from gms_mcp.bootstrap_server import main

                raise SystemExit(main())
                """
            )

            async def _exercise() -> None:
                params = StdioServerParameters(
                    command=sys.executable,
                    args=["-c", server_script],
                    cwd=str(PROJECT_ROOT),
                    env={"PYTHONPATH": str(SRC_ROOT)},
                )

                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=None) as session:
                        await session.initialize()

                        run_result = _unwrap_call_tool(
                            await session.call_tool(
                                "gm_run",
                                {
                                    "project_root": str(project_root),
                                    "background": True,
                                    "enable_bridge": True,
                                    "platform": "macOS",
                                    "runtime": "VM",
                                    "output_location": "project",
                                },
                            )
                        )

                        self.assertTrue(run_result["ok"])
                        self.assertTrue(run_result["bridge_enabled"])
                        self.assertEqual(run_result["bridge_port"], bridge_port)

                        peer = _BridgePeer(bridge_port)
                        peer.connect()
                        try:
                            latest_status = None
                            for _ in range(20):
                                latest_status = _unwrap_call_tool(
                                    await session.call_tool("gm_bridge_status", {"project_root": str(project_root)})
                                )
                                if latest_status["game_connected"]:
                                    break
                                await asyncio.sleep(0.1)

                            self.assertIsNotNone(latest_status)
                            self.assertTrue(latest_status["server_running"])
                            self.assertTrue(latest_status["game_connected"])

                            logs_result = _unwrap_call_tool(
                                await session.call_tool("gm_run_logs", {"project_root": str(project_root), "lines": 5})
                            )
                            self.assertTrue(logs_result["ok"])
                            self.assertEqual(logs_result["logs"][0]["message"], "hello from test")

                            command_result = _unwrap_call_tool(
                                await session.call_tool(
                                    "gm_run_command",
                                    {"project_root": str(project_root), "command": "ping", "timeout": 1.0},
                                )
                            )
                            self.assertTrue(command_result["ok"])
                            self.assertEqual(command_result["result"], "pong")
                        finally:
                            peer.close()

                        post_disconnect_status = _unwrap_call_tool(
                            await session.call_tool("gm_bridge_status", {"project_root": str(project_root)})
                        )
                        self.assertTrue(post_disconnect_status["ok"])

            anyio.run(_exercise)


if __name__ == "__main__":
    unittest.main()
