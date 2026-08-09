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

        tools_with_output_mode = 0
        for tool in tools.values():
            properties = tool.input_schema.get("properties", {})
            if "output_mode" not in properties:
                continue
            tools_with_output_mode += 1
            self.assertEqual(
                collect_enum_values(properties["output_mode"]),
                output_mode_values,
                tool.name,
            )
        self.assertGreater(tools_with_output_mode, 50)


if __name__ == "__main__":
    unittest.main()
