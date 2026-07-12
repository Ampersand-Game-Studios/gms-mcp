from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from gms_mcp.gamemaker_mcp_server import build_server


def _tools(profile: str):
    with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": profile}, clear=False):
        return asyncio.run(build_server().list_tools())


def _unwrap_call_tool(result):
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1].get("result", result[1])
    return result


class TestMCPProfiles(unittest.TestCase):
    def test_default_core_is_curated_and_all_profile_is_complete(self):
        core_specs = _tools("core")
        all_specs = _tools("all")
        core = {tool.name for tool in core_specs}
        all_tools = {tool.name for tool in all_specs}

        self.assertLessEqual(len(core), 35)
        self.assertTrue(core < all_tools)
        self.assertIn("gm_capabilities", core)
        self.assertIn("gm_safe_delete", core)
        self.assertNotIn("gm_create_script", core)
        self.assertNotIn("gm_event_add", core)
        self.assertNotIn("gm_room_instance_add", core)
        self.assertIn("gm_create_script", all_tools)
        self.assertIn("gm_event_add", all_tools)
        self.assertIn("gm_room_instance_add", all_tools)
        self.assertNotIn("gm_cli", all_tools)
        self.assertNotIn("gm_asset_delete", all_tools)
        self.assertNotIn("gm_workflow_delete", all_tools)

    def test_capabilities_reports_restart_time_configuration(self):
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "events,rooms"}, clear=False):
            server = build_server()
            result = _unwrap_call_tool(asyncio.run(server.call_tool("gm_capabilities", {})))

        self.assertTrue(result["ok"])
        self.assertEqual(result["enabled_toolsets"], ["core", "events", "rooms"])
        self.assertIn("assets", result["disabled_toolsets"])
        self.assertTrue(result["configuration"]["restart_required"])

    def test_tool_annotations_describe_read_and_destructive_intent(self):
        specs = {tool.name: tool for tool in _tools("all")}

        self.assertTrue(specs["gm_project_info"].annotations.readOnlyHint)
        self.assertTrue(specs["gm_project_info"].annotations.idempotentHint)
        self.assertTrue(specs["gm_safe_delete"].annotations.destructiveHint)
        self.assertFalse(specs["gm_create_script"].annotations.readOnlyHint)
        self.assertFalse(specs["gm_create_script"].annotations.destructiveHint)

    def test_unknown_toolset_fails_at_server_startup(self):
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "made-up-domain"}, clear=False):
            with self.assertRaisesRegex(ValueError, "Unknown GMS_MCP_TOOLSETS"):
                build_server()


if __name__ == "__main__":
    unittest.main()
