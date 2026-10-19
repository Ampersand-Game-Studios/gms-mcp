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

import json
import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime

LOGGER = logging.getLogger("gms_helpers.bridge_server")
if not LOGGER.handlers:
    LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False


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

    def __init__(self, port: int = DEFAULT_PORT, *, expected_identity: Optional[Dict[str, str]] = None):
        self.port = port
        self.host = "127.0.0.1"
        self.expected_identity = dict(expected_identity) if expected_identity is not None else None
        self.connection_error: Optional[str] = None

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

        # Protocol 2 handshake sent by the game (HELLO:<json>); None for older endpoints.
        self.hello: Optional[Dict[str, Any]] = None

        # Callbacks
        self._on_connect: Optional[Callable[[], None]] = None
        self._on_disconnect: Optional[Callable[[], None]] = None
        self._on_log: Optional[Callable[[LogEntry], None]] = None

    def _log(self, level: int, message: str, *args: Any, exc_info: bool = False) -> None:
        """
        BridgeServer may run inside a stdio MCP server process.
        Never write directly to stdout/stderr from here.
        """
        try:
            LOGGER.log(level, message, *args, exc_info=exc_info)
        except Exception:
            pass

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
                # Port 0 asks the OS for a free port, so several servers can run at once.
                self.port = int(self._server_socket.getsockname()[1])
                self._server_socket.listen(1)

                self._running = True

                # Start server thread
                self._server_thread = threading.Thread(target=self._server_loop, name="BridgeServer", daemon=True)
                self._server_thread.start()

                self._log(logging.INFO, "[BRIDGE] Server started on %s:%s", self.host, self.port)
                return True

            except Exception as e:
                self._log(logging.ERROR, "[BRIDGE] Failed to start server: %s", e, exc_info=True)
                self._cleanup_server()
                return False

    def stop(self) -> None:
        """Stop the bridge server and disconnect any client."""
        with self._lock:
            if not self._running:
                return

            self._log(logging.INFO, "[BRIDGE] Stopping server...")
            self._running = False

            # Close client connection
            self._disconnect_client()

            # Close server socket
            self._cleanup_server()

            # Wait for threads to finish
            if self._server_thread and self._server_thread.is_alive():
                self._server_thread.join(timeout=2.0)

            self._log(logging.INFO, "[BRIDGE] Server stopped")

    def _cleanup_server(self) -> None:
        """Clean up server socket."""
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

    def _disconnect_client(self, client_socket: Optional[socket.socket] = None) -> None:
        """Disconnect only the client owned by the calling receive loop."""
        if client_socket is not None and self._client_socket is not client_socket:
            return
        if self._client_socket:
            try:
                self._client_socket.close()
            except Exception:
                pass
            self._client_socket = None

        was_connected = self._connected
        self._connected = False
        self.hello = None

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

                    # Authenticate before exposing the connection to any tool or
                    # replacing a connected game. Older endpoints fail closed.
                    hello = None
                    if self.expected_identity is not None:
                        try:
                            handshake = bytearray()
                            deadline = time.monotonic() + 2.0
                            while b"\n" not in handshake and len(handshake) < 16384:
                                if time.monotonic() >= deadline or not self._running:
                                    raise ValueError("Bridge identity handshake timed out")
                                try:
                                    chunk = client_socket.recv(1)
                                except socket.timeout:
                                    continue
                                if not chunk:
                                    raise ValueError("Bridge closed before identity handshake")
                                if chunk != b"\x00":
                                    handshake.extend(chunk)
                            line = handshake.decode("utf-8").strip()
                            if not line.startswith("HELLO:"):
                                raise ValueError("Missing bridge identity")
                            hello = json.loads(line[6:])
                            if not isinstance(hello, dict) or any(
                                hello.get(key) != value for key, value in self.expected_identity.items()
                            ):
                                raise ValueError("Bridge project/session identity mismatch")
                        except (ValueError, OSError) as exc:
                            self.connection_error = str(exc)
                            client_socket.close()
                            continue

                    with self._lock:
                        if self._connected:
                            client_socket.close()
                            continue

                        self._client_socket = client_socket
                        self.hello = hello
                        self.connection_error = None
                        self._connected = True

                    self._log(logging.INFO, "[BRIDGE] Game connected from %s", addr)

                    if self._on_connect:
                        try:
                            self._on_connect()
                        except Exception:
                            pass

                    # Start receive thread for this connection
                    self._receive_thread = threading.Thread(
                        target=self._receive_loop, args=(client_socket,), name="BridgeReceiver", daemon=True
                    )
                    self._receive_thread.start()

                    # Also start send thread
                    send_thread = threading.Thread(
                        target=self._send_loop, args=(client_socket,), name="BridgeSender", daemon=True
                    )
                    send_thread.start()

                except socket.timeout:
                    continue

            except Exception as e:
                if self._running:
                    self._log(logging.ERROR, "[BRIDGE] Server error: %s", e, exc_info=True)
                break

    def _receive_loop(self, client_socket: socket.socket) -> None:
        """Receive loop - reads data from connected game."""
        buffer = ""

        while self._running and self._connected and self._client_socket is client_socket:
            try:
                if not self._client_socket:
                    break

                try:
                    data = client_socket.recv(4096)
                    if not data:
                        # Connection closed
                        self._log(logging.INFO, "[BRIDGE] Game disconnected")
                        self._disconnect_client(client_socket)
                        break

                    buffer += data.decode("utf-8", errors="replace")
                    # GameMaker's `buffer_write(..., buffer_string, ...)` writes a NUL-terminated string.
                    # When we receive raw TCP bytes and split on '\n', subsequent messages may start with '\x00'
                    # (e.g. '\x00LOG:' / '\x00RSP:'), which would fail our startswith() checks.
                    buffer = buffer.replace("\x00", "")

                    # Process complete lines
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            self._process_message(line)

                except socket.timeout:
                    continue

            except Exception as e:
                if self._running and self._connected:
                    self._log(logging.ERROR, "[BRIDGE] Receive error: %s", e, exc_info=True)
                self._disconnect_client(client_socket)
                break

    def _send_loop(self, client_socket: socket.socket) -> None:
        """Send loop - sends queued commands to game."""
        while self._running and self._connected and self._client_socket is client_socket:
            try:
                # Get command from queue (with timeout)
                try:
                    cmd_id, command = self._command_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if self._client_socket is not client_socket or not self._connected:
                    break

                # Send command
                message = f"CMD:{cmd_id}|{command}\n"
                try:
                    client_socket.sendall(message.encode("utf-8"))
                except Exception as e:
                    self._log(logging.ERROR, "[BRIDGE] Send error: %s", e, exc_info=True)
                    # Put command back for retry? Or mark as failed?
                    with self._command_lock:
                        if cmd_id in self._pending_commands:
                            self._pending_commands[cmd_id].error = str(e)
                            self._pending_commands[cmd_id].completed_at = time.time()

            except Exception as e:
                if self._running:
                    self._log(logging.ERROR, "[BRIDGE] Send loop error: %s", e, exc_info=True)
                break

    def _process_message(self, message: str) -> None:
        """Process a message received from the game."""
        try:
            if message.startswith("LOG:"):
                # Log message: LOG:<timestamp>|<message>
                content = message[4:]
                if "|" in content:
                    timestamp, log_msg = content.split("|", 1)
                else:
                    timestamp = str(int(time.time() * 1000))
                    log_msg = content

                entry = LogEntry(timestamp=timestamp, message=log_msg)

                with self._log_lock:
                    self._log_buffer.append(entry)
                    # Trim buffer if too large
                    if len(self._log_buffer) > self.MAX_LOG_BUFFER:
                        self._log_buffer = self._log_buffer[-self.MAX_LOG_BUFFER // 2 :]

                if self._on_log:
                    try:
                        self._on_log(entry)
                    except Exception:
                        pass

            elif message.startswith("HELLO:"):
                # Protocol 2 handshake: HELLO:<json describing the game endpoint>
                try:
                    hello = json.loads(message[6:])
                    if self.expected_identity is not None and (
                        not isinstance(hello, dict)
                        or any(hello.get(key) != value for key, value in self.expected_identity.items())
                    ):
                        self._disconnect_client()
                        return
                    self.hello = hello if isinstance(hello, dict) else {"raw": message[6:]}
                except ValueError:
                    self.hello = {"raw": message[6:]}

            elif message.startswith("RSP:"):
                # Command response: RSP:<cmd_id>|<result>
                content = message[4:]
                if "|" in content:
                    cmd_id, result = content.split("|", 1)
                else:
                    cmd_id = content
                    result = ""

                with self._command_lock:
                    if cmd_id in self._pending_commands:
                        self._pending_commands[cmd_id].result = result
                        self._pending_commands[cmd_id].success = True
                        self._pending_commands[cmd_id].completed_at = time.time()

        except Exception as e:
            self._log(logging.ERROR, "[BRIDGE] Error processing message: %s", e, exc_info=True)

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
                entries = self._log_buffer[since_index : since_index + count]
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
            return CommandResult(command_id="", command=command, success=False, error="Not connected to game")

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
            "hello": self.hello,
            "connection_error": self.connection_error,
        }


# Global bridge server instance (per project)
_bridge_servers: Dict[str, BridgeServer] = {}
_servers_lock = threading.Lock()


def get_bridge_server(project_root: str, create: bool = True, port: Optional[int] = None) -> Optional[BridgeServer]:
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

    # The managed launch owns its dynamic port and lifetime. Never create a
    # second fixed-port listener for tools targeting this same project.
    from .live_session import get_session

    session = get_session(key)
    if session is not None:
        return session.bridge if session.alive and session.bridge and session.bridge.is_running else None

    with _servers_lock:
        if key not in _bridge_servers and create:
            import uuid

            from .mac_runtime import project_identity

            _bridge_servers[key] = BridgeServer(
                port=0 if port is None else port,
                expected_identity={"project_id": project_identity(Path(key)), "session_id": uuid.uuid4().hex},
            )
        return _bridge_servers.get(key)


def stop_bridge_server(project_root: str) -> None:
    """Stop and remove the bridge server for a project."""
    from pathlib import Path

    key = str(Path(project_root).resolve())

    with _servers_lock:
        server = _bridge_servers.pop(key, None)
        if server:
            server.stop()
