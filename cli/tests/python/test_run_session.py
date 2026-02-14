#!/usr/bin/env python3
"""
Tests for run_session.py - Persistent game session tracking.

Tests cover:
- RunSession dataclass serialization
- RunSessionManager session lifecycle (create, get, clear)
- Process status checking
- Cross-instance session persistence
"""

import json
import os
import subprocess
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add source to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from gms_helpers.run_session import (
    RunSession,
    RunSessionManager,
    get_session_manager,
)


class TestRunSession(unittest.TestCase):
    """Tests for the RunSession dataclass."""
    
    def test_run_session_creation(self):
        """Test creating a RunSession with required fields."""
        session = RunSession(
            run_id="test_run_123",
            pid=12345,
            exe_path="/path/to/game.exe",
            project_root="/path/to/project",
            started_at="2026-01-09T15:00:00",
        )
        
        self.assertEqual(session.run_id, "test_run_123")
        self.assertEqual(session.pid, 12345)
        self.assertEqual(session.exe_path, "/path/to/game.exe")
        self.assertEqual(session.project_root, "/path/to/project")
        self.assertEqual(session.started_at, "2026-01-09T15:00:00")
        
    def test_run_session_default_values(self):
        """Test RunSession has correct default values."""
        session = RunSession(
            run_id="test",
            pid=1,
            exe_path="/test",
            project_root="/test",
            started_at="2026-01-09T15:00:00",
        )
        
        self.assertEqual(session.platform_target, "Windows")
        self.assertEqual(session.runtime_type, "VM")
        self.assertIsNone(session.log_file)
        self.assertIsNone(session.bridge_port)
        
    def test_run_session_custom_values(self):
        """Test RunSession with custom optional values."""
        session = RunSession(
            run_id="test",
            pid=1,
            exe_path="/test",
            project_root="/test",
            started_at="2026-01-09T15:00:00",
            platform_target="macOS",
            runtime_type="YYC",
            log_file="/path/to/log.txt",
            bridge_port=6502,
        )
        
        self.assertEqual(session.platform_target, "macOS")
        self.assertEqual(session.runtime_type, "YYC")
        self.assertEqual(session.log_file, "/path/to/log.txt")
        self.assertEqual(session.bridge_port, 6502)
        
    def test_run_session_to_dict(self):
        """Test serializing RunSession to dict."""
        session = RunSession(
            run_id="test_123",
            pid=99999,
            exe_path="/game.exe",
            project_root="/project",
            started_at="2026-01-09T15:00:00",
        )
        
        data = session.to_dict()
        
        self.assertIsInstance(data, dict)
        self.assertEqual(data["run_id"], "test_123")
        self.assertEqual(data["pid"], 99999)
        self.assertEqual(data["exe_path"], "/game.exe")
        self.assertEqual(data["project_root"], "/project")
        
    def test_run_session_from_dict(self):
        """Test deserializing RunSession from dict."""
        data = {
            "run_id": "from_dict_123",
            "pid": 54321,
            "exe_path": "/restored/game.exe",
            "project_root": "/restored/project",
            "started_at": "2026-01-09T16:00:00",
            "platform_target": "Windows",
            "runtime_type": "VM",
            "log_file": None,
            "bridge_port": None,
        }
        
        session = RunSession.from_dict(data)
        
        self.assertEqual(session.run_id, "from_dict_123")
        self.assertEqual(session.pid, 54321)
        self.assertEqual(session.exe_path, "/restored/game.exe")
        
    def test_run_session_round_trip(self):
        """Test that to_dict -> from_dict preserves all data."""
        original = RunSession(
            run_id="round_trip_test",
            pid=11111,
            exe_path="/round/trip.exe",
            project_root="/round/trip",
            started_at="2026-01-09T17:00:00",
            platform_target="Linux",
            runtime_type="YYC",
            log_file="/logs/game.log",
            bridge_port=7777,
        )
        
        data = original.to_dict()
        restored = RunSession.from_dict(data)
        
        self.assertEqual(original.run_id, restored.run_id)
        self.assertEqual(original.pid, restored.pid)
        self.assertEqual(original.exe_path, restored.exe_path)
        self.assertEqual(original.project_root, restored.project_root)
        self.assertEqual(original.started_at, restored.started_at)
        self.assertEqual(original.platform_target, restored.platform_target)
        self.assertEqual(original.runtime_type, restored.runtime_type)
        self.assertEqual(original.log_file, restored.log_file)
        self.assertEqual(original.bridge_port, restored.bridge_port)


