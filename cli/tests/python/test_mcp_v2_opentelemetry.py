"""The SDK's built-in OpenTelemetry middleware remains observable in GMS MCP."""

from __future__ import annotations

import time
import unittest

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared._otel import extract_trace_context
from mcp.types import CallToolResult, TextContent
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class MCPV2OpenTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_builtin_middleware_emits_a_structured_tool_error_span(self):
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        server = MCPServer("otel-contract")

        @server.tool()
        def failing_tool() -> CallToolResult:
            return CallToolResult(content=[TextContent(type="text", text="expected failure")], is_error=True)

        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool("failing_tool", {})

        self.assertTrue(result.is_error)
        span = next(span for span in exporter.get_finished_spans() if span.name == "tools/call failing_tool")
        attributes = dict(span.attributes or {})
        self.assertEqual(attributes["mcp.method.name"], "tools/call")
        self.assertEqual(attributes["mcp.protocol.version"], "2026-07-28")
        self.assertEqual(attributes["gen_ai.operation.name"], "execute_tool")
        self.assertEqual(attributes["gen_ai.tool.name"], "failing_tool")
        self.assertEqual(attributes["error.type"], "tool_error")

    def test_a_crafted_traceparent_is_parsed_in_linear_time(self):
        # GHSA-mf5v-w3w3-f6cg: before opentelemetry-api 1.45.2 this took tens of seconds.
        traceparent = "00-" + "a" * 32 + "-" + "b" * 16 + "-01-" + " " * 100_000 + "\nx"
        started = time.perf_counter()
        context = extract_trace_context({"traceparent": traceparent})
        self.assertIsNone(context)
        self.assertLess(time.perf_counter() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
