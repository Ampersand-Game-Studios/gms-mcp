---
name: workflow-commands
description: Complete workflow operation command reference
---

# Workflow Commands Reference

High-level asset operations: duplicate, token-aware rename, dependency-aware delete, and sprite swap.

## Duplicate Asset

Copy an asset to create a variant.

```bash
gms workflow duplicate objects/o_enemy/o_enemy.yy o_enemy_fast --yes
```
- `--yes` - Skip confirmation prompt

**What gets duplicated:**
- The .yy configuration file
- Associated files (.gml, images, etc.)
- Internal references updated to new name
- Local sprite/room identities regenerated where GameMaker requires uniqueness
- External dependency references preserved

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
gms workflow rename scripts/scr_old_name/scr_old_name.yy scr_new_name
```

**What gets updated:**
- The .yy file and directory name
- The asset's internal name field
- The project .yyp file
- Exact executable GML identifier references
- Structured GameMaker resource references

Comments, ordinary strings, and longer identifiers containing the old name are intentionally unchanged. The exact first string argument to `asset_get_index(...)` is an explicit asset reference and is updated.
If GML declares, assigns, or accepts a parameter with the same name as the asset, rename stops before mutation and reports the ambiguous binding.

**Examples:**
```bash
gms workflow rename scripts/scr_old_name/scr_old_name.yy scr_new_name
gms workflow rename objects/o_player/o_player.yy o_hero
```

## Dependency-aware Delete

Preview or remove an asset by type and name. Preview is the default.

```bash
gms workflow safe-delete --asset-type script --asset-name scr_old --apply
```
- `--apply` - Perform the deletion after dependency analysis
- `--force` - Permit deletion with dependencies; references remain unchanged and are reported

**Examples:**
```bash
gms workflow safe-delete --asset-type script --asset-name scr_old
gms workflow safe-delete --asset-type script --asset-name scr_old --apply
```

There is no automatic `undefined` substitution. Referenced assets are blocked unless `--force` is explicit.

## Swap Sprite

Replace a sprite's PNG source image.

```bash
gms workflow swap-sprite sprites/spr_player/spr_player.yy art/player.png
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
gms workflow safe-delete --asset-type object --asset-name o_unused
gms workflow safe-delete --asset-type object --asset-name o_unused --apply
```

### Update Art
```bash
gms workflow swap-sprite sprites/spr_player/spr_player.yy art/player_v2.png
```
