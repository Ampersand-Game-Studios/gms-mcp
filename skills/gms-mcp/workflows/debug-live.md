---
name: debug-live
description: Debug a running game with the MCP bridge's supported commands and buffered logs
---

## When to use

- Querying a running game's room or instance state
- Changing rooms or test globals without restarting
- Spawning test instances
- Reading logs emitted through `__mcp_log(...)`

## Bridge contract

The bridge exposes a fixed command protocol through MCP. It does not evaluate arbitrary GML. Supported commands are `ping`, `goto_room`, `get_var`, `set_var`, `spawn`, `room_info`, and `instance_count`.

`gm_run_logs` returns buffered `__mcp_log(...)` entries. It is a snapshot call; there is no follow/stream option, and ordinary `show_debug_message(...)` output is not automatically included.

## Setup

Install the bridge and place its controller in the startup room in one transaction. Omit `room_name` only when the `.yyp` has a valid first `RoomOrderNodes` entry.

```mcp
gm_bridge_enable_one_shot {"project_root":".","room_name":"r_start","layer":"Instances"}
gm_bridge_status {"project_root":"."}
```

Start the game in the background so the MCP server remains available for bridge calls.

```mcp
gm_run {"project_root":".","background":true,"enable_bridge":true}
gm_run_status {"project_root":"."}
gm_bridge_status {"project_root":"."}
```

Do not send commands until `gm_bridge_status` reports both `server_running: true` and `game_connected: true`.

## Supported command examples

```mcp
gm_run_command {"project_root":".","command":"ping"}
gm_run_command {"project_root":".","command":"room_info"}
gm_run_command {"project_root":".","command":"instance_count o_enemy"}
gm_run_command {"project_root":".","command":"get_var global.score"}
gm_run_command {"project_root":".","command":"set_var global.debug_mode 1"}
gm_run_command {"project_root":".","command":"spawn o_enemy 100 100"}
gm_run_command {"project_root":".","command":"goto_room r_boss_fight"}
```

Names passed to `goto_room`, `spawn`, and `instance_count` must be registered GameMaker assets. `get_var` and `set_var` only support global variables.

## Reading logs

Game code must call `__mcp_log(message)` for an entry to appear here.

```mcp
gm_run_logs {"project_root":".","lines":50}
```

Call `gm_run_logs` again for a later snapshot. The bridge keeps a bounded in-memory buffer; this workflow does not provide continuous streaming.

## Stop and remove

```mcp
gm_run_stop {"project_root":"."}
gm_bridge_uninstall {"project_root":"."}
```

Uninstall the bridge before a release build. Verify removal and the stopped session explicitly:

```mcp
gm_bridge_status {"project_root":"."}
gm_run_status {"project_root":"."}
```

## Failure checks

- Not installed: run `gm_bridge_enable_one_shot` and verify its returned room and instance ID.
- Server not running: start with `gm_run` using `background: true` and `enable_bridge: true`.
- Game not connected: verify the bridge instance is in the startup room's instance layer and creation order.
- Unknown command: use only the fixed protocol listed above or deliberately extend `__mcp_execute_command` in the installed bridge.
- Missing logs: confirm game code uses `__mcp_log(...)`, then request another snapshot.
