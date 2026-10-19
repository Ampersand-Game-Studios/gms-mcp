#!/usr/bin/env python3
"""Regression tests for MCP stdio transport safety."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from gms_mcp.server.results import unwrap_call_tool_result

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class _BridgePeer:
    def __init__(self, port: int, identity: dict[str, str]):
        self.port = port
        self.identity = identity
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        sock.connect(("127.0.0.1", self.port))
        sock.sendall(("HELLO:" + json.dumps(self.identity) + "\nLOG:1|hello from test\n").encode())
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

            server_script = textwrap.dedent(
                f"""
                import sys
                from pathlib import Path
                from unittest.mock import patch

                repo_root = Path({str(PROJECT_ROOT)!r})
                src_root = repo_root / "src"
                if str(src_root) not in sys.path:
                    sys.path.insert(0, str(src_root))

                import json
                import subprocess
                import zipfile
                from types import SimpleNamespace
                from gms_helpers import live_session, mac_runtime, snapshot_build
                from gms_helpers.runner import GameMakerRunner

                root = Path({str(project_root)!r})
                children = []

                def _compile(root, **options):
                    work = root / "work"
                    work.mkdir()
                    archive = work / "game.zip"
                    with zipfile.ZipFile(archive, "w") as stream:
                        stream.writestr("game.ios", b"data")
                    return ({{"ok": True, "label": options["label"]}},
                        snapshot_build.BuildResult(True, "COMPILE_OK", game_archive=archive), work, None)

                def _prepare(runner, root, label):
                    save = root / "save"
                    staging = save / "stage"
                    staging.mkdir(parents=True)
                    return mac_runtime.MacRuntime(runner, staging, save, "fixture")

                def _launch(runner, staging, game_file, run_dir, environment):
                    child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                                             stdin=subprocess.PIPE)
                    children.append(child)
                    (root / "bridge-env.json").write_text(json.dumps(environment))
                    log = staging / "debug.txt"
                    log.write_text("fixture")
                    return child, log

                patches = [
                    patch("gms_helpers.bridge_installer.get_bridge_status", return_value={{"installed": True}}),
                    patch("gms_helpers.snapshot_build.snapshot_compile", side_effect=_compile),
                    patch("gms_helpers.snapshot_build.require_mac_runner", return_value=Path("runner")),
                    patch("gms_helpers.live_session.prepare_mac_runtime", side_effect=_prepare),
                    patch("gms_helpers.snapshot_build.launch_mac_runner", side_effect=_launch),
                    patch.object(GameMakerRunner, "_snapshot_macos_processes",
                        lambda self: {{child.pid: SimpleNamespace(command="fixture runner", started="fixture start")
                                      for child in children}}),
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
                    env={
                        "PYTHONPATH": str(SRC_ROOT),
                        "GMS_MCP_TOOLSETS": "bridge",
                        "GM_PROJECT_ROOT": str(project_root),
                        "GMS_MCP_LOCK_DIR": str(project_root / "locks"),
                    },
                )

                async with Client(stdio_client(params), read_timeout_seconds=None) as client:
                    run_result = unwrap_call_tool_result(
                        await client.call_tool(
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
                    bridge_port = run_result["bridge_port"]
                    environment = json.loads((project_root / "bridge-env.json").read_text())
                    self.assertEqual(bridge_port, int(environment["GMS_MCP_BRIDGE_PORT"]))
                    identity = {
                        "project_id": environment["GMS_MCP_BRIDGE_PROJECT_ID"],
                        "session_id": environment["GMS_MCP_BRIDGE_SESSION_ID"],
                    }

                    peer = _BridgePeer(bridge_port, identity)
                    peer.connect()
                    try:
                        latest_status = None
                        for _ in range(20):
                            latest_status = unwrap_call_tool_result(
                                await client.call_tool("gm_bridge_status", {"project_root": str(project_root)})
                            )
                            if latest_status["game_connected"]:
                                break
                            await asyncio.sleep(0.1)

                        self.assertIsNotNone(latest_status)
                        self.assertTrue(latest_status["server_running"])
                        self.assertTrue(latest_status["game_connected"])

                        logs_result = unwrap_call_tool_result(
                            await client.call_tool("gm_run_logs", {"project_root": str(project_root), "lines": 5})
                        )
                        self.assertTrue(logs_result["ok"])
                        self.assertEqual(logs_result["logs"][0]["message"], "hello from test")

                        command_result = unwrap_call_tool_result(
                            await client.call_tool(
                                "gm_run_command",
                                {"project_root": str(project_root), "command": "ping", "timeout": 1.0},
                            )
                        )
                        self.assertTrue(command_result["ok"])
                        self.assertEqual(command_result["result"], "pong")
                    finally:
                        peer.close()

                    post_disconnect_status = unwrap_call_tool_result(
                        await client.call_tool("gm_bridge_status", {"project_root": str(project_root)})
                    )
                    self.assertTrue(post_disconnect_status["ok"])
                    stopped = unwrap_call_tool_result(
                        await client.call_tool("gm_game_stop", {"project_root": str(project_root)})
                    )
                    self.assertTrue(stopped["ok"])

            anyio.run(_exercise)


if __name__ == "__main__":
    unittest.main()
