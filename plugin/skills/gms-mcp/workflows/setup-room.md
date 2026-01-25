---
name: setup-room
description: Create and populate rooms with layers and instances
---

## When to use

- Setting up level layouts
- Placing UI elements in rooms
- Creating procedural room configurations
- Batch placement of objects

## Workflow

### Basic Instance Placement

1. **Ensure the room and layer exist**:
   ```bash
   gms room layer list r_level_01
   ```

2. **Add instances**:
   ```bash
   gms room instance add r_level_01 o_wall 64 64 --layer Instances
   gms room instance add r_level_01 o_player 128 128 --layer Instances
   ```

3. **List instances to verify**:
   ```bash
   gms room instance list r_level_01
   ```

### Grid-Based Placement

For tile-aligned placement, calculate positions based on grid size:

```bash
# 32x32 grid, place walls around perimeter
# Top row (y=0)
gms room instance add r_level o_wall 0 0 --layer Instances
gms room instance add r_level o_wall 32 0 --layer Instances
gms room instance add r_level o_wall 64 0 --layer Instances
# ... continue pattern
```

### Layer Management

1. **Create necessary layers**:
   ```bash
   gms room layer add r_level instance Instances --depth 0
   gms room layer add r_level background Background --depth 1000
   ```

2. **Set layer depths** appropriately:
   - Lower depth = drawn on top
   - Background: 1000+
   - Instances: 0
   - UI: -1000 or lower

### Room Duplication for Variants

```bash
# Create base room, then duplicate for variations
gms asset create room r_level_template --width 1024 --height 768
# Set up the template...

gms room ops duplicate r_level_template r_level_01
gms room ops duplicate r_level_template r_level_02
```

## Example: Simple Level Setup

```bash
# Create room
gms asset create room r_test_level --width 640 --height 480

# Add layers
gms room layer add r_test_level instance Instances --depth 0
gms room layer add r_test_level background Background --depth 100

# Place player spawn
gms room instance add r_test_level o_player 64 64 --layer Instances

# Place some enemies
gms room instance add r_test_level o_enemy 256 128 --layer Instances
gms room instance add r_test_level o_enemy 384 256 --layer Instances

# Place collectibles
gms room instance add r_test_level o_coin 128 192 --layer Instances
gms room instance add r_test_level o_coin 320 320 --layer Instances

# Verify
gms room instance list r_test_level
```

## Tips

- Use room duplication for level variants
- Create a "template" room with common layers
- Keep instance counts reasonable for editor performance
- Use creation code for dynamic variations (via IDE, not CLI)
