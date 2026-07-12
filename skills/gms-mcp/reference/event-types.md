---
name: event-types
description: Complete event type and specification reference
---

# Event Types Reference

## Event Specification Syntax

Events are specified as `event_type` or `event_type:subtype`.

```bash
gms event add o_player collision:o_wall
gms event remove o_player alarm:0
```

## Event Types

### Lifecycle Events
| Event | Subtypes | Examples |
|-------|----------|----------|
| `create` | None | `create` |
| `destroy` | None | `destroy` |
| `cleanup` | None | `cleanup` |

### Step Events
| Event | Subtypes | Examples |
|-------|----------|----------|
| `step` | 0=Normal, 1=Begin, 2=End | `step`, `step:1`, `step:2` |

### Alarm Events
| Event | Subtypes | Examples |
|-------|----------|----------|
| `alarm` | 0-11 | `alarm:0`, `alarm:5`, `alarm:11` |

### Draw Events
| Event | Subtypes | Examples |
|-------|----------|----------|
| `draw` | 0=Draw | `draw` |
| `draw` | 64=Draw GUI | `draw:64` |
| `draw` | 65=Resize | `draw:65` |
| `draw` | 72=Draw Begin | `draw:72` |
| `draw` | 73=Draw End | `draw:73` |
| `draw` | 74=Draw GUI Begin | `draw:74` |
| `draw` | 75=Draw GUI End | `draw:75` |

### Input Events
| Event | Subtypes | Examples |
|-------|----------|----------|
| `keyboard` | Key code | `keyboard:32` (space) |
| `keypress` | Key code | `keypress:13` (enter) |
| `keyrelease` | Key code | `keyrelease:32` |
| `mouse` | Button code | `mouse:0` (left click) |

### Collision Events
| Event | Subtypes | Examples |
|-------|----------|----------|
| `collision` | Object name | `collision:o_wall`, `collision:o_enemy` |

### Other Events
| Event | Subtypes | Examples |
|-------|----------|----------|
| `other` | 10=Room Start | `other:10` |
| `other` | 11=Room End | `other:11` |
| `other` | 30=Animation End | `other:30` |
| `other` | 70=User Event 0 | `other:70` |

## Common Key Codes

| Key | Code | Key | Code |
|-----|------|-----|------|
| Space | 32 | Enter | 13 |
| Left | 37 | Up | 38 |
| Right | 39 | Down | 40 |
| A | 65 | W | 87 |
| S | 83 | D | 68 |
| Escape | 27 | Shift | 16 |
| Ctrl | 17 | Alt | 18 |

## Event Commands

### Add Event
```bash
gms event add o_player create --template templates/player_create.gml
```

### Remove Event
```bash
gms event remove o_player alarm:0 --keep-file
```
- `--keep-file` - Don't delete the .gml file

### List Events
```bash
gms event list o_player
```

### Duplicate Event
```bash
gms event duplicate o_player step:0 step:1
```
Examples:

- `gms event duplicate o_player step:0 step:1` copies step to begin step.
- `gms event duplicate o_player collision:o_enemy collision:o_wall` copies collision handling to another existing object target.

Collision event files use `Collision_<object_name>.gml`, and their `collisionObjectId` is a GameMaker object reference. Numeric collision subtypes such as `collision:0` are invalid.

### Validate Events
```bash
gms event validate o_player
```

### Fix Event Issues
```bash
gms event fix o_player --no-safe-mode
```
- Default (safe mode): Only removes orphan .gml files
- `--no-safe-mode`: Also adds orphan events to .yy
