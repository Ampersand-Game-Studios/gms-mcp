#!/usr/bin/env python3
"""
Bridge Installer for GameMaker MCP

Handles safe installation and removal of bridge assets in GameMaker projects.
Uses a transactional approach with backup/rollback to ensure project integrity.

Safety principles:
1. Create files before modifying .yyp
2. Backup .yyp before any modifications
3. Verify changes after each step
4. Rollback on any failure
5. All assets use __mcp_ prefix for easy identification
"""

import json
import shutil
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from .utils import load_json, save_json


def _find_yyp_in_dir(directory: Path) -> Optional[Path]:
    """Find a .yyp file in the given directory."""
    yyp_files = list(directory.glob("*.yyp"))
    if not yyp_files:
        return None
    return yyp_files[0]


def _detect_asset_format(project_root: Path, asset_type: str) -> str:
    """
    Detect the format version string used for an asset type in this project.
    
    Reads an existing asset of the given type and extracts its version string.
    Falls back to empty string if no existing assets found.
    
    Args:
        project_root: Path to project root
        asset_type: Asset type folder name (e.g., "objects", "scripts")
        
    Returns:
        Version string (e.g., "v1" or "")
    """
    asset_dir = project_root / asset_type
    if not asset_dir.exists():
        return ""
    
    # Find first .yy file
    for subdir in asset_dir.iterdir():
        if subdir.is_dir():
            yy_files = list(subdir.glob("*.yy"))
            if yy_files:
                try:
                    data = load_json(yy_files[0])
                    # Look for the $GM* key
                    for key in data:
                        if key.startswith("$GM"):
                            return data[key]
                except Exception:
                    pass
    return ""


# Bridge asset names
BRIDGE_OBJECT_NAME = "__mcp_bridge"
BRIDGE_SCRIPT_NAME = "__mcp_log"
BRIDGE_FOLDER_NAME = "__mcp"

# Asset type constants
ASSET_TYPE_OBJECT = "objects"
ASSET_TYPE_SCRIPT = "scripts"
ASSET_TYPE_FOLDER = "folders"


class BridgeInstallError(Exception):
    """Error during bridge installation/removal."""
    pass


