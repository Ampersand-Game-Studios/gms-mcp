---
name: setup-object
description: Create a new object with sprite and events
---

## When to use

When creating a new game object that needs a sprite and event handlers.

## Workflow

1. **Create the sprite** (if needed):
   ```bash
   gms asset create sprite spr_player --parent-path "folders/Sprites.yy"
   ```

2. **Create the object** with sprite reference:
   ```bash
   gms asset create object o_player --parent-path "folders/Objects.yy" --sprite-id spr_player
   ```

3. **Add common events**:
   ```bash
   gms event add o_player create
   gms event add o_player step
   gms event add o_player draw
   ```

4. **Add collision events** (if needed):
   ```bash
   gms event add o_player collision:o_wall
   gms event add o_player collision:o_enemy
   ```

5. **Verify**:
   ```bash
   gms event list o_player
   ```

## Example: Enemy Object

```bash
# Create sprite and object
gms asset create sprite spr_enemy --parent-path "folders/Sprites/Enemies.yy"
gms asset create object o_enemy --parent-path "folders/Objects/Enemies.yy" --sprite-id spr_enemy

# Add behavior events
gms event add o_enemy create      # Initialize variables
gms event add o_enemy step        # AI/movement logic
gms event add o_enemy draw        # Custom drawing
gms event add o_enemy alarm:0     # Attack timer
gms event add o_enemy destroy     # Death effects

# Add collision
gms event add o_enemy collision:o_player_bullet
```

## Example: Child Object (Inheritance)

```bash
# Create child that inherits from parent
gms asset create object o_enemy_boss --parent-path "folders/Objects/Enemies.yy" \
  --sprite-id spr_enemy_boss --parent-object o_enemy

# Child only needs unique events
gms event add o_enemy_boss create    # Override parent init
gms event add o_enemy_boss alarm:1   # Special attack
```

## Naming Conventions

| Type | Prefix | Example |
|------|--------|---------|
| Object | `o_` | `o_player`, `o_enemy` |
| Sprite | `spr_` | `spr_player_idle` |

## Tips

- Always put assets in folders, not project root
- Set sprite before creating object when possible
- Use parent objects for shared behavior
- Add only the events you need (don't create empty ones)
