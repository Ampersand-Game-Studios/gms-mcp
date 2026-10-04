"""Public GMS contracts affected by the MCP SDK 2.3 release."""

from __future__ import annotations

import asyncio
from importlib.metadata import version
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx2
import uvicorn
from mcp import Client
from mcp.client.session_group import StreamableHttpParameters
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from gms_mcp.gamemaker_mcp_server import build_server
from gms_mcp.server.results import unwrap_call_tool_result


HTTP_TOKEN = "sdk-compatibility-test-token-2026-10-05"


class MCPSDKCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.project = Path(self.temporary_directory.name).resolve()
        (self.project / "SDKCompatibility.yyp").write_text(
            json.dumps({"name": "SDKCompatibility", "resources": [], "Folders": []}), encoding="utf-8"
        )
        self.environment = patch.dict(
            os.environ,
            {
                "CI": "1",
                "GMS_MCP_TELEMETRY": "off",
                "GM_PROJECT_ROOT": str(self.project),
                "GMS_MCP_TOOLSETS": "all",
                "GMS_MCP_EXPOSE_HOST_DIAGNOSTICS": "0",
            },
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_sdk_and_wire_types_are_installed_in_lockstep(self):
        self.assertEqual(version("mcp"), version("mcp-types"))

    async def test_all_project_headers_register_and_remain_visible(self):
        async with Client(build_server(), mode="2026-07-28") as client:
            listed = await client.list_tools()
        headers = []
        for tool in listed.tools:
            names = []
            for schema in tool.input_schema.get("properties", {}).values():
                if "x-mcp-header" not in schema:
                    continue
                self.assertIn(schema["type"], {"string", "integer", "boolean"})
                names.append(schema["x-mcp-header"].lower())
                headers.append((tool.name, schema["x-mcp-header"]))
            self.assertEqual(len(names), len(set(names)), tool.name)
        self.assertIn(("gm_project_info", "project-root"), headers)

    async def test_legacy_empty_params_and_metadata_do_not_break_gms_middleware(self):
        observed = []

        async def observe(context, call_next):
            observed.append((context.method, context.params, context.meta))
            return await call_next(context)

        server = build_server()
        server.middleware.append(observe)
        async with Client(server, mode="legacy") as client:
            self.assertIsNone(client.server_capabilities.experimental)
            await client.list_tools()
            await client.list_resources()
            await client.list_resource_templates()
            await client.list_prompts()
            result = unwrap_call_tool_result(await client.call_tool("gm_project_info", {"project_root": "."}))

        for method in ("tools/list", "resources/list", "resources/templates/list", "prompts/list"):
            request = next(item for item in observed if item[0] == method)
            self.assertIsNone(request[1], method)
            self.assertIsNone(request[2], method)
        self.assertEqual(result["yyp"], "SDKCompatibility.yyp")
        self.assertEqual(result["project_directory"], ".")

    async def test_header_routed_http_uses_registered_schema_and_preserves_project_boundary(self):
        observed_methods = []
        project_headers = []

        async def observe(context, call_next):
            observed_methods.append(context.method)
            return await call_next(context)

        with socket.socket() as reserved_socket:
            reserved_socket.bind(("127.0.0.1", 0))
            port = reserved_socket.getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}/mcp"
        mcp = build_server(http_auth_value=HTTP_TOKEN, http_auth_issuer_url=endpoint)
        mcp.middleware.append(observe)
        app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, host="127.0.0.1")

        async def record_project_header(scope, receive, send):
            if scope["type"] == "http":
                project_headers.append(dict(scope["headers"]).get(b"mcp-param-project-root"))
            await app(scope, receive, send)

        server = uvicorn.Server(uvicorn.Config(record_project_header, host="127.0.0.1", port=port, log_level="error"))
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(server.started, "authenticated loopback fixture did not start")
            for mode, event_limit in (("2026-07-28", 1024 * 1024), ("2026-07-28", None), ("legacy", 1024 * 1024)):
                with self.subTest(mode=mode, max_sse_event_size=event_limit):
                    parameters = StreamableHttpParameters(
                        url=endpoint,
                        headers={"Authorization": f"Bearer {HTTP_TOKEN}"},
                        max_sse_event_size=event_limit,
                    )
                    async with (
                        httpx2.AsyncClient(headers=parameters.headers, timeout=parameters.timeout) as http_client,
                        Client(
                            streamable_http_client(
                                parameters.url,
                                http_client=http_client,
                                max_sse_event_size=parameters.max_sse_event_size,
                            ),
                            mode=mode,
                        ) as client,
                    ):
                        await client.list_tools()
                        observed_methods.clear()
                        project_headers.clear()
                        raw = await client.call_tool("gm_project_info", {"project_root": "."})
                        result = unwrap_call_tool_result(raw)
                        self.assertFalse(raw.is_error)
                        self.assertEqual(result["yyp"], "SDKCompatibility.yyp")
                        self.assertEqual(result["project_directory"], ".")
                        self.assertEqual(observed_methods, ["tools/call"])
                        if mode == "2026-07-28":
                            self.assertIn(b".", project_headers)
                        else:
                            self.assertNotIn(b".", project_headers)
                        denied = await client.call_tool("gm_project_info", {"project_root": "../outside"})
                        self.assertTrue(denied.is_error)
                        self.assertEqual(unwrap_call_tool_result(denied)["error_code"], "project_access_denied")
                        self.assertNotIn(str(self.project), json.dumps(denied.model_dump(mode="json")))
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=5)

    async def test_real_stdio_entrypoint_serves_modern_and_legacy_clients(self):
        repository = Path(__file__).resolve().parents[3]
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "gms_mcp"],
            cwd=str(self.project),
            env={
                "PYTHONPATH": str(repository / "src"),
                "CI": "1",
                "GMS_MCP_TELEMETRY": "off",
                "GM_PROJECT_ROOT": str(self.project),
                "GMS_MCP_TOOLSETS": "all",
                "GMS_MCP_EXPOSE_HOST_DIAGNOSTICS": "0",
            },
        )
        for mode in ("2026-07-28", "legacy"):
            with self.subTest(mode=mode):
                async with Client(parameters, mode=mode, read_timeout_seconds=15) as client:
                    listed = await client.list_tools()
                    self.assertIn("gm_project_info", {tool.name for tool in listed.tools})
                    raw = await client.call_tool("gm_project_info", {"project_root": "."})
                    result = unwrap_call_tool_result(raw)
                    self.assertFalse(raw.is_error)
                    self.assertEqual(result["yyp"], "SDKCompatibility.yyp")
                    self.assertEqual(result["project_directory"], ".")


if __name__ == "__main__":
    unittest.main()
