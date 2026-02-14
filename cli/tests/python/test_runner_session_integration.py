#!/usr/bin/env python3
"""
Tests for runner.py integration with run_session.py.

Tests cover:
- Background mode execution
- Session creation on game start
- Session cleanup on game stop
- Stop/status using session manager
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

# Add source to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from gms_helpers.runner import (
    GameMakerRunner,
    detect_default_target_platform,
    normalize_platform_target,
)
from gms_helpers.run_session import RunSessionManager


class TestRunnerSessionIntegration(unittest.TestCase):
    """Tests for GameMakerRunner's session management integration."""
    
    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a minimal .yyp file so GameMakerRunner initializes
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_runner_has_session_manager(self):
        """Test that GameMakerRunner creates a session manager."""
        runner = GameMakerRunner(self.project_root)
        self.assertIsInstance(runner._session_manager, RunSessionManager)
        
    def test_runner_session_manager_uses_project_root(self):
        """Test session manager uses correct project root."""
        runner = GameMakerRunner(self.project_root)
        self.assertEqual(
            runner._session_manager.project_root,
            self.project_root.resolve()
        )
        

class TestRunnerStopGame(unittest.TestCase):
    """Tests for stop_game using session manager."""
    
    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a minimal .yyp file
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_stop_game_returns_dict(self):
        """Test stop_game returns a dict (not bool like before)."""
        runner = GameMakerRunner(self.project_root)
        result = runner.stop_game()
        
        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)
        self.assertIn("message", result)
        
    def test_stop_game_no_session(self):
        """Test stop_game when no session exists."""
        runner = GameMakerRunner(self.project_root)
        result = runner.stop_game()
        
        self.assertFalse(result["ok"])
        self.assertIn("No game session", result["message"])
        
    def test_stop_game_with_dead_session(self):
        """Test stop_game when session exists but process is dead."""
        runner = GameMakerRunner(self.project_root)
        
        # Create a session with a fake PID
        runner._session_manager.create_session(
            pid=999999999,
            exe_path="/fake/game.exe",
        )
        
        result = runner.stop_game()
        
        self.assertTrue(result["ok"])
        self.assertIn("already stopped", result["message"])


class TestRunnerIsGameRunning(unittest.TestCase):
    """Tests for is_game_running using session manager."""
    
    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a minimal .yyp file
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_is_game_running_no_session(self):
        """Test is_game_running returns False when no session."""
        runner = GameMakerRunner(self.project_root)
        self.assertFalse(runner.is_game_running())
        
    def test_is_game_running_dead_process(self):
        """Test is_game_running returns False when process is dead."""
        runner = GameMakerRunner(self.project_root)
        
        # Create a session with a fake PID
        runner._session_manager.create_session(
            pid=999999999,
            exe_path="/fake/game.exe",
        )
        
        self.assertFalse(runner.is_game_running())
        
    def test_is_game_running_current_process(self):
        """Test is_game_running returns True for live process."""
        import os
        runner = GameMakerRunner(self.project_root)
        
        # Create a session with current PID (known to be alive)
        runner._session_manager.create_session(
            pid=os.getpid(),
            exe_path="/current/process.exe",
        )
        
        self.assertTrue(runner.is_game_running())


class TestRunnerGetGameStatus(unittest.TestCase):
    """Tests for get_game_status method."""
    
    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a minimal .yyp file
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_get_game_status_returns_dict(self):
        """Test get_game_status returns a dict."""
        runner = GameMakerRunner(self.project_root)
        status = runner.get_game_status()
        
        self.assertIsInstance(status, dict)
        
    def test_get_game_status_no_session(self):
        """Test get_game_status when no session exists."""
        runner = GameMakerRunner(self.project_root)
        status = runner.get_game_status()
        
        self.assertFalse(status["has_session"])
        self.assertFalse(status["running"])
        
    def test_get_game_status_with_session(self):
        """Test get_game_status when session exists."""
        import os
        runner = GameMakerRunner(self.project_root)
        
        # Create a session
        session = runner._session_manager.create_session(
            pid=os.getpid(),
            exe_path="/status/test.exe",
        )
        
        status = runner.get_game_status()
        
        self.assertTrue(status["has_session"])
        self.assertTrue(status["running"])
        self.assertEqual(status["pid"], os.getpid())
        self.assertEqual(status["run_id"], session.run_id)


