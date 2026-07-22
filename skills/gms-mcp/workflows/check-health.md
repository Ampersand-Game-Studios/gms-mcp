---
name: check-health
description: Quick project health check
---

## When to use

- Before running the game
- Before committing changes
- After pulling from version control
- When something seems wrong

## Quick Check

```bash
gms diagnostics --depth quick
```

This checks for:
- JSON syntax errors
- Naming convention violations
- Basic project structure issues

## Deep Check

```bash
gms diagnostics --depth deep --include-info
```

This adds:
- Orphaned asset detection
- Reference validation
- Comprehensive audit

## Fix Issues Automatically

```bash
gms maintenance auto --fix --verbose
```

## Environment Health

Check your GameMaker installation and runtime:
```bash
gms maintenance health
```

## Pre-Commit Workflow

```bash
# Quick validation before committing
gms diagnostics --depth quick && echo "Ready to commit"
```

## Common Issues and Fixes

### JSON Errors
```bash
gms maintenance validate-json
gms maintenance lint --fix
```

### Orphaned Files
```bash
gms maintenance list-orphans
gms maintenance clean-orphans --delete --skip-types folder
```

### Event Mismatches
```bash
gms maintenance sync-events --fix
```