class TestRunSessionManager(unittest.TestCase):
    """Tests for RunSessionManager."""
    
    def setUp(self):
        """Create a temporary directory for test sessions."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RunSessionManager(Path(self.temp_dir))
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_sessions_dir_created(self):
        """Test that sessions directory is created when needed."""
        sessions_dir = Path(self.temp_dir) / ".gms_mcp" / "sessions"
        self.assertFalse(sessions_dir.exists())
        
        self.manager._ensure_sessions_dir()
        
        self.assertTrue(sessions_dir.exists())
        
    def test_create_session(self):
        """Test creating a new session."""
        session = self.manager.create_session(
            pid=12345,
            exe_path="/test/game.exe",
            platform_target="Windows",
            runtime_type="VM",
        )
        
        self.assertIsInstance(session, RunSession)
        self.assertEqual(session.pid, 12345)
        self.assertEqual(session.exe_path, "/test/game.exe")
        self.assertTrue(session.run_id.startswith("run_"))
        
    def test_create_session_persists_to_disk(self):
        """Test that created session is written to disk."""
        session = self.manager.create_session(
            pid=99999,
            exe_path="/persisted/game.exe",
        )
        
        session_file = Path(self.temp_dir) / ".gms_mcp" / "sessions" / "current.json"
        self.assertTrue(session_file.exists())
        
        with open(session_file, "r") as f:
            data = json.load(f)
            
        self.assertEqual(data["pid"], 99999)
        self.assertEqual(data["exe_path"], "/persisted/game.exe")
        
    def test_get_current_session(self):
        """Test retrieving the current session."""
        # Create a session
        created = self.manager.create_session(
            pid=11111,
            exe_path="/get/test.exe",
        )
        
        # Retrieve it
        retrieved = self.manager.get_current_session()
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.pid, created.pid)
        self.assertEqual(retrieved.run_id, created.run_id)
        
    def test_get_current_session_none_when_empty(self):
        """Test get_current_session returns None when no session exists."""
        result = self.manager.get_current_session()
        self.assertIsNone(result)
        
    def test_get_current_session_handles_corrupted_file(self):
        """Test get_current_session handles corrupted JSON gracefully."""
        sessions_dir = Path(self.temp_dir) / ".gms_mcp" / "sessions"
        sessions_dir.mkdir(parents=True)
        
        # Write invalid JSON
        session_file = sessions_dir / "current.json"
        with open(session_file, "w") as f:
            f.write("{ invalid json }")
            
        result = self.manager.get_current_session()
        self.assertIsNone(result)
        
    def test_clear_session(self):
        """Test clearing the current session."""
        # Create a session
        self.manager.create_session(pid=22222, exe_path="/clear/test.exe")
        
        # Verify it exists
        self.assertIsNotNone(self.manager.get_current_session())
        
        # Clear it
        result = self.manager.clear_session()
        
        self.assertTrue(result)
        self.assertIsNone(self.manager.get_current_session())
        
    def test_clear_session_returns_false_when_empty(self):
        """Test clear_session returns False when no session exists."""
        result = self.manager.clear_session()
        self.assertFalse(result)
        
    def test_generate_run_id_unique(self):
        """Test that generated run IDs are unique."""
        ids = set()
        for _ in range(100):
            run_id = self.manager._generate_run_id()
            self.assertNotIn(run_id, ids)
            ids.add(run_id)
            time.sleep(0.001)  # Small delay to ensure different timestamps
            
    def test_generate_run_id_format(self):
        """Test run ID format is run_<timestamp>."""
        run_id = self.manager._generate_run_id()
        self.assertTrue(run_id.startswith("run_"))
        # Should be run_ followed by timestamp in milliseconds
        timestamp_part = run_id[4:]
        self.assertTrue(timestamp_part.isdigit())


class TestRunSessionManagerProcessChecks(unittest.TestCase):
    """Tests for process checking functionality."""
    
    def setUp(self):
        """Create a temporary directory for test sessions."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RunSessionManager(Path(self.temp_dir))
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_is_process_alive_current_process(self):
        """Test is_process_alive returns True for the current process."""
        current_pid = os.getpid()
        self.assertTrue(self.manager.is_process_alive(current_pid))
        
    def test_is_process_alive_nonexistent_process(self):
        """Test is_process_alive returns False for non-existent process."""
        # Use a very high PID that's unlikely to exist
        fake_pid = 999999999
        self.assertFalse(self.manager.is_process_alive(fake_pid))
        
    @patch("subprocess.run")
    def test_is_process_alive_timeout(self, mock_run):
        """Test is_process_alive handles timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tasklist", timeout=5)
        
        result = self.manager.is_process_alive(12345)
        self.assertFalse(result)

    @patch("gms_helpers.run_session.os.kill")
    @patch("gms_helpers.run_session.os.killpg", create=True)
    @patch("gms_helpers.run_session.os.getpgrp", return_value=900, create=True)
    @patch("gms_helpers.run_session.os.getpgid", return_value=1000, create=True)
    @patch("gms_helpers.run_session.platform.system", return_value="Darwin")
    def test_kill_process_uses_process_group(
        self, mock_system, mock_getpgid, mock_getpgrp, mock_killpg, mock_kill
    ):
        """Test Unix kill_process targets the process group when available."""
        self.manager.kill_process(12345, force=True)

        mock_getpgid.assert_called_once_with(12345)
        mock_getpgrp.assert_called_once_with()
        mock_killpg.assert_called_once_with(1000, signal.SIGKILL)
        mock_kill.assert_not_called()


class TestRunSessionManagerStatus(unittest.TestCase):
    """Tests for get_session_status and stop_game."""
    
    def setUp(self):
        """Create a temporary directory for test sessions."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RunSessionManager(Path(self.temp_dir))
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_get_session_status_no_session(self):
        """Test status when no session exists."""
        status = self.manager.get_session_status()
        
        self.assertFalse(status["has_session"])
        self.assertFalse(status["running"])
        self.assertEqual(status["message"], "No game session found")
        
    def test_get_session_status_with_session(self):
        """Test status when session exists."""
        # Create a session with current process PID (so it shows as running)
        current_pid = os.getpid()
        self.manager.create_session(
            pid=current_pid,
            exe_path="/status/test.exe",
            platform_target="Windows",
            runtime_type="VM",
        )
        
        status = self.manager.get_session_status()
        
        self.assertTrue(status["has_session"])
        self.assertTrue(status["running"])
        self.assertEqual(status["pid"], current_pid)
        self.assertIn("run_", status["run_id"])
        
    def test_get_session_status_dead_process(self):
        """Test status when session exists but process is dead."""
        # Create a session with a fake PID
        self.manager.create_session(
            pid=999999999,  # Very unlikely to exist
            exe_path="/dead/test.exe",
        )
        
        status = self.manager.get_session_status()
        
        self.assertTrue(status["has_session"])
        self.assertFalse(status["running"])
        self.assertIn("not running", status["message"])
        
    def test_stop_game_no_session(self):
        """Test stop_game when no session exists."""
        result = self.manager.stop_game()
        
        self.assertFalse(result["ok"])
        self.assertIn("No game session", result["message"])
        
    def test_stop_game_already_stopped(self):
        """Test stop_game when process is already dead."""
        # Create a session with a fake PID
        self.manager.create_session(
            pid=999999999,  # Very unlikely to exist
            exe_path="/stopped/test.exe",
        )
        
        result = self.manager.stop_game()
        
        self.assertTrue(result["ok"])
        self.assertIn("already stopped", result["message"])
        
        # Session should be cleared
        self.assertIsNone(self.manager.get_current_session())


