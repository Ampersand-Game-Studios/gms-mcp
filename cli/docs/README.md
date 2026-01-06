# GameMaker Studio CLI Helper Tools Documentation

## 📚 Documentation Index

Welcome to the comprehensive documentation for the GameMaker Studio CLI helper tools. These Python-based tools enhance your GameMaker development workflow with powerful command-line utilities.

## 🚀 Quick Start

From the repo root, set `PYTHONPATH=src` so module invocations resolve:

```powershell
$Env:PYTHONPATH = "$PWD\src"
```


```bash
# Create a new script
python -m gms_helpers.asset_helper script player_move --parent-path "folders/Player/Scripts.yy"

# Create a new shader (Phase 2)
python -m gms_helpers.asset_helper shader sh_blur --parent-path "folders/Shaders.yy"

# Manage room layers (Phase 1)
python -m gms_helpers.room_layer_helper add-layer r_game "lyr_enemies" --type instance --depth 100
```

## MCP integration (Cursor example)

This repo includes an **MCP server** (`gms-mcp`) that exposes GameMaker operations as tools (asset creation, maintenance, compile/run).

- Cursor (workspace): `gms-mcp-init --cursor` (writes `.cursor/mcp.json`)
- Cursor (global, multi-project): `gms-mcp-init --cursor-global` (writes `~/.cursor/mcp.json`)
- Other clients (examples): `gms-mcp-init --vscode --windsurf --antigravity` (writes `mcp-configs/*.mcp.json`)

## 📖 Core Documentation

### Setup & Overview
- **[Systems Overview](SYSTEMS_OVERVIEW.md)** - High-level architecture overview
- **[Console Commands](CONSOLE_COMMANDS.md)** - In-game console system reference
- **[Folder Path System](FOLDER_PATH_SYSTEM.md)** - Complete guide to GameMaker folder paths (IMPORTANT)

