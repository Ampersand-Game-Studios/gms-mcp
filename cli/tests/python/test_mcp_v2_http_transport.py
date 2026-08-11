"""Public CLI contract for the local-only Streamable HTTP transport."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.requests import Request

from gms_mcp import gamemaker_mcp_server


class MCPV2HTTPTransportTests(unittest.TestCase):
    def test_loopback_streamable_http_uses_stateless_transport(self):
        server = MagicMock()
        with (
            patch("gms_mcp.gamemaker_mcp_server.build_server", return_value=server),
            patch("gms_mcp.gamemaker_mcp_server._record_mcp_event"),
        ):
            exit_code = gamemaker_mcp_server.main(
                ["--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8765", "--path", "/gms"]
            )

        self.assertEqual(exit_code, 0)
        server.run.assert_called_once()
        (transport,) = server.run.call_args.args
        options = server.run.call_args.kwargs
        self.assertEqual(transport, "streamable-http")
        self.assertEqual(options["host"], "127.0.0.1")
        self.assertEqual(options["port"], 8765)
        self.assertEqual(options["streamable_http_path"], "/gms")
        self.assertTrue(options["stateless_http"])
        security = options["transport_security"]
        self.assertTrue(security.enable_dns_rebinding_protection)
        self.assertEqual(security.allowed_hosts, ["127.0.0.1", "127.0.0.1:8765"])
        self.assertEqual(security.allowed_origins, ["http://127.0.0.1:8765"])

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


if __name__ == "__main__":
    unittest.main()
