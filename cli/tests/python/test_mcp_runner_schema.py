from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from gms_mcp.gamemaker_mcp_server import build_server


def collect_enum_values(schema: object) -> set[str]:
    if isinstance(schema, dict):
        values = set(schema.get("enum", []))
        for value in schema.values():
            values.update(collect_enum_values(value))
        return values
    if isinstance(schema, list):
        values: set[str] = set()
        for value in schema:
            values.update(collect_enum_values(value))
        return values
    return set()


class MCPRunnerSchemaTests(unittest.TestCase):
    def test_runner_schemas_expose_platform_and_output_mode_enums(self):
        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "all"}, clear=False):
            tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
        platform_values = {"Windows", "macOS", "Linux", "HTML5", "Android", "iOS", "GX.games"}
        output_mode_values = {"full", "tail", "none"}

        for tool_name in ("gm_compile", "gm_run"):
            properties = tools[tool_name].input_schema["properties"]
            self.assertEqual(collect_enum_values(properties["platform"]), platform_values)
            self.assertEqual(collect_enum_values(properties["output_mode"]), output_mode_values)

        for tool_name in ("gm_run_stop", "gm_run_status"):
            properties = tools[tool_name].input_schema["properties"]
            self.assertEqual(collect_enum_values(properties["output_mode"]), output_mode_values)

        # Only runner tools expose output_mode / tail_lines in their listed schemas; other tools
        # hide those and legacy maintenance flags while still accepting them if passed.
        tools_with_output_mode = {
            tool.name for tool in tools.values() if "output_mode" in tool.input_schema.get("properties", {})
        }
        self.assertEqual(tools_with_output_mode, {"gm_compile", "gm_run", "gm_run_stop", "gm_run_status"})
        create_props = tools["gm_create_script"].input_schema["properties"]
        for hidden in ("output_mode", "tail_lines", "skip_maintenance", "no_auto_fix", "maintenance_verbose"):
            self.assertNotIn(hidden, create_props)


if __name__ == "__main__":
    unittest.main()
