from __future__ import annotations

from typing import Any, Dict

from ..mcp_types import Context
from ..project import _resolve_project_directory
from ..direct import _pushd


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
        Attempts to remove __mcp_bridge room instances as part of uninstall.
        Uses backup/rollback to ensure project integrity.

        Note: If room cleanup cannot be completed, warnings are returned in the result.
        
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
    async def gm_bridge_enable_one_shot(
        port: int = 6502,
        room_name: str = "",
        layer: str = "Instances",
        x: float = 0,
        y: float = 0,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        One-shot bridge enable:
        - Install bridge assets (if missing)
        - Ensure __mcp_bridge instance exists in the startup room
        - Ensure the instance is present in instanceCreationOrder[]

        Args:
            port: Bridge server port (default: 6502)
            room_name: Optional explicit room name. If empty, uses first RoomOrderNodes entry (startup room)
            layer: Instance layer name (default: "Instances")
            x, y: Placement coordinates for the bridge instance (default: 0,0)
            project_root: Path to project root

        Returns:
            Dict with ok, room_name, instance_id, and validation details.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)

        from gms_helpers.utils import load_json_loose
        from gms_helpers.bridge_installer import install_bridge, BRIDGE_OBJECT_NAME
        from gms_helpers.room_layer_helper import add_layer
        from gms_helpers.room_instance_helper import add_instance

        yyp_files = sorted(project_directory.glob("*.yyp"))
        if not yyp_files:
            return {"ok": False, "error": f"No .yyp found in {project_directory}"}
        yyp_path = yyp_files[0]
        yyp_data = load_json_loose(yyp_path) or {}

        def _detect_startup_room() -> str:
            for node in yyp_data.get("RoomOrderNodes", []) or []:
                room_id = (node or {}).get("roomId", {}) if isinstance(node, dict) else {}
                if isinstance(room_id, dict) and room_id.get("name"):
                    return str(room_id["name"])
            for res in yyp_data.get("resources", []) or []:
                res_id = (res or {}).get("id", {}) if isinstance(res, dict) else {}
                path = res_id.get("path") if isinstance(res_id, dict) else None
                name = res_id.get("name") if isinstance(res_id, dict) else None
                if isinstance(path, str) and path.startswith("rooms/") and isinstance(name, str) and name:
                    return name
            return ""

        target_room = room_name.strip() if room_name else _detect_startup_room()
        if not target_room:
            return {
                "ok": False,
                "error": "Could not determine startup room (missing RoomOrderNodes/resources room entry).",
                "hint": "Pass room_name explicitly, or add the startup room to RoomOrderNodes in the .yyp.",
                "yyp": str(yyp_path),
            }

        room_file = project_directory / "rooms" / target_room / f"{target_room}.yy"
        if not room_file.exists():
            return {
                "ok": False,
                "error": f"Startup room file not found: {room_file}",
                "hint": "Create the room first (gm_create_room) or ensure RoomOrderNodes points at an existing room.",
            }

        install_result = install_bridge(str(project_directory), port)
        if not install_result.get("ok"):
            return {"ok": False, "error": install_result.get("error") or install_result, "install": install_result}

        # All room helpers are path-relative; operate from project_directory.
        with _pushd(project_directory):
            # Ensure the target layer exists (create instance layer if missing).
            room_data = load_json_loose(room_file) or {}
            layers = room_data.get("layers", []) if isinstance(room_data, dict) else []
            layer_exists = any(isinstance(l, dict) and l.get("name") == layer for l in (layers or []))
            if not layer_exists:
                add_layer(target_room, layer, "instance", 0)

            # Idempotent instance placement: reuse existing __mcp_bridge instance if present.
            room_data = load_json_loose(room_file) or {}
            existing_instance_id = None
            for lyr in room_data.get("layers", []) or []:
                if not isinstance(lyr, dict) or lyr.get("resourceType") != "GMRInstanceLayer":
                    continue
                for inst in lyr.get("instances", []) or []:
                    if not isinstance(inst, dict):
                        continue
                    obj = inst.get("objectId") or {}
                    if isinstance(obj, dict) and obj.get("name") == BRIDGE_OBJECT_NAME:
                        existing_instance_id = inst.get("name")
                        break
                if existing_instance_id:
                    break

            instance_id = existing_instance_id or add_instance(target_room, BRIDGE_OBJECT_NAME, x, y, layer)

            # Validate instanceCreationOrder includes instance_id; if not, patch it in.
            room_data = load_json_loose(room_file) or {}
            creation_order = room_data.get("instanceCreationOrder")
            if not isinstance(creation_order, list):
                creation_order = []
                room_data["instanceCreationOrder"] = creation_order

            def _has(entry: Any) -> bool:
                if isinstance(entry, str):
                    return entry == instance_id
                if isinstance(entry, dict):
                    return entry.get("name") == instance_id or entry.get("%Name") == instance_id
                return False

            if not any(_has(e) for e in creation_order):
                if creation_order and isinstance(creation_order[0], str):
                    creation_order.append(instance_id)
                else:
                    creation_order.append({"name": instance_id, "path": f"rooms/{target_room}/{target_room}.yy"})

                from gms_helpers.utils import save_json_loose

                save_json_loose(room_file, room_data)

        return {
            "ok": True,
            "project_directory": str(project_directory),
            "room_name": target_room,
            "layer": layer,
            "instance_id": instance_id,
            "install": install_result,
            "instance_creation_order_ok": True,
        }

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