class BridgeInstaller:
    """
    Handles installation and removal of MCP bridge assets.
    
    The bridge consists of:
    - __mcp_bridge object (handles networking)
    - __mcp_log script (logging helper)
    - __mcp folder (organizational)
    """
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.yyp_path = _find_yyp_in_dir(self.project_root)
        if not self.yyp_path:
            raise BridgeInstallError(f"No .yyp file found in {self.project_root}")
        
        self.backup_path: Optional[Path] = None
        
        # Detect format versions from existing assets
        self._object_version = _detect_asset_format(self.project_root, "objects")
        self._script_version = _detect_asset_format(self.project_root, "scripts")
        self._folder_version = _detect_asset_format(self.project_root, "folders")
    
    def is_installed(self) -> bool:
        """Check if bridge is already installed."""
        # Check for bridge object
        bridge_object_dir = self.project_root / ASSET_TYPE_OBJECT / BRIDGE_OBJECT_NAME
        if not bridge_object_dir.exists():
            return False
        
        # Check for .yy file
        bridge_yy = bridge_object_dir / f"{BRIDGE_OBJECT_NAME}.yy"
        if not bridge_yy.exists():
            return False
        
        # Check if registered in .yyp
        try:
            yyp_data = load_json(self.yyp_path)
            resources = yyp_data.get("resources", [])
            for resource in resources:
                path = resource.get("id", {}).get("path", "")
                if BRIDGE_OBJECT_NAME in path:
                    return True
        except Exception:
            pass
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get detailed installation status."""
        status = {
            "installed": False,
            "object_exists": False,
            "script_exists": False,
            "folder_exists": False,
            "registered_in_yyp": False,
            "issues": [],
        }
        
        # Check object
        bridge_object_dir = self.project_root / ASSET_TYPE_OBJECT / BRIDGE_OBJECT_NAME
        bridge_object_yy = bridge_object_dir / f"{BRIDGE_OBJECT_NAME}.yy"
        status["object_exists"] = bridge_object_yy.exists()
        
        # Check script
        bridge_script_dir = self.project_root / ASSET_TYPE_SCRIPT / BRIDGE_SCRIPT_NAME
        bridge_script_yy = bridge_script_dir / f"{BRIDGE_SCRIPT_NAME}.yy"
        status["script_exists"] = bridge_script_yy.exists()
        
        # Check folder
        bridge_folder_yy = self.project_root / ASSET_TYPE_FOLDER / f"{BRIDGE_FOLDER_NAME}.yy"
        status["folder_exists"] = bridge_folder_yy.exists()
        
        # Check .yyp registration
        try:
            yyp_data = load_json(self.yyp_path)
            resources = yyp_data.get("resources", [])
            registered_count = 0
            for resource in resources:
                path = resource.get("id", {}).get("path", "")
                if "__mcp" in path:
                    registered_count += 1
            status["registered_in_yyp"] = registered_count >= 2  # At least object and script
        except Exception as e:
            status["issues"].append(f"Failed to read .yyp: {e}")
        
        # Determine overall status
        status["installed"] = (
            status["object_exists"] and 
            status["script_exists"] and 
            status["registered_in_yyp"]
        )
        
        # Check for inconsistencies
        if status["object_exists"] and not status["registered_in_yyp"]:
            status["issues"].append("Bridge files exist but not registered in .yyp")
        if status["registered_in_yyp"] and not status["object_exists"]:
            status["issues"].append("Bridge registered in .yyp but files missing")
        
        return status
    
    def _backup_yyp(self) -> Path:
        """Create a backup of the .yyp file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{self.yyp_path.stem}.yyp.mcp_backup_{timestamp}"
        backup_path = self.yyp_path.parent / backup_name
        shutil.copy2(self.yyp_path, backup_path)
        self.backup_path = backup_path
        return backup_path
    
    def _restore_yyp(self) -> None:
        """Restore .yyp from backup."""
        if self.backup_path and self.backup_path.exists():
            shutil.copy2(self.backup_path, self.yyp_path)
            self.backup_path.unlink()
            self.backup_path = None
    
    def _cleanup_backup(self) -> None:
        """Remove backup file on success."""
        if self.backup_path and self.backup_path.exists():
            self.backup_path.unlink()
            self.backup_path = None

    def _iter_room_files(self, yyp_data: Dict[str, Any]) -> List[Path]:
        """Return room .yy files listed in the project resources."""
        room_files: List[Path] = []
        seen: set[str] = set()
        resources = yyp_data.get("resources", [])
        if not isinstance(resources, list):
            return room_files

        for resource in resources:
            if not isinstance(resource, dict):
                continue
            res_id = resource.get("id")
            if not isinstance(res_id, dict):
                continue
            rel_path = res_id.get("path")
            if not isinstance(rel_path, str):
                continue

            normalized = rel_path.replace("\\", "/")
            if not normalized.startswith("rooms/") or not normalized.endswith(".yy"):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)

            room_file = self.project_root / Path(normalized)
            if room_file.exists():
                room_files.append(room_file)

        return room_files

    @staticmethod
    def _is_bridge_instance(instance_data: Dict[str, Any]) -> bool:
        """Check whether a room instance points to the bridge object."""
        object_id = instance_data.get("objectId")
        if not isinstance(object_id, dict):
            return False

        object_name = str(object_id.get("name", ""))
        object_path = str(object_id.get("path", "")).replace("\\", "/")
        return (
            object_name == BRIDGE_OBJECT_NAME
            or object_path == f"objects/{BRIDGE_OBJECT_NAME}/{BRIDGE_OBJECT_NAME}.yy"
            or f"/{BRIDGE_OBJECT_NAME}/" in object_path
        )

    def _cleanup_bridge_room_instances(self, yyp_data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove __mcp_bridge instances from all project rooms."""
        summary: Dict[str, Any] = {
            "rooms_modified": [],
            "instances_removed": 0,
            "creation_code_deleted": 0,
            "warnings": [],
        }

        for room_file in self._iter_room_files(yyp_data):
            try:
                room_data = load_json(room_file)
                if not isinstance(room_data, dict):
                    summary["warnings"].append(f"Failed to parse room JSON: {room_file}")
                    continue

                layers = room_data.get("layers", [])
                if not isinstance(layers, list):
                    continue

                changed = False
                removed_instance_ids: set[str] = set()
                removed_count = 0

                for layer in layers:
                    if not isinstance(layer, dict):
                        continue
                    instances = layer.get("instances")
                    if not isinstance(instances, list):
                        continue

                    kept_instances = []
                    for instance in instances:
                        if isinstance(instance, dict) and self._is_bridge_instance(instance):
                            removed_count += 1
                            instance_name = instance.get("name") or instance.get("%Name")
                            if isinstance(instance_name, str) and instance_name:
                                removed_instance_ids.add(instance_name)
                            changed = True
                            continue
                        kept_instances.append(instance)

                    if len(kept_instances) != len(instances):
                        layer["instances"] = kept_instances

                if removed_instance_ids:
                    creation_order = room_data.get("instanceCreationOrder")
                    if isinstance(creation_order, list):
                        before_count = len(creation_order)

                        def _keep(entry: Any) -> bool:
                            if isinstance(entry, str):
                                return entry not in removed_instance_ids
                            if isinstance(entry, dict):
                                entry_name = entry.get("name") or entry.get("%Name")
                                return entry_name not in removed_instance_ids
                            return True

                        room_data["instanceCreationOrder"] = [entry for entry in creation_order if _keep(entry)]
                        if len(room_data["instanceCreationOrder"]) != before_count:
                            changed = True

                    for instance_id in removed_instance_ids:
                        creation_code_file = room_file.parent / f"{instance_id}.gml"
                        if creation_code_file.exists():
                            creation_code_file.unlink()
                            summary["creation_code_deleted"] += 1

                if changed:
                    save_json(room_data, room_file)
                    summary["instances_removed"] += removed_count
                    summary["rooms_modified"].append(str(room_file.relative_to(self.project_root)))
            except Exception as exc:
                summary["warnings"].append(f"Failed to clean room '{room_file}': {exc}")

        return summary
    
    def _generate_uuid(self) -> str:
        """Generate a GameMaker-style UUID."""
        return str(uuid.uuid4())
    
    def _create_folder_asset(self) -> Tuple[Path, Dict[str, Any]]:
        """Create the __mcp folder asset."""
        folder_yy_path = self.project_root / ASSET_TYPE_FOLDER / f"{BRIDGE_FOLDER_NAME}.yy"
        
        folder_data = {
            "$GMFolder": self._folder_version,
            "%Name": BRIDGE_FOLDER_NAME,
            "folderPath": f"folders/{BRIDGE_FOLDER_NAME}.yy",
            "name": BRIDGE_FOLDER_NAME,
            "resourceType": "GMFolder",
            "resourceVersion": "2.0",
        }
        
        return folder_yy_path, folder_data
    
    def _create_script_asset(self) -> Tuple[Path, Dict[str, Any], str]:
        """Create the __mcp_log script asset."""
        script_dir = self.project_root / ASSET_TYPE_SCRIPT / BRIDGE_SCRIPT_NAME
        script_yy_path = script_dir / f"{BRIDGE_SCRIPT_NAME}.yy"
        script_gml_path = script_dir / f"{BRIDGE_SCRIPT_NAME}.gml"
        
        script_data = {
            "$GMScript": self._script_version,
            "%Name": BRIDGE_SCRIPT_NAME,
            "isCompatibility": False,
            "isDnD": False,
            "name": BRIDGE_SCRIPT_NAME,
            "parent": {
                "name": BRIDGE_FOLDER_NAME,
                "path": f"folders/{BRIDGE_FOLDER_NAME}.yy",
            },
            "resourceType": "GMScript",
            "resourceVersion": "2.0",
        }
        
        script_gml = '''/// @function __mcp_log(message)
/// @description Log a message to both debug output and MCP bridge
/// @param {string} message The message to log
function __mcp_log(_message) {
    var _timestamp = string(current_time);
    var _full_msg = "[" + _timestamp + "] " + string(_message);
    
    // Always log to standard debug output
    show_debug_message(_full_msg);
    
    // Send to MCP bridge if connected
    if (variable_global_exists("__mcp_socket") && global.__mcp_socket >= 0) {
        var _packet = "LOG:" + _timestamp + "|" + string(_message) + chr(10);
        var _buffer = buffer_create(string_byte_length(_packet) + 1, buffer_fixed, 1);
        buffer_write(_buffer, buffer_string, _packet);
        network_send_raw(global.__mcp_socket, _buffer, buffer_tell(_buffer));
        buffer_delete(_buffer);
    }
}

/// @function __mcp_send_response(cmd_id, result)
/// @description Send a command response to MCP bridge
/// @param {string} cmd_id The command ID to respond to
/// @param {string} result The result string
function __mcp_send_response(_cmd_id, _result) {
    if (variable_global_exists("__mcp_socket") && global.__mcp_socket >= 0) {
        var _packet = "RSP:" + string(_cmd_id) + "|" + string(_result) + chr(10);
        var _buffer = buffer_create(string_byte_length(_packet) + 1, buffer_fixed, 1);
        buffer_write(_buffer, buffer_string, _packet);
        network_send_raw(global.__mcp_socket, _buffer, buffer_tell(_buffer));
        buffer_delete(_buffer);
    }
}
'''
        
        return script_yy_path, script_data, script_gml
    
    def _create_object_asset(self, port: int = 6502) -> Tuple[Path, Dict[str, Any], Dict[str, str]]:
        """Create the __mcp_bridge object asset."""
        object_dir = self.project_root / ASSET_TYPE_OBJECT / BRIDGE_OBJECT_NAME
        object_yy_path = object_dir / f"{BRIDGE_OBJECT_NAME}.yy"
        
        # Events always use v1 format in modern GameMaker
        event_version = "v1"
        
        object_data = {
            "$GMObject": self._object_version,
            "%Name": BRIDGE_OBJECT_NAME,
            "eventList": [
                {"$GMEvent": event_version, "%Name": "Create_0", "collisionObjectId": None, "eventNum": 0, "eventType": 0, "isDnD": False, "name": "Create_0", "resourceType": "GMEvent", "resourceVersion": "2.0"},
                {"$GMEvent": event_version, "%Name": "Step_0", "collisionObjectId": None, "eventNum": 0, "eventType": 3, "isDnD": False, "name": "Step_0", "resourceType": "GMEvent", "resourceVersion": "2.0"},
                {"$GMEvent": event_version, "%Name": "Other_68", "collisionObjectId": None, "eventNum": 68, "eventType": 7, "isDnD": False, "name": "Other_68", "resourceType": "GMEvent", "resourceVersion": "2.0"},
                {"$GMEvent": event_version, "%Name": "Destroy_0", "collisionObjectId": None, "eventNum": 0, "eventType": 1, "isDnD": False, "name": "Destroy_0", "resourceType": "GMEvent", "resourceVersion": "2.0"},
            ],
            "managed": True,
            "name": BRIDGE_OBJECT_NAME,
            "overriddenProperties": [],
            "parent": {
                "name": BRIDGE_FOLDER_NAME,
                "path": f"folders/{BRIDGE_FOLDER_NAME}.yy",
            },
            "parentObjectId": None,
            "persistent": True,
            "physicsAngularDamping": 0.1,
            "physicsDensity": 0.5,
            "physicsFriction": 0.2,
            "physicsGroup": 0,
            "physicsKinematic": False,
            "physicsLinearDamping": 0.1,
            "physicsObject": False,
            "physicsRestitution": 0.1,
            "physicsSensor": False,
            "physicsShape": 1,
            "physicsShapePoints": [],
            "physicsStartAwake": True,
            "properties": [],
            "resourceType": "GMObject",
            "resourceVersion": "2.0",
            "solid": False,
            "spriteId": None,
            "spriteMaskId": None,
            "visible": False,
        }
        
        # Event GML files
        events = {}
        
        # Create Event
        events["Create_0.gml"] = f'''/// @description Initialize MCP Bridge connection
// This object connects to the MCP bridge server for debugging/control

global.__mcp_socket = -1;
global.__mcp_enabled = false;
global.__mcp_buffer = "";
global.__mcp_port = {port};

// Try to connect to MCP bridge server
var _socket = network_create_socket(network_socket_tcp);
var _result = network_connect_raw(_socket, "127.0.0.1", global.__mcp_port);

if (_result >= 0) {{
    global.__mcp_socket = _socket;
    global.__mcp_enabled = true;
    __mcp_log("[MCP] Bridge connected on port " + string(global.__mcp_port));
}} else {{
    // No bridge server running - that's fine, game runs normally
    network_destroy(_socket);
    global.__mcp_socket = -1;
    global.__mcp_enabled = false;
}}
'''
        
        # Step Event
        events["Step_0.gml"] = '''/// @description Process any pending MCP commands
// This runs every frame to check for incoming commands

// Nothing to do if not connected
if (!global.__mcp_enabled) exit;

// Connection check - if socket was closed, disable
if (global.__mcp_socket < 0) {
    global.__mcp_enabled = false;
    exit;
}
'''
        
        # Async Networking Event (Other_68)
        events["Other_68.gml"] = '''/// @description Handle network events from MCP bridge
var _type = async_load[? "type"];
var _sock = async_load[? "id"];

// Only process our socket
if (_sock != global.__mcp_socket) exit;

switch (_type) {
    case network_type_data:
        // Received data from bridge
        var _buffer = async_load[? "buffer"];
        var _size = async_load[? "size"];
        
        if (_size > 0) {
            var _data = buffer_read(_buffer, buffer_string);
            global.__mcp_buffer += _data;
            
            // Process complete lines
            while (string_pos(chr(10), global.__mcp_buffer) > 0) {
                var _newline_pos = string_pos(chr(10), global.__mcp_buffer);
                var _line = string_copy(global.__mcp_buffer, 1, _newline_pos - 1);
                global.__mcp_buffer = string_delete(global.__mcp_buffer, 1, _newline_pos);
                
                // Process command line
                if (string_pos("CMD:", _line) == 1) {
                    var _content = string_delete(_line, 1, 4);
                    var _pipe_pos = string_pos("|", _content);
                    if (_pipe_pos > 0) {
                        var _cmd_id = string_copy(_content, 1, _pipe_pos - 1);
                        var _command = string_delete(_content, 1, _pipe_pos);
                        
                        // Execute command
                        var _result = __mcp_execute_command(_command);
                        __mcp_send_response(_cmd_id, _result);
                    }
                }
            }
        }
        break;
        
    case network_type_disconnect:
        // Bridge disconnected
        __mcp_log("[MCP] Bridge disconnected");
        global.__mcp_enabled = false;
        global.__mcp_socket = -1;
        break;
}

/// @function __mcp_execute_command(command)
/// @description Execute a command from MCP and return result
function __mcp_execute_command(_command) {
    // Parse command (space-separated)
    var _parts = [];
    var _temp = _command;
    while (string_length(_temp) > 0) {
        var _space = string_pos(" ", _temp);
        if (_space > 0) {
            array_push(_parts, string_copy(_temp, 1, _space - 1));
            _temp = string_delete(_temp, 1, _space);
        } else {
            array_push(_parts, _temp);
            _temp = "";
        }
    }
    
    if (array_length(_parts) == 0) return "ERROR:Empty command";
    
    var _action = _parts[0];
    
    switch (_action) {
        case "ping":
            return "pong";
            
        case "goto_room":
            if (array_length(_parts) > 1) {
                var _room = asset_get_index(_parts[1]);
                if (_room >= 0 && room_exists(_room)) {
                    room_goto(_room);
                    return "OK:Changed to " + _parts[1];
                }
                return "ERROR:Room not found: " + _parts[1];
            }
            return "ERROR:Missing room name";
            
        case "get_var":
            if (array_length(_parts) > 1) {
                var _var_name = _parts[1];
                // Check if it starts with "global."
                if (string_pos("global.", _var_name) == 1) {
                    var _real_name = string_delete(_var_name, 1, 7);
                    if (variable_global_exists(_real_name)) {
                        return "OK:" + string(variable_global_get(_real_name));
                    }
                    return "ERROR:Global variable not found: " + _real_name;
                }
                return "ERROR:Only global variables supported";
            }
            return "ERROR:Missing variable name";
            
        case "set_var":
            if (array_length(_parts) > 2) {
                var _var_name = _parts[1];
                var _value = _parts[2];
                if (string_pos("global.", _var_name) == 1) {
                    var _real_name = string_delete(_var_name, 1, 7);
                    // Try to convert to real if it looks like a number
                    var _real_value = real(_value);
                    if (string(_real_value) == _value) {
                        variable_global_set(_real_name, _real_value);
                    } else {
                        variable_global_set(_real_name, _value);
                    }
                    return "OK:Set " + _var_name;
                }
                return "ERROR:Only global variables supported";
            }
            return "ERROR:Missing variable name or value";
            
        case "spawn":
            if (array_length(_parts) > 3) {
                var _obj = asset_get_index(_parts[1]);
                var _x = real(_parts[2]);
                var _y = real(_parts[3]);
                if (_obj >= 0 && object_exists(_obj)) {
                    var _inst = instance_create_depth(_x, _y, 0, _obj);
                    return "OK:Created " + _parts[1] + " at " + string(_x) + "," + string(_y);
                }
                return "ERROR:Object not found: " + _parts[1];
            }
            return "ERROR:Usage: spawn <object> <x> <y>";
            
        case "room_info":
            return "OK:" + room_get_name(room) + " (" + string(room_width) + "x" + string(room_height) + ")";
            
        case "instance_count":
            if (array_length(_parts) > 1) {
                var _obj = asset_get_index(_parts[1]);
                if (_obj >= 0) {
                    return "OK:" + string(instance_number(_obj));
                }
                return "ERROR:Object not found";
            }
            return "OK:" + string(instance_count);
            
        default:
            return "ERROR:Unknown command: " + _action;
    }
}
'''
        
        # Destroy Event
        events["Destroy_0.gml"] = '''/// @description Clean up MCP bridge connection
if (global.__mcp_socket >= 0) {
    network_destroy(global.__mcp_socket);
    global.__mcp_socket = -1;
}
global.__mcp_enabled = false;
'''
        
        return object_yy_path, object_data, events
    
    def install(self, port: int = 6502) -> Dict[str, Any]:
        """
        Install the MCP bridge into the project.
        
        Uses a transactional approach:
        1. Backup .yyp
        2. Create all files
        3. Verify files
        4. Update .yyp
        5. Verify .yyp
        
        On failure, rolls back all changes.
        
        Args:
            port: Port number for bridge server
            
        Returns:
            Dict with installation result
        """
        if self.is_installed():
            return {
                "ok": True,
                "message": "Bridge already installed",
                "already_installed": True,
            }
        
        created_paths: List[Path] = []
        
        try:
            # Step 1: Backup .yyp
            print("[BRIDGE] Backing up .yyp...")
            self._backup_yyp()
            
            # Step 2: Create folder asset
            print("[BRIDGE] Creating folder asset...")
            folder_yy_path, folder_data = self._create_folder_asset()
            folder_yy_path.parent.mkdir(parents=True, exist_ok=True)
            save_json(folder_data, folder_yy_path)
            created_paths.append(folder_yy_path)
            
            # Step 3: Create script asset
            print("[BRIDGE] Creating script asset...")
            script_yy_path, script_data, script_gml = self._create_script_asset()
            script_yy_path.parent.mkdir(parents=True, exist_ok=True)
            save_json(script_data, script_yy_path)
            created_paths.append(script_yy_path)
            
            script_gml_path = script_yy_path.parent / f"{BRIDGE_SCRIPT_NAME}.gml"
            script_gml_path.write_text(script_gml, encoding='utf-8')
            created_paths.append(script_gml_path)
            
            # Step 4: Create object asset
            print("[BRIDGE] Creating object asset...")
            object_yy_path, object_data, events = self._create_object_asset(port)
            object_yy_path.parent.mkdir(parents=True, exist_ok=True)
            save_json(object_data, object_yy_path)
            created_paths.append(object_yy_path)
            
            for event_name, event_code in events.items():
                event_path = object_yy_path.parent / event_name
                event_path.write_text(event_code, encoding='utf-8')
                created_paths.append(event_path)
            
            # Step 5: Verify all files exist
            print("[BRIDGE] Verifying files...")
            for path in created_paths:
                if not path.exists():
                    raise BridgeInstallError(f"Failed to create: {path}")
            
            # Step 6: Update .yyp
            print("[BRIDGE] Updating .yyp...")
            yyp_data = load_json(self.yyp_path)
            
            # Add folder - match format of existing folders in .yyp
            existing_folders = yyp_data.get("Folders", [])
            folder_format = ""
            if existing_folders:
                folder_format = existing_folders[0].get("$GMFolder", "")
            
            yyp_data.setdefault("Folders", []).append({
                "$GMFolder": folder_format,
                "%Name": BRIDGE_FOLDER_NAME,
                "folderPath": f"folders/{BRIDGE_FOLDER_NAME}.yy",
                "name": BRIDGE_FOLDER_NAME,
                "resourceType": "GMFolder",
                "resourceVersion": "2.0",
            })
            
            # Add resources
            resources = yyp_data.setdefault("resources", [])
            
            # Add folder resource
            resources.append({
                "id": {
                    "name": BRIDGE_FOLDER_NAME,
                    "path": f"folders/{BRIDGE_FOLDER_NAME}.yy",
                },
            })
            
            # Add script resource
            resources.append({
                "id": {
                    "name": BRIDGE_SCRIPT_NAME,
                    "path": f"scripts/{BRIDGE_SCRIPT_NAME}/{BRIDGE_SCRIPT_NAME}.yy",
                },
            })
            
            # Add object resource
            resources.append({
                "id": {
                    "name": BRIDGE_OBJECT_NAME,
                    "path": f"objects/{BRIDGE_OBJECT_NAME}/{BRIDGE_OBJECT_NAME}.yy",
                },
            })
            
            save_json(yyp_data, self.yyp_path)
            
            # Step 7: Verify .yyp is valid
            print("[BRIDGE] Verifying .yyp...")
            verify_data = load_json(self.yyp_path)
            if not verify_data:
                raise BridgeInstallError("Failed to verify .yyp after modification")
            
            # Success - clean up backup
            self._cleanup_backup()
            
            print("[BRIDGE] Installation complete!")
            return {
                "ok": True,
                "message": "Bridge installed successfully",
                "port": port,
                "files_created": len(created_paths),
            }
            
        except Exception as e:
            print(f"[BRIDGE] Installation failed: {e}")
            print("[BRIDGE] Rolling back...")
            
            # Rollback: restore .yyp
            self._restore_yyp()
            
            # Rollback: delete created files
            for path in reversed(created_paths):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
            
            # Clean up empty directories
            for asset_type in [ASSET_TYPE_OBJECT, ASSET_TYPE_SCRIPT]:
                asset_dir = self.project_root / asset_type / BRIDGE_OBJECT_NAME
                if asset_dir.exists() and not any(asset_dir.iterdir()):
                    try:
                        asset_dir.rmdir()
                    except Exception:
                        pass
            
            return {
                "ok": False,
                "error": str(e),
                "message": f"Installation failed: {e}",
            }
    
    def uninstall(self) -> Dict[str, Any]:
        """
        Remove the MCP bridge from the project.
        
        Returns:
            Dict with uninstallation result
        """
        if not self.is_installed():
            return {
                "ok": True,
                "message": "Bridge not installed",
                "already_uninstalled": True,
            }
        
        try:
            # Step 1: Backup .yyp
            print("[BRIDGE] Backing up .yyp...")
            self._backup_yyp()
            
            # Step 2: Load .yyp and clean room instances before deleting assets
            print("[BRIDGE] Updating .yyp...")
            yyp_data = load_json(self.yyp_path)

            room_cleanup = self._cleanup_bridge_room_instances(yyp_data)
            
            # Remove from Folders
            if "Folders" in yyp_data:
                yyp_data["Folders"] = [
                    f for f in yyp_data["Folders"]
                    if BRIDGE_FOLDER_NAME not in f.get("folderPath", "")
                ]
            
            # Remove from resources
            if "resources" in yyp_data:
                yyp_data["resources"] = [
                    r for r in yyp_data["resources"]
                    if "__mcp" not in r.get("id", {}).get("path", "")
                ]
            
            save_json(yyp_data, self.yyp_path)
            
            # Step 3: Delete files
            print("[BRIDGE] Removing files...")
            deleted_count = 0
            
            # Delete object directory
            object_dir = self.project_root / ASSET_TYPE_OBJECT / BRIDGE_OBJECT_NAME
            if object_dir.exists():
                shutil.rmtree(object_dir)
                deleted_count += 1
            
            # Delete script directory
            script_dir = self.project_root / ASSET_TYPE_SCRIPT / BRIDGE_SCRIPT_NAME
            if script_dir.exists():
                shutil.rmtree(script_dir)
                deleted_count += 1
            
            # Delete folder .yy
            folder_yy = self.project_root / ASSET_TYPE_FOLDER / f"{BRIDGE_FOLDER_NAME}.yy"
            if folder_yy.exists():
                folder_yy.unlink()
                deleted_count += 1
            
            # Success - clean up backup
            self._cleanup_backup()
            
            print("[BRIDGE] Uninstallation complete!")
            warnings = room_cleanup.get("warnings", [])
            return {
                "ok": True,
                "message": "Bridge removed successfully",
                "items_deleted": deleted_count,
                "rooms_cleaned": len(room_cleanup.get("rooms_modified", [])),
                "instances_removed": room_cleanup.get("instances_removed", 0),
                "creation_code_removed": room_cleanup.get("creation_code_deleted", 0),
                "warnings": warnings,
            }
            
        except Exception as e:
            print(f"[BRIDGE] Uninstallation failed: {e}")
            print("[BRIDGE] Rolling back...")
            
            # Rollback: restore .yyp
            self._restore_yyp()
            
            return {
                "ok": False,
                "error": str(e),
                "message": f"Uninstallation failed: {e}",
            }


def install_bridge(project_root: str, port: int = 6502) -> Dict[str, Any]:
    """
    Install bridge into a project.
    
    Args:
        project_root: Path to project root
        port: Bridge server port
        
    Returns:
        Installation result dict
    """
    try:
        installer = BridgeInstaller(Path(project_root))
        return installer.install(port)
    except Exception as e:
        return {"ok": False, "error": str(e), "message": f"Installation failed: {e}"}


def uninstall_bridge(project_root: str) -> Dict[str, Any]:
    """
    Remove bridge from a project.
    
    Args:
        project_root: Path to project root
        
    Returns:
        Uninstallation result dict
    """
    try:
        installer = BridgeInstaller(Path(project_root))
        return installer.uninstall()
    except Exception as e:
        return {"ok": False, "error": str(e), "message": f"Uninstallation failed: {e}"}


def is_bridge_installed(project_root: str) -> bool:
    """Check if bridge is installed in a project."""
    try:
        installer = BridgeInstaller(Path(project_root))
        return installer.is_installed()
    except Exception:
        return False


def get_bridge_status(project_root: str) -> Dict[str, Any]:
    """Get detailed bridge installation status."""
    try:
        installer = BridgeInstaller(Path(project_root))
        return installer.get_status()
    except Exception as e:
        return {"ok": False, "error": str(e), "installed": False}
