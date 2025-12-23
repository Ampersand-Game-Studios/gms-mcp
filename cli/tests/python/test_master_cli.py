#!/usr/bin/env python3
"""Test suite for the master CLI."""

import unittest
import subprocess
import sys
import os
from pathlib import Path

class TestMasterCLI(unittest.TestCase):
    """Test the master CLI functionality."""

    def setUp(self):
        """Set up test environment."""
        self.python_exe = sys.executable
        repo_root = Path(__file__).resolve().parents[3]
        self.env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}

    def run_gms_command(self, args):
        """Run a gms command and return result."""
        cmd = [self.python_exe, "-m", "gms_helpers.gms"] + args
        # Run from gamemaker directory so CLI tools find the .yyp file
        repo_root = Path(__file__).resolve().parents[3]
        gamemaker_dir = repo_root / "gamemaker"
        result = subprocess.run(cmd, cwd=str(gamemaker_dir), capture_output=True, text=True, encoding='utf-8', env=self.env)
        return result.returncode, result.stdout, result.stderr

    def test_help_commands(self):
        """Test help functionality."""
        # Main help
        returncode, stdout, stderr = self.run_gms_command(["--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("GameMaker Studio Development Tools", stdout)
        self.assertIn("asset", stdout)
        self.assertIn("event", stdout)
        self.assertIn("workflow", stdout)
        self.assertIn("room", stdout)
        self.assertIn("maintenance", stdout)

        # Category help tests
        categories = ["asset", "event", "workflow", "room", "maintenance"]
        for category in categories:
            returncode, stdout, stderr = self.run_gms_command([category, "--help"])
            self.assertEqual(returncode, 0, f"Failed to get help for {category}")

    def test_asset_commands(self):
        """Test asset command structure."""
        # Test asset help
        returncode, stdout, stderr = self.run_gms_command(["asset", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("create", stdout)
        self.assertIn("delete", stdout)

        # Test asset create help
        returncode, stdout, stderr = self.run_gms_command(["asset", "create", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("script", stdout)
        self.assertIn("object", stdout)
        self.assertIn("sprite", stdout)

        # Test specific asset type help
        returncode, stdout, stderr = self.run_gms_command(["asset", "create", "script", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("--parent-path", stdout)

    def test_event_commands(self):
        """Test event command structure."""
        returncode, stdout, stderr = self.run_gms_command(["event", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("add", stdout)
        self.assertIn("remove", stdout)
        self.assertIn("list", stdout)
        self.assertIn("validate", stdout)
        self.assertIn("fix", stdout)

        # Test event add help
        returncode, stdout, stderr = self.run_gms_command(["event", "add", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("object", stdout)
        self.assertIn("event", stdout)

    def test_workflow_commands(self):
        """Test workflow command structure."""
        returncode, stdout, stderr = self.run_gms_command(["workflow", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("duplicate", stdout)
        self.assertIn("rename", stdout)
        self.assertIn("delete", stdout)
        self.assertIn("swap-sprite", stdout)

    def test_room_commands(self):
        """Test room command structure."""
        returncode, stdout, stderr = self.run_gms_command(["room", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("layer", stdout)
        self.assertIn("ops", stdout)  # Changed from "template" to "ops"
        self.assertIn("instance", stdout)

        # Test room layer help
        returncode, stdout, stderr = self.run_gms_command(["room", "layer", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("add", stdout)
        self.assertIn("remove", stdout)
        self.assertIn("list", stdout)

    def test_maintenance_commands(self):
        """Test maintenance command structure."""
        returncode, stdout, stderr = self.run_gms_command(["maintenance", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("auto", stdout)
        self.assertIn("lint", stdout)
        self.assertIn("validate-json", stdout)
        self.assertIn("list-orphans", stdout)

        # Test maintenance auto help
        returncode, stdout, stderr = self.run_gms_command(["maintenance", "auto", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("--fix", stdout)
        self.assertIn("--verbose", stdout)

    def test_version_command(self):
        """Test version flag."""
        returncode, stdout, stderr = self.run_gms_command(["--version"])
        self.assertEqual(returncode, 0)
        self.assertIn("GMS Tools 2.0", stdout)

    def test_invalid_commands(self):
        """Test error handling for invalid commands."""
        # Invalid category
        returncode, stdout, stderr = self.run_gms_command(["invalid"])
        self.assertNotEqual(returncode, 0)

        # Invalid subcommand
        returncode, stdout, stderr = self.run_gms_command(["asset", "invalid"])
        self.assertNotEqual(returncode, 0)

        # Missing required arguments
        returncode, stdout, stderr = self.run_gms_command(["asset", "create", "script"])
        self.assertNotEqual(returncode, 0)

    def test_global_options(self):
        """Test global options like --project-root."""
        # This should work without error
        returncode, stdout, stderr = self.run_gms_command(["--project-root", ".", "maintenance", "list-orphans"])
        # We don't check returncode as it depends on project state
        # Just ensure the option is accepted
        self.assertNotIn("unrecognized arguments", stderr)

if __name__ == "__main__":
    unittest.main()
