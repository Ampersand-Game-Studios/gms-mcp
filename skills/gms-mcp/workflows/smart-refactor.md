---
name: smart-refactor
description: Atomic token-aware rename with automatic reference updates
---

## When to use

When renaming any GameMaker asset where references need to be updated across the codebase.

## Workflow

1. **Identify the asset path**:
   ```bash
   gms symbol find-definition scr_player_move
   ```

2. **Preview references** that will need updating:
   ```bash
   gms symbol find-references scr_player_move
   ```

3. **Execute the atomic token-aware rename**:
   ```bash
   gms workflow rename scripts/scr_player_move/scr_player_move.yy scr_player_movement
   ```

   This command:
   - Renames the .yy file and directory
   - Updates the asset's internal name field
   - Updates the project .yyp file
   - Updates exact executable GML identifier tokens
   - Leaves comments, ordinary strings, and longer identifiers unchanged
   - Updates an exact first string argument to `asset_get_index(...)`, because that is an explicit asset lookup
   - Stops before mutation if a declaration, parameter, macro, enum, or assignment shadows the asset name
   - Updates parsed GameMaker resource-reference structures

4. **Rebuild the symbol index**:
   ```bash
   gms symbol build --force
   ```

5. **Verify the rename**:
   ```bash
   gms symbol find-definition scr_player_movement
   gms symbol find-references scr_player_move  # Should return nothing
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

- The workflow rename updates token-aware GML references and structured GameMaker metadata; it does not perform suffix-based or prose rewrites
- Always rebuild the symbol index after renaming
- For objects with events, all .gml files are automatically renamed