class TestRunnerCrossInstancePersistence(unittest.TestCase):
    """Test that sessions persist across GameMakerRunner instances."""
    
    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a minimal .yyp file
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_session_visible_to_new_runner_instance(self):
        """Test that session created by one runner is visible to another."""
        import os
        
        # Create session with first runner
        runner1 = GameMakerRunner(self.project_root)
        runner1._session_manager.create_session(
            pid=os.getpid(),
            exe_path="/persist/game.exe",
        )
        
        # Delete first runner
        del runner1
        
        # Create new runner - should see the session
        runner2 = GameMakerRunner(self.project_root)
        
        self.assertTrue(runner2.is_game_running())
        
    def test_stop_works_across_instances(self):
        """Test that stop_game works on session from different instance."""
        # Create session with first runner
        runner1 = GameMakerRunner(self.project_root)
        runner1._session_manager.create_session(
            pid=999999999,  # Fake PID
            exe_path="/cross/instance.exe",
        )
        del runner1
        
        # Stop with new runner
        runner2 = GameMakerRunner(self.project_root)
        result = runner2.stop_game()
        
        self.assertTrue(result["ok"])
        
        # Session should be cleared
        self.assertFalse(runner2.is_game_running())


class TestRunnerBackgroundMode(unittest.TestCase):
    """Tests for background mode functionality."""
    
    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create a minimal .yyp file
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    @patch.object(GameMakerRunner, '_run_project_ide_temp_approach')
    def test_background_true_returns_dict(self, mock_run):
        """Test that background=True returns a dict with session info."""
        mock_run.return_value = {
            "ok": True,
            "background": True,
            "pid": 12345,
            "run_id": "test_run_123",
            "message": "Game started in background",
        }
        
        runner = GameMakerRunner(self.project_root)
        result = runner.run_project_direct(background=True)
        
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("background"))
        
    @patch.object(GameMakerRunner, '_run_project_ide_temp_approach')
    def test_background_false_returns_bool_or_dict(self, mock_run):
        """Test that background=False behavior (can return bool or dict)."""
        mock_run.return_value = True
        
        runner = GameMakerRunner(self.project_root)
        result = runner.run_project_direct(background=False)
        
        # Should call the method and return its result
        mock_run.assert_called_once()


class TestRunnerLaunchTargetDetection(unittest.TestCase):
    """Tests for platform-specific launch artifact detection."""

    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')
        self.runner = GameMakerRunner(self.project_root)

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_launch_target_windows_exe(self):
        """Windows target should select the generated .exe."""
        build_dir = self.project_root / "build_windows"
        build_dir.mkdir()
        exe_path = build_dir / "MyGame.exe"
        exe_path.write_text("binary")

        launch = self.runner._find_launch_target(build_dir, "MyGame", "Windows")
        self.assertEqual(launch, exe_path)

    def test_find_launch_target_macos_app_binary(self):
        """macOS target should resolve executable inside .app bundle."""
        build_dir = self.project_root / "build_macos"
        app_bin = build_dir / "MyGame.app" / "Contents" / "MacOS"
        app_bin.mkdir(parents=True)
        binary_path = app_bin / "MyGame"
        binary_path.write_text("#!/bin/sh\necho ok\n")
        binary_path.chmod(0o755)

        launch = self.runner._find_launch_target(build_dir, "MyGame", "macOS")
        self.assertEqual(launch, binary_path)

    def test_find_launch_target_macos_fallback_any_app(self):
        """macOS target should fall back to any .app when project-named app is absent."""
        build_dir = self.project_root / "build_macos_fallback"
        app_bin = build_dir / "Runner.app" / "Contents" / "MacOS"
        app_bin.mkdir(parents=True)
        binary_path = app_bin / "Runner"
        binary_path.write_text("#!/bin/sh\necho runner\n")
        binary_path.chmod(0o755)

        launch = self.runner._find_launch_target(build_dir, "NotTheProjectName", "macOS")
        self.assertEqual(launch, binary_path)


class TestRunnerPlatformDefaults(unittest.TestCase):
    """Tests for platform default/normalization helpers."""

    @patch("gms_helpers.runner.platform.system", return_value="Darwin")
    def test_detect_default_target_platform_macos(self, _mock_system):
        self.assertEqual(detect_default_target_platform(), "macOS")

    @patch("gms_helpers.runner.platform.system", return_value="Linux")
    def test_detect_default_target_platform_linux(self, _mock_system):
        self.assertEqual(detect_default_target_platform(), "Linux")

    @patch("gms_helpers.runner.platform.system", return_value="Windows")
    def test_detect_default_target_platform_windows(self, _mock_system):
        self.assertEqual(detect_default_target_platform(), "Windows")

    def test_normalize_platform_target_alias(self):
        self.assertEqual(normalize_platform_target("macos"), "macOS")
        self.assertEqual(normalize_platform_target("ios"), "iOS")




