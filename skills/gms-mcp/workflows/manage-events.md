---
name: manage-events
description: Add, remove, and manage object events
---

## When to use

When working with object events: adding new events, removing old ones, duplicating events, or fixing event/file mismatches.

## Event Specification Syntax

Events are specified as `event_type` or `event_type:subtype_number`.

| Event Type | Subtypes | Examples |
|------------|----------|----------|
| `create` | None | `create` |
| `destroy` | None | `destroy` |
| `cleanup` | None | `cleanup` |
| `step` | 0=Step, 1=Begin, 2=End | `step`, `step:1`, `step:2` |
| `alarm` | 0-11 | `alarm:0`, `alarm:5` |
| `draw` | 0=Draw, 64=GUI, 65=Resize, 72=Pre, 73=Post, 74=Begin GUI, 75=End GUI | `draw`, `draw:64` |
| `mouse` | Various | `mouse:0` (left button) |
| `keyboard` | Key codes | `keyboard:32` (space) |
| `keypress` | Key codes | `keypress:13` (enter) |
| `keyrelease` | Key codes | `keyrelease:32` |
| `collision` | Object name | `collision:o_wall` |
| `other` | Various | `other:10` (room start) |
| `async` | Various | `async:75` (HTTP) |

## Workflow

### Adding an event
```bash
gms event add o_player create
gms event add o_player step:0        # Normal step
gms event add o_player draw:64       # Draw GUI
gms event add o_player alarm:0
gms event add o_player collision:o_wall
```

### Adding with a template
```bash
gms event add o_player create --template templates/player_init.gml
```

### Listing object events
```bash
gms event list o_player
```

### Removing an event
```bash
gms event remove o_player alarm:5
gms event remove o_player alarm:5 --keep-file  # Keep .gml file
```

### Duplicating an event
```bash
# Copy step:0 to step:1 (begin step)
gms event duplicate o_player step:0 1
```

### Validating events
```bash
# Check for mismatches between .yy and .gml files
gms event validate o_player
```

### Fixing event issues
```bash
# Safe mode: only removes orphan .gml files
gms event fix o_player

# Unsafe mode: also adds orphan events to .yy
gms event fix o_player --no-safe-mode
```

## Common Patterns

### Setting up a standard object
```bash
gms asset create object o_enemy --parent-path "folders/Objects.yy"
gms event add o_enemy create
gms event add o_enemy step
gms event add o_enemy draw
gms event add o_enemy destroy
```

### Adding collision detection
```bash
gms event add o_player collision:o_enemy
gms event add o_player collision:o_wall
gms event add o_player collision:o_pickup
```

### Setting up alarms
```bash
gms event add o_enemy alarm:0   # Attack timer
gms event add o_enemy alarm:1   # Patrol timer
gms event add o_enemy alarm:2   # Spawn timer
```

### Setting up input handling
```bash
gms event add o_player keyboard:37    # Left arrow
gms event add o_player keyboard:38    # Up arrow
gms event add o_player keyboard:39    # Right arrow
gms event add o_player keyboard:40    # Down arrow
gms event add o_player keypress:32    # Space pressed
```

## Tips

- Use `event list` to see what events already exist before adding
- Use `event validate` to catch mismatches before they cause issues
- Use `--keep-file` when removing events if you want to preserve the code
- Collision events use the object name, not `collision:0`
- Step event without subtype defaults to `step:0` (normal step)

## Never Do

- Add duplicate events (will fail)
- Remove events without checking if code should be preserved
- Use `--no-safe-mode` fix without understanding what it will add
- Forget to run validation after manual .gml file changes
