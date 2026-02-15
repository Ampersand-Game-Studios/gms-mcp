#!/usr/bin/env python3
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _unwrap_call_tool(result):
    """
    FastMCP.call_tool returns a tuple in our runtime:
      ([ContentBlock...], {"result": <tool_return_value>})
    Keep tests tolerant to either (tuple or direct dict) return forms.
    """
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        payload = result[1]
        if "result" in payload:
            return payload["result"]
    if isinstance(result, dict):
        return result
    raise AssertionError(f"Unexpected call_tool return type: {type(result)} ({result!r})")


def _create_basic_gamemaker_project(project_root: Path, *, name: str = "TestProject") -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    # Asset helper validation requires at least one standard asset directory to exist.
    for d in ("objects", "sprites", "scripts", "rooms"):
        (project_root / d).mkdir(parents=True, exist_ok=True)

    yyp_path = project_root / f"{name}.yyp"
    yyp_data = {
        "$GMProject": "",
        "%Name": name,
        "name": name,
        "resources": [],
        "folders": [],
        "resourceType": "GMProject",
        "resourceVersion": "2.0",
    }
    yyp_path.write_text(json.dumps(yyp_data, indent=2), encoding="utf-8")
    return yyp_path


class TestMCPIntegrationTools(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        _create_basic_gamemaker_project(self.project_root)

        from gms_mcp.gamemaker_mcp_server import build_server

        self.mcp = build_server()

    def tearDown(self):
        try:
            self._temp_dir.cleanup()
        except Exception:
            pass

    def test_list_tools_includes_core_entries(self):
        tools = asyncio.run(self.mcp.list_tools())
        names = {t.name for t in tools}

        # Sanity checks: these are stable, core tools.
        self.assertIn("gm_project_info", names)
        self.assertIn("gm_list_assets", names)
        self.assertIn("gm_create_script", names)

    def test_call_gm_project_info_through_server(self):
        # Avoid network in tests (PyPI update check).
        with patch(
            "gms_mcp.server.tools.project_health.check_for_updates",
            return_value={"update_available": False},
        ):
            out = asyncio.run(
                self.mcp.call_tool(
                    "gm_project_info",
                    {"project_root": str(self.project_root)},
                )
            )
        result = _unwrap_call_tool(out)

        self.assertEqual(result.get("yyp"), "TestProject.yyp")
        self.assertEqual(Path(result["project_directory"]).resolve(), self.project_root.resolve())

    def test_call_asset_create_and_list_assets_through_server(self):
        out = asyncio.run(
            self.mcp.call_tool(
                "gm_create_script",
                {"name": "scr_utils", "project_root": str(self.project_root)},
            )
        )
        result = _unwrap_call_tool(out)
        self.assertTrue(result.get("ok"), msg=result.get("error") or result.get("stderr") or result.get("stdout"))

        # Confirm files were actually created in the project.
        self.assertTrue((self.project_root / "scripts" / "scr_utils" / "scr_utils.yy").exists())
        self.assertTrue((self.project_root / "scripts" / "scr_utils" / "scr_utils.gml").exists())

        out = asyncio.run(
            self.mcp.call_tool(
                "gm_list_assets",
                {"asset_type": "script", "project_root": str(self.project_root)},
            )
        )
        assets_result = _unwrap_call_tool(out)
        self.assertGreaterEqual(int(assets_result.get("count", 0)), 1)
        scripts = (assets_result.get("assets") or {}).get("script") or []
        self.assertTrue(any(a.get("name") == "scr_utils" for a in scripts), msg=str(scripts))


if __name__ == "__main__":
    unittest.main()