class TestRunnerPrefabsPath(unittest.TestCase):
    """Tests for get_prefabs_path method."""

    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)

        # Create a minimal .yyp file
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_prefabs_path_returns_path_or_none(self):
        """Test get_prefabs_path returns Path or None."""
        runner = GameMakerRunner(self.project_root)
        result = runner.get_prefabs_path()

        # Result should be either a Path object or None
        self.assertTrue(result is None or isinstance(result, Path))

    @patch.dict('os.environ', {'GMS_PREFABS_PATH': ''})
    def test_get_prefabs_path_empty_env_var(self):
        """Test get_prefabs_path with empty env var falls back to defaults."""
        runner = GameMakerRunner(self.project_root)
        # Should not raise, just return result based on default paths
        result = runner.get_prefabs_path()
        self.assertTrue(result is None or isinstance(result, Path))

    def test_get_prefabs_path_with_valid_env_var(self):
        """Test get_prefabs_path uses GMS_PREFABS_PATH environment variable."""
        import os
        # Create a temporary prefabs directory
        prefabs_dir = Path(self.temp_dir) / "custom_prefabs"
        prefabs_dir.mkdir()

        with patch.dict('os.environ', {'GMS_PREFABS_PATH': str(prefabs_dir)}):
            runner = GameMakerRunner(self.project_root)
            result = runner.get_prefabs_path()

            self.assertEqual(result, prefabs_dir)

    def test_get_prefabs_path_env_var_nonexistent_path(self):
        """Test get_prefabs_path ignores non-existent env var path."""
        with patch.dict('os.environ', {'GMS_PREFABS_PATH': '/nonexistent/path/prefabs'}):
            runner = GameMakerRunner(self.project_root)
            result = runner.get_prefabs_path()

            # Should fall back to default paths (which may or may not exist)
            # The env path should NOT be returned since it doesn't exist
            if result is not None:
                self.assertNotEqual(str(result), '/nonexistent/path/prefabs')


class TestRunnerIgorCommandPrefabs(unittest.TestCase):
    """Tests for prefabs flag in Igor command building."""

    def setUp(self):
        """Create a temporary directory for test project."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)

        # Create a minimal .yyp file
        yyp_path = self.project_root / "test_project.yyp"
        yyp_path.write_text('{"name": "test_project", "resources": []}')

        # Create a temporary prefabs directory
        self.prefabs_dir = Path(self.temp_dir) / "test_prefabs"
        self.prefabs_dir.mkdir()

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch.object(GameMakerRunner, 'find_gamemaker_runtime')
    @patch.object(GameMakerRunner, 'find_license_file')
    def test_build_igor_command_includes_prefabs(self, mock_license, mock_runtime):
        """Test build_igor_command includes --pf flag when prefabs path exists."""
        # Mock runtime and license
        mock_runtime.return_value = Path("/fake/Igor.exe")
        mock_license.return_value = Path("/fake/licence.plist")

        with patch.dict('os.environ', {'GMS_PREFABS_PATH': str(self.prefabs_dir)}):
            runner = GameMakerRunner(self.project_root)
            runner.runtime_path = Path("/fake/runtime")

            cmd = runner.build_igor_command(action="Run")

            # Check that --pf flag is in the command
            cmd_str = ' '.join(cmd)
            self.assertIn('--pf=', cmd_str)
            self.assertIn(str(self.prefabs_dir), cmd_str)

    @patch.object(GameMakerRunner, 'find_gamemaker_runtime')
    @patch.object(GameMakerRunner, 'find_license_file')
    @patch.object(GameMakerRunner, 'get_prefabs_path')
    def test_build_igor_command_no_prefabs_when_none(self, mock_prefabs, mock_license, mock_runtime):
        """Test build_igor_command omits --pf flag when no prefabs path."""
        # Mock runtime and license
        mock_runtime.return_value = Path("/fake/Igor.exe")
        mock_license.return_value = Path("/fake/licence.plist")
        mock_prefabs.return_value = None

        runner = GameMakerRunner(self.project_root)
        runner.runtime_path = Path("/fake/runtime")

        cmd = runner.build_igor_command(action="Run")

        # Check that --pf flag is NOT in the command
        cmd_str = ' '.join(cmd)
        self.assertNotIn('--pf=', cmd_str)

if __name__ == "__main__":
    unittest.main()
