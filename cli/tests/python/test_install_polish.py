import unittest
import os
import json
from pathlib import Path
from gms_mcp.install import _make_server_config

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

if __name__ == "__main__":
    unittest.main()