### CLI Helper Tools
- **[CLI Helper Tools](CLI_HELPER_TOOLS.md)** - Complete reference for all CLI commands
- **[Event Helper](CLI_HELPER_TOOLS.md#object-event-helper-eventhelperpy)** - Manage object events
- **[Asset Helper](CLI_HELPER_TOOLS.md#asset-creation-helper-assethelperpy)** - Create all asset types
- **[Test Suite Guide](TEST_SUITE_GUIDE.md)** - How to run and understand the test suite

## 🎯 Implementation Phases

### ✅ Phase 3: Advanced Assets & Code Intelligence
**Status**: Complete

**Features Added**:
- Full GML Symbol Indexing (functions, enums, macros, globalvars)
- Definition jump and Reference tracing across the project
- Sound asset creation with automatic placeholder generation
- Tileset management with sprite linking
- Path creation (straight/smooth)
- Timeline support with moment stubs
- Sequence creation with naming enforcement
- Note asset management
- Maintenance automation fixes for Igor compiler compatibility

## 📊 Tool Coverage

### Currently Supported Asset Types (14 total)
| Asset Type | Command | Prefix | Phase |
|------------|---------|--------|-------|
| Scripts | `script` | `snake_case` (or `PascalCase` with `--constructor`) | Original |
| Objects | `object` | `o_` | Original |
| Sprites | `sprite` | `spr_` | Original |
| Rooms | `room` | `r_` | Original |
| Folders | `folder` | - | Original |
| Fonts | `font` | `fnt_` | Phase 2 |
| Shaders | `shader` | `sh_` or `shader_` | Phase 2 |
| Animation Curves | `animcurve` | `curve_` or `ac_` | Phase 2 |
| Sounds | `sound` | `snd_` | **Phase 3** |
| Tilesets | `tileset` | `ts_` | **Phase 3** |
| Paths | `path` | `pth_` | **Phase 3** |
| Timelines | `timeline` | `tl_` | **Phase 3** |
| Sequences | `sequence` | `seq_` | **Phase 3** |
| Notes | `note` | `note_` | **Phase 3** |

### Asset Management Commands
| Command | Purpose | Features |
|---------|---------|----------|
| `delete` | Remove assets safely | **NEW**: Supports all asset types, dry-run mode |

### Room Management Tools
| Tool | Purpose | Phase |
|------|---------|-------|
| `room_layer_helper.py` | Manage layers in rooms | Phase 1 |
| `room_instance_helper.py` | Manage object instances | Phase 1 |
| `room_helper.py` | Standard room operations (duplicate, rename, delete, list) | Phase 1 |

### Maintenance Commands
| Command | Purpose |
|---------|---------|
| **`auto_maintenance.py`** | **🔧 Comprehensive health check (9 steps)** |
| **`auto_maintenance.py --fix`** | **🔧 Fix all issues automatically** |
| `maint lint` | Check project for issues |
| `maint fix-commas` | Fix JSON trailing commas |
| `maint list-orphans` | Find orphaned assets |
| `maint prune-missing` | Remove missing references |
| `maint validate-paths` | Validate folder paths (.yyp-based) |
| `maint validate-paths --strict-disk-check` | Also check physical .yy files (legacy) |
| `maint dedupe-resources` | Remove duplicate resources |

## 💡 Understanding GameMaker Folder Paths

**IMPORTANT**: GameMaker folder paths (like `folders/Scripts.yy`) are **logical references** in the `.yyp` file, not physical directories on disk.

### Key Points:
- **Logical Folders**: Organize assets in GameMaker's asset browser
- **Physical Files**: Actual asset files (scripts, objects, etc.) on disk
- **Default Validation**: Tools check the `.yyp` Folders list (recommended)
- **Legacy Validation**: Use `--strict-disk-check` only if needed for physical file checking

## 💡 Common Workflows

### Creating a Complete UI System
```bash
# 1. Create folder structure
python -m gms_helpers.asset_helper folder "UI" --path "folders/UI.yy"
python -m gms_helpers.asset_helper folder "Fonts" --path "folders/UI/Fonts.yy"

# 2. Create fonts (Phase 2)
python -m gms_helpers.asset_helper font fnt_ui_title --parent-path "folders/UI/Fonts.yy" --size 32 --bold
python -m gms_helpers.asset_helper font fnt_ui_body --parent-path "folders/UI/Fonts.yy" --size 16

# 3. Create UI objects
python -m gms_helpers.asset_helper object o_button --parent-path "folders/UI.yy"
python -m gms_helpers.asset_helper object o_menu --parent-path "folders/UI.yy"
```

### Setting Up Visual Effects
```bash
# 1. Create shader effects (Phase 2)
python -m gms_helpers.asset_helper shader sh_blur --parent-path "folders/VFX.yy"
python -m gms_helpers.asset_helper shader sh_glow --parent-path "folders/VFX.yy"

# 2. Create animation curves for effects (Phase 2)
python -m gms_helpers.asset_helper animcurve curve_fade_in --parent-path "folders/VFX.yy" --curve-type ease_in
python -m gms_helpers.asset_helper animcurve curve_pulse --parent-path "folders/VFX.yy" --curve-type smooth
```

### Managing Game Rooms
```bash
# 1. Duplicate existing room (Phase 1)
python -m gms_helpers.room_helper duplicate r_base_level r_level_01

# 2. Add custom layers
python -m gms_helpers.room_layer_helper add-layer r_level_01 "lyr_hazards" --type instance --depth 3500

# 3. Place instances
python -m gms_helpers.room_instance_helper add-instance r_level_01 o_spike \
  --layer "lyr_hazards" --x 200 --y 400
```

## 🔧 Maintenance & Health

### Pre-flight Check
```bash
# Check for any issues before starting work
python -m gms_helpers.asset_helper maint lint
python -m gms_helpers.asset_helper maint dedupe-resources --dry-run
```

### Post-creation Cleanup
```bash
# After creating many assets, ensure project health
python -m gms_helpers.asset_helper maint fix-commas
python -m gms_helpers.asset_helper maint prune-missing
```

## 📋 Best Practices

1. **Always use the CLI tools** for asset creation when possible
2. **Follow naming conventions** - tools enforce them automatically
3. **Run maintenance regularly** - especially `dedupe-resources`
4. **Use base rooms for duplication** for consistent room structures
5. **Check help first** - Every tool has `--help` with examples

## 🆘 Troubleshooting

### Common Issues
- **"Resource already registered"** → Run `maint dedupe-resources`
- **"Cannot find folder path"** → Check folder exists in .yyp Folders list with `maint validate-paths`
- **"Folder path not found"** → **Tool exits immediately** - create folder first or use existing path
- **Font looks wrong** → Regenerate in GameMaker IDE after creation
- **Shader black screen** → Start with generated passthrough code

### Recent Changes
- **Stricter validation**: Tools now **immediately exit** when folder paths are invalid (prevents corrupted projects)
- **Delete command**: New `delete` sub-command for safe asset removal with dry-run support
- **Igor Compatibility**: Objects and events now use standardized schemas (`$GMObject: "v1"`, `resourceVersion: "2.0"`) to prevent build failures.

### Getting Help
1. Check command help: `python -m gms_helpers.<tool> --help`
2. Review relevant documentation section
3. Run maintenance commands to check project health
4. Examine the generated files for issues

## 🚀 Future Development

### Potential Phase 4+ Additions
- Sprite sheet / Texture group management
- Extension editing (JSON-based)
- Live GML reloading system

### Contributing
The modular architecture makes it easy to add new asset types:
1. Create asset class in `assets.py`
2. Add command handler in `asset_helper.py`
3. Update validation in `utils.py`
4. Document thoroughly

---

## 📞 Quick Reference Card

```bash
# Asset Creation
script <name> --parent-path <path>
object <name> --parent-path <path> [--sprite-id <sprite>] [--parent-object <parent>]
sprite <name> --parent-path <path>
room <name> --parent-path <path> [--width <w>] [--height <h>]
font <name> --parent-path <path> [--size <n>] [--bold] [--italic]
shader <name> --parent-path <path> [--shader-type <1-4>]
animcurve <name> --parent-path <path> [--curve-type <type>]
sound <name> --parent-path <path> [--volume <n>] [--pitch <n>]
tileset <name> --parent-path <path> --sprite-id <sprite>
path <name> --parent-path <path> [--path-type <type>]
timeline <name> --parent-path <path>
sequence <name> --parent-path <path>
note <name> --parent-path <path>

# Code Intelligence
python -m gms_helpers.gms symbol build
python -m gms_helpers.gms symbol find-definition <name>
python -m gms_helpers.gms symbol find-references <name>
python -m gms_helpers.gms symbol list [--kind <type>] [--name-filter <str>]

# Room Management
python -m gms_helpers.room_layer_helper add-layer <room> <layer> --type <type> --depth <n>
python -m gms_helpers.room_instance_helper add-instance <room> <object> --layer <layer> --x <x> --y <y>
python -m gms_helpers.room_helper duplicate <source_room> <new_room>
python -m gms_helpers.room_helper rename <old_room> <new_room>
python -m gms_helpers.room_helper delete <room> [--dry-run]
python -m gms_helpers.room_helper list [--verbose]

# Maintenance
python -m gms_helpers.asset_helper maint lint
python -m gms_helpers.asset_helper maint dedupe-resources [--auto]
python -m gms_helpers.asset_helper maint fix-commas
```

---

**Current Version**: Phase 3 Complete - 14 asset types supported with comprehensive room management, maintenance tools, and GML symbol intelligence.
