import unittest
import os
import json
import tempfile
from pathlib import Path
from gms_mcp.install import (
    _make_server_config,
    _workspace_folder_var,
    _make_claude_code_plugin_manifest,
    _make_claude_code_mcp_config,
    _generate_claude_code_plugin,
)

class TestInstallAutodetect(unittest.TestCase):
    def test_make_server_config_autodetect(self):
        # Set some environment variables to detect
        os.environ["GMS_MCP_GMS_PATH"] = "C:\\path\\to\\gms.exe"
        os.environ["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = "60"
        os.environ["GMS_MCP_ENABLE_DIRECT"] = "1"
        
        try:
            config = _make_server_config(
                client="cursor",
                server_name="gms-test",
                command="gms-mcp",
                args=[],
                gm_project_root_rel_posix="gamemaker"
            )
            
            env = config["mcpServers"]["gms-test"]["env"]
            
            self.assertEqual(env["GMS_MCP_GMS_PATH"], "C:\\path\\to\\gms.exe")
            self.assertEqual(env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"], "60")
            self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "1")
            self.assertEqual(env["GM_PROJECT_ROOT"], "${workspaceFolder}/gamemaker")
            
        finally:
            # Clean up env vars
            for var in ["GMS_MCP_GMS_PATH", "GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "GMS_MCP_ENABLE_DIRECT"]:
                if var in os.environ:
                    del os.environ[var]

    def test_make_server_config_no_autodetect(self):
        # Ensure they AREN'T set
        for var in ["GMS_MCP_GMS_PATH", "GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "GMS_MCP_ENABLE_DIRECT"]:
            if var in os.environ:
                del os.environ[var]
                
        config = _make_server_config(
            client="cursor",
            server_name="gms-test",
            command="gms-mcp",
            args=[],
            gm_project_root_rel_posix=None
        )
        
        env = config["mcpServers"]["gms-test"]["env"]
        
        self.assertNotIn("GMS_MCP_GMS_PATH", env)
        self.assertNotIn("GMS_MCP_DEFAULT_TIMEOUT_SECONDS", env)
        self.assertNotIn("GMS_MCP_ENABLE_DIRECT", env)
        self.assertEqual(env["GM_PROJECT_ROOT"], "${workspaceFolder}")

class TestClaudeCodeSupport(unittest.TestCase):
    """Tests for Claude Code plugin generation."""

    def test_workspace_folder_var_cursor(self):
        """Cursor should use ${workspaceFolder}."""
        self.assertEqual(_workspace_folder_var("cursor"), "${workspaceFolder}")

    def test_workspace_folder_var_vscode(self):
        """VS Code should use ${workspaceFolder}."""
        self.assertEqual(_workspace_folder_var("vscode"), "${workspaceFolder}")

    def test_workspace_folder_var_claude_code(self):
        """Claude Code should use ${CLAUDE_PROJECT_DIR}."""
        self.assertEqual(_workspace_folder_var("claude-code"), "${CLAUDE_PROJECT_DIR}")

    def test_workspace_folder_var_claude_code_global(self):
        """Claude Code global should use ${CLAUDE_PROJECT_DIR}."""
        self.assertEqual(_workspace_folder_var("claude-code-global"), "${CLAUDE_PROJECT_DIR}")

    def test_make_claude_code_plugin_manifest_structure(self):
        """Plugin manifest should have required fields."""
        manifest = _make_claude_code_plugin_manifest()

        self.assertIn("name", manifest)
        self.assertEqual(manifest["name"], "gms-mcp")
        self.assertIn("description", manifest)
        self.assertIn("version", manifest)
        self.assertIn("author", manifest)
        self.assertIn("name", manifest["author"])
        self.assertIn("repository", manifest)
        self.assertIn("license", manifest)
        self.assertIn("keywords", manifest)
        self.assertIsInstance(manifest["keywords"], list)

    def test_make_claude_code_mcp_config_structure(self):
        """MCP config should have correct structure with CLAUDE_PROJECT_DIR."""
        config = _make_claude_code_mcp_config(
            server_name="gms",
            command="gms-mcp",
            args=[],
        )

        self.assertIn("gms", config)
        server = config["gms"]
        self.assertEqual(server["command"], "gms-mcp")
        self.assertEqual(server["args"], [])
        self.assertIn("env", server)
        self.assertEqual(server["env"]["GM_PROJECT_ROOT"], "${CLAUDE_PROJECT_DIR}")
        self.assertEqual(server["env"]["PYTHONUNBUFFERED"], "1")

    def test_make_claude_code_mcp_config_custom_server_name(self):
        """MCP config should use custom server name."""
        config = _make_claude_code_mcp_config(
            server_name="custom-gms",
            command="python",
            args=["-m", "gms_mcp.bootstrap_server"],
        )

        self.assertIn("custom-gms", config)
        self.assertNotIn("gms", config)
        server = config["custom-gms"]
        self.assertEqual(server["command"], "python")
        self.assertEqual(server["args"], ["-m", "gms_mcp.bootstrap_server"])

    def test_make_claude_code_mcp_config_env_autodetect(self):
        """MCP config should include detected environment variables."""
        os.environ["GMS_MCP_GMS_PATH"] = "/path/to/gms"
        os.environ["GMS_MCP_ENABLE_DIRECT"] = "1"

        try:
            config = _make_claude_code_mcp_config(
                server_name="gms",
                command="gms-mcp",
                args=[],
            )

            env = config["gms"]["env"]
            self.assertEqual(env["GMS_MCP_GMS_PATH"], "/path/to/gms")
            self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "1")
        finally:
            del os.environ["GMS_MCP_GMS_PATH"]
            del os.environ["GMS_MCP_ENABLE_DIRECT"]

    def test_generate_claude_code_plugin_dry_run(self):
        """Dry run should not create files but return paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"

            written = _generate_claude_code_plugin(
                plugin_dir=plugin_dir,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
            )

            # Should return expected paths
            self.assertEqual(len(written), 2)
            self.assertTrue(any(".claude-plugin" in str(p) for p in written))
            self.assertTrue(any(".mcp.json" in str(p) for p in written))

            # But files should NOT exist (dry run)
            self.assertFalse(plugin_dir.exists())

    def test_generate_claude_code_plugin_creates_files(self):
        """Plugin generation should create correct file structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "gms-mcp"

            written = _generate_claude_code_plugin(
                plugin_dir=plugin_dir,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=False,
            )

            # Files should exist
            manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
            mcp_config_path = plugin_dir / ".mcp.json"

            self.assertTrue(manifest_path.exists())
            self.assertTrue(mcp_config_path.exists())

            # Validate manifest content
            with open(manifest_path) as f:
                manifest = json.load(f)
            self.assertEqual(manifest["name"], "gms-mcp")

            # Validate MCP config content
            with open(mcp_config_path) as f:
                mcp_config = json.load(f)
            self.assertIn("gms", mcp_config)
            self.assertEqual(mcp_config["gms"]["env"]["GM_PROJECT_ROOT"], "${CLAUDE_PROJECT_DIR}")


if __name__ == "__main__":
    unittest.main()
