#!/usr/bin/env python3
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    for d in ("objects", "sprites", "scripts", "rooms", "texturegroups"):
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
        "configs": {
            "name": "Default",
            "children": [
                {"name": "desktop", "children": []},
            ],
        },
        "TextureGroups": [
            {
                "$GMTextureGroup": "",
                "%Name": "Default",
                "name": "Default",
                "resourceType": "GMTextureGroup",
                "resourceVersion": "2.0",
                "ConfigValues": {},
            }
        ],
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

    def _call_tool(self, tool_name: str, arguments: dict):
        out = asyncio.run(self.mcp.call_tool(tool_name, arguments))
        return _unwrap_call_tool(out)

    def test_list_tools_includes_core_entries(self):
        tools = asyncio.run(self.mcp.list_tools())
        names = {t.name for t in tools}

        # Sanity checks: these are stable, core tools.
        self.assertIn("gm_project_info", names)
        self.assertIn("gm_list_assets", names)
        self.assertIn("gm_create_script", names)
        self.assertIn("gm_texture_group_list", names)

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

    def test_tool_registration_parity_includes_critical_categories(self):
        tools = asyncio.run(self.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertGreaterEqual(len(names), 94)

        expected = {
            "gm_project_info",
            "gm_create_script",
            "gm_list_assets",
            "gm_maintenance_validate_json",
            "gm_runtime_list",
            "gm_run_status",
            "gm_bridge_status",
            "gm_doc_categories",
            "gm_event_list",
            "gm_workflow_delete",
            "gm_room_ops_list",
            "gm_texture_group_list",
            "gm_texture_group_assign",
            "gm_list_symbols",
        }
        self.assertTrue(expected.issubset(names), msg=f"Missing critical tools: {sorted(expected - names)}")

    def test_smoke_calls_across_tool_categories(self):
        with patch(
            "gms_mcp.server.tools.project_health.check_for_updates",
            return_value={"update_available": False},
        ):
            project_info = self._call_tool("gm_project_info", {"project_root": str(self.project_root)})
        self.assertEqual(project_info.get("yyp"), "TestProject.yyp")

        create_script = self._call_tool(
            "gm_create_script",
            {"name": "scr_utils", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_script.get("ok"), msg=create_script.get("error") or create_script.get("stdout"))

        create_object = self._call_tool(
            "gm_create_object",
            {"name": "o_player", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_object.get("ok"), msg=create_object.get("error") or create_object.get("stdout"))

        create_room = self._call_tool(
            "gm_create_room",
            {"name": "r_main", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_room.get("ok"), msg=create_room.get("error") or create_room.get("stdout"))

        introspection = self._call_tool(
            "gm_list_assets",
            {"asset_type": "script", "project_root": str(self.project_root)},
        )
        self.assertGreaterEqual(int(introspection.get("count", 0)), 1)

        maintenance = self._call_tool(
            "gm_maintenance_validate_json",
            {"project_root": str(self.project_root)},
        )
        self.assertIn("ok", maintenance)

        runtime = self._call_tool(
            "gm_runtime_list",
            {"project_root": str(self.project_root)},
        )
        self.assertIn("count", runtime)
        self.assertIn("runtimes", runtime)

        runner_status = self._call_tool(
            "gm_run_status",
            {"project_root": str(self.project_root)},
        )
        self.assertIn("running", runner_status)
        self.assertIn("has_session", runner_status)

        fake_bridge_server = SimpleNamespace(get_status=lambda: {"running": True, "connected": False, "log_count": 0})
        with patch("gms_helpers.bridge_installer.get_bridge_status", return_value={"installed": True}), patch(
            "gms_helpers.bridge_server.get_bridge_server",
            return_value=fake_bridge_server,
        ):
            bridge_status = self._call_tool(
                "gm_bridge_status",
                {"project_root": str(self.project_root)},
            )
        self.assertTrue(bridge_status.get("ok"))
        self.assertTrue(bridge_status.get("installed"))

        with patch("gms_helpers.gml_docs.list_categories", return_value={"ok": True, "categories": ["Drawing"]}):
            docs = self._call_tool("gm_doc_categories", {})
        self.assertTrue(docs.get("ok"))
        self.assertIn("categories", docs)

        event_add = self._call_tool(
            "gm_event_add",
            {"object": "o_player", "event": "create", "project_root": str(self.project_root)},
        )
        self.assertTrue(event_add.get("ok"), msg=event_add.get("error") or event_add.get("stdout"))

        events = self._call_tool(
            "gm_event_list",
            {"object": "o_player", "project_root": str(self.project_root)},
        )
        self.assertTrue(events.get("ok"), msg=events.get("error") or events.get("stdout"))

        workflow_delete = self._call_tool(
            "gm_workflow_delete",
            {
                "asset_path": "scripts/scr_utils/scr_utils.yy",
                "dry_run": True,
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(workflow_delete.get("ok"), msg=workflow_delete.get("error") or workflow_delete.get("stdout"))
        self.assertIn("dry-run", (workflow_delete.get("stdout") or "").lower())

        rooms = self._call_tool(
            "gm_room_ops_list",
            {"project_root": str(self.project_root)},
        )
        self.assertTrue(rooms.get("ok"), msg=rooms.get("error") or rooms.get("stdout"))

        texture_groups = self._call_tool(
            "gm_texture_group_list",
            {"project_root": str(self.project_root)},
        )
        self.assertTrue(texture_groups.get("ok"))
        self.assertGreaterEqual(int(texture_groups.get("count", 0)), 1)

    def test_safe_delete_tool_dry_run_and_apply(self):
        create_target = self._call_tool(
            "gm_create_script",
            {"name": "scr_target", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_target.get("ok"), msg=create_target.get("error") or create_target.get("stdout"))

        create_caller = self._call_tool(
            "gm_create_script",
            {"name": "scr_caller", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_caller.get("ok"), msg=create_caller.get("error") or create_caller.get("stdout"))

        caller_file = self.project_root / "scripts" / "scr_caller" / "scr_caller.gml"
        caller_file.write_text("function scr_caller() {\n    script_execute(scr_target);\n}\n", encoding="utf-8")

        dry_run = self._call_tool(
            "gm_safe_delete",
            {
                "asset_type": "script",
                "asset_name": "scr_target",
                "dry_run": True,
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(dry_run.get("blocked"))
        self.assertFalse(dry_run.get("deleted"))

        applied = self._call_tool(
            "gm_safe_delete",
            {
                "asset_type": "script",
                "asset_name": "scr_target",
                "dry_run": False,
                "force": True,
                "clean_refs": True,
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(applied.get("ok"), msg=applied)
        self.assertTrue(applied.get("deleted"), msg=applied)
        self.assertGreaterEqual(int(applied.get("cleaned_refs", {}).get("replacements", 0)), 1)
        self.assertFalse((self.project_root / "scripts" / "scr_target").exists())

        build_index = self._call_tool(
            "gm_build_index",
            {"project_root": str(self.project_root), "force": True},
        )
        self.assertTrue(build_index.get("ok"), msg=build_index.get("error") or build_index.get("stdout"))

        symbols = self._call_tool(
            "gm_list_symbols",
            {"project_root": str(self.project_root), "max_results": 5},
        )
        self.assertTrue(symbols.get("ok"), msg=symbols.get("error") or symbols.get("stdout"))


if __name__ == "__main__":
    unittest.main()
