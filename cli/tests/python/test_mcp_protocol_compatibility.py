from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from mcp import Client

from gms_mcp.gamemaker_mcp_server import build_server
from gms_mcp.server.results import unwrap_call_tool_result


class MCPProtocolCompatibilityTests(unittest.TestCase):
    async def _snapshot(self, mode: str) -> tuple[str, list, dict]:
        server = build_server()
        async with Client(server, mode=mode) as client:
            listed = await client.list_tools()
            capabilities = unwrap_call_tool_result(await client.call_tool("gm_capabilities", {}))
            return str(client.protocol_version), listed.tools, capabilities

    def test_modern_and_legacy_clients_expose_the_same_tool_contract(self):
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "core"}, clear=False):
            modern_version, modern_tools, modern_capabilities = asyncio.run(self._snapshot("2026-07-28"))
            legacy_version, legacy_tools, legacy_capabilities = asyncio.run(self._snapshot("legacy"))

        self.assertEqual(modern_version, "2026-07-28")
        self.assertEqual(legacy_version, "2025-11-25")
        self.assertEqual([tool.name for tool in modern_tools], [tool.name for tool in legacy_tools])
        self.assertEqual(modern_capabilities, legacy_capabilities)
        self.assertFalse(any("ctx" in tool.input_schema.get("properties", {}) for tool in modern_tools))

        specs = {tool.name: tool for tool in modern_tools}
        self.assertTrue(specs["gm_project_info"].annotations.read_only_hint)
        self.assertTrue(specs["gm_project_info"].annotations.idempotent_hint)
        self.assertTrue(specs["gm_safe_delete"].annotations.destructive_hint)

    def test_raw_tool_order_is_deterministic(self):
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "all"}, clear=False):
            server = build_server()
            first = [tool.name for tool in asyncio.run(server.list_tools())]
            second = [tool.name for tool in asyncio.run(server.list_tools())]

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
