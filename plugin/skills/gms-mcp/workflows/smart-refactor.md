---
name: smart-refactor
description: Atomic rename with automatic reference updates
---

## When to use

When renaming any GameMaker asset where references need to be updated across the codebase.

## Workflow

1. **Identify the asset path**:
   ```bash
   gms symbol find-definition <current_name>
   ```

2. **Preview references** that will need updating:
   ```bash
   gms symbol find-references <current_name>
   ```

3. **Execute the atomic rename**:
   ```bash
   gms workflow rename <asset_path.yy> <new_name>
   ```

   This command:
   - Renames the .yy file and directory
   - Updates the asset's internal name field
   - Updates the project .yyp file
   - Updates all GML references automatically

4. **Rebuild the symbol index**:
   ```bash
   gms symbol build --force
   ```

5. **Verify the rename**:
   ```bash
   gms symbol find-definition <new_name>
   gms symbol find-references <old_name>  # Should return nothing
   ```

## Example

Renaming `scr_player_move` to `scr_player_movement`:

```bash
# Find the asset
gms symbol find-definition scr_player_move
# Returns: scripts/scr_player_move/scr_player_move.yy

# Check what will be affected
gms symbol find-references scr_player_move

# Execute rename
gms workflow rename scripts/scr_player_move/scr_player_move.yy scr_player_movement

# Verify
gms symbol build --force
gms symbol find-definition scr_player_movement
```

## Notes

- The workflow rename handles all internal GameMaker file updates
- Always rebuild the symbol index after renaming
- For objects with events, all .gml files are automatically renamed
