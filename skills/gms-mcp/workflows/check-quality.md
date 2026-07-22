---
name: check-quality
description: Detect GML anti-patterns and code quality issues
---

## When to use

- Before committing changes to GML code
- When reviewing unfamiliar code
- When debugging unexpected behavior

## Workflow

1. **Run project-wide diagnostics**:
   ```bash
   gms diagnostics --depth deep
   ```

2. **Check specific issues**:
   ```bash
   gms maintenance lint
   ```

3. **Auto-fix safe issues**:
   ```bash
   gms maintenance auto --fix
   ```

## Common GML Anti-Patterns to Watch For

### Variable Scope Issues
- Using `var` inside with() blocks (creates local, not instance variable)
- Missing `self.` prefix when setting instance variables in scripts
- Global variables without `global.` prefix

### Performance Issues
- `string()` concatenation in loops (use arrays or buffers)
- `instance_find()` every frame (cache results)
- Deep nested with() blocks

### Maintenance Issues
- Magic numbers without macros/constants
- Duplicate code across events
- Overly long Step events (split into scripts)

### Type Safety
- Missing `undefined` checks on ds_map/struct access
- Array index without bounds checking
- String operations on potentially undefined values

## Example

```bash
# Full project check
gms diagnostics --depth deep --include-info

# Quick lint
gms maintenance lint

# Fix and report
gms maintenance auto --fix --verbose
```

## Integration

Run diagnostics after significant changes and before running the game:
```bash
gms diagnostics --depth quick && gms run start
```
