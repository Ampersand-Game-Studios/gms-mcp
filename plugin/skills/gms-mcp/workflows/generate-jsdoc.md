---
name: generate-jsdoc
description: Auto-generate JSDoc documentation for GML scripts
---

## When to use

- After creating new scripts or functions
- When updating function signatures
- When preparing code for team handoff

## Workflow

1. **Analyze the function** to understand:
   - Parameters and their types
   - Return value and type
   - Purpose and behavior

2. **Generate JSDoc header** in GameMaker format:
   ```gml
   /// @function function_name(param1, param2)
   /// @description Brief description of what this function does
   /// @param {type} param1 Description of first parameter
   /// @param {type} param2 Description of second parameter
   /// @returns {type} Description of return value
   ```

3. **Add to the script** at the top of the function

## GML Type Reference

| Type | Description |
|------|-------------|
| `Real` | Number (integer or decimal) |
| `String` | Text string |
| `Bool` | true or false |
| `Array` | Array of any type |
| `Array<Type>` | Typed array |
| `Struct` | Anonymous struct |
| `Id.Instance` | Instance ID |
| `Asset.GMObject` | Object asset |
| `Asset.GMSprite` | Sprite asset |
| `Asset.GMRoom` | Room asset |
| `Constant.*` | Enum or macro constant |
| `Any` | Mixed/unknown type |
| `Undefined` | Can be undefined |

## Example

Before:
```gml
function player_take_damage(amount, source) {
    hp -= amount;
    if (hp <= 0) {
        instance_destroy();
        return true;
    }
    return false;
}
```

After:
```gml
/// @function player_take_damage(amount, source)
/// @description Apply damage to the player and handle death
/// @param {Real} amount Damage points to apply
/// @param {Id.Instance} source Instance that caused the damage
/// @returns {Bool} True if player died, false otherwise
function player_take_damage(amount, source) {
    hp -= amount;
    if (hp <= 0) {
        instance_destroy();
        return true;
    }
    return false;
}
```

## Tips

- Be specific about parameter constraints (e.g., "must be positive")
- Document side effects in the description
- Use `@pure` tag for functions with no side effects
- Add `@deprecated` for functions being phased out
