"""Loopback HTTP coverage for the 2026-07-28 input-required retry path."""

from __future__ import annotations

import asyncio
import socket
import unittest

import uvicorn
from mcp import Client
from mcp.types import ElicitResult

from support.mcp_resolve_conformance import build_server


async def _accept(_context, _params) -> ElicitResult:
    return ElicitResult(action="accept", content={"name": "Ada"})


class MCPV2ResolveHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stateless_loopback_http_retries_the_same_tool_over_multiple_posts(self):
        posts = 0
        app = build_server().streamable_http_app(streamable_http_path="/mcp", stateless_http=True, host="127.0.0.1")

        async def counted_app(scope, receive, send):
            nonlocal posts
            if scope["type"] == "http" and scope["method"] == "POST":
                posts += 1
            await app(scope, receive, send)

        with socket.socket() as reserved_socket:
            reserved_socket.bind(("127.0.0.1", 0))
            port = reserved_socket.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(counted_app, host="127.0.0.1", port=port, log_level="error"))
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(server.started, "loopback fixture did not start")
            async with Client(
                f"http://127.0.0.1:{port}/mcp", mode="2026-07-28", elicitation_callback=_accept
            ) as client:
                result = await client.call_tool("test_input_required_result_elicitation")
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=5)

        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "hello Ada")
        self.assertGreaterEqual(posts, 2)


if __name__ == "__main__":
    unittest.main()
