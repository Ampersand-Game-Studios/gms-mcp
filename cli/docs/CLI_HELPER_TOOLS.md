# Python Helper CLI Tools - GMS Master CLI

This document covers the unified `gms` command-line tool that provides all GameMaker development functionality. The `gms` command replaces all individual Python scripts with a single, organized interface.

## MCP integration (Cursor example)

This repo includes an MCP server (`gms-mcp`) that mirrors the `gms` CLI as tools (direct import first, CLI fallback):

- **Assets**: create all supported asset types + delete
- **Events**: add/remove/duplicate/list/validate/fix
- **Workflow**: duplicate/rename/delete/swap-sprite
- **Rooms**: ops/layers/instances
- **Code Intelligence** (GML symbol analysis):
  - `gm_build_index`: Build/rebuild the GML symbol index (cached for performance)
  - `gm_find_definition`: Find definition(s) of a GML symbol (function, enum, macro, globalvar)
  - `gm_find_references`: Find all references to a symbol across the project
  - `gm_list_symbols`: List all symbols with optional filtering by kind, name, or file
- **Introspection**: 
  - `gm_list_assets`: List all project assets (scripts, objects, etc.) with advanced filtering support (**`asset_type`**, **`name_contains`**, **`folder_prefix`**).
  - `gm_read_asset`: Read complete .yy JSON metadata.
  - `gm_search_references`: Search for patterns (string or regex) across the project.
  - `gm_get_asset_graph`: Build dependency graphs with deep GML code parsing.
  - `gm_get_project_stats`: Quick project-wide statistics.
- **Maintenance**: auto + all subcommands
- **Runner**: compile/run + stop/status
- **Escape hatch**: `gm_cli` (shell-out to `gms.py` with arbitrary args)

MCP setup/notes: `README.md` (generate Cursor config: `gms-mcp-init --cursor`; other client examples: `gms-mcp-init --vscode --windsurf --antigravity`)

## **CRITICAL PREREQUISITE: Python Installation**

**BEFORE attempting ANY CLI tool usage, Python MUST be properly installed and added to system PATH.**

### **PYTHON PATH REQUIREMENT**

**If ANY of these commands fail:**
- `python --version`
- `python -c "print('Hello')"`
- `where python` (PowerShell) or `which python` (bash)

**STOP IMMEDIATELY - The CLI tools will NOT work without Python in PATH.**

### **Required Actions:**
- Python is NOT properly installed or added to system PATH
- User must reinstall Python with "Add to PATH" option enabled
- NO attempts should be made to fix or work around this issue
- NO modifications to the tools will resolve PATH issues

