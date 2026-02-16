#!/usr/bin/env python3
"""
TCP Bridge Server for GameMaker MCP

Provides bidirectional communication between MCP tools and running GameMaker games.
The server listens on localhost and the game connects out to it (avoiding firewall prompts).

Protocol:
- Game -> Server: LOG:<timestamp>|<message>\n
- Server -> Game: CMD:<cmd_id>|<command>\n
- Game -> Server: RSP:<cmd_id>|<result>\n
"""

import socket
import threading
import queue
import time
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime


@dataclass
class LogEntry:
    """A log message received from the game."""
    timestamp: str
    message: str
    received_at: float = field(default_factory=time.time)


@dataclass
class CommandResult:
    """Result of a command sent to the game."""
    command_id: str
    command: str
    result: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    sent_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class BridgeServer:
    """
    TCP server that bridges MCP tools and GameMaker games.
    
    The server:
    - Listens on localhost (default port 6502)
    - Accepts one game connection at a time
    - Buffers incoming log messages
    - Queues outgoing commands
    - Tracks command responses
    
    Thread-safe for concurrent MCP tool access.
    """
    
    DEFAULT_PORT = 6502
    MAX_LOG_BUFFER = 10000
    SOCKET_TIMEOUT = 0.5  # seconds
    
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.host = "127.0.0.1"
        
        # Server state
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._running = False
        self._connected = False
        
        # Thread management
        self._server_thread: Optional[threading.Thread] = None
        self._receive_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        
        # Data buffers (thread-safe)
        self._log_buffer: List[LogEntry] = []
        self._log_lock = threading.Lock()
        
        # Command tracking
        self._command_queue: queue.Queue = queue.Queue()
        self._pending_commands: Dict[str, CommandResult] = {}
        self._command_lock = threading.Lock()
        self._command_counter = 0
        
        # Callbacks
        self._on_connect: Optional[Callable[[], None]] = None
        self._on_disconnect: Optional[Callable[[], None]] = None
        self._on_log: Optional[Callable[[LogEntry], None]] = None
    
    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running
    
    @property
    def is_connected(self) -> bool:
        """Check if a game is connected."""
        return self._connected
    
    def start(self) -> bool:
        """
        Start the bridge server.
        
        Returns:
            True if server started successfully, False otherwise
        """
        with self._lock:
            if self._running:
                return True
            
            try:
                # Create server socket
                self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._server_socket.settimeout(self.SOCKET_TIMEOUT)
                self._server_socket.bind((self.host, self.port))
                self._server_socket.listen(1)
                
                self._running = True
                
                # Start server thread
                self._server_thread = threading.Thread(
                    target=self._server_loop,
                    name="BridgeServer",
                    daemon=True
                )
                self._server_thread.start()
                
                print(f"[BRIDGE] Server started on {self.host}:{self.port}")
                return True
                
            except Exception as e:
                print(f"[BRIDGE] Failed to start server: {e}")
                self._cleanup_server()
                return False
    
    def stop(self) -> None:
        """Stop the bridge server and disconnect any client."""
        with self._lock:
            if not self._running:
                return
            
            print("[BRIDGE] Stopping server...")
            self._running = False
            
            # Close client connection
            self._disconnect_client()
            
            # Close server socket
            self._cleanup_server()
            
            # Wait for threads to finish
            if self._server_thread and self._server_thread.is_alive():
                self._server_thread.join(timeout=2.0)
            
            print("[BRIDGE] Server stopped")
    
    def _cleanup_server(self) -> None:
        """Clean up server socket."""
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
    
    def _disconnect_client(self) -> None:
        """Disconnect the current client."""
        if self._client_socket:
            try:
                self._client_socket.close()
            except Exception:
                pass
            self._client_socket = None
        
        was_connected = self._connected
        self._connected = False

        # Fail any pending commands immediately so callers don't sit on timeout
        # when the game connection drops mid-request.
        with self._command_lock:
            now = time.time()
            for pending in self._pending_commands.values():
                if pending.completed_at is None:
                    pending.error = pending.error or "Game disconnected"
                    pending.completed_at = now

        if was_connected and self._on_disconnect:
            try:
                self._on_disconnect()
            except Exception:
                pass
    
    def _server_loop(self) -> None:
        """Main server loop - accepts connections."""
        while self._running:
            try:
                if not self._server_socket:
                    break
                
                # Accept new connection
                try:
                    client_socket, addr = self._server_socket.accept()
                    client_socket.settimeout(self.SOCKET_TIMEOUT)
                    
                    with self._lock:
                        # Close any existing connection
                        self._disconnect_client()
                        
                        self._client_socket = client_socket
                        self._connected = True
                    
                    print(f"[BRIDGE] Game connected from {addr}")
                    
                    if self._on_connect:
                        try:
                            self._on_connect()
                        except Exception:
                            pass
                    
                    # Start receive thread for this connection
                    self._receive_thread = threading.Thread(
                        target=self._receive_loop,
                        name="BridgeReceiver",
                        daemon=True
                    )
                    self._receive_thread.start()
                    
                    # Also start send thread
                    send_thread = threading.Thread(
                        target=self._send_loop,
                        name="BridgeSender",
                        daemon=True
                    )
                    send_thread.start()
                    
                except socket.timeout:
                    continue
                    
            except Exception as e:
                if self._running:
                    print(f"[BRIDGE] Server error: {e}")
                break
    
    def _receive_loop(self) -> None:
        """Receive loop - reads data from connected game."""
        buffer = ""
        
        while self._running and self._connected:
            try:
                if not self._client_socket:
                    break
                
                try:
                    data = self._client_socket.recv(4096)
                    if not data:
                        # Connection closed
                        print("[BRIDGE] Game disconnected")
                        self._disconnect_client()
                        break
                    
                    buffer += data.decode('utf-8', errors='replace')
                    # GameMaker's `buffer_write(..., buffer_string, ...)` writes a NUL-terminated string.
                    # When we receive raw TCP bytes and split on '\n', subsequent messages may start with '\x00'
                    # (e.g. '\x00LOG:' / '\x00RSP:'), which would fail our startswith() checks.
                    buffer = buffer.replace('\x00', '')
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if line:
                            self._process_message(line)
                            
                except socket.timeout:
                    continue
                    
            except Exception as e:
                if self._running and self._connected:
                    print(f"[BRIDGE] Receive error: {e}")
                self._disconnect_client()
                break
    
    def _send_loop(self) -> None:
        """Send loop - sends queued commands to game."""
        while self._running and self._connected:
            try:
                # Get command from queue (with timeout)
                try:
                    cmd_id, command = self._command_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                if not self._client_socket or not self._connected:
                    break
                
                # Send command
                message = f"CMD:{cmd_id}|{command}\n"
                try:
                    self._client_socket.sendall(message.encode('utf-8'))
                except Exception as e:
                    print(f"[BRIDGE] Send error: {e}")
                    # Put command back for retry? Or mark as failed?
                    with self._command_lock:
                        if cmd_id in self._pending_commands:
                            self._pending_commands[cmd_id].error = str(e)
                            self._pending_commands[cmd_id].completed_at = time.time()
                    
            except Exception as e:
                if self._running:
                    print(f"[BRIDGE] Send loop error: {e}")
                break
    
    def _process_message(self, message: str) -> None:
        """Process a message received from the game."""
        try:
            if message.startswith("LOG:"):
                # Log message: LOG:<timestamp>|<message>
                content = message[4:]
                if '|' in content:
                    timestamp, log_msg = content.split('|', 1)
                else:
                    timestamp = str(int(time.time() * 1000))
                    log_msg = content
                
                entry = LogEntry(timestamp=timestamp, message=log_msg)
                
                with self._log_lock:
                    self._log_buffer.append(entry)
                    # Trim buffer if too large
                    if len(self._log_buffer) > self.MAX_LOG_BUFFER:
                        self._log_buffer = self._log_buffer[-self.MAX_LOG_BUFFER // 2:]
                
                if self._on_log:
                    try:
                        self._on_log(entry)
                    except Exception:
                        pass
                        
            elif message.startswith("RSP:"):
                # Command response: RSP:<cmd_id>|<result>
                content = message[4:]
                if '|' in content:
                    cmd_id, result = content.split('|', 1)
                else:
                    cmd_id = content
                    result = ""
                
                with self._command_lock:
                    if cmd_id in self._pending_commands:
                        self._pending_commands[cmd_id].result = result
                        self._pending_commands[cmd_id].success = True
                        self._pending_commands[cmd_id].completed_at = time.time()
                        
        except Exception as e:
            print(f"[BRIDGE] Error processing message: {e}")
    
    def get_logs(self, count: int = 50, since_index: int = 0) -> List[Dict[str, Any]]:
        """
        Get recent log entries.
        
        Args:
            count: Maximum number of entries to return
            since_index: Return entries after this index (for pagination)
            
        Returns:
            List of log entries as dicts
        """
        with self._log_lock:
            if since_index > 0:
                entries = self._log_buffer[since_index:since_index + count]
            else:
                entries = self._log_buffer[-count:]
            
            return [
                {
                    "timestamp": e.timestamp,
                    "message": e.message,
                    "received_at": e.received_at,
                }
                for e in entries
            ]
    
    def get_log_count(self) -> int:
        """Get total number of buffered log entries."""
        with self._log_lock:
            return len(self._log_buffer)
    
    def clear_logs(self) -> None:
        """Clear the log buffer."""
        with self._log_lock:
            self._log_buffer.clear()
    
    def send_command(self, command: str, timeout: float = 5.0) -> CommandResult:
        """
        Send a command to the game and wait for response.
        
        Args:
            command: Command string to send
            timeout: Seconds to wait for response
            
        Returns:
            CommandResult with success/failure and result
        """
        if not self._connected:
            return CommandResult(
                command_id="",
                command=command,
                success=False,
                error="Not connected to game"
            )
        
        # Generate command ID
        with self._command_lock:
            self._command_counter += 1
            cmd_id = f"cmd_{self._command_counter}"
            
            # Create pending command
            result = CommandResult(command_id=cmd_id, command=command)
            self._pending_commands[cmd_id] = result
        
        # Queue command for sending
        self._command_queue.put((cmd_id, command))
        
        # Wait for response
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._command_lock:
                if result.completed_at is not None:
                    # Remove from pending
                    self._pending_commands.pop(cmd_id, None)
                    return result
            if not self._connected:
                with self._command_lock:
                    self._pending_commands.pop(cmd_id, None)
                result.error = "Game disconnected"
                result.completed_at = time.time()
                return result
            time.sleep(0.05)
        
        # Timeout
        with self._command_lock:
            self._pending_commands.pop(cmd_id, None)
        
        result.error = "Command timed out"
        result.completed_at = time.time()
        return result
    
    def send_command_async(self, command: str) -> str:
        """
        Send a command without waiting for response.
        
        Args:
            command: Command string to send
            
        Returns:
            Command ID for tracking
        """
        if not self._connected:
            return ""
        
        with self._command_lock:
            self._command_counter += 1
            cmd_id = f"cmd_{self._command_counter}"
            
            result = CommandResult(command_id=cmd_id, command=command)
            self._pending_commands[cmd_id] = result
        
        self._command_queue.put((cmd_id, command))
        return cmd_id
    
    def get_command_result(self, cmd_id: str) -> Optional[CommandResult]:
        """Get the result of an async command."""
        with self._command_lock:
            return self._pending_commands.get(cmd_id)
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return {
            "running": self._running,
            "connected": self._connected,
            "host": self.host,
            "port": self.port,
            "log_count": self.get_log_count(),
            "pending_commands": len(self._pending_commands),
        }


# Global bridge server instance (per project)
_bridge_servers: Dict[str, BridgeServer] = {}
_servers_lock = threading.Lock()


def get_bridge_server(project_root: str, create: bool = True) -> Optional[BridgeServer]:
    """
    Get or create a bridge server for a project.
    
    Args:
        project_root: Path to project root
        create: If True, create server if it doesn't exist
        
    Returns:
        BridgeServer instance or None
    """
    from pathlib import Path
    key = str(Path(project_root).resolve())
    
    with _servers_lock:
        if key not in _bridge_servers and create:
            _bridge_servers[key] = BridgeServer()
        return _bridge_servers.get(key)


def stop_bridge_server(project_root: str) -> None:
    """Stop and remove the bridge server for a project."""
    from pathlib import Path
    key = str(Path(project_root).resolve())
    
    with _servers_lock:
        server = _bridge_servers.pop(key, None)
        if server:
            server.stop()
