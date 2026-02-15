from __future__ import annotations

from typing import Any, Dict

from ..mcp_types import Context


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Bridge tools (Phase 3)
    # -----------------------------
    @mcp.tool()
    async def gm_bridge_install(
        port: int = 6502,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Install the MCP bridge into the GameMaker project.
        
        The bridge enables bidirectional communication between Cursor agents
        and running GameMaker games, providing:
        - Real-time log capture via __mcp_log(...) (also calls show_debug_message in-game)
        - Command execution (spawn objects, change rooms, set variables)
        - Game state querying

        Note: Installing the bridge does not automatically place an instance in any room.
        The game will only connect if __mcp_bridge is instantiated at runtime
        (for example, by placing it in the startup room).
        
        Bridge assets use __mcp_ prefix and can be removed with gm_bridge_uninstall.
        Once installed, the bridge is automatically used when running with gm_run.
        
        Args:
            port: Port for bridge server (default: 6502)
            project_root: Path to project root
            
        Returns:
            Installation result with ok, message, and details
        """
        # Bridge installer needs actual project_root, not repo_root
        from gms_helpers.bridge_installer import install_bridge
        
        try:
            result = install_bridge(project_root, port)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Installation failed: {e}"}

    @mcp.tool()
    async def gm_bridge_uninstall(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Remove the MCP bridge from the GameMaker project.
        
        Safely removes all __mcp_ prefixed assets and cleans up .yyp references.
        Uses backup/rollback to ensure project integrity.

        Important: If you placed __mcp_bridge instances into rooms, remove those instances first.
        Uninstalling removes the object asset; leaving room instance references can break IDE loading.
        
        Args:
            project_root: Path to project root
            
        Returns:
            Uninstallation result with ok, message, and details
        """
        # Bridge installer needs actual project_root, not repo_root
        from gms_helpers.bridge_installer import uninstall_bridge
        
        try:
            result = uninstall_bridge(project_root)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Uninstallation failed: {e}"}

    @mcp.tool()
    async def gm_bridge_status(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Check bridge installation and connection status.
        
        Returns:
            Dict with:
            - installed: bool - whether bridge assets exist in project
            - server_running: bool - whether bridge server is active
            - game_connected: bool - whether a game is connected to bridge
            - log_count: int - number of buffered log messages
        """
        # Bridge needs actual project_root, not repo_root
        from gms_helpers.bridge_installer import get_bridge_status
        from gms_helpers.bridge_server import get_bridge_server
        
        try:
            # Get installation status
            install_status = get_bridge_status(project_root)
            
            # Get server status
            server = get_bridge_server(project_root, create=False)
            server_status = server.get_status() if server else {
                "running": False,
                "connected": False,
                "log_count": 0,
            }
            
            return {
                "ok": True,
                "installed": install_status.get("installed", False),
                "server_running": server_status.get("running", False),
                "game_connected": server_status.get("connected", False),
                "log_count": server_status.get("log_count", 0),
                "install_details": install_status,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Status check failed: {e}"}

    @mcp.tool()
    async def gm_run_logs(
        lines: int = 50,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Get recent log output from the running game.
        
        Requires:
        - Bridge installed (gm_bridge_install)
        - Game running (gm_run with background=true)
        - Game connected to bridge
        
        Args:
            lines: Number of log lines to return (default: 50)
            project_root: Path to project root
            
        Notes:
        - Only logs sent via __mcp_log(...) are available to this tool.
        
        Returns:
            Dict with:
            - ok: bool
            - logs: list of log entries
            - log_count: total buffered logs
            - connected: whether game is connected
        """
        # Bridge needs actual project_root, not repo_root
        from gms_helpers.bridge_server import get_bridge_server
        
        try:
            server = get_bridge_server(project_root, create=False)
            
            if not server:
                return {
                    "ok": False,
                    "error": "Bridge server not running",
                    "message": "No bridge server active. Run the game first.",
                    "logs": [],
                }
            
            if not server.is_connected:
                return {
                    "ok": False,
                    "error": "Game not connected",
                    "message": "Game is not connected to bridge. Is bridge installed?",
                    "logs": [],
                    "server_running": True,
                }
            
            logs = server.get_logs(count=lines)
            
            return {
                "ok": True,
                "logs": logs,
                "log_count": server.get_log_count(),
                "connected": True,
                "message": f"Retrieved {len(logs)} log entries",
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Failed to get logs: {e}", "logs": []}

    @mcp.tool()
    async def gm_run_command(
        command: str,
        timeout: float = 5.0,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Send a command to the running game via MCP bridge.
        
        Built-in commands:
        - ping: Test connection (responds with "pong")
        - goto_room <room_name>: Change to specified room
        - get_var global.<name>: Get a global variable value
        - set_var global.<name> <value>: Set a global variable
        - spawn <object_name> <x> <y>: Create an instance
        - room_info: Get current room name and size
        - instance_count [object]: Count instances
        
        Custom commands can be added by editing __mcp_bridge.
        
        Args:
            command: Command string to send
            timeout: Seconds to wait for response (default: 5.0)
            project_root: Path to project root
            
        Returns:
            Dict with command result (ok, result, or error)
        """
        # Bridge needs actual project_root, not repo_root
        from gms_helpers.bridge_server import get_bridge_server
        
        try:
            server = get_bridge_server(project_root, create=False)
            
            if not server:
                return {
                    "ok": False,
                    "error": "Bridge server not running",
                    "message": "No bridge server active. Run the game first.",
                }
            
            if not server.is_connected:
                return {
                    "ok": False,
                    "error": "Game not connected",
                    "message": "Game is not connected to bridge.",
                }
            
            result = server.send_command(command, timeout=timeout)
            
            if result.success:
                return {
                    "ok": True,
                    "command": command,
                    "result": result.result,
                    "message": f"Command executed: {result.result}",
                }
            else:
                return {
                    "ok": False,
                    "command": command,
                    "error": result.error or "Command failed",
                    "message": result.error or "Command failed",
                }
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Failed to send command: {e}"}
