---
name: symbol-commands
description: Complete symbol index and code intelligence reference
---

# Symbol Commands Reference

The symbol index enables code navigation and understanding.

## Building the Index

```bash
gms symbol build [--force]
```
- `--force` - Rebuild from scratch, ignore cache

**When to rebuild:**
- After major code changes
- After pulling from version control
- If find results seem stale

## Find Definition

Find where a symbol is defined.

```bash
gms symbol find-definition <symbol_name>
```

**Output includes:**
- File path
- Line number
- Symbol type (function, enum, macro, etc.)

**Examples:**
```bash
gms symbol find-definition player_move
gms symbol find-definition Player           # Constructor
gms symbol find-definition ENEMY_STATE      # Enum
gms symbol find-definition MAX_SPEED        # Macro
```

## Find References

Find all usages of a symbol.

```bash
gms symbol find-references <symbol_name> [--max-results INT]
```
- `--max-results` - Limit results (default: 50)

**Examples:**
```bash
gms symbol find-references player_move
gms symbol find-references player_move --max-results 20
```

## List Symbols

List symbols in the project with filtering.

```bash
gms symbol list [options]
```

### Filter by Kind
```bash
--kind <TYPE>
```

| Kind | Description | Example |
|------|-------------|---------|
| `function` | Script functions | `function player_move()` |
| `constructor` | Constructor functions | `function Player() constructor` |
| `enum` | Enumerations | `enum STATES { }` |
| `macro` | Macros/constants | `#macro SPEED 5` |
| `globalvar` | Global variables | `globalvar score` |

### Filter by Name
```bash
--name-filter <STRING>
```
Case-insensitive substring match.

### Filter by File
```bash
--file-filter <STRING>
```
Case-insensitive substring match on file path.

### Limit Results
```bash
--max-results <INT>
```
Default: 100

### Examples

```bash
# All functions
gms symbol list --kind function

# All enums
gms symbol list --kind enum

# Functions containing "player"
gms symbol list --kind function --name-filter player

# Symbols in enemy files
gms symbol list --file-filter enemy

# Combined filters
gms symbol list --kind function --name-filter init --max-results 20
```

## Diagnostics

Quick project analysis (not part of symbol commands but related).

```bash
gms diagnostics [--depth quick|deep] [--include-info]
```
- `--depth quick` - Fast scan (default)
- `--depth deep` - Comprehensive analysis
- `--include-info` - Include info-level diagnostics

## Common Workflows

### Understanding New Code
```bash
gms symbol list --kind function --max-results 100
gms symbol list --name-filter init
gms symbol find-definition game_init
gms symbol find-references game_init
```

### Pre-Refactor Analysis
```bash
gms symbol find-definition old_function
gms symbol find-references old_function
gms symbol list --name-filter old_function
```

### Finding Dead Code
```bash
gms symbol list --kind function
gms symbol find-references potentially_unused  # No results = candidate for removal
```
