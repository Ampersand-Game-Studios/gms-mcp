"""Public CLI contract for the local-only Streamable HTTP transport."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.requests import Request
from starlette.testclient import TestClient

from gms_mcp import gamemaker_mcp_server

HTTP_BEARER_TOKEN = "q8F0Zvr2N3ukMiJ9cLeA5DwyX7sBpR4h"


class MCPV2HTTPTransportTests(unittest.TestCase):
    def test_loopback_streamable_http_uses_stateless_transport(self):
        server = MagicMock()
        with (
            patch.dict(os.environ, {"GMS_MCP_HTTP_BEARER_TOKEN": HTTP_BEARER_TOKEN}, clear=False),
            patch("gms_mcp.gamemaker_mcp_server.build_server", return_value=server) as build_server,
            patch("gms_mcp.gamemaker_mcp_server._record_mcp_event"),
        ):
            exit_code = gamemaker_mcp_server.main(
                ["--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8765", "--path", "/gms"]
            )

        self.assertEqual(exit_code, 0)
        build_server.assert_called_once_with(
            http_auth_value=HTTP_BEARER_TOKEN,
            http_auth_issuer_url="http://127.0.0.1:8765/gms",
        )
        server.run.assert_called_once()
        (transport,) = server.run.call_args.args
        options = server.run.call_args.kwargs
        self.assertEqual(transport, "streamable-http")
        self.assertEqual(options["host"], "127.0.0.1")
        self.assertEqual(options["port"], 8765)
        self.assertEqual(options["streamable_http_path"], "/gms")
        self.assertTrue(options["stateless_http"])
        self.assertEqual(options["max_request_body_size"], gamemaker_mcp_server._HTTP_MAX_REQUEST_BODY_BYTES)
        security = options["transport_security"]
        self.assertTrue(security.enable_dns_rebinding_protection)
        self.assertEqual(security.allowed_hosts, ["127.0.0.1", "127.0.0.1:8765"])
        self.assertEqual(security.allowed_origins, ["http://127.0.0.1:8765"])

    def test_loopback_http_requires_bearer_token_before_server_construction(self):
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("gms_mcp.gamemaker_mcp_server.build_server") as build_server,
            redirect_stderr(stderr),
        ):
            exit_code = gamemaker_mcp_server.main(["--transport", "streamable-http"])

        self.assertEqual(exit_code, 2)
        build_server.assert_not_called()
        self.assertIn("GMS_MCP_HTTP_BEARER_TOKEN", stderr.getvalue())

    def test_loopback_http_rejects_short_bearer_token_before_server_construction(self):
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"GMS_MCP_HTTP_BEARER_TOKEN": "too-short"}, clear=False),
            patch("gms_mcp.gamemaker_mcp_server.build_server") as build_server,
            redirect_stderr(stderr),
        ):
            exit_code = gamemaker_mcp_server.main(["--transport", "streamable-http"])

        self.assertEqual(exit_code, 2)
        build_server.assert_not_called()
        self.assertIn("32-4096", stderr.getvalue())

    def test_loopback_http_rejects_non_bearer_token_characters(self):
        stderr = io.StringIO()
        invalid_token = f"{'a' * 31}£"
        with (
            patch.dict(os.environ, {"GMS_MCP_HTTP_BEARER_TOKEN": invalid_token}, clear=False),
            patch("gms_mcp.gamemaker_mcp_server.build_server") as build_server,
            redirect_stderr(stderr),
        ):
            exit_code = gamemaker_mcp_server.main(["--transport", "streamable-http"])

        self.assertEqual(exit_code, 2)
        build_server.assert_not_called()
        self.assertIn("bearer-token characters", stderr.getvalue())

    def test_non_loopback_http_fails_closed_before_server_construction(self):
        stderr = io.StringIO()
        with patch("gms_mcp.gamemaker_mcp_server.build_server") as build_server, redirect_stderr(stderr):
            exit_code = gamemaker_mcp_server.main(["--transport", "streamable-http", "--host", "0.0.0.0"])

        self.assertEqual(exit_code, 2)
        build_server.assert_not_called()
        self.assertIn("restricted to loopback hosts", stderr.getvalue())

    def test_invalid_http_path_fails_closed(self):
        stderr = io.StringIO()
        with patch("gms_mcp.gamemaker_mcp_server.build_server") as build_server, redirect_stderr(stderr):
            exit_code = gamemaker_mcp_server.main(["--transport", "streamable-http", "--path", "mcp"])

        self.assertEqual(exit_code, 2)
        build_server.assert_not_called()
        self.assertIn("absolute URL path", stderr.getvalue())


class MCPV2HTTPRebindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_security_rejects_unapproved_host_and_origin(self):
        settings = gamemaker_mcp_server._http_transport_security("127.0.0.1", 8765)
        middleware = TransportSecurityMiddleware(settings)

        bad_host = Request({"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"host", b"attacker.test")]})
        bad_origin = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [(b"host", b"127.0.0.1:8765"), (b"origin", b"https://attacker.test")],
            }
        )

        host_response = await middleware.validate_request(bad_host)
        origin_response = await middleware.validate_request(bad_origin)

        if host_response is None:
            raise AssertionError("Expected invalid Host to be rejected")
        self.assertEqual(host_response.status_code, 421)
        if origin_response is None:
            raise AssertionError("Expected invalid Origin to be rejected")
        self.assertEqual(origin_response.status_code, 403)


class MCPV2HTTPAuthenticationAndBodyLimitTests(unittest.TestCase):
    def test_http_app_rejects_missing_credentials_and_oversized_bodies(self):
        fixture_project = Path(__file__).parents[1] / "fixtures" / "mcp-conformance"
        with patch.dict(os.environ, {"GM_PROJECT_ROOT": str(fixture_project)}, clear=False):
            app = gamemaker_mcp_server.build_server(
                http_auth_value=HTTP_BEARER_TOKEN,
                http_auth_issuer_url="http://127.0.0.1:8765/mcp",
            ).streamable_http_app(
                streamable_http_path="/mcp",
                stateless_http=True,
                host="127.0.0.1",
                max_request_body_size=gamemaker_mcp_server._HTTP_MAX_REQUEST_BODY_BYTES,
            )

        with TestClient(app) as client:
            unauthenticated = client.post(
                "/mcp",
                content=b"{}",
                headers={"accept": "application/json", "content-type": "application/json"},
            )
            invalid_token = client.post(
                "/mcp",
                content=b"{}",
                headers={
                    "accept": "application/json",
                    "authorization": "Bearer wrong-token",
                    "content-type": "application/json",
                },
            )
            oversized = client.post(
                "/mcp",
                content=b"x" * (gamemaker_mcp_server._HTTP_MAX_REQUEST_BODY_BYTES + 1),
                headers={
                    "accept": "application/json",
                    "authorization": f"Bearer {HTTP_BEARER_TOKEN}",
                    "content-type": "application/json",
                },
            )

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(invalid_token.status_code, 401)
        self.assertEqual(oversized.status_code, 413)


if __name__ == "__main__":
    unittest.main()
