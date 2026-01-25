---
name: analyze-logic
description: Summarize and understand script/object logic
---

## When to use

- Understanding unfamiliar code
- Documenting existing functionality
- Planning refactoring work
- Debugging complex logic

## Workflow

1. **Find the asset's location**:
   ```bash
   gms symbol find-definition <script_or_object_name>
   ```

2. **List symbols defined in the file**:
   ```bash
   gms symbol list --file-filter <asset_name>
   ```

3. **Find what it depends on**:
   - Read the code directly
   - Look for function calls, object references, sprite references

4. **Find what depends on it**:
   ```bash
   gms symbol find-references <asset_name>
   ```

5. **Create a summary** including:
   - Purpose (what does it do?)
   - Inputs (parameters, global state read)
   - Outputs (return values, global state modified)
   - Side effects (instance creation, file I/O, etc.)
   - Dependencies (other scripts/objects called)

## Example

Analyzing `scr_inventory_add`:

```bash
# Find it
gms symbol find-definition scr_inventory_add

# See all functions in this script
gms symbol list --file-filter inventory --kind function

# Who calls it?
gms symbol find-references scr_inventory_add
```

Summary output:
```
scr_inventory_add(item_id, quantity)
- Purpose: Add items to player inventory
- Inputs: item_id (real), quantity (real)
- Outputs: true if added, false if inventory full
- Side effects: Modifies global.inventory array
- Calls: scr_inventory_get_slot, scr_item_stack_max
- Called by: o_pickup, o_shop, scr_quest_reward
```

## Tips

- Start with the entry points (Create events, room creation code)
- Follow the call chain depth-first for complex systems
- Document as you go to avoid re-analysis
