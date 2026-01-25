---
name: safe-delete
description: Check dependencies before deleting GameMaker assets
---

## When to use

Before deleting ANY GameMaker asset (script, object, sprite, room, etc.), use this workflow to prevent broken references.

## Workflow

1. **Check for references** to the asset you want to delete:
   ```bash
   gms symbol find-references <asset_name>
   ```

2. **Analyze the results**:
   - If no references found: Safe to delete
   - If references exist: Must update or remove references first

3. **If references exist**, either:
   - Update calling code to use alternative
   - Delete the referencing assets first (recursively apply safe-delete)

4. **Delete the asset**:
   ```bash
   gms asset delete <asset_type> <asset_name>
   ```

5. **Run maintenance** to verify project integrity:
   ```bash
   gms maintenance auto
   ```

## Example

User wants to delete `scr_old_collision`:

```bash
# Step 1: Check references
gms symbol find-references scr_old_collision

# Output shows o_player and o_enemy use it
# Step 2: Update those objects first, then:

gms asset delete script scr_old_collision
gms maintenance auto
```

## Never Do

- Delete assets without checking references first
- Ignore "symbol not found" warnings (may indicate stale index)
- Skip the maintenance check after deletion
