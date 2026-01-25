---
name: pre-commit
description: Validate project before committing changes
---

## When to use

Before committing changes to version control.

## Quick Validation

```bash
gms diagnostics --depth quick
```

If clean, you're ready to commit.

## If Issues Found

1. **Review the diagnostics output**

2. **Auto-fix safe issues**:
   ```bash
   gms maintenance auto --fix
   ```

3. **Re-run diagnostics**:
   ```bash
   gms diagnostics --depth quick
   ```

4. **Commit when clean**

## Full Pre-Commit Workflow

```bash
# 1. Quick check
gms diagnostics --depth quick

# 2. If issues, fix them
gms maintenance auto --fix --verbose

# 3. Rebuild symbol index (if code changed)
gms symbol build --force

# 4. Final verification
gms diagnostics --depth quick

# 5. Ready to commit
git add .
git commit -m "Your message"
```

## One-Liner

```bash
gms diagnostics --depth quick && git add . && git commit -m "Your message"
```

This only commits if diagnostics pass.

## Tips

- Run diagnostics before every commit
- Fix issues immediately, don't accumulate them
- Deep diagnostics take longer but catch more issues
- If you're in a hurry, at least run quick diagnostics
