---
name: duplicate-asset
description: Copy an existing asset to create a variant
---

## When to use

When you need a new asset based on an existing one - faster than creating from scratch.

## Workflow

1. **Find the asset path**:
   ```bash
   gms symbol find-definition asset_name
   ```

2. **Duplicate it**:
   ```bash
   gms workflow duplicate path/to/asset.yy new_name
   ```

3. **Modify the duplicate** as needed

4. **Verify**:
   ```bash
   gms maintenance auto
   ```

## Examples

### Duplicate an object
```bash
gms workflow duplicate objects/o_enemy/o_enemy.yy o_enemy_fast
# Now edit o_enemy_fast to change speed, behavior, etc.
```

### Duplicate a script
```bash
gms workflow duplicate scripts/scr_utils/scr_utils.yy scr_utils_v2
```

### Duplicate a room
```bash
gms workflow duplicate rooms/r_level_01/r_level_01.yy r_level_02
# Great for creating level variants
```

### Duplicate a sprite
```bash
gms workflow duplicate sprites/spr_player/spr_player.yy spr_player_alt
# Then swap the image if needed
```

## Skip Confirmation

```bash
gms workflow duplicate path/to/asset.yy new_name --yes
```

## What Gets Duplicated

- The .yy configuration file
- All associated files (.gml, images, etc.)
- Internal references updated to new name

## Tips

- Use for creating enemy variants, level copies, etc.
- After duplicating, customize the copy - don't leave identical assets
- For objects, duplicating also copies all events
- For rooms, duplicating copies all layers and instances
