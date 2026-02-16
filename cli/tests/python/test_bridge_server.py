#!/usr/bin/env python3
"""
Tests for bridge_server.py - TCP bridge for game communication.

Tests cover:
- Server lifecycle (start/stop)
- Log buffering
- Command sending and responses
- Thread safety
"""

import sys
import socket
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add source to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from gms_helpers.bridge_server import (
    BridgeServer,
    LogEntry,
    CommandResult,
    get_bridge_server,
    stop_bridge_server,
)


class TestLogEntry(unittest.TestCase):
    """Tests for LogEntry dataclass."""
    
    def test_log_entry_creation(self):
        """Test creating a log entry."""
        entry = LogEntry(timestamp="12345", message="Test message")
        
        self.assertEqual(entry.timestamp, "12345")
        self.assertEqual(entry.message, "Test message")
        self.assertIsNotNone(entry.received_at)


class TestCommandResult(unittest.TestCase):
    """Tests for CommandResult dataclass."""
    
    def test_command_result_creation(self):
        """Test creating a command result."""
        result = CommandResult(command_id="cmd_1", command="ping")
        
        self.assertEqual(result.command_id, "cmd_1")
        self.assertEqual(result.command, "ping")
        self.assertFalse(result.success)
        self.assertIsNone(result.result)
        
    def test_command_result_with_success(self):
        """Test command result with success."""
        result = CommandResult(
            command_id="cmd_2",
            command="test",
            result="OK",
            success=True,
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.result, "OK")


class TestBridgeServerBasic(unittest.TestCase):
    """Basic tests for BridgeServer."""
    
    def test_server_creation(self):
        """Test creating a bridge server."""
        server = BridgeServer(port=6510)
        
        self.assertEqual(server.port, 6510)
        self.assertEqual(server.host, "127.0.0.1")
        self.assertFalse(server.is_running)
        self.assertFalse(server.is_connected)
        
    def test_server_start_stop(self):
        """Test starting and stopping the server."""
        server = BridgeServer(port=6511)
        
        # Start
        result = server.start()
        self.assertTrue(result)
        self.assertTrue(server.is_running)
        
        # Stop
        server.stop()
        self.assertFalse(server.is_running)
        
    def test_server_double_start(self):
        """Test starting an already running server."""
        server = BridgeServer(port=6512)
        
        server.start()
        result = server.start()  # Second start should return True
        
        self.assertTrue(result)
        server.stop()
        
    def test_server_status(self):
        """Test getting server status."""
        server = BridgeServer(port=6513)
        
        status = server.get_status()
        
        self.assertFalse(status["running"])
        self.assertFalse(status["connected"])
        self.assertEqual(status["port"], 6513)
        self.assertEqual(status["log_count"], 0)


class TestBridgeServerLogs(unittest.TestCase):
    """Tests for log buffering functionality."""
    
    def setUp(self):
        """Create a server for testing."""
        self.server = BridgeServer(port=6520)
        
    def tearDown(self):
        """Stop server if running."""
        self.server.stop()
        
    def test_empty_logs(self):
        """Test getting logs from empty buffer."""
        logs = self.server.get_logs()
        
        self.assertEqual(len(logs), 0)
        
    def test_log_count(self):
        """Test log count."""
        count = self.server.get_log_count()
        
        self.assertEqual(count, 0)
        
    def test_clear_logs(self):
        """Test clearing log buffer."""
        # Add some logs manually
        self.server._log_buffer.append(LogEntry("1", "test1"))
        self.server._log_buffer.append(LogEntry("2", "test2"))
        
        self.assertEqual(self.server.get_log_count(), 2)
        
        self.server.clear_logs()
        
        self.assertEqual(self.server.get_log_count(), 0)


class TestBridgeServerCommands(unittest.TestCase):
    """Tests for command functionality."""
    
    def setUp(self):
        """Create a server for testing."""
        self.server = BridgeServer(port=6530)
        
    def tearDown(self):
        """Stop server if running."""
        self.server.stop()
        
    def test_send_command_not_connected(self):
        """Test sending command when not connected."""
        result = self.server.send_command("ping", timeout=0.1)
        
        self.assertFalse(result.success)
        self.assertIn("Not connected", result.error)
        
    def test_send_command_async_not_connected(self):
        """Test async command when not connected."""
        cmd_id = self.server.send_command_async("ping")
        
        self.assertEqual(cmd_id, "")


