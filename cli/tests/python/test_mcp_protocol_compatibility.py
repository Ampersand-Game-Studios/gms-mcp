from __future__ import annotations

import asyncio
import json
import os
import unittest
from typing import Any
from unittest.mock import patch

from mcp import Client

from gms_mcp.gamemaker_mcp_server import build_server
from gms_mcp.server.results import unwrap_call_tool_result


class MCPProtocolCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _serialized_tool_contracts(tools: list[Any]) -> dict[str, str]:
        """Return wire-format contracts keyed by name without map-order noise."""
        return {
            tool.name: json.dumps(
                tool.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            for tool in tools
        }

    async def _snapshot(self, mode: str) -> tuple[str, list, dict]:
        server = build_server()
        async with Client(server, mode=mode) as client:
            listed = await client.list_tools()
            capabilities = unwrap_call_tool_result(await client.call_tool("gm_capabilities", {}))
            return str(client.protocol_version), listed.tools, capabilities

    def _assert_tool_contract_parity(self, toolsets: str) -> None:
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": toolsets}, clear=False):
            modern_version, modern_tools, modern_capabilities = asyncio.run(self._snapshot("2026-07-28"))
            legacy_version, legacy_tools, legacy_capabilities = asyncio.run(self._snapshot("legacy"))

        self.assertEqual(modern_version, "2026-07-28")
        self.assertEqual(legacy_version, "2025-11-25")
        self.assertEqual([tool.name for tool in modern_tools], [tool.name for tool in legacy_tools])
        modern_contracts = self._serialized_tool_contracts(modern_tools)
        legacy_contracts = self._serialized_tool_contracts(legacy_tools)
        self.assertEqual(len(modern_contracts), len(modern_tools))
        self.assertEqual(len(legacy_contracts), len(legacy_tools))
        self.assertEqual(modern_contracts, legacy_contracts)
        self.assertEqual(modern_capabilities, legacy_capabilities)
        self.assertFalse(any("ctx" in tool.input_schema.get("properties", {}) for tool in modern_tools))

        specs = {tool.name: tool for tool in modern_tools}
        self.assertTrue(specs["gm_project_info"].annotations.read_only_hint)
        self.assertTrue(specs["gm_project_info"].annotations.idempotent_hint)
        self.assertTrue(specs["gm_safe_delete"].annotations.destructive_hint)

    def test_modern_and_legacy_clients_expose_the_same_tool_contract(self):
        for toolsets in ("core", "all"):
            with self.subTest(toolsets=toolsets):
                self._assert_tool_contract_parity(toolsets)

    def test_raw_tool_order_is_deterministic(self):
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "all"}, clear=False):
            server = build_server()
            first = [tool.name for tool in asyncio.run(server.list_tools())]
            second = [tool.name for tool in asyncio.run(server.list_tools())]

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
