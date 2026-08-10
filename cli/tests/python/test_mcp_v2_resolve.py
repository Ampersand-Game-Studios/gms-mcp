"""Public MCP 2026-07-28 input-required contracts."""

from __future__ import annotations

import asyncio
import unittest
from typing import Annotated

from mcp import Client
from mcp.server.mcpserver import Context, Elicit, MCPServer, Resolve
from mcp.server.request_state import RequestStateSecurity
from mcp.types import ElicitResult, InputRequiredResult
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel

from support.mcp_resolve_conformance import build_server


class NameForm(BaseModel):
    name: str


async def _accept(_context, _params) -> ElicitResult:
    return ElicitResult(action="accept", content={"name": "Ada"})


def _resolve_name() -> Elicit[NameForm]:
    return Elicit("Enter a name", NameForm)


def _requires_form(name: Annotated[NameForm, Resolve(_resolve_name)]) -> str:
    return name.name


class MCPV2ResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_automatically_drives_interim_input_required_result(self):
        async with Client(build_server(), mode="2026-07-28", elicitation_callback=_accept) as client:
            result = await client.call_tool("test_input_required_result_elicitation")

        self.assertFalse(result.is_error)
        self.assertEqual(result.content[0].text, "hello Ada")

    async def test_manual_resume_exposes_typed_interim_result_and_accept_decline_cancel(self):
        async with Client(build_server(), mode="2026-07-28") as client:
            for action in ("accept", "decline", "cancel"):
                initial = await client.session.call_tool(
                    "test_input_required_result_elicitation", allow_input_required=True
                )
                self.assertIsInstance(initial, InputRequiredResult)
                assert isinstance(initial, InputRequiredResult)
                self.assertIn("user_name", initial.input_requests or {})
                final = await client.session.call_tool(
                    "test_input_required_result_elicitation",
                    input_responses={"user_name": ElicitResult(action=action, content={"name": "Ada"})},
                    request_state=initial.request_state,
                    allow_input_required=True,
                )
                self.assertNotIsInstance(final, InputRequiredResult)
                self.assertEqual(final.content[0].text, "hello Ada" if action == "accept" else f"elicitation {action}")

    async def test_resolve_rejects_a_client_without_form_elicitation_capability(self):
        server = MCPServer("missing-form-capability")
        server.tool(name="requires_form")(_requires_form)

        async with Client(server, mode="2026-07-28") as client:
            with self.assertRaises(MCPError) as raised:
                await client.session.call_tool("requires_form", allow_input_required=True)

        self.assertEqual(raised.exception.code, -32021)

    async def test_request_state_rejects_tampering_argument_mismatch_and_expiry(self):
        async def issue_state(ctx: Context, project: str) -> str | InputRequiredResult:
            if (ctx.input_responses or {}).get("confirm") is not None:
                return project
            return InputRequiredResult(request_state="resume", input_requests={"confirm": _form_request()})

        server = MCPServer(
            "sealed-state",
            request_state_security=RequestStateSecurity.ephemeral(ttl=0.01),
        )
        server.tool(name="issue_state")(issue_state)
        async with Client(server, mode="2026-07-28") as client:
            initial = await client.session.call_tool("issue_state", {"project": "one"}, allow_input_required=True)
            assert isinstance(initial, InputRequiredResult)
            response = {"confirm": ElicitResult(action="accept", content={"ok": True})}
            for state, project in ((f"{initial.request_state}x", "one"), (initial.request_state, "two")):
                with self.assertRaises(MCPError) as raised:
                    await client.session.call_tool(
                        "issue_state",
                        {"project": project},
                        input_responses=response,
                        request_state=state,
                        allow_input_required=True,
                    )
                self.assertEqual(raised.exception.code, -32602)

            await asyncio.sleep(0.02)
            with self.assertRaises(MCPError) as raised:
                await client.session.call_tool(
                    "issue_state",
                    {"project": "one"},
                    input_responses=response,
                    request_state=initial.request_state,
                    allow_input_required=True,
                )
        self.assertEqual(raised.exception.code, -32602)


def _form_request():
    from mcp.types import ElicitRequest, ElicitRequestFormParams

    return ElicitRequest(
        params=ElicitRequestFormParams(
            message="Confirm", requested_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}}
        )
    )


if __name__ == "__main__":
    unittest.main()