class TestBridgeServerGlobal(unittest.TestCase):
    """Tests for global server management."""
    
    def test_get_bridge_server_creates(self):
        """Test get_bridge_server creates new server."""
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            server = get_bridge_server(temp_dir, create=True)
            
            self.assertIsNotNone(server)
            self.assertIsInstance(server, BridgeServer)
            
            # Cleanup
            stop_bridge_server(temp_dir)
            
    def test_get_bridge_server_returns_same(self):
        """Test get_bridge_server returns same instance."""
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            server1 = get_bridge_server(temp_dir, create=True)
            server2 = get_bridge_server(temp_dir, create=True)
            
            self.assertIs(server1, server2)
            
            # Cleanup
            stop_bridge_server(temp_dir)
            
    def test_get_bridge_server_no_create(self):
        """Test get_bridge_server with create=False."""
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            server = get_bridge_server(temp_dir, create=False)
            
            self.assertIsNone(server)
            
    def test_stop_bridge_server(self):
        """Test stopping a bridge server."""
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            server = get_bridge_server(temp_dir, create=True)
            server.start()
            
            self.assertTrue(server.is_running)
            
            stop_bridge_server(temp_dir)
            
            self.assertFalse(server.is_running)


class TestBridgeServerConnection(unittest.TestCase):
    """Tests for connection handling (requires actual socket connection)."""
    
    def setUp(self):
        """Create and start a server for testing."""
        # Use an available port to avoid collisions with any local bridge/dev servers.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

        self.server = BridgeServer(port=self.port)
        self.server.start()
        time.sleep(0.1)  # Give server time to start
        
    def tearDown(self):
        """Stop server."""
        self.server.stop()
        
    def test_client_connection(self):
        """Test that a client can connect."""
        # Create a test client
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        
        try:
            client.connect(("127.0.0.1", self.port))
            time.sleep(0.2)  # Give server time to accept
            
            self.assertTrue(self.server.is_connected)
            
        finally:
            client.close()
            
    def test_client_sends_log(self):
        """Test receiving log from client."""
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        
        try:
            client.connect(("127.0.0.1", self.port))
            time.sleep(0.2)
            
            # Send a log message
            client.sendall(b"LOG:12345|Test log message\n")
            time.sleep(0.2)
            
            # Check log was received
            logs = self.server.get_logs()
            self.assertGreater(len(logs), 0)
            self.assertEqual(logs[-1]["message"], "Test log message")
            
        finally:
            client.close()

    def test_client_sends_logs_with_nul_bytes(self):
        """
        Test receiving multiple LOG lines when NUL bytes are present in the TCP stream.

        GameMaker commonly writes strings with `buffer_write(..., buffer_string, ...)`, which
        NUL-terminates the payload. When multiple messages are received in a single TCP read,
        subsequent lines can begin with '\\x00' and must still be parsed.
        """
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)

        try:
            client.connect(("127.0.0.1", self.port))
            time.sleep(0.2)

            # Send two log lines with an embedded NUL between them (simulates GM buffer_string).
            client.sendall(b"LOG:1|First\n\x00LOG:2|Second\n")
            time.sleep(0.2)

            logs = self.server.get_logs()
            messages = [l["message"] for l in logs]

            self.assertIn("First", messages)
            self.assertIn("Second", messages)

        finally:
            client.close()
            
    def test_command_response(self):
        """Test command/response flow."""
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.setblocking(False)
        
        try:
            client.connect(("127.0.0.1", self.port))
            time.sleep(0.2)
            
            # Start a thread to respond to commands
            def responder():
                import select
                while True:
                    try:
                        ready = select.select([client], [], [], 0.5)
                        if ready[0]:
                            data = client.recv(1024)
                            if data and data.startswith(b"CMD:"):
                                # Parse and respond
                                parts = data.decode().strip().split("|")
                                cmd_id = parts[0].replace("CMD:", "")
                                response = f"RSP:{cmd_id}|pong\n"
                                client.sendall(response.encode())
                                break
                    except Exception:
                        break
            
            # Start responder thread
            thread = threading.Thread(target=responder, daemon=True)
            thread.start()
            
            # Send command
            result = self.server.send_command("ping", timeout=2.0)
            
            thread.join(timeout=1.0)
            
            self.assertTrue(result.success)
            self.assertEqual(result.result, "pong")
            
        except BlockingIOError:
            pass  # Expected for non-blocking socket
        finally:
            try:
                client.close()
            except Exception:
                pass

    def test_disconnect_during_command_fails_without_timeout(self):
        """Pending command should fail immediately when the game disconnects."""
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)

        try:
            client.connect(("127.0.0.1", self.port))
            time.sleep(0.2)

            def disconnect_on_command():
                try:
                    data = client.recv(1024)
                    if data and data.startswith(b"CMD:"):
                        client.close()
                except Exception:
                    pass

            thread = threading.Thread(target=disconnect_on_command, daemon=True)
            thread.start()

            start = time.time()
            result = self.server.send_command("ping", timeout=2.0)
            elapsed = time.time() - start

            thread.join(timeout=1.0)

            self.assertFalse(result.success)
            self.assertEqual(result.error, "Game disconnected")
            # Should return quickly on disconnect, not wait for full timeout.
            self.assertLess(elapsed, 1.5)
        finally:
            try:
                client.close()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