class TestGetSessionManager(unittest.TestCase):
    """Tests for the get_session_manager convenience function."""
    
    def test_get_session_manager_default(self):
        """Test get_session_manager with default path."""
        manager = get_session_manager()
        self.assertIsInstance(manager, RunSessionManager)
        
    def test_get_session_manager_custom_path(self):
        """Test get_session_manager with custom path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = get_session_manager(temp_dir)
            self.assertIsInstance(manager, RunSessionManager)
            self.assertEqual(manager.project_root, Path(temp_dir).resolve())


class TestSessionPersistenceAcrossInstances(unittest.TestCase):
    """Test that sessions persist across manager instances."""
    
    def setUp(self):
        """Create a temporary directory for test sessions."""
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_session_survives_new_instance(self):
        """Test that a session created by one instance can be read by another."""
        # Create session with first instance
        manager1 = RunSessionManager(Path(self.temp_dir))
        session = manager1.create_session(
            pid=12345,
            exe_path="/persist/test.exe",
        )
        original_run_id = session.run_id
        
        # Delete the first manager
        del manager1
        
        # Create new instance
        manager2 = RunSessionManager(Path(self.temp_dir))
        
        # Should be able to read the session
        retrieved = manager2.get_current_session()
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.run_id, original_run_id)
        self.assertEqual(retrieved.pid, 12345)
        
    def test_status_works_across_instances(self):
        """Test get_session_status works with session from different instance."""
        # Create session with first instance
        manager1 = RunSessionManager(Path(self.temp_dir))
        manager1.create_session(
            pid=os.getpid(),  # Use current PID so it shows as running
            exe_path="/cross/instance.exe",
        )
        del manager1
        
        # Check status with new instance
        manager2 = RunSessionManager(Path(self.temp_dir))
        status = manager2.get_session_status()
        
        self.assertTrue(status["has_session"])
        self.assertTrue(status["running"])


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""
    
    def setUp(self):
        """Create a temporary directory for test sessions."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RunSessionManager(Path(self.temp_dir))
        
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_create_session_with_optional_fields(self):
        """Test creating session with all optional fields."""
        session = self.manager.create_session(
            pid=55555,
            exe_path="/optional/test.exe",
            platform_target="macOS",
            runtime_type="YYC",
            log_file="/logs/game.log",
            bridge_port=6502,
        )
        
        self.assertEqual(session.platform_target, "macOS")
        self.assertEqual(session.runtime_type, "YYC")
        self.assertEqual(session.log_file, "/logs/game.log")
        self.assertEqual(session.bridge_port, 6502)
        
    def test_session_with_special_characters_in_path(self):
        """Test session handles paths with special characters."""
        session = self.manager.create_session(
            pid=66666,
            exe_path="/path with spaces/game (1).exe",
        )
        
        # Retrieve and verify
        retrieved = self.manager.get_current_session()
        self.assertEqual(retrieved.exe_path, "/path with spaces/game (1).exe")
        
    def test_multiple_create_overwrites(self):
        """Test that creating a new session overwrites the old one."""
        session1 = self.manager.create_session(pid=11111, exe_path="/first.exe")
        session2 = self.manager.create_session(pid=22222, exe_path="/second.exe")
        
        # Only the second session should exist
        current = self.manager.get_current_session()
        self.assertEqual(current.pid, 22222)
        self.assertNotEqual(current.run_id, session1.run_id)


if __name__ == "__main__":
    unittest.main()
