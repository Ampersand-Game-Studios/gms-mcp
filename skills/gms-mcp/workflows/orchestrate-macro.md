---
name: orchestrate-macro
description: Create multi-asset systems with coordinated components
---

## When to use

When building a game system that requires multiple coordinated assets:
- Inventory systems (UI object, data scripts, item objects)
- Dialog systems (manager, UI, data)
- Combat systems (player, enemies, projectiles, effects)
- Save/load systems (manager, serializers, UI)

## Workflow

1. **Plan the asset structure**:
   - List all objects, scripts, sprites needed
   - Define the folder organization
   - Identify shared dependencies

2. **Create folders first**:
   ```bash
   gms asset create folder Systems --path "folders/Systems.yy"
   gms asset create folder Systems/Inventory --path "folders/Systems/Inventory.yy"
   ```

3. **Create scripts (data/logic layer)**:
   ```bash
   gms asset create script scr_inventory_data --parent-path "folders/Systems/Inventory.yy"
   gms asset create script scr_inventory_utils --parent-path "folders/Systems/Inventory.yy"
   ```

4. **Create objects (behavior layer)**:
   ```bash
   gms asset create object o_inventory_manager --parent-path "folders/Systems/Inventory.yy"
   gms asset create object o_inventory_ui --parent-path "folders/Systems/Inventory.yy"
   ```

5. **Add events to objects**:
   ```bash
   gms event add o_inventory_manager create
   gms event add o_inventory_manager step
   gms event add o_inventory_ui draw_gui
   ```

6. **Verify structure**:
   ```bash
   gms maintenance auto
   ```

## Example: Dialog System

```bash
# Create folder structure
gms asset create folder Dialog --path "folders/Systems/Dialog.yy"

# Core scripts
gms asset create script scr_dialog_data --parent-path "folders/Systems/Dialog.yy"
gms asset create script scr_dialog_parser --parent-path "folders/Systems/Dialog.yy"

# Manager object
gms asset create object o_dialog_manager --parent-path "folders/Systems/Dialog.yy"
gms event add o_dialog_manager create
gms event add o_dialog_manager step
gms event add o_dialog_manager cleanup

# UI object
gms asset create object o_dialog_box --parent-path "folders/Systems/Dialog.yy"
gms event add o_dialog_box create
gms event add o_dialog_box step
gms event add o_dialog_box draw_gui

# Verify
gms maintenance auto
```

## Best Practices

- Create all assets in a dedicated folder for the system
- Use consistent naming prefixes within the system
- Create manager objects as singletons (persistent)
- Separate data (scripts) from behavior (objects)
- Document the system entry points
