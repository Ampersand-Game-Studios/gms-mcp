#!/usr/bin/env python3
import argparse
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_mcp.server import dispatch as server
from gms_mcp.server.direct import _capture_output
from gms_mcp.server.dry_run_policy import _requires_dry_run_for_tool
from gms_mcp.server.results import ToolRunResult


class TestCaptureOutputSystemExit(unittest.TestCase):
    def test_system_exit_nonzero_captured(self):
        def _fn():
            print("hello")
            print("oops", file=sys.stderr)
            raise SystemExit(2)

        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        self.assertFalse(ok)
        self.assertIn("hello", out)
        self.assertIn("oops", err)
        self.assertIsNone(result)
        self.assertIsNotNone(error_text)
        self.assertIn("SystemExit: 2", error_text)
        self.assertEqual(exit_code, 2)
        self.assertIn("stdout:", error_text)
        self.assertIn("stderr:", error_text)
        self.assertIn("hello", error_text)
        self.assertIn("oops", error_text)

    def test_system_exit_zero_ok(self):
        def _fn():
            print("done")
            raise SystemExit(0)

        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        self.assertTrue(ok)
        self.assertIn("done", out)
        self.assertEqual(err, "")
        self.assertIsNone(error_text)
        self.assertEqual(exit_code, 0)


class TestRunWithFallbackDefaults(unittest.TestCase):
    def test_default_uses_cli_when_direct_disabled(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {}, clear=True):
            with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                    result = asyncio.run(
                        server._run_with_fallback(
                            direct_handler=lambda _args: True,
                            direct_args=argparse.Namespace(),
                            cli_args=["unknown", "tool"],
                            project_root=".",
                            prefer_cli=False,
                            output_mode="full",
                            quiet=True,
                        )
                    )

        self.assertFalse(result["direct_used"])
        self.assertTrue(mock_cli.called)
        self.assertFalse(mock_direct.called)

    def test_opt_in_direct_via_env(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "1"}, clear=True):
            # Re-initialize policy manager to pick up env var
            from gms_mcp.execution_policy import PolicyManager
            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                        result = asyncio.run(
                            server._run_with_fallback(
                                direct_handler=lambda _args: True,
                                direct_args=argparse.Namespace(),
                                cli_args=["unknown", "tool"],
                                project_root=".",
                                prefer_cli=False,
                                output_mode="full",
                                quiet=True,
                            )
                        )

        self.assertTrue(result["direct_used"])
        self.assertTrue(mock_direct.called)
        self.assertFalse(mock_cli.called)


class TestDryRunPolicyAllowlist(unittest.TestCase):
    def test_require_dry_run_enforced_without_allowlist(self):
        with patch.dict(os.environ, {"GMS_MCP_REQUIRE_DRY_RUN": "1"}, clear=True):
            self.assertTrue(_requires_dry_run_for_tool("gm_asset_delete"))

    def test_require_dry_run_allowlist_bypasses_named_tool(self):
        with patch.dict(
            os.environ,
            {
                "GMS_MCP_REQUIRE_DRY_RUN": "1",
                "GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST": "gm_asset_delete, gm_workflow_delete",
            },
            clear=True,
        ):
            self.assertFalse(_requires_dry_run_for_tool("gm_asset_delete"))
            self.assertFalse(_requires_dry_run_for_tool("gm_workflow_delete"))
            self.assertTrue(_requires_dry_run_for_tool("gm_room_ops_delete"))

    def test_require_dry_run_allowlist_semicolon_and_case_insensitive(self):
        with patch.dict(
            os.environ,
            {
                "GMS_MCP_REQUIRE_DRY_RUN": "1",
                "GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST": "GM_ASSET_DELETE;GM_WORKFLOW_DELETE",
            },
            clear=True,
        ):
            self.assertFalse(_requires_dry_run_for_tool("gm_asset_delete"))
            self.assertFalse(_requires_dry_run_for_tool("gm_workflow_delete"))


if __name__ == "__main__":
    unittest.main()
