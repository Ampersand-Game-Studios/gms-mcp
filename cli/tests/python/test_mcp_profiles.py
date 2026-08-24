from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from gms_mcp.gamemaker_mcp_server import build_server
from gms_mcp.server.results import unwrap_call_tool_result


def _tools(profile: str):
    with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": profile}, clear=False):
        return asyncio.run(build_server().list_tools())


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
            result = unwrap_call_tool_result(asyncio.run(server.call_tool("gm_capabilities", {})))

        self.assertTrue(result["ok"])
        self.assertEqual(result["enabled_toolsets"], ["core", "events", "rooms"])
        self.assertIn("assets", result["disabled_toolsets"])
        self.assertTrue(result["configuration"]["restart_required"])

    def test_tool_annotations_describe_read_and_destructive_intent(self):
        specs = {tool.name: tool for tool in _tools("all")}

        self.assertTrue(specs["gm_project_info"].annotations.read_only_hint)
        self.assertTrue(specs["gm_project_info"].annotations.idempotent_hint)
        self.assertTrue(specs["gm_safe_delete"].annotations.destructive_hint)
        self.assertFalse(specs["gm_create_script"].annotations.read_only_hint)
        self.assertFalse(specs["gm_create_script"].annotations.destructive_hint)

    def test_unknown_toolset_fails_at_server_startup(self):
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "made-up-domain"}, clear=False):
            with self.assertRaisesRegex(ValueError, "Unknown GMS_MCP_TOOLSETS"):
                build_server()

    def test_read_only_core_omits_project_mutators(self):
        with patch.dict(
            os.environ,
            {"GMS_MCP_TOOLSETS": "core", "GMS_MCP_READ_ONLY": "1"},
            clear=False,
        ):
            tools = {tool.name for tool in asyncio.run(build_server().list_tools())}

        self.assertIn("gm_project_info", tools)
        self.assertNotIn("gm_safe_delete", tools)
        self.assertNotIn("gm_workflow_rename", tools)
        self.assertNotIn("gm_sprite_add_frame", tools)
        self.assertNotIn("gm_run", tools)
        self.assertNotIn("gm_run_stop", tools)
        self.assertNotIn("gm_run_status", tools)
        self.assertNotIn("gm_compile", tools)
        self.assertNotIn("gm_verification_status", tools)
        self.assertNotIn("gm_verification_flush", tools)
        self.assertNotIn("gm_build_index", tools)

    def test_resourcetool_has_no_caller_selected_path_or_timeout(self):
        specs = {tool.name: tool for tool in _tools("resourcetool")}

        schema = specs["gm_resourcetool_validate"].input_schema
        self.assertEqual(schema.get("properties", {}), {})

    def test_read_only_rejects_optional_toolsets(self):
        with patch.dict(
            os.environ,
            {"GMS_MCP_TOOLSETS": "assets", "GMS_MCP_READ_ONLY": "1"},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "READ_ONLY"):
                build_server()


if __name__ == "__main__":
    unittest.main()
