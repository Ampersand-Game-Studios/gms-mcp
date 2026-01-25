---
name: doc-commands
description: GML documentation lookup and search reference
---

# Documentation Commands Reference

Look up GML function documentation from manual.gamemaker.io with local caching.

## Lookup Function

Look up documentation for a specific GML function.

```bash
gms doc lookup <function_name> [--refresh]
```
- `--refresh` - Bypass cache and fetch fresh documentation

**Output includes:**
- Category and subcategory
- Description
- Syntax/signature
- Parameters (name, type, description)
- Return value
- Examples (when available)

**Examples:**
```bash
gms doc lookup draw_sprite
gms doc lookup string_pos
gms doc lookup instance_create_layer
gms doc lookup ds_list_add --refresh
```

## Search Functions

Search for GML functions by name.

```bash
gms doc search <query> [--category STRING] [--limit INT]
```
- `--category` - Filter by category (e.g., "Drawing", "Strings")
- `--limit` - Maximum results (default: 20)

**Examples:**
```bash
# Search by name
gms doc search draw
gms doc search collision

# Filter by category
gms doc search sprite --category "Asset Management"
gms doc search create --category Drawing

# Limit results
gms doc search string --limit 50
```

## List Functions

List GML functions with filtering.

```bash
gms doc list [--category STRING] [--pattern REGEX] [--limit INT]
```
- `--category` - Filter by category name (partial match)
- `--pattern` - Filter by regex pattern on function name
- `--limit` - Maximum results (default: 100)

**Examples:**
```bash
# List all functions in a category
gms doc list --category Drawing
gms doc list --category "Data Structures"

# Filter by pattern
gms doc list --pattern "^draw_"
gms doc list --pattern "sprite"
gms doc list --pattern "_ext$"

# Combine filters
gms doc list --category Strings --pattern "^string_"
```

## List Categories

List all available GML documentation categories.

```bash
gms doc categories
```

**Output includes:**
- Category names
- Function counts per category
- Subcategories with counts

## Cache Management

### View Cache Stats

```bash
gms doc cache stats
```

**Shows:**
- Cache directory location
- Index age
- Number of indexed functions
- Number of cached function docs
- Cache size

### Clear Cache

```bash
gms doc cache clear [--functions-only]
```
- `--functions-only` - Only clear cached function docs, keep the index

**When to clear:**
- After GameMaker updates (new functions)
- If documentation seems outdated
- To free disk space

## Categories

Common GML documentation categories:

| Category | Description |
|----------|-------------|
| Drawing | Sprites, shapes, text, surfaces, GPU |
| Strings | String manipulation and formatting |
| Maths | Numbers, angles, matrices, date/time |
| Asset Management | Sprites, audio, rooms, objects, instances |
| Data Structures | Lists, maps, grids, stacks, queues |
| Movement | Collisions, motion planning |
| Game | Input (keyboard, mouse, gamepad) |
| File | File handling, INI, text, binary, JSON |
| Buffers | Buffer operations |
| Networking | Network functions |
| Cameras | Cameras and viewports |

## Common Workflows

### Learning a New Function
```bash
gms doc lookup function_name
```

### Finding Related Functions
```bash
gms doc search keyword
gms doc list --category "Category Name"
```

### Exploring a Category
```bash
gms doc categories
gms doc list --category Drawing --limit 200
```

### Keeping Docs Fresh
```bash
gms doc cache stats
gms doc cache clear  # If index is old
gms doc lookup function_name --refresh  # Refresh single function
```
