---
name: maintenance-commands
description: Complete maintenance command reference
---

# Maintenance Commands Reference

All commands: `gms maintenance <command> [options]`

## Core Commands

### auto
Comprehensive auto-maintenance.
```bash
gms maintenance auto [--fix] [--verbose]
```
- `--fix` - Apply fixes automatically
- `--verbose` - Show detailed output

### lint
Check for JSON errors and naming issues.
```bash
gms maintenance lint [--fix]
```

### health
Check environment setup (GameMaker installation, runtimes).
```bash
gms maintenance health
```

### fix-issues
Run comprehensive auto-maintenance with fixes enabled.
```bash
gms maintenance fix-issues [--verbose]
```

## Validation Commands

### validate-json
Check JSON syntax in all project files.
```bash
gms maintenance validate-json
```

### validate-paths
Check that folder paths referenced in assets exist.
```bash
gms maintenance validate-paths [--strict-disk-check] [--include-parent-folders]
```
- `--strict-disk-check` - Also check .yy files exist on disk
- `--include-parent-folders` - Show parent folders as orphaned

## Orphan Management

### list-orphans
Find orphaned assets (files without project references).
```bash
gms maintenance list-orphans
```

### prune-missing
Remove references to missing assets from project file.
```bash
gms maintenance prune-missing [--dry-run]
```
- `--dry-run` - Preview without making changes

### clean-orphans
Delete orphaned files from disk.
```bash
gms maintenance clean-orphans [--delete] [--skip-types TYPE...]
```
- Default is dry-run (preview only)
- `--delete` - Actually delete files
- `--skip-types` - Asset types to skip (default: folder)

## Cleanup Commands

### clean-old-files
Remove .old.yy backup files from project.
```bash
gms maintenance clean-old-files [--delete]
```
- Default is dry-run (preview only)
- `--delete` - Actually delete files

### dedupe-resources
Remove duplicate resource entries from project file.
```bash
gms maintenance dedupe-resources [--auto] [--dry-run]
```
- `--auto` - Keep first occurrence automatically
- `--dry-run` - Preview without making changes

## Event Synchronization

### sync-events
Synchronize object event .yy and .gml files.
```bash
gms maintenance sync-events [--fix] [--object NAME]
```
- Default is dry-run
- `--fix` - Apply fixes
- `--object` - Sync specific object only

## Common Workflows

### Quick Health Check
```bash
gms maintenance auto
```

### Fix Everything
```bash
gms maintenance auto --fix --verbose
```

### Clean Up Messy Project
```bash
gms maintenance list-orphans
gms maintenance prune-missing --dry-run
gms maintenance prune-missing
gms maintenance clean-orphans --delete --skip-types folder
gms maintenance clean-old-files --delete
gms maintenance sync-events --fix
gms maintenance auto --fix
```

### Pre-Commit Validation
```bash
gms diagnostics --depth quick
```
