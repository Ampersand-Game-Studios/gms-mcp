---
name: debug-live
description: Debug running games with bridge commands and logs
---

## When to use

- Sending commands to a running game
- Reading real-time game logs
- Live debugging without restarting
- Inspecting game state during runtime

## What is the Bridge?

The bridge is a GameMaker extension that enables two-way communication between gms-mcp and a running game. It allows:
- Sending GML commands to execute in the game
- Receiving debug output and logs
- Inspecting variables and game state

## Setup

### Installing the Bridge Extension

```bash
# Install bridge extension to your project
gms bridge install

# Check installation status
gms bridge status

# Remove bridge extension
gms bridge uninstall
```

**Note:** The bridge extension must be installed in your project before it can be used.

### Verifying Installation

```bash
gms bridge status
```

Output shows:
- Whether bridge extension is installed
- Whether bridge is currently connected
- Connection details

## Running with Bridge

```bash
# Start game (bridge connects automatically if installed)
gms run start

# Check status
gms run status
gms bridge status
```

## Sending Commands

Execute GML code in the running game:

```bash
# Simple command
gms run command "show_debug_message('Hello from MCP!')"

# Change a variable
gms run command "global.debug_mode = true"

# Call a function
gms run command "player_heal(50)"

# Spawn an instance
gms run command "instance_create_layer(100, 100, 'Instances', o_enemy)"
```

## Reading Logs

View debug output from the running game:

```bash
# Get recent logs
gms run logs

# Follow logs (continuous output)
gms run logs --follow
```

**Logs include:**
- `show_debug_message()` output
- Runtime errors
- Bridge communication messages

## Workflow: Live Debugging

1. **Install bridge** (one-time)
   ```bash
   gms bridge install
   ```

2. **Start the game**
   ```bash
   gms run start
   ```

3. **Watch logs in another terminal**
   ```bash
   gms run logs --follow
   ```

4. **Send debug commands**
   ```bash
   gms run command "show_debug_message(string(player.hp))"
   gms run command "global.invincible = true"
   ```

5. **Stop when done**
   ```bash
   gms run stop
   ```

## Workflow: Testing Specific Scenarios

```bash
# Start game
gms run start

# Teleport player to test area
gms run command "player.x = 500; player.y = 300"

# Give player items for testing
gms run command "inventory_add(ITEM.SWORD, 1)"
gms run command "player.gold = 9999"

# Trigger specific state
gms run command "room_goto(r_boss_fight)"
```

## Workflow: Inspecting State

```bash
# Check player state
gms run command "show_debug_message('HP: ' + string(player.hp))"
gms run command "show_debug_message('Position: ' + string(player.x) + ',' + string(player.y))"

# Check global state
gms run command "show_debug_message('Score: ' + string(global.score))"

# Count instances
gms run command "show_debug_message('Enemies: ' + string(instance_number(o_enemy)))"
```

## Tips

- Bridge adds minimal overhead - safe for development builds
- Commands execute in the game's context (access to all variables/functions)
- Use `show_debug_message()` in commands to see results in logs
- Bridge auto-reconnects if game restarts
- Remove bridge from release builds (`gms bridge uninstall`)

## Common Issues

### "Bridge not connected"
```bash
# Check if game is running
gms run status

# Check bridge status
gms bridge status

# Restart game
gms run stop
gms run start
```

### "Command failed"
- Check GML syntax in your command
- Ensure referenced objects/variables exist
- Check logs for error details

### "Bridge not found"
```bash
# Install the bridge extension
gms bridge install

# Verify
gms bridge status
```

## Never Do

- Ship release builds with bridge installed
- Send commands that crash the game (test in safe ways)
- Assume bridge commands are instant (there's slight latency)
- Forget to uninstall bridge before distribution
