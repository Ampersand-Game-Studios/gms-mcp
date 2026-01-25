---
name: workflow-commands
description: Complete workflow operation command reference
---

# Workflow Commands Reference

High-level asset operations: duplicate, rename, delete, swap.

## Duplicate Asset

Copy an asset to create a variant.

```bash
gms workflow duplicate <asset_path> <new_name> [--yes]
```
- `--yes` - Skip confirmation prompt

**What gets duplicated:**
- The .yy configuration file
- Associated files (.gml, images, etc.)
- Internal references updated to new name

**Examples:**
```bash
# Duplicate object
gms workflow duplicate objects/o_enemy/o_enemy.yy o_enemy_fast

# Duplicate script
gms workflow duplicate scripts/scr_utils/scr_utils.yy scr_utils_v2

# Duplicate room
gms workflow duplicate rooms/r_level_01/r_level_01.yy r_level_02

# Skip confirmation
gms workflow duplicate objects/o_enemy/o_enemy.yy o_enemy_boss --yes
```

## Rename Asset

Rename an asset and update all references.

```bash
gms workflow rename <asset_path> <new_name>
```

**What gets updated:**
- The .yy file and directory name
- The asset's internal name field
- The project .yyp file
- All GML code references

**Examples:**
```bash
gms workflow rename scripts/scr_old_name/scr_old_name.yy scr_new_name
gms workflow rename objects/o_player/o_player.yy o_hero
```

## Delete Asset

Remove an asset from the project.

```bash
gms workflow delete <asset_path> [--dry-run]
```
- `--dry-run` - Preview without deleting

**Important:** Always check for references first!
```bash
gms symbol find-references asset_name
gms workflow delete path/to/asset.yy --dry-run
gms workflow delete path/to/asset.yy
```

## Swap Sprite

Replace a sprite's PNG source image.

```bash
gms workflow swap-sprite <sprite_path> <png_path>
```

**What gets preserved:**
- Sprite origin point
- Collision mask settings
- Animation settings
- All references to the sprite

**What gets replaced:**
- The image data
- Image dimensions (if different)

**Examples:**
```bash
gms workflow swap-sprite sprites/spr_player/spr_player.yy new_player.png
```

## Finding Asset Paths

Use symbol tools to find .yy paths:
```bash
gms symbol find-definition asset_name
# Output: path/to/asset.yy:1 (type)
```

## Common Workflows

### Create Variant
```bash
gms workflow duplicate objects/o_enemy/o_enemy.yy o_enemy_fast
# Edit o_enemy_fast as needed
```

### Safe Rename
```bash
gms symbol find-references old_name  # Check what uses it
gms workflow rename path/to/old_name.yy new_name
gms symbol build --force             # Rebuild index
```

### Safe Delete
```bash
gms symbol find-references asset_name  # Check dependencies
gms workflow delete path/to/asset.yy --dry-run
gms workflow delete path/to/asset.yy
gms maintenance auto                   # Verify project
```

### Update Art
```bash
gms workflow swap-sprite sprites/spr_player/spr_player.yy art/player_v2.png
```
