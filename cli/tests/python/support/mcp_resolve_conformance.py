"""Dedicated SEP-2322 fixture server, isolated from the application server."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    CallToolResult,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    ListRootsRequest,
    SamplingMessage,
    TextContent,
)


def _complete(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)])


def _form(message: str, properties: dict[str, Any], required: list[str]) -> ElicitRequest:
    return ElicitRequest(
        params=ElicitRequestFormParams(
            message=message,
            requested_schema={"type": "object", "properties": properties, "required": required},
        )
    )


def _answer(ctx: Context, key: str) -> ElicitResult | None:
    response = (ctx.input_responses or {}).get(key)
    return response if isinstance(response, ElicitResult) else None


def _pending(
    key: str, request: ElicitRequest | CreateMessageRequest | ListRootsRequest, state: str
) -> InputRequiredResult:
    return InputRequiredResult(input_requests={key: request}, request_state=state)


def build_server() -> MCPServer:
    """Build a server exposing the exact official 2026-07-28 scenario names."""
    server = MCPServer("mcp-resolve-conformance")

    @server.tool(name="test_input_required_result_elicitation")
    def elicitation(ctx: Context) -> CallToolResult | InputRequiredResult:
        answer = _answer(ctx, "user_name")
        if answer is None:
            return _pending(
                "user_name",
                _form("Enter a user name", {"name": {"type": "string"}}, ["name"]),
                "elicitation-v1",
            )
        if answer.action == "accept" and answer.content is not None:
            return _complete(f"hello {answer.content.get('name', '')}")
        return _complete(f"elicitation {answer.action}")

    @server.tool(name="test_input_required_result_sampling")
    def sampling(ctx: Context) -> CallToolResult | InputRequiredResult:
        response = (ctx.input_responses or {}).get("sample")
        if response is None:
            return _pending(
                "sample",
                CreateMessageRequest(
                    params=CreateMessageRequestParams(
                        messages=[SamplingMessage(role="user", content=TextContent(text="Reply with Paris."))],
                        max_tokens=16,
                    )
                ),
                "sampling-v1",
            )
        return _complete("sampling complete")

    @server.tool(name="test_input_required_result_list_roots")
    def list_roots(ctx: Context) -> CallToolResult | InputRequiredResult:
        if (ctx.input_responses or {}).get("roots") is None:
            return _pending("roots", ListRootsRequest(), "roots-v1")
        return _complete("roots complete")

    @server.tool(name="test_input_required_result_request_state")
    def request_state(ctx: Context) -> CallToolResult | InputRequiredResult:
        answer = _answer(ctx, "confirmation")
        if answer is None:
            return _pending(
                "confirmation",
                _form("Confirm request state", {"ok": {"type": "boolean"}}, ["ok"]),
                "request-state-v1",
            )
        return _complete("request state complete")

    @server.tool(name="test_input_required_result_multiple_inputs")
    def multiple_inputs(ctx: Context) -> CallToolResult | InputRequiredResult:
        answers = ctx.input_responses or {}
        if {"name", "sample", "roots"}.issubset(answers):
            return _complete("multiple inputs complete")
        return InputRequiredResult(
            input_requests={
                "name": _form("Enter a name", {"name": {"type": "string"}}, ["name"]),
                "sample": CreateMessageRequest(
                    params=CreateMessageRequestParams(
                        messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))], max_tokens=16
                    )
                ),
                "roots": ListRootsRequest(),
            },
            request_state="multiple-v1",
        )

    @server.tool(name="test_input_required_result_multi_round")
    def multi_round(ctx: Context) -> CallToolResult | InputRequiredResult:
        answers = ctx.input_responses or {}
        if ctx.request_state == "round-1" and _answer(ctx, "name") is not None:
            return _pending(
                "color",
                _form("Choose a color", {"color": {"type": "string"}}, ["color"]),
                "round-2",
            )
        if ctx.request_state == "round-2" and _answer(ctx, "color") is not None:
            return _complete("multi-round complete")
        if not answers:
            return _pending(
                "name",
                _form("Enter a name", {"name": {"type": "string"}}, ["name"]),
                "round-1",
            )
        return _pending(
            "name",
            _form("Enter a name", {"name": {"type": "string"}}, ["name"]),
            "round-1",
        )

    @server.tool(name="test_input_required_result_tampered_state")
    def tampered_state(ctx: Context) -> CallToolResult | InputRequiredResult:
        if _answer(ctx, "confirmation") is not None:
            return _complete("tampered state accepted only when sealed")
        return _pending(
            "confirmation",
            _form("Confirm state", {"ok": {"type": "boolean"}}, ["ok"]),
            "tampered-state-v1",
        )

    @server.tool(name="test_input_required_result_capabilities")
    def capabilities(ctx: Context) -> CallToolResult | InputRequiredResult:
        capabilities = ctx.client_capabilities
        if capabilities is not None and capabilities.sampling is not None:
            return _pending(
                "sample",
                CreateMessageRequest(
                    params=CreateMessageRequestParams(
                        messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))], max_tokens=16
                    )
                ),
                "capabilities-v1",
            )
        return _complete("no supported input capability")

    @server.prompt(name="test_input_required_result_prompt")
    def prompt(ctx: Context) -> str | InputRequiredResult:
        answer = _answer(ctx, "context")
        if answer is None:
            return _pending(
                "context",
                _form("Provide context", {"context": {"type": "string"}}, ["context"]),
                "prompt-v1",
            )
        return "prompt complete"

    return server
