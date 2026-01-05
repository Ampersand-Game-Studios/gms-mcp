#!/usr/bin/env python3
import unittest
import sys
import os
import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src directory to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_mcp.execution_policy import policy_manager, ExecutionMode, ToolPolicy, PolicyManager
from gms_mcp import gamemaker_mcp_server as server

class TestExecutionPolicy(unittest.TestCase):
    def test_default_detection(self):
        """Test that default mode is detected from environment."""
        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "1"}):
            pm = PolicyManager()
            self.assertEqual(pm._default_mode, ExecutionMode.DIRECT)
            
        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "0"}):
            pm = PolicyManager()
            self.assertEqual(pm._default_mode, ExecutionMode.SUBPROCESS)

    def test_tool_specific_policy(self):
        """Test that specific tools have their own policies."""
        pm = PolicyManager()
        
        # Introspection should be DIRECT
        self.assertEqual(pm.get_policy("gm-list-assets").mode, ExecutionMode.DIRECT)
        
        # Runner should be SUBPROCESS
        self.assertEqual(pm.get_policy("run-start").mode, ExecutionMode.SUBPROCESS)
        
        # Unknown tool should use default (SUBPROCESS)
        self.assertEqual(pm.get_policy("unknown-tool").mode, ExecutionMode.SUBPROCESS)

    def test_override_policy(self):
        """Test overriding a policy."""
        pm = PolicyManager()
        pm.set_policy("my-tool", ToolPolicy(mode=ExecutionMode.DIRECT, timeout_seconds=10))
        
        policy = pm.get_policy("my-tool")
        self.assertEqual(policy.mode, ExecutionMode.DIRECT)
        self.assertEqual(policy.timeout_seconds, 10)

class TestServerPolicyIntegration(unittest.TestCase):
    @patch("gms_mcp.gamemaker_mcp_server._run_direct")
    @patch("gms_mcp.gamemaker_mcp_server._run_cli_async")
    def test_run_with_fallback_uses_policy(self, mock_cli, mock_direct):
        """Test that _run_with_fallback respects the policy manager."""
        mock_direct.return_value = server.ToolRunResult(ok=True, stdout="direct", stderr="", direct_used=True)
        
        async def _fake_cli(*args, **kwargs):
            return server.ToolRunResult(ok=True, stdout="cli", stderr="", direct_used=False)
        mock_cli.side_effect = _fake_cli

        # Force a tool to be SUBPROCESS
        policy_manager.set_policy("test-tool", ToolPolicy(mode=ExecutionMode.SUBPROCESS))
        
        import asyncio
        result = asyncio.run(server._run_with_fallback(
            direct_handler=lambda x: True,
            direct_args=argparse.Namespace(),
            cli_args=["test", "tool"],
            project_root=".",
            prefer_cli=False,
            tool_name="test-tool"
        ))
        
        self.assertFalse(result["direct_used"])
        self.assertTrue(mock_cli.called)
        self.assertFalse(mock_direct.called)

        # Force the same tool to be DIRECT
        mock_cli.reset_mock()
        mock_direct.reset_mock()
        policy_manager.set_policy("test-tool", ToolPolicy(mode=ExecutionMode.DIRECT))
        
        result = asyncio.run(server._run_with_fallback(
            direct_handler=lambda x: True,
            direct_args=argparse.Namespace(),
            cli_args=["test", "tool"],
            project_root=".",
            prefer_cli=False,
            tool_name="test-tool"
        ))
        
        self.assertTrue(result["direct_used"])
        self.assertTrue(mock_direct.called)
        self.assertFalse(mock_cli.called)

if __name__ == "__main__":
    unittest.main()
