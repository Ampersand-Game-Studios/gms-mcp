---
name: cleanup-project
description: Clean up and maintain GameMaker project health
---

## When to use

- After making many changes to a project
- When the IDE shows errors or warnings
- Before committing changes to version control
- When inheriting or cleaning up a project
- Periodically as preventive maintenance

## Quick Health Check vs Deep Analysis

### Quick check (recommended first)
```bash
gms diagnostics --depth quick
```

### Deep analysis (thorough)
```bash
gms diagnostics --depth deep --include-info
```

### Auto-maintenance with fixes
```bash
gms maintenance auto --fix --verbose
```

## Maintenance Commands

### Core Commands

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `maintenance auto` | Comprehensive check | First line of defense |
| `maintenance lint` | JSON/naming issues | After manual edits |
| `maintenance health` | Environment check | Setup/troubleshooting |

### Orphan Detection and Cleanup

```bash
# Find orphaned assets (files without project references)
gms maintenance list-orphans

# Remove references to missing assets from project file
gms maintenance prune-missing --dry-run    # Preview
gms maintenance prune-missing              # Execute

# Delete orphaned files from disk
gms maintenance clean-orphans --skip-types folder    # Preview (dry-run default)
gms maintenance clean-orphans --delete --skip-types folder  # Actually delete
```

### File Cleanup

```bash
# Find and remove .old.yy backup files
gms maintenance clean-old-files            # Preview
gms maintenance clean-old-files --delete   # Actually delete
```

### Validation

```bash
# Validate JSON syntax in all project files
gms maintenance validate-json

# Validate folder paths exist
gms maintenance validate-paths
gms maintenance validate-paths --strict-disk-check
```

### Deduplication

```bash
# Find duplicate resource entries
gms maintenance dedupe-resources --dry-run

# Auto-fix duplicates (keep first occurrence)
gms maintenance dedupe-resources --auto
```

### Event Synchronization

```bash
# Sync event .yy and .gml files across all objects
gms maintenance sync-events            # Dry-run
gms maintenance sync-events --fix      # Apply fixes

# Sync specific object only
gms maintenance sync-events --fix --object o_player
```

## Workflow: Cleaning Up a Messy Project

1. **Assess the damage**
   ```bash
   gms diagnostics --depth deep
   ```

2. **Fix JSON issues first**
   ```bash
   gms maintenance validate-json
   gms maintenance lint --fix
   ```

3. **Handle orphans**
   ```bash
   gms maintenance list-orphans
   gms maintenance prune-missing --dry-run
   gms maintenance prune-missing
   ```

4. **Clean up files**
   ```bash
   gms maintenance clean-old-files --delete
   gms maintenance clean-orphans --delete --skip-types folder
   ```

5. **Sync events**
   ```bash
   gms maintenance sync-events --fix
   ```

6. **Final verification**
   ```bash
   gms maintenance auto --fix --verbose
   ```

## Workflow: Pre-Commit Check

```bash
# Quick validation before committing
gms diagnostics --depth quick && echo "Ready to commit"
```

## Tips

- Always use `--dry-run` first when deleting or pruning
- Skip folder cleanup (`--skip-types folder`) unless you're sure
- Run `maintenance auto` after any batch operations
- Use `--verbose` to see what's being fixed
- `maintenance health` checks your GameMaker/runtime setup, not project files

## Never Do

- Run cleanup commands without `--dry-run` preview first
- Delete orphaned folders without checking contents
- Skip maintenance after bulk asset operations
- Ignore validation warnings (they often indicate real problems)
