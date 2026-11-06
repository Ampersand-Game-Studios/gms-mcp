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

import hmac
import json
import secrets
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
    - Listens on localhost (ephemeral port)
    - Accepts one game connection at a time
    - Buffers incoming log messages
    - Queues outgoing commands
    - Tracks command responses

    Thread-safe for concurrent MCP tool access.
    """

    DEFAULT_PORT = 0
    MAX_LOG_BUFFER = 10000
    MAX_LINE_BYTES = 1024 * 1024
    MAX_LOG_BYTES = 8 * 1024 * 1024
    HELLO_TIMEOUT = 3.0
    SOCKET_TIMEOUT = 0.5  # seconds

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._requested_port = port
        self.host = "127.0.0.1"
        self.token = secrets.token_urlsafe(32)

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
        self._log_bytes = 0

        # Command tracking
        self._command_queue: queue.Queue = queue.Queue()
        self._pending_commands: Dict[str, CommandResult] = {}
        self._command_lock = threading.Lock()

        # Authenticated endpoint metadata; credentials are never exposed in status.
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
                self.token = secrets.token_urlsafe(32)
                # Create server socket
                self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._server_socket.settimeout(self.SOCKET_TIMEOUT)
                self._server_socket.bind((self.host, self._requested_port))
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
                self._running = False
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

            self._log(logging.INFO, "[BRIDGE] Server stopped")

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
                self._client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._client_socket.close()
            except Exception:
                pass
            self._client_socket = None

        was_connected = self._connected
        self._connected = False
        self.hello = None
        self._command_queue = queue.Queue()

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

    def _read_hello(self, client: socket.socket) -> tuple[Dict[str, Any], bytes]:
        deadline = time.monotonic() + self.HELLO_TIMEOUT
        buffer = bytearray()
        search_from = 0
        while self._running and time.monotonic() < deadline:
            try:
                data = client.recv(4096)
            except socket.timeout:
                continue
            if not data:
                break
            buffer.extend(data)
            newline = buffer.find(b"\n", search_from)
            if newline >= 0:
                if newline > self.MAX_LINE_BYTES:
                    break
                line = bytes(buffer[:newline]).replace(b"\x00", b"")
                if not line.startswith(b"HELLO:"):
                    break
                hello = json.loads(line[6:])
                token = hello.get("token") if isinstance(hello, dict) else None
                if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.token.encode()):
                    break
                hello.pop("token")
                return hello, bytes(buffer[newline + 1 :])
            if len(buffer) > self.MAX_LINE_BYTES:
                break
            search_from = len(buffer)
        raise ValueError("Bridge authentication failed or timed out")

    def _server_loop(self) -> None:
        """Authenticate candidates before replacing the active game connection."""
        listener = self._server_socket
        while self._running and listener is not None and self._server_socket is listener:
            try:
                client, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(self.SOCKET_TIMEOUT)
            try:
                hello, buffered = self._read_hello(client)
            except (OSError, ValueError, RecursionError):
                client.close()
                continue
            with self._lock:
                if not self._running or self._server_socket is not listener:
                    client.close()
                    break
                self._disconnect_client()
                self._client_socket = client
                self.hello = hello
                self._connected = True
                commands = self._command_queue
            if self._on_connect:
                try:
                    self._on_connect()
                except Exception:
                    pass
            self._receive_thread = threading.Thread(
                target=self._receive_loop, args=(client, buffered), name="BridgeReceiver", daemon=True
            )
            self._receive_thread.start()
            threading.Thread(target=self._send_loop, args=(client, commands), name="BridgeSender", daemon=True).start()

    def _disconnect_socket(self, client: socket.socket) -> None:
        with self._lock:
            if self._client_socket is client:
                self._disconnect_client()

    def _receive_loop(self, client: socket.socket, initial: bytes = b"") -> None:
        """Frame bytes before decoding, scanning each incoming byte only once."""
        buffer = bytearray(initial)
        search_from = 0
        try:
            while self._running and self._client_socket is client:
                while True:
                    newline = buffer.find(b"\n", search_from)
                    if newline < 0:
                        if len(buffer) > self.MAX_LINE_BYTES:
                            return
                        search_from = len(buffer)
                        break
                    if newline > self.MAX_LINE_BYTES:
                        return
                    line = bytes(buffer[:newline]).replace(b"\x00", b"").decode("utf-8", errors="replace").strip()
                    del buffer[: newline + 1]
                    search_from = 0
                    with self._lock:
                        if self._client_socket is not client:
                            return
                        if line:
                            self._process_message(line)
                try:
                    data = client.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    return
                buffer.extend(data)
        except OSError:
            pass
        finally:
            self._disconnect_socket(client)

    def _send_loop(self, client: socket.socket, commands: queue.Queue) -> None:
        """Send only on the socket and queue owned by this connection."""
        while self._running and self._client_socket is client:
            try:
                cmd_id, command = commands.get(timeout=self.SOCKET_TIMEOUT)
            except queue.Empty:
                continue
            with self._lock:
                if self._client_socket is not client:
                    return
                with self._command_lock:
                    pending = self._pending_commands.get(cmd_id)
                    if pending is None or pending.completed_at is not None:
                        continue
                try:
                    client.sendall(f"CMD:{cmd_id}|{command}\n".encode("utf-8"))
                except OSError:
                    self._disconnect_socket(client)
                    return

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
                    self._log_bytes += len(timestamp.encode("utf-8")) + len(log_msg.encode("utf-8"))
                    while len(self._log_buffer) > self.MAX_LOG_BUFFER or self._log_bytes > self.MAX_LOG_BYTES:
                        removed = self._log_buffer.pop(0)
                        self._log_bytes -= len(removed.timestamp.encode("utf-8")) + len(removed.message.encode("utf-8"))

                if self._on_log:
                    try:
                        self._on_log(entry)
                    except Exception:
                        pass

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
            self._log_bytes = 0

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
            cmd_id = secrets.token_urlsafe(24)

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
            cmd_id = secrets.token_urlsafe(24)

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

    with _servers_lock:
        if key not in _bridge_servers and create:
            _bridge_servers[key] = BridgeServer() if port is None else BridgeServer(port=port)
        return _bridge_servers.get(key)


def stop_bridge_server(project_root: str) -> None:
    """Stop and remove the bridge server for a project."""
    from pathlib import Path

    key = str(Path(project_root).resolve())

    with _servers_lock:
        server = _bridge_servers.pop(key, None)
        if server:
            server.stop()
