#!/usr/bin/env python3
"""Test suite for agent setup functionality."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"


class TestAgentSetup(unittest.TestCase):
    """Test the agent setup functionality."""

    def setUp(self):
        """Set up test environment."""
        self.agent_setup_script = SRC_ROOT / "gms_helpers" / "agent_setup.py"
        self.gms_script = SRC_ROOT / "gms_helpers" / "gms.py"
        self.python_exe = sys.executable
        self.env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}

        self.original_cwd = os.getcwd()
        gamemaker_dir = PROJECT_ROOT / "gamemaker"
        if gamemaker_dir.exists():
            os.chdir(gamemaker_dir)

    def tearDown(self):
        """Clean up test environment."""
        os.chdir(self.original_cwd)

    def test_gms_script_exists(self):
        """Test that the gms.py script exists and is accessible."""
        self.assertTrue(self.gms_script.exists(), "gms.py script should exist")

    def test_agent_setup_script_exists(self):
        """Test that the agent_setup.py script exists."""
        self.assertTrue(self.agent_setup_script.exists(), "agent_setup.py script should exist")

    def test_direct_gms_execution(self):
        """Test that gms can be executed via module invocation."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, "gms should execute successfully")
        self.assertIn("GMS Tools", result.stdout, "Should show version information")

    def test_gms_help_system(self):
        """Test that the help system works properly."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, "Main help should work")
        self.assertIn("GameMaker Studio Development Tools", result.stdout)
        self.assertIn("asset", result.stdout)
        self.assertIn("event", result.stdout)
        self.assertIn("maintenance", result.stdout)

    def test_asset_command_structure(self):
        """Test that asset commands are properly structured."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "asset", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, "Asset help should work")
        self.assertIn("create", result.stdout)
        self.assertIn("delete", result.stdout)

    def test_maintenance_commands(self):
        """Test that maintenance commands work."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "maintenance", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, "Maintenance help should work")
        stdout_text = result.stdout or ""
        self.assertIn("auto", stdout_text, "Should have auto maintenance command")
        self.assertIn("lint", stdout_text, "Should have lint command")

    def test_event_command_structure(self):
        """Test that event commands are properly structured."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "event", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, "Event help should work")
        self.assertIn("add", result.stdout)
        self.assertIn("remove", result.stdout)
        self.assertIn("list", result.stdout)

    def test_workflow_command_structure(self):
        """Test that workflow commands are properly structured."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "workflow", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, "Workflow help should work")
        self.assertIn("duplicate", result.stdout)
        self.assertIn("rename", result.stdout)
        self.assertIn("delete", result.stdout)

    def test_room_command_structure(self):
        """Test that room commands are properly structured."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "room", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(result.returncode, 0, "Room help should work")
        self.assertIn("layer", result.stdout)
        self.assertIn("ops", result.stdout)
        self.assertIn("instance", result.stdout)

    def test_command_imports(self):
        """Test that all command modules can be imported successfully."""
        commands_dir = Path(__file__).parent / "commands"
        sys.path.insert(0, str(commands_dir.parent))

        try:
            from commands.asset_commands import handle_asset_create, handle_asset_delete
            from commands.event_commands import handle_event_add, handle_event_list
            from commands.workflow_commands import handle_workflow_duplicate
            from commands.room_commands import handle_room_layer_add
            from commands.maintenance_commands import handle_maintenance_auto

            self.assertTrue(callable(handle_asset_create))
            self.assertTrue(callable(handle_asset_delete))
            self.assertTrue(callable(handle_event_add))
            self.assertTrue(callable(handle_event_list))
            self.assertTrue(callable(handle_workflow_duplicate))
            self.assertTrue(callable(handle_room_layer_add))
            self.assertTrue(callable(handle_maintenance_auto))
        except ImportError as e:
            self.fail(f"Failed to import command modules: {e}")

    def test_error_handling(self):
        """Test that invalid commands are handled properly."""
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "invalid"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )
        self.assertNotEqual(result.returncode, 0, "Invalid command should fail")

        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "asset", "invalid"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )
        self.assertNotEqual(result.returncode, 0, "Invalid subcommand should fail")


class TestAgentSetupFullCoverage(unittest.TestCase):
    """Additional tests to exercise agent_setup.py error paths."""

    agent_setup_script = SRC_ROOT / "gms_helpers" / "agent_setup.py"

    def test_setup_powershell_function_missing_script(self):
        """Test setup_powershell_function when gms.py doesn't exist."""
        from gms_helpers.agent_setup import setup_powershell_function

        with patch("gms_helpers.agent_setup.__file__", "/fake/path/agent_setup.py"):
            with patch("pathlib.Path.exists", return_value=False):
                result = setup_powershell_function()
                self.assertFalse(result)

    def test_setup_bash_alias_missing_script(self):
        """Test setup_bash_alias when gms.py doesn't exist."""
        from gms_helpers.agent_setup import setup_bash_alias

        with patch("gms_helpers.agent_setup.__file__", "/fake/path/agent_setup.py"):
            with patch("pathlib.Path.exists", return_value=False):
                result = setup_bash_alias()
                self.assertFalse(result)

    def test_setup_bash_alias_exception(self):
        """Test setup_bash_alias when os.system raises exception."""
        from gms_helpers.agent_setup import setup_bash_alias

        with patch("gms_helpers.agent_setup.__file__", str(self.agent_setup_script)):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("os.system", side_effect=Exception("Test error")):
                    result = setup_bash_alias()
                    self.assertFalse(result)

    def test_test_gms_command_timeout(self):
        """Test test_gms_command when subprocess times out."""
        from gms_helpers.agent_setup import test_gms_command

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gms", 5)):
            result = test_gms_command()
            self.assertFalse(result)

    def test_test_gms_command_subprocess_error(self):
        """Test test_gms_command when subprocess raises SubprocessError."""
        from gms_helpers.agent_setup import test_gms_command

        with patch("subprocess.run", side_effect=subprocess.SubprocessError("Test error")):
            result = test_gms_command()
            self.assertFalse(result)

    def test_setup_powershell_direct_execution_exception(self):
        """Test setup_powershell_function when direct execution test raises exception."""
        from gms_helpers.agent_setup import setup_powershell_function

        with patch("gms_helpers.agent_setup.__file__", str(self.agent_setup_script)):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.run", side_effect=Exception("Test execution error")):
                    result = setup_powershell_function()
                    self.assertFalse(result)

    def test_main_execution_success(self):
        """Test main execution path with a mocked successful setup."""
        test_script = f"""
import sys
sys.path.insert(0, {str(SRC_ROOT)!r})
from gms_helpers.agent_setup import main
import unittest.mock as mock

with mock.patch("gms_helpers.agent_setup.test_gms_command", return_value=True):
    success = main()
    if success:
        print("SUCCESS")
"""
        result = subprocess.run(
            [sys.executable, "-c", test_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(SRC_ROOT)},
        )

        if "Setup complete" not in result.stdout:
            print(f"DEBUG: Return code: {result.returncode}")
            print(f"DEBUG: Stdout: '{result.stdout}'")
            print(f"DEBUG: Stderr: '{result.stderr}'")
        self.assertIn("Setup complete", result.stdout)


if __name__ == "__main__":
    unittest.main()
