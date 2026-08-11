"""End-to-end MCP v2 features exposed by the public GMS server factory."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mcp import Client
from mcp.client.extension import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ResourceUpdated
from mcp.types import TextContent, TextResourceContents

from gms_mcp.gamemaker_mcp_server import build_server


def _text_content(content: object) -> str:
    if not isinstance(content, TextContent):
        raise AssertionError(f"Expected text tool content, got {content!r}")
    return content.text


def _text_resource_content(content: object) -> TextResourceContents:
    if not isinstance(content, TextResourceContents):
        raise AssertionError(f"Expected text resource content, got {content!r}")
    return content


def _structured_content(result: object) -> dict[str, object]:
    structured = getattr(result, "structured_content", None)
    if not isinstance(structured, dict):
        raise AssertionError(f"Expected structured tool result, got {structured!r}")
    return structured


class GMSMCPV2FeatureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "TestGame.yyp").write_text(
            json.dumps({"name": "TestGame", "resources": [], "Folders": []}), encoding="utf-8"
        )
        self.environ = patch.dict(
            os.environ,
            {"GM_PROJECT_ROOT": str(self.project_root), "GMS_MCP_TOOLSETS": "core"},
            clear=False,
        )
        self.environ.start()

    def tearDown(self) -> None:
        self.environ.stop()
        self.temp_dir.cleanup()

    async def test_modern_client_exposes_apps_templates_and_cache_hints(self):
        server = build_server()
        apps_client = advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})

        async with Client(server, mode="2026-07-28", extensions=[apps_client]) as client:
            tool_result = await client.list_tools()
            resource_result = await client.list_resources()
            template_result = await client.list_resource_templates()
            dashboard = await client.call_tool("gm_project_dashboard", {})
            ui = await client.read_resource("ui://gms-mcp/project-dashboard.html")

        dashboard_tool = next(tool for tool in tool_result.tools if tool.name == "gm_project_dashboard")
        if not isinstance(dashboard_tool.meta, dict) or not isinstance(dashboard_tool.meta.get("ui"), dict):
            raise AssertionError(f"Expected MCP Apps tool metadata, got {dashboard_tool.meta!r}")
        self.assertEqual(tool_result.ttl_ms, 300_000)
        self.assertEqual(tool_result.cache_scope, "public")
        self.assertEqual(dashboard_tool.meta["ui"]["resourceUri"], "ui://gms-mcp/project-dashboard.html")
        self.assertEqual(_structured_content(dashboard)["project_name"], "TestGame")
        self.assertFalse(dashboard.is_error)
        self.assertIn("TestGame contains", _text_content(dashboard.content[0]))
        self.assertEqual(ui.contents[0].mime_type, APP_MIME_TYPE)
        self.assertIn("ui/initialize", _text_resource_content(ui.contents[0]).text)
        self.assertIn(
            "gms://project/assets/{asset_type}/{asset_name}",
            [t.uri_template for t in template_result.resource_templates],
        )
        self.assertIn("gms://project/rooms/{room_name}", [t.uri_template for t in template_result.resource_templates])
        self.assertIn("ui://gms-mcp/project-dashboard.html", [str(r.uri) for r in resource_result.resources])

    async def test_dashboard_has_a_text_result_for_clients_without_apps(self):
        async with Client(build_server(), mode="2026-07-28") as client:
            result = await client.call_tool("gm_project_dashboard", {})

        self.assertFalse(result.is_error)
        self.assertIn("TestGame contains", _text_content(result.content[0]))
        self.assertEqual(_structured_content(result)["project_name"], "TestGame")

    async def test_dashboard_failure_is_structured_and_does_not_leak_host_details(self):
        with patch(
            "gms_helpers.introspection.get_project_stats",
            side_effect=RuntimeError("/private/secret"),
        ):
            async with Client(build_server(), mode="2026-07-28") as client:
                result = await client.call_tool("gm_project_dashboard", {})

        payload = _structured_content(result)["result"]
        if not isinstance(payload, dict):
            raise AssertionError(f"Expected structured error payload, got {payload!r}")
        self.assertTrue(result.is_error)
        self.assertEqual(payload["error_code"], "internal_error")
        self.assertNotIn("/private/secret", _text_content(result.content[0]))

    async def test_project_access_failure_is_a_structured_tool_error(self):
        async with Client(build_server(), mode="2026-07-28") as client:
            result = await client.call_tool("gm_project_info", {"project_root": "../outside"})

        self.assertTrue(result.is_error)
        payload = _structured_content(result)["result"]
        if not isinstance(payload, dict):
            raise AssertionError(f"Expected structured error payload, got {payload!r}")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "project_access_denied")
        self.assertNotIn(str(self.project_root.parent), _text_content(result.content[0]))

    async def test_external_project_edit_reaches_a_modern_client_subscription(self):
        async with Client(build_server(), mode="2026-07-28") as client:
            async with client.listen(resource_subscriptions=["gms://project/index"]) as subscription:
                (self.project_root / "external_edit.gml").write_text(
                    "show_debug_message('external');", encoding="utf-8"
                )
                event = await asyncio.wait_for(anext(subscription), timeout=3)

        if not isinstance(event, ResourceUpdated):
            raise AssertionError(f"Expected resource update, got {event!r}")
        self.assertEqual(event.uri, "gms://project/index")

    async def test_committed_mutation_reaches_a_modern_client_subscription(self):
        for directory in ("objects", "sprites", "scripts", "rooms", "texturegroups"):
            (self.project_root / directory).mkdir()
        with patch.dict(
            os.environ,
            {"GMS_MCP_TOOLSETS": "all", "GMS_MCP_POST_MUTATION_VERIFY": "off"},
            clear=False,
        ):
            async with Client(build_server(), mode="2026-07-28") as client:
                async with client.listen(resource_subscriptions=["gms://project/index"]) as subscription:
                    result = await client.call_tool("gm_create_script", {"name": "scr_subscription"})
                    event = await asyncio.wait_for(anext(subscription), timeout=3)

        self.assertFalse(result.is_error)
        self.assertTrue((self.project_root / "scripts" / "scr_subscription" / "scr_subscription.yy").exists())
        if not isinstance(event, ResourceUpdated):
            raise AssertionError(f"Expected resource update, got {event!r}")
        self.assertEqual(event.uri, "gms://project/index")

    async def test_committed_sync_mutation_reaches_a_modern_client_subscription(self):
        def create_texture_group(project_directory, *_args, **_kwargs):
            (Path(project_directory) / "sync-mutation.marker").write_text("committed", encoding="utf-8")
            return {"ok": True, "name": "SyncSubscription"}

        with (
            patch.dict(
                os.environ,
                {"GMS_MCP_TOOLSETS": "all", "GMS_MCP_POST_MUTATION_VERIFY": "off"},
                clear=False,
            ),
            patch(
                "gms_helpers.texture_group.mutations.texture_group_create",
                side_effect=create_texture_group,
            ),
        ):
            async with Client(build_server(), mode="2026-07-28") as client:
                async with client.listen(resource_subscriptions=["gms://project/index"]) as subscription:
                    result = await client.call_tool("gm_texture_group_create", {"name": "SyncSubscription"})
                    event = await asyncio.wait_for(anext(subscription), timeout=3)

        self.assertFalse(result.is_error)
        self.assertTrue((self.project_root / "sync-mutation.marker").exists())
        if not isinstance(event, ResourceUpdated):
            raise AssertionError(f"Expected resource update, got {event!r}")
        self.assertEqual(event.uri, "gms://project/index")


class MCPV2SDKExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_enters_once_and_sync_tools_run_in_a_worker_thread(self):
        lifecycle: list[str] = []
        event_loop_thread = threading.get_ident()

        @asynccontextmanager
        async def lifespan(_server):
            lifecycle.append("enter")
            try:
                yield {"ready": True}
            finally:
                lifecycle.append("exit")

        server = MCPServer("execution-contract", lifespan=lifespan)

        @server.tool()
        def sync_thread_id() -> int:
            return threading.get_ident()

        async with Client(server, mode="2026-07-28") as client:
            first = await client.call_tool("sync_thread_id", {})
            second = await client.call_tool("sync_thread_id", {})

        self.assertEqual(lifecycle, ["enter", "exit"])
        self.assertNotEqual(int(_text_content(first.content[0])), event_loop_thread)
        self.assertNotEqual(int(_text_content(second.content[0])), event_loop_thread)


if __name__ == "__main__":
    unittest.main()
