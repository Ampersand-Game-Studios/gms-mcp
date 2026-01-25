---
name: setup-script
description: Create a new script with proper documentation
---

## When to use

When creating a new script file for functions or constructors.

## Workflow: Regular Script

1. **Create the script**:
   ```bash
   gms asset create script scr_player_utils --parent-path "folders/Scripts.yy"
   ```

2. **Edit the .gml file** to add your function with JSDoc:
   ```gml
   /// @function player_take_damage(amount, source)
   /// @description Apply damage to the player
   /// @param {Real} amount Damage points to apply
   /// @param {Id.Instance} source Instance that caused damage
   /// @returns {Bool} True if player died
   function player_take_damage(amount, source) {
       hp -= amount;
       if (hp <= 0) {
           instance_destroy();
           return true;
       }
       return false;
   }
   ```

## Workflow: Constructor Script

1. **Create with --constructor flag**:
   ```bash
   gms asset create script Player --constructor --parent-path "folders/Scripts.yy"
   ```

2. **Edit the .gml file**:
   ```gml
   /// @function Player(x, y)
   /// @description Player entity constructor
   /// @param {Real} x Starting X position
   /// @param {Real} y Starting Y position
   function Player(_x, _y) constructor {
       x = _x;
       y = _y;
       hp = 100;
       speed = 4;

       static move = function(dx, dy) {
           x += dx * speed;
           y += dy * speed;
       };

       static take_damage = function(amount) {
           hp -= amount;
           return hp <= 0;
       };
   }
   ```

## Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Regular script | `scr_` prefix, snake_case | `scr_player_utils` |
| Constructor | PascalCase, no prefix | `Player`, `Enemy`, `Inventory` |
| Functions | snake_case | `player_move`, `enemy_spawn` |

## JSDoc Types Reference

| Type | Description |
|------|-------------|
| `Real` | Number |
| `String` | Text |
| `Bool` | true/false |
| `Array` | Array |
| `Struct` | Struct/object |
| `Id.Instance` | Instance ID |
| `Asset.GMObject` | Object reference |
| `Asset.GMSprite` | Sprite reference |
| `Function` | Function reference |
| `Any` | Mixed type |

## Tips

- One script file can contain multiple functions
- Group related functions in the same script
- Use constructors for data objects (entities, items, etc.)
- Always add JSDoc for functions that will be called externally
- Use `static` for methods in constructors
