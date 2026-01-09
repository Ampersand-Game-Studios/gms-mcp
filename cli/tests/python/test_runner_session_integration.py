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

from gms_helpers.runner import GameMakerRunner
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


if __name__ == "__main__":
    unittest.main()
