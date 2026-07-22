---
name: find-code
description: Find definitions and references using the symbol index
---

## When to use

- Finding where a function/variable is defined
- Finding all usages of a symbol
- Understanding unfamiliar code
- Before refactoring or deleting code
- Exploring project structure

## Building the Symbol Index

The symbol index must be built before using find commands.

```bash
# Build index (uses cache if available)
gms symbol build

# Force rebuild (ignore cache)
gms symbol build --force
```

**When to rebuild:**
- After major code changes
- After pulling from version control
- If find results seem stale

## Finding Definitions

```bash
# Find where a function is defined
gms symbol find-definition player_take_damage

# Find a constructor
gms symbol find-definition Player

# Find an enum
gms symbol find-definition ENEMY_STATE
```

**Output includes:**
- File path
- Line number
- Symbol type (function, enum, macro, etc.)

## Finding References

```bash
# Find all usages of a function
gms symbol find-references player_take_damage

# Limit results
gms symbol find-references player_take_damage --max-results 20
```

**Use cases:**
- Before renaming (see what will be affected)
- Before deleting (check for dependencies)
- Understanding code flow

## Listing Symbols

```bash
# List all symbols
gms symbol list

# Filter by type
gms symbol list --kind function
gms symbol list --kind enum
gms symbol list --kind macro
gms symbol list --kind globalvar
gms symbol list --kind constructor

# Filter by name
gms symbol list --name-filter player

# Filter by file
gms symbol list --file-filter enemy

# Combine filters
gms symbol list --kind function --name-filter init

# Limit results
gms symbol list --max-results 50
```

## Project Diagnostics

```bash
# Quick scan for issues
gms diagnostics --depth quick

# Deep analysis with all info
gms diagnostics --depth deep --include-info
```

## Workflow: Understanding New Code

1. **Get overview of symbols**
   ```bash
   gms symbol list --kind function --max-results 100
   ```

2. **Find key entry points**
   ```bash
   gms symbol list --name-filter init
   gms symbol list --name-filter main
   gms symbol list --name-filter start
   ```

3. **Trace from entry point**
   ```bash
   gms symbol find-definition game_init
   # Read the code, find function calls
   gms symbol find-definition player_spawn
   ```

4. **Find all usages of key functions**
   ```bash
   gms symbol find-references player_spawn
   ```

## Workflow: Pre-Refactor Analysis

1. **Find what you're changing**
   ```bash
   gms symbol find-definition old_function_name
   ```

2. **Find all usages**
   ```bash
   gms symbol find-references old_function_name
   ```

3. **Check for related symbols**
   ```bash
   gms symbol list --name-filter old_function
   ```

4. **After refactoring, rebuild index**
   ```bash
   gms symbol build --force
   ```

## Workflow: Finding Dead Code

1. **List all functions**
   ```bash
   gms symbol list --kind function > all_functions.txt
   ```

2. **Check each for references**
   ```bash
   gms symbol find-references potentially_unused_func
   ```

3. **No references = candidate for removal** (but check for dynamic calls)

## Tips

- Rebuild index after large changes
- Use `--max-results` to avoid overwhelming output
- Combine with grep for more complex searches
- The index is cached - first build is slow, subsequent builds are fast
- Index includes: functions, enums, macros, global variables, constructors

## Symbol Types

| Kind | Description | Example |
|------|-------------|---------|
| `function` | Script functions | `function player_move()` |
| `constructor` | Constructor functions | `function Player() constructor` |
| `enum` | Enumerations | `enum STATES { IDLE, WALK }` |
| `macro` | Macros/constants | `#macro SPEED 5` |
| `globalvar` | Global variables | `globalvar score` |

## Never Do

- Use stale index for critical refactoring decisions
- Assume no references means safe to delete (check for string-based calls)
- Skip index rebuild after pulling changes from others
