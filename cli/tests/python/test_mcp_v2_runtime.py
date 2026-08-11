"""MCP 2.0 runtime contracts independent of a GameMaker installation."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ResourceUpdated, ServerEvent
from mcp.types import TextResourceContents
from mcp.shared.exceptions import MCPError

from gms_mcp.server.mcp_v2 import (
    ASSET_GRAPH_URI,
    MCP_CACHE_HINTS,
    PROJECT_INDEX_URI,
    MCPV2Runtime,
    MutationSerializationMiddleware,
)
from gms_mcp.server.project import ProjectAccessPolicy
from gms_mcp.server.results import mcp_tool_result, unwrap_call_tool_result


def _runtime(project_root: Path, **kwargs: Any) -> MCPV2Runtime:
    root = project_root.resolve()
    return MCPV2Runtime(ProjectAccessPolicy(project_root=root, lexical_root=root), **kwargs)


class MCPV2RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_hints_are_advertised_and_honored_by_modern_client(self):
        calls: list[str] = []

        async def count_requests(ctx, call_next):
            calls.append(ctx.method)
            return await call_next(ctx)

        server = MCPServer("cache-contract", cache_hints=cast(Any, MCP_CACHE_HINTS), middleware=[count_requests])

        @server.resource("test://resource")
        def resource() -> str:
            return "resource"

        async with Client(server, mode="2026-07-28") as client:
            first = await client.list_resources()
            second = await client.list_resources()

        self.assertEqual(first.ttl_ms, 300_000)
        self.assertEqual(first.cache_scope, "public")
        self.assertEqual(second.resources, first.resources)
        self.assertEqual(calls.count("resources/list"), 1)

    async def test_committed_mutation_publishes_both_project_resource_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = _runtime(Path(temp_dir))
            events: list[ServerEvent] = []
            unsubscribe = runtime.subscriptions.subscribe(events.append)
            try:
                async with runtime.mutation_scope():
                    (Path(temp_dir) / "project.yyp").write_text("{}", encoding="utf-8")
                    await asyncio.sleep(0)
                    self.assertEqual(events, [])
                await runtime.publish_committed_mutation()
            finally:
                unsubscribe()

        self.assertTrue(all(isinstance(event, ResourceUpdated) for event in events))
        self.assertEqual(
            [event.uri for event in events if isinstance(event, ResourceUpdated)], [PROJECT_INDEX_URI, ASSET_GRAPH_URI]
        )

    async def test_modern_client_receives_committed_resource_update_subscription(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = _runtime(Path(temp_dir))
            server = MCPServer("subscription-contract", subscriptions=runtime.subscriptions)

            @server.resource(PROJECT_INDEX_URI)
            def project_index() -> str:
                return "{}"

            async with Client(server, mode="2026-07-28") as client:
                async with client.listen(resource_subscriptions=[PROJECT_INDEX_URI]) as subscription:
                    await runtime.publish_committed_mutation()
                    event = await asyncio.wait_for(anext(subscription), timeout=1)

        if not isinstance(event, ResourceUpdated):
            raise AssertionError(f"Expected resource update, got {event!r}")
        self.assertEqual(event.uri, PROJECT_INDEX_URI)

    async def test_external_project_edit_is_debounced_and_published(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = _runtime(root, poll_seconds=0.005, debounce_seconds=0)
            events: list[ServerEvent] = []
            unsubscribe = runtime.subscriptions.subscribe(events.append)
            watcher = asyncio.create_task(runtime.watch_project())
            try:
                (root / "external.gml").write_text("show_debug_message('changed');", encoding="utf-8")
                for _ in range(100):
                    if events:
                        break
                    await asyncio.sleep(0.01)
            finally:
                watcher.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await watcher
                unsubscribe()

        self.assertTrue(all(isinstance(event, ResourceUpdated) for event in events))
        self.assertEqual(
            [event.uri for event in events if isinstance(event, ResourceUpdated)], [PROJECT_INDEX_URI, ASSET_GRAPH_URI]
        )

    async def test_rolled_back_mutation_does_not_publish_resource_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = _runtime(root, poll_seconds=0.005, debounce_seconds=0)
            events: list[ServerEvent] = []
            unsubscribe = runtime.subscriptions.subscribe(events.append)
            watcher = asyncio.create_task(runtime.watch_project())
            try:
                async with runtime.mutation_scope():
                    temporary_change = root / "rolled-back.gml"
                    temporary_change.write_text("temporary", encoding="utf-8")
                    await asyncio.sleep(0.02)
                    temporary_change.unlink()
                await asyncio.sleep(0.03)
            finally:
                watcher.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await watcher
                unsubscribe()

        self.assertEqual(events, [])

    async def test_snapshot_started_during_rollback_is_discarded_after_scope_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = _runtime(root, poll_seconds=0.001, debounce_seconds=0)
            events: list[ServerEvent] = []
            unsubscribe = runtime.subscriptions.subscribe(events.append)
            snapshot_started = threading.Event()
            release_snapshot = threading.Event()

            from gms_mcp.server import mcp_v2

            original_snapshot = mcp_v2._snapshot_project

            def delayed_snapshot(project_root: Path):
                snapshot = original_snapshot(project_root)
                snapshot_started.set()
                release_snapshot.wait(timeout=1)
                return snapshot

            with patch("gms_mcp.server.mcp_v2._snapshot_project", delayed_snapshot):
                watcher = asyncio.create_task(runtime.watch_project())
                try:
                    async with runtime.mutation_scope():
                        temporary_change = root / "overlapped-rollback.gml"
                        temporary_change.write_text("temporary", encoding="utf-8")
                        self.assertTrue(await asyncio.to_thread(snapshot_started.wait, 1))
                        temporary_change.unlink()
                    release_snapshot.set()
                    await asyncio.sleep(0.03)
                finally:
                    release_snapshot.set()
                    watcher.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await watcher
                    unsubscribe()

        self.assertEqual(events, [])

    async def test_mutation_middleware_serializes_writes_but_not_reads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = _runtime(Path(temp_dir))
            middleware = MutationSerializationMiddleware(
                runtime,
                lambda name: name == "gm_project_info",
                lambda result: bool(result.get("committed")) if isinstance(result, dict) else False,
            )
            active_writes = 0
            maximum_writes = 0
            read_started = asyncio.Event()
            release = asyncio.Event()

            async def call_next(ctx):
                nonlocal active_writes, maximum_writes
                if ctx.params["name"] == "gm_project_info":
                    read_started.set()
                    return {"ok": True}
                active_writes += 1
                maximum_writes = max(maximum_writes, active_writes)
                await release.wait()
                active_writes -= 1
                return {"ok": True}

            write_context = lambda: SimpleNamespace(method="tools/call", params={"name": "gm_create_object"})
            read_context = SimpleNamespace(method="tools/call", params={"name": "gm_project_info"})
            first = asyncio.create_task(middleware(cast(Any, write_context()), call_next))
            await asyncio.sleep(0)
            second = asyncio.create_task(middleware(cast(Any, write_context()), call_next))
            await middleware(cast(Any, read_context), call_next)
            self.assertTrue(read_started.is_set())
            release.set()
            await asyncio.gather(first, second)

        self.assertEqual(maximum_writes, 1)

    async def test_structured_tool_failures_set_is_error_without_host_leakage(self):
        result = mcp_tool_result(
            {"ok": False, "error": "bad input", "cwd": "/private/project"},
            project_root="/private/project",
        )

        self.assertTrue(result.is_error)
        payload = unwrap_call_tool_result(result)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "bad input")
        self.assertNotIn("cwd", payload)

    async def test_rfc6570_template_rejects_encoded_path_escape_before_handler_runs(self):
        server = MCPServer("template-contract")
        calls: list[str] = []

        @server.resource("test://asset/{asset_name}")
        def asset(asset_name: str) -> str:
            calls.append(asset_name)
            return asset_name

        async with Client(server, mode="2026-07-28") as client:
            valid = await client.read_resource("test://asset/o_player")
            with self.assertRaises(MCPError):
                await client.read_resource("test://asset/%2E%2E%2Foutside")
            with self.assertRaises(MCPError):
                await client.read_resource("test://asset/%2Ftmp")

        content = valid.contents[0]
        if not isinstance(content, TextResourceContents):
            raise AssertionError(f"Expected text resource content, got {content!r}")
        self.assertEqual(content.text, "o_player")
        self.assertEqual(calls, ["o_player"])


if __name__ == "__main__":
    unittest.main()
