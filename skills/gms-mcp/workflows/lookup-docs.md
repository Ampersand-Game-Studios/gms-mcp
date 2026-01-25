---
name: lookup-docs
description: Look up GML function documentation from the official manual
---

## When to use

- Learning how a GML function works
- Checking function parameters and return values
- Finding related functions for a task
- Exploring what functions are available in a category
- Verifying syntax before using a function

## Looking Up a Function

```bash
# Look up any GML function
gms doc lookup draw_sprite

# Force refresh from manual.gamemaker.io
gms doc lookup draw_sprite --refresh
```

**Output includes:**
- Category (e.g., "Drawing > Sprites_And_Tiles")
- Description explaining what the function does
- Syntax showing the function signature
- Parameters with types and descriptions
- Return value
- Code examples (when available)

## Searching for Functions

When you don't know the exact function name:

```bash
# Search by keyword
gms doc search collision
gms doc search sprite
gms doc search string

# Filter by category
gms doc search create --category Drawing
gms doc search add --category "Data Structures"

# Get more results
gms doc search draw --limit 50
```

## Exploring Categories

```bash
# See all categories
gms doc categories

# List functions in a category
gms doc list --category Drawing
gms doc list --category Strings
gms doc list --category "Data Structures"
```

## Workflow: Learning a New API Area

1. **See what categories exist**
   ```bash
   gms doc categories
   ```

2. **Explore the relevant category**
   ```bash
   gms doc list --category "Data Structures"
   ```

3. **Look up specific functions**
   ```bash
   gms doc lookup ds_list_create
   gms doc lookup ds_list_add
   ```

## Workflow: Finding the Right Function

1. **Search by what you want to do**
   ```bash
   gms doc search collision
   ```

2. **Narrow by category if needed**
   ```bash
   gms doc search collision --category Movement
   ```

3. **Look up promising candidates**
   ```bash
   gms doc lookup collision_rectangle
   gms doc lookup place_meeting
   ```

## Workflow: Using Pattern Matching

For more precise filtering:

```bash
# Functions starting with "draw_"
gms doc list --pattern "^draw_"

# Functions ending with "_ext"
gms doc list --pattern "_ext$"

# Functions containing "sprite"
gms doc list --pattern "sprite"

# Combine with category
gms doc list --category Drawing --pattern "^draw_sprite"
```

## Managing the Cache

Documentation is cached locally for fast access:

```bash
# Check cache status
gms doc cache stats

# Clear entire cache (will re-fetch as needed)
gms doc cache clear

# Clear only function docs, keep index
gms doc cache clear --functions-only
```

**Cache location:** `~/.gms-mcp/doc_cache/`

**When to clear:**
- After GameMaker updates with new functions
- If documentation seems wrong or outdated
- Index refreshes automatically after 7 days
- Function docs expire after 30 days

## Tips

- First lookup fetches from web (may take a moment)
- Subsequent lookups use local cache (instant)
- Use `--refresh` to get latest docs for a specific function
- Over 1000 GML functions are indexed
- Index is built on first use, then cached

## Common Function Categories

| Task | Category | Example Search |
|------|----------|---------------|
| Drawing sprites | Drawing | `gms doc search sprite --category Drawing` |
| Handling text | Strings | `gms doc list --category Strings` |
| Collision detection | Movement | `gms doc search collision` |
| Data storage | Data Structures | `gms doc list --category "Data Structures"` |
| File I/O | File | `gms doc list --category File` |
| Math operations | Maths | `gms doc search angle --category Maths` |
| Audio playback | Asset Management | `gms doc search audio` |
| Keyboard input | Game | `gms doc search keyboard` |

## Never Do

- Assume documentation is always current (GameMaker updates may add functions)
- Skip reading parameter descriptions (subtle requirements matter)
- Ignore return values (many functions return useful data)
- Clear cache unnecessarily (it speeds up lookups significantly)
