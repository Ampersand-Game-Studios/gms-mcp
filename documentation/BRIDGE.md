## TCP Bridge (MCP Bridge) - Live Game Logging and Commands

## QUICK REFERENCE CHECKLIST FOR AGENTS

Before running a game with the bridge, verify ALL of the following:

- [ ] **Correct project_root**: Run `gm_project_info()` first to confirm the `.yyp` location
- [ ] **Bridge installed**: Run `gm_bridge_install()` if not already installed
- [ ] **Bridge instance in room**: Use `gm_room_instance_add()` to add `__mcp_bridge` to your startup room
- [ ] **instanceCreationOrder populated**: The room's `.yy` file MUST have the instance in `instanceCreationOrder[]` (not just in `layers[].instances[]`)
- [ ] **Startup room is correct**: Check `RoomOrderNodes` in the `.yyp` - the first room listed is the startup room
- [ ] **Use `__mcp_log()` not `show_debug_message()`**: Only `__mcp_log()` sends messages to the bridge
- [ ] **Sandbox disabled** (Windows): Set `option_windows_disable_sandbox: true` in options_windows.yy for networking

**Typical workflow**:
```
1. gm_project_info(project_root="gamemaker")           # Verify project
2. gm_bridge_install(project_root="gamemaker")         # Install bridge (once)
3. gm_room_instance_add(..., "__mcp_bridge", ...)      # Add to startup room (once)
4. [Verify instanceCreationOrder in room .yy file]     # CRITICAL - see troubleshooting
5. gm_run(background=true, enable_bridge=true)         # Run game
6. [Wait 3-5 seconds for connection]
7. gm_bridge_status() -> game_connected: true          # Verify connection
8. gm_run_command("ping") -> "pong"                    # Test commands
9. gm_run_command("spawn MyObject 100 100")            # Spawn objects
10. gm_run_logs(lines=50)                              # Read logs
11. gm_run_stop()                                      # Stop game
```

---

This document is the source of truth for the optional TCP bridge used by `gms-mcp`.
It enables bidirectional communication between:

- The MCP server (Python) running in your editor (Cursor or another MCP client)
- A running GameMaker game (GML client code inside the project)

The bridge is designed to be:

- Opt-in: the game runs normally when the bridge is not installed or not running.
- Local-only: the server listens on `127.0.0.1` and the game connects out to it.
- Low footprint: assets are prefixed with `__mcp_` for easy identification/removal.
- Safe-by-default: bridge install/uninstall use backup/rollback for `.yyp` edits.

## Key concepts (read this first)

### 1) `project_root` must point at the folder containing the `.yyp`

All bridge tools accept `project_root`.
It must be the directory that contains the `.yyp` file (not necessarily your repo root).

In this repo's sample project, the `.yyp` is `gamemaker/BLANK GAME.yyp`, so the correct `project_root` is `gamemaker`.

If you pass the wrong `project_root`, you will see:

- `No .yyp file found ...` during install/status, or
- A running game that you cannot query logs from (because you started the bridge server for a different root).

Recommendation:

- Always run `gm_project_info(project_root=...)` first, then reuse that same `project_root` consistently for:
  - `gm_bridge_install`, `gm_bridge_status`, `gm_run`, `gm_run_command`, `gm_run_logs`, `gm_run_stop`

### 2) Installing the bridge does NOT automatically connect it

`gm_bridge_install` installs assets and registers them in the `.yyp`, but it does not place an instance into any room.

To actually connect, an instance of `__mcp_bridge` must be created at runtime (typically by placing it into your startup room).

### 3) `gm_run_logs` only shows logs sent via `__mcp_log(...)`

The bridge does not "scrape" GameMaker's debug console.
Only messages sent over TCP are visible to the MCP server, and the official way to send a log is:

- `__mcp_log("your message")`

If your game code only calls `show_debug_message(...)`, you will see the message in the IDE, but not in `gm_run_logs`.

### 4) Restart rules