### **Correct Python Installation Steps:**
1. Download Python from [python.org](https://python.org)
2. **CRITICAL**: Check "Add Python to PATH" during installation
3. Restart terminal/command prompt completely
4. Verify installation: `python --version` should return a version number
5. Only THEN proceed with CLI tool setup below

---

## **CRITICAL REQUIREMENT: Project Root**

**All CLI commands must run against the directory that contains your `.yyp` file.**

### Recommended (simple + predictable)
Run commands from inside `gamemaker/`:

```powershell
cd gamemaker
gms --version
gms asset create script my_function --parent-path "folders/Scripts.yy"
```

### Supported (run from anywhere)
The `gms` CLI will auto-locate the project using:
- `--project-root <path>` (preferred for one-off commands)
- `GM_PROJECT_ROOT` or `PROJECT_ROOT` environment variable (preferred for a whole session)
- automatic upward search for a `.yyp` (fallback)
- automatic `./gamemaker` detection when invoked from repo root (fallback)

### Cursor agents (recommended: no setup, no cwd dependency)
Cursor agents often execute commands from a temp working directory. Avoid relative wrappers like `.\gms.bat`.

Use module invocation with `PYTHONPATH` set to the repo `src` directory:

```powershell
$Env:PYTHONPATH = "<WORKSPACE>\src"
python -m gms_helpers.gms --project-root "<WORKSPACE>\gamemaker" --version
python -m gms_helpers.gms --project-root "<WORKSPACE>\gamemaker" asset create script my_function --parent-path "folders/Scripts.yy"
```

### **Project Directory Structure (Typical):**
```
gms2-template/           <- Project Root (repo root)
|-- gamemaker/           <- CLI WORKING DIRECTORY (run CLI here)
|   |-- project.yyp      <- GameMaker project file
|   |-- objects/         <- GameMaker assets
|   |-- scripts/         <- GameMaker assets
|   `-- ...
|-- src/
|   `-- gms_helpers/     <- Main CLI toolkit
`-- cli/                 <- CLI wrappers + tests/docs
    |-- tests/
    |-- docs/
    `-- reports/
```

### **CORRECT Usage Patterns:**

**Option A (recommended):**

```powershell
cd gamemaker
dir *.yyp    # Should show your project file
gms --version
gms asset create script my_function --parent-path "folders/Scripts.yy"
```

**Option B (run from repo root / any directory):**

```powershell
gms --project-root gamemaker --version
gms --project-root gamemaker asset create script my_function --parent-path "folders/Scripts.yy"
```

**Option C (persistent session):**

```powershell
$Env:GM_PROJECT_ROOT = "$PWD\gamemaker"
# OR
$Env:PROJECT_ROOT = "$PWD\gamemaker"
gms --version
gms asset create script my_function --parent-path "folders/Scripts.yy"
```

### **COMMON MISTAKES:**
```powershell
# WRONG - Running from project root
C:\...\gms2-template> gms --version
ERROR: No .yyp file found in current directory

# WRONG - Running from src directory
C:\...\gms2-template\src> gms --version
ERROR: No .yyp file found in current directory

# CORRECT - Running from gamemaker directory
C:\...\gms2-template\gamemaker> gms --version
Found GameMaker project: project.yyp
```

### **Troubleshooting Project Root Issues:**

**If you see: "ERROR: No .yyp file found in current directory"**

1. **Check current directory:** `pwd` (Linux/Mac) or `cd` (Windows)
2. **List files:** `ls` (Linux/Mac) or `dir` (Windows)
3. **Look for .yyp file:** Should see a `.yyp` file in the directory
4. **Fix it using one of:**
   - `cd gamemaker`
   - `gms --project-root gamemaker ...`
   - `$Env:GM_PROJECT_ROOT = "$PWD\gamemaker"`
   - `$Env:PROJECT_ROOT = "$PWD\gamemaker"`

**The CLI tools now automatically validate the working directory and will show clear error messages if you're in the wrong location.**

### **Why This Requirement Exists:**
- CLI tools need **direct access** to the `.yyp` project file
- Asset paths are **relative** to the GameMaker project root
- Maintenance operations require access to the **full project structure**

## Project Structure & Import Management

### Code Organization
The CLI tools are organized under `src/gms_helpers/` in the project structure:
```
gms2-template/
|-- gamemaker/           # GameMaker project files (.yyp, assets)
|-- src/
|   `-- gms_helpers/     # Main CLI toolkit
`-- cli/
    |-- tests/           # CLI test suite
    |-- docs/            # CLI docs
    `-- reports/         # CLI reports
```

### Import Path Management
**For Developers Working on CLI Tools:**

The project uses a centralized import management system to maintain clean, consistent imports:

- **All imports use**: `from gms_helpers.MODULE import ...`
- **Configuration lives in**: `cli/test_config.py`
- **To reorganize imports**: Run `python cli/update_test_imports.py`

**Example correct imports:**
```python
# Test files
from gms_helpers.asset_helper import create_script
from gms_helpers.event_helper import add_event

# Patch decorators in tests
@patch('gms_helpers.asset_helper.create_script')
```

**Future-Proofing:**
If the package location needs to change (e.g., `gms_helpers` -> `src.gamemaker_tools`):
1. Update `REAL_PACKAGE_PATH` in `cli/test_config.py`
2. Run `python cli/update_test_imports.py`
3. All imports are automatically updated across the entire test suite

This system eliminates hardcoded import paths and provides a single source of truth for package organization.

## Project Layout Update (July 2025)
The GameMaker project now resides in the `gamemaker/` directory at the repo root.
All CLI calls and tests will automatically respect the location when either of the following is true:

1. The `--project-root gamemaker` flag is supplied, **or**
2. The environment variable `PROJECT_ROOT` is set to the absolute path of `gamemaker/`.

Example - ad-hoc command:
```bash
# One-off
gms --project-root gamemaker asset list
```

Example - persistent (PowerShell):
```powershell
$Env:PROJECT_ROOT = "$PWD\gamemaker"
```

Example - persistent (bash/zsh):
```bash
export PROJECT_ROOT="$(git rev-parse --show-toplevel)/gamemaker"
```

If neither flag nor env-var is supplied the CLI falls back to searching upward from the current working directory for a `.yyp` file (and also checks for a `gamemaker/` folder while searching).

## **CRITICAL: PowerShell Syntax**

**For PowerShell users: Use `;` (semicolon) for command chaining:**

```powershell
$Env:PYTHONPATH = "$PWD\..\src"; cd gamemaker; python -m gms_helpers.gms --version
```

**Path**: Use `python -m gms_helpers.*` with `PYTHONPATH=src` when running from source.

## GML Code Intelligence

The `gms` CLI provides powerful GML symbol analysis and cross-reference capabilities.

### Usage
```bash
gms symbol [command] [arguments]
```

### Commands

- **build** - Build or rebuild the GML symbol index
```bash
gms symbol build
gms symbol build --force
```

- **find-definition** - Find the definition of a symbol
```bash
gms symbol find-definition scr_player_init
gms symbol find-definition GlobalVarName
```

- **find-references** - Find all references to a symbol
```bash
gms symbol find-references o_player
gms symbol find-references my_custom_function --max-results 100
```

- **list** - List all symbols in the project
```bash
gms symbol list
gms symbol list --kind function --name-filter "init"
gms symbol list --file-filter "scripts/player"
```

---

## Installation

### Zero-click in-repo usage
If you are **inside** the project folder you can run the wrappers in `cli/`:

```powershell
.\cli\gms.bat --help
```

```bash
./cli/gms --help
```

### Global installation (one-time)
To make the `gms` command available everywhere, run the auto-installer once:

```bash
python cli/agent_setup.py   # detects shell & installs itself
```

What this does:
1. Adds `cli` to your **user PATH** (Windows & *nix)
2. On Windows creates a tiny `gms.cmd` shim in `%LOCALAPPDATA%\Microsoft\WindowsApps` so the command works **immediately** in the current PowerShell session.

No manual copy/paste, profile edits, or shell restarts required.

## Quick Reference

```bash
# Help & Information
gms --help                           # Show all available commands
gms [category] --help               # Show commands for a category
gms [category] [action] --help      # Show detailed help for an action

# Runner Commands (Compile & Run)
gms run start                        # Run game (IDE-style temp directory)
gms run start --output-location project  # Run game (classic output folder)
gms run compile --platform HTML5    # Compile for HTML5
gms run stop                         # Stop running game

# Asset Management
gms asset create script my_function --parent-path "folders/Scripts.yy"
gms asset create object o_player --parent-path "folders/Objects.yy"
gms asset delete sprite spr_old --dry-run

# Event Management
gms event add o_player create
gms event remove o_enemy step
gms event list o_player

# Maintenance
gms maintenance auto                 # Dry-run maintenance check
gms maintenance auto --fix           # Fix detected issues
```

---

## Object Event Management

Manage GameMaker object events via the command line.

### Usage
```bash
gms event [command] [arguments]
```

### Commands

- **add** - Add an event to an object
```bash
gms event add o_player create
gms event add o_enemy step:end
gms event add o_wall collision:o_player
gms event add o_boss alarm:0
```

- **remove** - Remove an event from an object
```bash
gms event remove o_player destroy
gms event remove o_enemy step:1 --keep-file
```

- **duplicate** - Duplicate an event within an object
```bash
gms event duplicate o_boss step:0 1
gms event duplicate o_player create 1
```

- **list** - List all events for an object
```bash
gms event list o_player
gms event list o_enemy
```

- **validate** - Validate object events
```bash
gms event validate o_player
gms event validate o_enemy
```

- **fix** - Fix object event issues
```bash
python -m gms_helpers.event_helper fix o_player
python -m gms_helpers.event_helper fix o_enemy --no-safe-mode
```

### Event Specification Quick-Reference

| Spec | Description |
|------|-------------|
| `create` | Create event |
| `destroy` | Destroy event |
| `step[:begin|:end|:n]` | Step event variants |
| `draw[:gui]` | Draw / Draw-GUI |
| `collision:o_object` | Collision with object |
| `alarm:n` | Alarm `n` |

### Options
- `--template [file]` - Use custom template file for event content
- `--keep-file` - Keep GML file when removing an event
- `--no-safe-mode` - Allow potentially destructive fixes

---

## Runner Commands

Compile and run GameMaker projects with flexible output location options that match your workflow needs.

### Usage
```bash
gms run [command] [arguments]
```

### Commands

- **start** - Compile and run the GameMaker project
```bash
gms run start                                    # Default: IDE-style temp directory
gms run start --output-location temp             # Explicit temp directory (same as default)
gms run start --output-location project          # Classic output folder in project
gms run start --platform Windows --runtime YYC  # Specify platform and runtime
gms run start --background                       # Run in background mode
```

- **compile** - Compile the project without running
```bash
gms run compile                                  # Compile for Windows VM (default)
gms run compile --platform HTML5 --runtime VM   # Compile for HTML5
gms run compile --platform macOS --runtime YYC  # Compile for macOS with YYC
```

- **stop** - Stop the currently running game
```bash
gms run stop
```

- **status** - Check if a game is currently running
```bash
gms run status
```

### Output Location Options

The `--output-location` parameter controls where GameMaker places compiled game files:

**`temp` (Default - Recommended):**
- Uses IDE-style temp directory: `C:\Users\[user]\AppData\Local\Temp\GameMakerStudio2\[project]\`
- Keeps project folder completely clean
- Save files and game data persist in same location as IDE F5 runs
- Ideal for development and testing

**`project` (Classic):**
- Creates output folder in project: `gamemaker\output\[project]\[project].win`
- Traditional GameMaker CLI behavior
- Useful for debugging or when you need access to compiled files
- Game data saves relative to project directory

### Platform & Runtime Options

**Supported Platforms:**
- `Windows` (default)
- `HTML5`
- `macOS`
- `Linux`
- `Android`
- `iOS`

**Runtime Types:**
- `VM` - Virtual Machine (default, faster compilation)
- `YYC` - YoYo Compiler (optimized output, slower compilation)

### Examples

```bash
# Quick development testing (recommended)
gms run start

# Debug with local files
gms run start --output-location project

# Compile HTML5 build
gms run compile --platform HTML5

# Performance testing with YYC
gms run start --runtime YYC

# Background development workflow
gms run start --background
```

### Notes
- All runner commands must be executed from the `gamemaker/` directory
- The temp approach uses the same save file locations as the GameMaker IDE
- Classic project output is useful when you need to inspect compiled files or assets

---

## Asset Creation Helper (`asset_helper.py`)

Create GameMaker assets with proper file structure and project integration.

### Usage
```bash
python -m gms_helpers.asset_helper [asset_type] [name] [options]
```

### Asset Types

- **script** - Create a script asset
```bash
# Regular snake_case script
python -m gms_helpers.asset_helper script my_function --parent-path "folders/Scripts.yy"
python -m gms_helpers.asset_helper script player_move --parent-path "folders/Actors/Characters/Player/Parent/Scripts.yy"

# Constructor script (allows PascalCase naming)
python -m gms_helpers.asset_helper script PlayerData --parent-path "folders/Scripts.yy" --constructor
python -m gms_helpers.asset_helper script InventoryItem --parent-path "folders/Scripts.yy" --constructor
```

- **object** - Create an object asset
```bash
python -m gms_helpers.asset_helper object o_player --parent-path "folders/Objects.yy"
python -m gms_helpers.asset_helper object o_enemy --parent-path "folders/Actors/Characters/Enemies/Parent.yy" --parent-object "o_character"
python -m gms_helpers.asset_helper object o_bullet --parent-path "folders/Objects.yy" --sprite-id "spr_bullet"
```

- **sprite** - Create a sprite asset
```bash
python -m gms_helpers.asset_helper sprite spr_player --parent-path "folders/Sprites.yy"
python -m gms_helpers.asset_helper sprite spr_enemy_idle --parent-path "folders/Actors/Characters/Enemies/Parent/Sprites.yy"
```

- **room** - Create a room asset
```bash
python -m gms_helpers.asset_helper room r_menu --parent-path "folders/Rooms.yy"
python -m gms_helpers.asset_helper room r_level_1 --parent-path "folders/Rooms.yy" --width 1920 --height 1080
```

- **folder** - Create a folder asset (supports nested paths)
```bash
python -m gms_helpers.asset_helper folder "Scripts" --path "folders/Scripts.yy"
python -m gms_helpers.asset_helper folder "Enemies" --path "folders/Actors/Characters/Enemies.yy"
python -m gms_helpers.asset_helper folder "Parent" --path "folders/Actors/Characters/Enemies/Parent.yy"
```

- **font** - Create a font asset
```bash
python -m gms_helpers.asset_helper font fnt_ui_title --parent-path "folders/Fonts.yy" --size 24 --bold
python -m gms_helpers.asset_helper font fnt_dialogue --parent-path "folders/UI/Fonts.yy" --font-name "Courier New" --size 16
python -m gms_helpers.asset_helper font fnt_hud_small --parent-path "folders/HUD.yy" --size 10 --aa-level 2
```

- **shader** - Create a shader asset
```bash
python -m gms_helpers.asset_helper shader sh_blur --parent-path "folders/Shaders.yy"
python -m gms_helpers.asset_helper shader sh_lighting --parent-path "folders/VFX/Shaders.yy" --shader-type 1
python -m gms_helpers.asset_helper shader shader_water --parent-path "folders/Effects.yy" --shader-type 2
```

- **animcurve** - Create an animation curve asset
```bash
python -m gms_helpers.asset_helper animcurve curve_ease_bounce --parent-path "folders/Curves.yy" --curve-type ease_in
python -m gms_helpers.asset_helper animcurve ac_player_jump --parent-path "folders/Player/Curves.yy" --curve-type smooth
python -m gms_helpers.asset_helper animcurve curve_camera_zoom --parent-path "folders/Camera.yy" --curve-type ease_out --channel-name "zoom"
```

- **sound** - Create a sound asset
```bash
python -m gms_helpers.asset_helper sound snd_player_jump --parent-path "folders/Sounds.yy" --volume 0.8 --pitch 1.2
```

- **tileset** - Create a tileset asset
```bash
python -m gms_helpers.asset_helper tileset ts_dungeon --parent-path "folders/Tilesets.yy" --sprite-id "spr_dungeon_tiles"
```

- **path** - Create a movement path asset
```bash
python -m gms_helpers.asset_helper path pth_enemy_patrol --parent-path "folders/Paths.yy" --path-type smooth
```

- **timeline** - Create a timeline asset
```bash
python -m gms_helpers.asset_helper timeline tl_cutscene_01 --parent-path "folders/Timelines.yy"
```

- **sequence** - Create a sequence asset
```bash
python -m gms_helpers.asset_helper sequence seq_opening_titles --parent-path "folders/Sequences.yy"
```

- **note** - Create a documentation note asset
```bash
python -m gms_helpers.asset_helper note note_todo_list --parent-path "folders/Notes.yy"
```

- **delete** - Delete an asset (NEW)
```bash
python -m gms_helpers.asset_helper delete script my_old_function --dry-run   # Preview deletion
python -m gms_helpers.asset_helper delete object o_old_enemy                 # Actually delete
python -m gms_helpers.asset_helper delete sprite spr_unused                  # Remove sprite
```

### Object Options
- `--parent-object [name]` - Set parent object for inheritance
  **IMPORTANT: Use ONLY the object name, NOT the full path**
  **CORRECT**: `--parent-object "o_actor"`
  **WRONG**: `--parent-object "objects/o_actor/o_actor.yy"`

- `--sprite-id [name]` - Assign a sprite to the object (e.g., `--sprite-id "spr_player"`)

### Room Options
- `--width [pixels]` - Set room width (default: 1024)
- `--height [pixels]` - Set room height (default: 768)

### Font Options
- `--font-name [name]` - Font family name (default: Arial)
- `--size [points]` - Font size in points (default: 12)
- `--bold` - Make the font bold
- `--italic` - Make the font italic
- `--aa-level [0-3]` - Anti-aliasing level: 0=none, 1=low, 2=medium, 3=high (default: 1)
- `--uses-sdf` - Enable SDF (Signed Distance Field) rendering (default: True)

### Shader Options
- `--shader-type [1-4]` - Shader language type:
  - 1 = GLSL ES (default, mobile/web compatible)
  - 2 = GLSL (desktop OpenGL)
  - 3 = HLSL 9 (DirectX 9)
  - 4 = HLSL 11 (DirectX 11)

### Animation Curve Options
- `--curve-type [type]` - Predefined curve shape:
  - `linear` - Straight line from 0 to 1 (default)
  - `smooth` - Smooth S-curve
  - `ease_in` - Slow start, fast end
  - `ease_out` - Fast start, slow end
- `--channel-name [name]` - Name for the curve channel (default: "curve")

### Delete Options
- `--dry-run` - Preview what would be deleted without making changes
- Supports all asset types: script, object, sprite, room, folder, font, shader, animcurve, sound, path, tileset, timeline, sequence, note
- Removes both .yyp entries and disk files/folders
- Runs automatic maintenance validation before and after deletion

### Global Options
- `--skip-maintenance` - Skip automatic maintenance operations (not recommended)
- `--no-auto-fix` - Prevent automatic issue fixing during maintenance
- `--maintenance-verbose` - Show verbose maintenance output (default: True)

### Key Features
- **Automatic .yyp Integration**: All assets are automatically added to the project file
- **Nested Folder Support**: Create complex folder hierarchies with proper nesting
- **Object Inheritance**: Objects can inherit from parent objects
- **Auto-Maintenance**: Validates project health before and after asset creation
- **Error Prevention**: Blocks asset creation if critical project issues are detected
- **Strict Folder Validation**: Immediately exits if parent folder path doesn't exist (prevents dangling assets)
- **Asset Deletion**: Safe removal of assets from both project and disk with preview mode

### Maintenance Commands

#### Comprehensive Auto-Maintenance (Recommended)
```bash
python -m gms_helpers.auto_maintenance                           # Run all 9 maintenance checks (dry-run)
python -m gms_helpers.auto_maintenance --fix --verbose           # Fix all issues with detailed output
```

#### Individual Maintenance Commands
```bash
python -m gms_helpers.asset_helper maint lint                    # Check project for issues
python -m gms_helpers.asset_helper maint fix-commas              # Fix trailing commas in JSON
python -m gms_helpers.asset_helper maint list-orphans            # Find orphaned assets
python -m gms_helpers.asset_helper maint prune-missing           # Remove missing asset references
python -m gms_helpers.asset_helper maint validate-paths          # Check folder path references (.yyp-based)
python -m gms_helpers.asset_helper maint validate-paths --strict-disk-check  # Also check physical .yy files (legacy)
python -m gms_helpers.asset_helper maint dedupe-resources        # Remove duplicate resource entries (interactive)
python -m gms_helpers.asset_helper maint dedupe-resources --auto # Remove duplicate resource entries (automatic)
```

### Path Validation Options
- `--strict-disk-check` - Also validate that folder .yy files exist on disk (legacy behavior, not recommended)
- `--include-parent-folders` - Show parent folders as orphaned even if they have subfolders with assets

### Understanding GameMaker Folder Paths

**IMPORTANT**: GameMaker folder paths (like `folders/Scripts.yy`) are **logical references** that exist only in the project's `.yyp` file, not physical directories on disk.

#### Key Concepts:
- **Logical Folders**: Entries in the `.yyp` file's "Folders" list that organize assets in GameMaker's asset browser
- **Physical Files**: Actual `.yy` files and directories on your hard drive
- **Folder Path Validation**: By default, tools validate against the `.yyp` Folders list (recommended)
- **Legacy Disk Validation**: Use `--strict-disk-check` only if you need to check physical `.yy` files exist

#### How Folder Validation Works:
1. **Default Behavior**: Checks if folder path exists in `.yyp` Folders list
2. **With --strict-disk-check**: Also verifies physical `.yy` files exist on disk
3. **Helpful Feedback**: Shows available folder paths when validation fails
4. **Strict Enforcement**: **IMMEDIATELY EXITS** if folder path is invalid (prevents dangling assets)

### Duplicate Resource Prevention (NEW)
The asset creation system now includes duplicate resource detection to prevent `.yyp` file corruption:

- **Pre-creation validation**: Checks for existing resources before creation
- **Conflict detection**: Identifies exact duplicates vs. name conflicts
- **Automatic cleanup**: `dedupe-resources` command removes duplicates interactively or automatically
- **Clear error messages**: Provides specific guidance when conflicts are detected

### Recommended Workflow (ENFORCED)
The CLI tools now enforce a strict workflow to prevent project corruption:

1. **Create folders first**: Always create required folders before creating assets
   ```bash
   python -m gms_helpers.asset_helper folder "My Scripts" --path "folders/My Scripts.yy"
   ```

2. **Then create assets**: The CLI will verify folder paths exist before proceeding
   ```bash
   python -m gms_helpers.asset_helper script my_function --parent-path "folders/My Scripts.yy"
   ```

3. **If creation fails**: Fix the folder path and rerun - **no dangling assets are left behind**
   ```bash
   # This will fail immediately with helpful error message
   python -m gms_helpers.asset_helper script test --parent-path "folders/DoesNotExist.yy"
   ```

4. **Clean up when needed**: Use maintenance commands or the new delete command
   ```bash
   python -m gms_helpers.asset_helper maint prune-missing  # Remove broken references
   python -m gms_helpers.asset_helper delete script old_script  # Remove specific assets
   ```

**Key Benefits**:
- **No more dangling assets**: Invalid folder paths cause immediate exit
- **Clear error messages**: Shows all available folder paths when validation fails
- **Project integrity**: Prevents corrupted .yyp files from invalid asset creation
- **Clean workflow**: Forces proper folder structure before asset creation

---

## Auto-Maintenance (`auto_maintenance.py`)

Comprehensive project health monitoring and automatic issue fixing.

### Usage
```bash
python -m gms_helpers.auto_maintenance [options]
```

### Options
- `--fix` - Actually fix issues (default: dry-run mode that only reports)
- `--verbose` - Show detailed output for each maintenance step
- `--dry-run` - Only report issues without fixing them (default behavior)

### What Auto-Maintenance Does
The auto-maintenance system performs a comprehensive 9-step health check:

1. **Linting** - Check for JSON syntax errors and structural issues
2. **Path Validation** - Verify all folder references are valid
3. **JSON Fixes** - Repair trailing comma issues in .yy files
4. **Missing Assets** - Remove references to deleted/missing assets
5. **Event Sync** - Ensure object events match physical .gml files
6. **Old File Cleanup** - Remove .bak and other temporary files
7. **Duplicate Detection** - Find and report duplicate resource entries
8. **Orphan Cleanup** - Remove orphaned asset files (with safety checks)
9. **Multi-Asset Directories** - Detect problematic asset organization

### Orphan Cleanup Safety Features
The orphan cleanup system includes comprehensive safety checks to prevent accidental deletion:

- **Multi-Asset Directory Protection** - Won't delete companion files (`.gml`, `.png`) if multiple assets exist in the same directory
- **UUID-Based Sprite Attribution** - Matches sprite PNG files to their exact `.yy` file using UUID references
- **Safety Warnings** - Reports when companion files are protected from deletion
- **Comprehensive Logging** - Shows exactly what was deleted vs. what was protected

### Example Output
```bash
# Dry-run mode (default)
python -m gms_helpers.auto_maintenance

# Fix mode with verbose output
python -m gms_helpers.auto_maintenance --fix --verbose

# Example safety warning output:
# SAFETY: Skipped companion files for objects/o_btn_social_discord/o_btn_social_twitter.yy - directory contains other assets
# Protected 368 companion files from accidental deletion
```

### Best Practices
- **Always run in dry-run mode first** to see what would be changed
- **Review safety warnings** to understand what files are being protected
- **Run after major changes** to ensure project health
- **Use `--verbose` flag** to understand what each step is doing

---

## Room Layer Helper (`room_layer_helper.py`)

Manage layers within GameMaker rooms.

### Usage
```bash
python -m gms_helpers.room_layer_helper [command] [arguments]
```

### Commands

- **add-layer** - Add a new layer to a room
```bash
python -m gms_helpers.room_layer_helper add-layer r_game "lyr_enemies" --type instance --depth 4150
python -m gms_helpers.room_layer_helper add-layer r_game "Background" --type background --depth 5000
```

- **remove-layer** - Remove a layer from a room
```bash
python -m gms_helpers.room_layer_helper remove-layer r_game "lyr_old_layer"
```

- **list-layers** - List all layers in a room
```bash
python -m gms_helpers.room_layer_helper list-layers r_game
```

- **reorder-layer** - Change the depth of a layer
```bash
python -m gms_helpers.room_layer_helper reorder-layer r_game "lyr_player" --new-depth 3950
```

### Layer Types
- `background` - Background layers (sprites, colors)
- `instance` - Instance layers (objects)
- `asset` - Asset layers (sprites, sounds)
- `tile` - Tile layers (tilemap)
- `path` - Path layers (movement paths)
- `effect` - Effect layers (particles, shaders)

### Features
- **Duplicate prevention**: Won't create layers with existing names
- **Automatic sorting**: Layers are automatically sorted by depth
- **Type validation**: Ensures valid layer types are used

---

## Room Instance Helper (`room_instance_helper.py`)

Manage object instances within GameMaker room layers.

### Usage
```bash
python -m gms_helpers.room_instance_helper [command] [arguments]
```

### Commands

- **add-instance** - Add an object instance to a room layer
```bash
python -m gms_helpers.room_instance_helper add-instance r_game o_player --layer "lyr_player" --x 100 --y 200
python -m gms_helpers.room_instance_helper add-instance r_game o_enemy_zombie --layer "lyr_enemies" --x 300 --y 400 --scale-x 1.5 --rotation 45
```

- **remove-instance** - Remove an instance from a room
```bash
python -m gms_helpers.room_instance_helper remove-instance r_game inst_12345678
```

- **list-instances** - List instances in a room (all or by layer)
```bash
python -m gms_helpers.room_instance_helper list-instances r_game
python -m gms_helpers.room_instance_helper list-instances r_game --layer "lyr_player"
```

- **modify-instance** - Modify properties of an instance
```bash
python -m gms_helpers.room_instance_helper modify-instance r_game inst_12345678 --x 150 --y 250 --rotation 45
```

- **set-creation-code** - Set creation code for an instance
```bash
python -m gms_helpers.room_instance_helper set-creation-code r_game inst_12345678 --code "hp = 100; damage = 25;"
```

### Instance Options
- `--x, --y` - Position coordinates
- `--scale-x, --scale-y` - Scale factors
- `--rotation` - Rotation in degrees
- `--creation-code` - Custom GML code for initialization

### Features
- **Layer validation**: Ensures target layer exists and is an instance layer
- **Automatic UUID generation**: Creates unique instance names automatically
- **Creation code support**: Add custom GML code that runs when instance is created

---

## Room Operations Helper (`room_helper.py`)

Manage room assets using standard operations aligned with other asset types.

### Usage
```bash
python -m gms_helpers.room_helper [command] [arguments]
```

### Commands

- **duplicate** - Duplicate an existing room with a new name
```bash
python -m gms_helpers.room_helper duplicate r_level_01 r_level_02
python -m gms_helpers.room_helper duplicate r_base_room r_custom_room
```

- **rename** - Rename an existing room
```bash
python -m gms_helpers.room_helper rename r_old_name r_new_name
python -m gms_helpers.room_helper rename r_temp r_level_final
```

- **delete** - Delete a room from the project
```bash
python -m gms_helpers.room_helper delete r_unused_room
python -m gms_helpers.room_helper delete r_test_room --dry-run
```

- **list** - List all rooms in the project
```bash
python -m gms_helpers.room_helper list
python -m gms_helpers.room_helper list --verbose
```

### Features
- **Standard workflow**: Uses the same duplicate/rename/delete operations as other asset types
- **Automatic UUID handling**: Properly regenerates instance UUIDs when duplicating rooms
- **Project integration**: Automatically updates `.yyp` file with all operations
- **Layer preservation**: Complete room structure including layers, instances, and settings is maintained
- **Safety features**: Dry-run mode for deletions, validation for all operations

### Room Operations
Room operations now follow the standard asset workflow pattern:
- **Duplication** preserves all room content while generating new instance UUIDs
- **Renaming** updates all references and file paths correctly
- **Deletion** removes room files and `.yyp` entries safely
- **Listing** provides overview of all rooms with size and layer information

---

## Comprehensive Documentation

For detailed usage examples, workflows, and best practices, see:
- **[Room Management Tools & Duplicate Resource Handling](ROOM_MANAGEMENT_TOOLS.md)** - Complete guide to the new room management system
- **[Folder Path System Guide](FOLDER_PATH_SYSTEM.md)** - Complete understanding of GameMaker folder paths (CRITICAL)

---

More helper tools will be documented here as they are added.

## Troubleshooting

### JSON Parsing Errors

**Issue**: GameMaker fails to load project with "Field 'builtinName': expected" errors in sprite files.

**Cause**: CLI-generated sprite files had malformed JSON with extra `"%Name": "frames"` field in tracks array.

**Fix**: Updated sprite creation template in `assets.py` to remove the extra field.

**Prevention**:
- New test: `test_sprite_creation_json_format()` validates sprite JSON structure
- Always run `gms maintenance auto` after asset creation to validate JSON

### Incomplete Asset Renaming

**Issue**: Asset rename leaves stale internal references (e.g., sprite keyframe paths still reference old .yy filenames).

**Cause**: Reference scanner missed internal .yy filename references within sprite JSON files.

**Symptoms**:
- GameMaker error: "Failed to load file 'path/old_name.yy'"
- Sprite sequence references point to non-existent files

**Fix**: Enhanced reference scanner to catch `.yy` filename references in addition to directory paths.

**Prevention**:
- Use `gms workflow rename` instead of manual renaming
- New test: `test_comprehensive_sprite_rename_catches_yy_filename_refs()` validates complete reference updates
- Always run comprehensive reference scanning with `--verbose` flag to see what references are found

### Missing Layer Image Files

**Issue**: GameMaker fails to load project with "File missing for GMSprite" errors for layer image files.

**Example Error**:
```
File missing for GMSprite spr_tabBtn_social_friends:
sprites\spr_tabBtn_social_friends\layers\884cb8470e2540609bfad170b5ba9028\ce98f980108641b3a381ae8fd0c57ceb.png
```

**Cause**: CLI sprite creation used incorrect layer directory structure:
- **Created**: `layers/[layer_uuid]/[frame_uuid].png` (wrong)
- **Expected**: `layers/[frame_uuid]/[layer_uuid].png` (correct)

**Fix**: Updated sprite creation in `assets.py` to use correct directory structure.

**Manual Fix** (if needed):
```bash
# Navigate to sprite directory
cd sprites/spr_sprite_name/layers

# Move files to correct structure
mkdir [frame_uuid]
move [layer_uuid]/[frame_uuid].png [frame_uuid]/[layer_uuid].png
rmdir [layer_uuid]
```

**Prevention**:
- New test: `test_sprite_creation_layer_directory_structure()` validates correct directory structure
- CLI now creates proper `layers/[frame_uuid]/[layer_uuid].png` structure

### Best Practices

1. **Always use CLI for asset operations** - Avoid manual JSON editing
2. **Run maintenance after changes** - `gms maintenance auto --verbose`
3. **Test project loading** - Open project in GameMaker after CLI operations
4. **Use comprehensive workflows** - `gms workflow rename` vs manual rename commands
