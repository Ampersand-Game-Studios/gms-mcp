---
name: room-commands
description: Complete room, layer, and instance command reference
---

# Room Commands Reference

## Room Operations

### List Rooms
```bash
gms room ops list [--verbose]
```

### Duplicate Room
```bash
gms room ops duplicate <source_room> <new_name>
```

### Rename Room
```bash
gms room ops rename <room_name> <new_name>
```

### Delete Room
```bash
gms room ops delete <room_name> [--dry-run]
```

## Layer Management

### Layer Types
| Type | Description |
|------|-------------|
| `background` | Background layer |
| `instance` / `instances` | Instance layer (for objects) |
| `asset` | Asset layer |
| `tile` | Tile layer |
| `path` | Path layer |
| `effect` | Effect layer |

### Add Layer
```bash
gms room layer add <room_name> <layer_type> <layer_name> [--depth INT]
```
- `--depth` - Layer depth (default: 0). Lower = drawn on top.

**Depth conventions:**
- Background: 1000+
- Instances: 0
- UI/Foreground: -1000 or lower

### Remove Layer
```bash
gms room layer remove <room_name> <layer_name>
```

### List Layers
```bash
gms room layer list <room_name>
```

### Examples
```bash
# Add instance layer
gms room layer add r_level instance Instances --depth 0

# Add background layer
gms room layer add r_level background Background --depth 1000

# Add UI layer (drawn on top)
gms room layer add r_level instance UI --depth -100

# List all layers
gms room layer list r_level
```

## Instance Management

### Add Instance
```bash
gms room instance add <room_name> <object_name> <x> <y> [--layer NAME]
```
- `--layer` - Layer to place instance on

### Remove Instance
```bash
gms room instance remove <room_name> <instance_id>
```

### List Instances
```bash
gms room instance list <room_name>
```

### Examples
```bash
# Add player at position
gms room instance add r_level o_player 64 64 --layer Instances

# Add multiple enemies
gms room instance add r_level o_enemy 256 128 --layer Instances
gms room instance add r_level o_enemy 384 256 --layer Instances

# List all instances
gms room instance list r_level
```

## Room Creation

```bash
gms asset create room <name> [--width INT] [--height INT] [--parent-path PATH]
```
- `--width` - Room width (default: 1024)
- `--height` - Room height (default: 768)

## Common Workflows

### Set Up New Level
```bash
# Create room
gms asset create room r_level_01 --width 1920 --height 1080 --parent-path "folders/Rooms.yy"

# Add layers
gms room layer add r_level_01 background Background --depth 1000
gms room layer add r_level_01 instance Instances --depth 0
gms room layer add r_level_01 instance UI --depth -100

# Add objects
gms room instance add r_level_01 o_player 64 64 --layer Instances
gms room instance add r_level_01 o_enemy 256 128 --layer Instances
```

### Create Level Variant
```bash
# Duplicate existing room
gms room ops duplicate r_level_01 r_level_02

# Modify as needed
gms room instance add r_level_02 o_enemy 512 256 --layer Instances
```

### Grid-Based Placement
Calculate positions based on grid size:
```bash
# 32x32 grid
gms room instance add r_level o_wall 0 0 --layer Instances
gms room instance add r_level o_wall 32 0 --layer Instances
gms room instance add r_level o_wall 64 0 --layer Instances
```