- If you change Python bridge code (`src/gms_helpers/bridge_server.py`, etc): restart MCP (Cursor "Reload Window" or restart the MCP server).
- If you change GML (`.gml`) assets: restart the game (re-run via `gm_run`).

## What the bridge installs (project footprint)

Bridge installation adds:

- Folder asset: `folders/__mcp.yy`
- Script asset: `scripts/__mcp_log/__mcp_log.yy` and `scripts/__mcp_log/__mcp_log.gml`
- Object asset: `objects/__mcp_bridge/__mcp_bridge.yy` and event code:
  - `objects/__mcp_bridge/Create_0.gml`
  - `objects/__mcp_bridge/Step_0.gml`
  - `objects/__mcp_bridge/Other_68.gml` (Async Networking)
  - `objects/__mcp_bridge/Destroy_0.gml`

Bridge installation also updates the project `.yyp`:

- Adds an entry to `Folders`
- Adds resource entries for the folder, script, and object

It does NOT add room instances automatically.

## End-to-end workflow (agent runbook)

This is the recommended, repeatable sequence for running a game and interacting with it.

### Step 0: Resolve the correct project root

Run:

- `gm_project_info(project_root=...)`

Use the returned `.yyp` directory as `project_root` for everything below.

### Step 1: Install the bridge (one-time per project)

- `gm_bridge_install(project_root=..., port=6502)`
- `gm_bridge_status(project_root=...)` should report `installed: true`

If you see `[ERROR] No .yyp file found ...`, your `project_root` is wrong.

### Step 2: Ensure `__mcp_bridge` is instantiated (required for connection)

Option A (recommended): Place an instance into your startup room.

- Find a room and instance layer:
  - `gm_room_ops_list(project_root=...)`
  - `gm_room_layer_list(room_name="<room>", project_root=...)`
- Add an instance (any position is fine; the object is `visible=false` by default):
  - `gm_room_instance_add(room_name="<room>", object_name="__mcp_bridge", x=0, y=0, layer="<instance_layer>", project_root=...)`

Option B: Spawn it from your own bootstrap/controller object in GML.

### Step 3: Run the game with bridge enabled

- `gm_run(project_root=..., background=true, enable_bridge=true)`
- `gm_bridge_status(project_root=...)` should report:
  - `server_running: true`
  - `game_connected: true`

If `game_connected` is false, the bridge object likely is not instantiated.

### Step 4: Verify command path

- `gm_run_command("ping", project_root=...)` -> `pong`
- `gm_run_command("room_info", project_root=...)` -> `OK:<room> (<w>x<h>)`

### Step 5: Spawn an object and read its logs

1) Compute the room center:

- \(x = room_width / 2\)
- \(y = room_height / 2\)

2) Spawn:

- `gm_run_command("spawn o_test_spawn <x> <y>", project_root=...)`

3) Read logs:

- `gm_run_logs(lines=50, project_root=...)`

If the spawned object does not appear in logs, confirm its Create event calls `__mcp_log(...)`.

### Step 6: Stop the game

- `gm_run_stop(project_root=...)`

## Logging guidance (how to make logs visible to the bridge)

### Recommended pattern

Use `__mcp_log(...)` for any message you want visible to the MCP server:

```gml
// Example
__mcp_log("Hello from Create event");
```

### Common mistake

This only logs locally (IDE), not to the bridge:

```gml
show_debug_message("This will not appear in gm_run_logs");
```

If you want it in both places, call `__mcp_log(...)` (it also calls `show_debug_message` internally).

## Protocol (how the Python server and the game talk)

This is a simple newline-delimited, UTF-8 text protocol over TCP.
Messages are one-per-line, terminated by `\n`.

- Game -> Server:
  - `LOG:<timestamp>|<message>\n`
  - `RSP:<cmd_id>|<result>\n`
- Server -> Game:
  - `CMD:<cmd_id>|<command>\n`

Notes:

- GameMaker `buffer_write(..., buffer_string, ...)` writes a NUL terminator (`\x00`).
  The server strips NUL bytes during receive so that parsing is stable across packets.
- The bridge supports one game connection at a time.

## Uninstalling safely (avoid breaking the project)

Important: `gm_bridge_uninstall` removes the `__mcp_` assets and `.yyp` entries, but it does not remove room instances you may have placed.

If a room still contains an instance referencing `__mcp_bridge` after uninstall, the IDE may fail to load the project due to missing resource references.

Recommended uninstall flow:

1) Stop the game:
   - `gm_run_stop(project_root=...)`
2) Remove room instances of `__mcp_bridge`:
   - For each room:
     - `gm_room_instance_list(room_name="<room>", project_root=...)`
     - Find the instance whose `object_name` is `__mcp_bridge`
     - `gm_room_instance_remove(room_name="<room>", instance_id="<id>", project_root=...)`
3) Uninstall:
   - `gm_bridge_uninstall(project_root=...)`
4) Confirm:
   - `gm_bridge_status(project_root=...)` -> `installed: false`

## Troubleshooting

### [ERROR] "No .yyp file found ..."

Cause: `project_root` is not the directory containing the `.yyp`.

Fix:

- Run `gm_project_info(project_root=...)` and use its reported project directory as `project_root`.

### `server_running: false`

Cause: The bridge server has not been started.

Fix:

- Run `gm_run(project_root=..., background=true, enable_bridge=true)`

### `server_running: true` but `game_connected: false`

Most common causes:

1. **`__mcp_bridge` is not instantiated in the running game** (not placed in a room).
2. **The `instanceCreationOrder` array is empty** in the room's `.yy` file (see CRITICAL section below).
3. The game is running from a different build/project than the one you think.
4. Windows Firewall is blocking the connection (unlikely for localhost).

Fix:

- Place an instance of `__mcp_bridge` in your startup room (see workflow Step 2), then restart via `gm_run`.
- **CRITICAL**: Verify the room's `instanceCreationOrder` includes the bridge instance (see below).

### CRITICAL: `instanceCreationOrder` must include the instance

**This is the most common cause of "game_connected: false" when the instance appears to be in the room.**

When you add an instance to a room (either via `gm_room_instance_add` or manually), the room's `.yy` file has TWO places that matter:

1. `layers[].instances[]` - The instance definition (position, object, etc.)
2. `instanceCreationOrder[]` - The order in which instances are created at runtime

**If `instanceCreationOrder` is empty or doesn't include your instance, the instance will NOT be created at runtime**, even though it appears in the room file.

Example of a BROKEN room file (instance exists but won't be created):
```json
{
  "instanceCreationOrder": [],  // EMPTY - instances won't be created!
  "layers": [
    {
      "instances": [
        {
          "name": "inst_abc123",
          "objectId": { "name": "__mcp_bridge", ... }
        }
      ]
    }
  ]
}
```

Example of a WORKING room file:
```json
{
  "instanceCreationOrder": [
    {
      "name": "inst_abc123",
      "path": "rooms/Room1/Room1.yy"
    }
  ],
  "layers": [
    {
      "instances": [
        {
          "name": "inst_abc123",
          "objectId": { "name": "__mcp_bridge", ... }
        }
      ]
    }
  ]
}
```

**How to fix**: Read the room's `.yy` file and ensure `instanceCreationOrder` contains an entry for each instance in `layers[].instances[]`. The entry format is:
```json
{
  "name": "<instance_name>",
  "path": "rooms/<RoomName>/<RoomName>.yy"
}
```

### Commands work but logs are missing

Most common cause:

- Your game code is using `show_debug_message` instead of `__mcp_log`.

Fix:

- Replace or supplement debug output with `__mcp_log(...)`, then restart the game.

### Logs/commands suddenly stop after changing code

Fix:

- If you changed Python: restart MCP.
- If you changed GML: restart the game via `gm_run`.

