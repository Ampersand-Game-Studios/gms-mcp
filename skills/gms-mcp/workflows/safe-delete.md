---
name: safe-delete
description: Check dependencies before deleting GameMaker assets
---

## When to use

Before deleting any GameMaker asset, use this dependency-aware workflow. It is a dry-run unless `--apply` is supplied.

## Workflow

1. **Run the dependency-aware dry-run**:
   ```bash
   gms workflow safe-delete --asset-type script --asset-name scr_old_collision
   ```

2. **Analyze the results**:
   - If no references are found, apply the deletion
   - If references exist, update or remove them first

3. **If references exist**, either:
   - Update calling code to use alternative
   - Delete the referencing assets first (recursively apply safe-delete)

4. **Delete the asset**:
   ```bash
   gms workflow safe-delete --asset-type script --asset-name scr_old_collision --apply
   ```

`--force --apply` permits deletion with dependencies but leaves those references unchanged and reports them as unresolved. It never rewrites code to `undefined`.

## Example

User wants to delete `scr_old_collision`:

```bash
# Step 1: Inspect the dependency-aware dry-run
gms workflow safe-delete --asset-type script --asset-name scr_old_collision

# Output shows o_player and o_enemy use it
# Step 2: Update those objects first, then:

gms workflow safe-delete --asset-type script --asset-name scr_old_collision
gms workflow safe-delete --asset-type script --asset-name scr_old_collision --apply
```

## Never Do

- Use a lower-level delete command to bypass dependency checks
- Treat `--force` as automatic reference cleanup
- Assume comments or ordinary string literals are executable dependencies; an exact first string argument to `asset_get_index(...)` is the deliberate exception
