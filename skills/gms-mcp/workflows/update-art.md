---
name: update-art
description: Replace sprite images without recreating assets
---

## When to use

When you have new art files and need to update existing sprites.

## Workflow

1. **Place the new PNG file** in an accessible location

2. **Swap the sprite image**:
   ```bash
   gms workflow swap-sprite sprites/spr_player/spr_player.yy path/to/new_player.png
   ```

3. **Verify in IDE** that the sprite looks correct

## Example: Batch Art Update

```bash
# Update multiple sprites from an art folder
gms workflow swap-sprite sprites/spr_player_idle/spr_player_idle.yy art/player_idle.png
gms workflow swap-sprite sprites/spr_player_walk/spr_player_walk.yy art/player_walk.png
gms workflow swap-sprite sprites/spr_player_jump/spr_player_jump.yy art/player_jump.png

# Verify project
gms maintenance auto
```

## What Gets Preserved

- Sprite origin point
- Collision mask settings
- Animation settings
- All references to the sprite

## What Gets Replaced

- The image data (PNG content)
- Image dimensions (if different)

## Tips

- Match dimensions if possible to avoid collision issues
- Test collision masks after updating if dimensions changed
- Works great for iterating on art during development
- Use consistent file naming to make batch updates easier

## Finding Sprite Paths

```bash
# Find where a sprite is defined
gms symbol find-definition spr_player
# Output: sprites/spr_player/spr_player.yy
```
