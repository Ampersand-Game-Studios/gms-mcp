# GameMaker Studio CLI Helper Tools Documentation

## 📚 Documentation Index

Welcome to the comprehensive documentation for the GameMaker Studio CLI helper tools. These Python-based tools enhance your GameMaker development workflow with powerful command-line utilities.

## 🚀 Quick Start

```bash
# Create a new script
python cli/gms_helpers/asset_helper.py script player_move --parent-path "folders/Player/Scripts.yy"

# Create a new shader (Phase 2)
python cli/gms_helpers/asset_helper.py shader sh_blur --parent-path "folders/Shaders.yy"

# Manage room layers (Phase 1)
python cli/gms_helpers/room_layer_helper.py add-layer r_game "lyr_enemies" --type instance --depth 100
```

## 🧩 Cursor MCP integration (recommended)

If you use Cursor, this repo also includes an **MCP server** that exposes GameMaker operations as tools (asset creation, maintenance, compile/run).

- Server: `gms-mcp` (installed command)
- Setup/notes: `README.md`
- Generate workspace config: `gms-mcp-init --cursor`
- After changing `~/.cursor/mcp.json`, **Reload Window** in Cursor

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

### ✅ Phase 1: Room Management & Duplicate Prevention
**Status**: Complete

**Features Added**:
- Duplicate resource prevention system
- Room layer management (`room_layer_helper.py`)
- Room instance management (`room_instance_helper.py`)
- Room operations system (`room_helper.py`) - duplicate, rename, delete, list

### ✅ Phase 2: Missing Asset Types
**Status**: Complete

**Features Added**:
- Font asset creation with customization options
- Shader asset creation with template code
- Animation curve creation with preset types

## 📊 Tool Coverage

### Currently Supported Asset Types (8 total)
| Asset Type | Command | Prefix | Phase |
|------------|---------|--------|-------|
| Scripts | `script` | `snake_case` (or `PascalCase` with `--constructor`) | Original |
| Objects | `object` | `o_` | Original |
| Sprites | `sprite` | `spr_` | Original |
| Rooms | `room` | `r_` | Original |
| Folders | `folder` | - | Original |
| Fonts | `font` | `fnt_` | **Phase 2** |
| Shaders | `shader` | `sh_` or `shader_` | **Phase 2** |
| Animation Curves | `animcurve` | `curve_` or `ac_` | **Phase 2** |

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
python cli/gms_helpers/asset_helper.py folder "UI" --path "folders/UI.yy"
python cli/gms_helpers/asset_helper.py folder "Fonts" --path "folders/UI/Fonts.yy"

# 2. Create fonts (Phase 2)
python cli/gms_helpers/asset_helper.py font fnt_ui_title --parent-path "folders/UI/Fonts.yy" --size 32 --bold
python cli/gms_helpers/asset_helper.py font fnt_ui_body --parent-path "folders/UI/Fonts.yy" --size 16

# 3. Create UI objects
python cli/gms_helpers/asset_helper.py object o_button --parent-path "folders/UI.yy"
python cli/gms_helpers/asset_helper.py object o_menu --parent-path "folders/UI.yy"
```

### Setting Up Visual Effects
```bash
# 1. Create shader effects (Phase 2)
python tooling/gms_helpers/asset_helper.py shader sh_blur --parent-path "folders/VFX.yy"
python tooling/gms_helpers/asset_helper.py shader sh_glow --parent-path "folders/VFX.yy"

# 2. Create animation curves for effects (Phase 2)
python tooling/gms_helpers/asset_helper.py animcurve curve_fade_in --parent-path "folders/VFX.yy" --curve-type ease_in
python tooling/gms_helpers/asset_helper.py animcurve curve_pulse --parent-path "folders/VFX.yy" --curve-type smooth
```

### Managing Game Rooms
```bash
# 1. Duplicate existing room (Phase 1)
python tooling/gms_helpers/room_helper.py duplicate r_base_level r_level_01

# 2. Add custom layers
python tooling/gms_helpers/room_layer_helper.py add-layer r_level_01 "lyr_hazards" --type instance --depth 3500

# 3. Place instances
python tooling/gms_helpers/room_instance_helper.py add-instance r_level_01 o_spike \
  --layer "lyr_hazards" --x 200 --y 400
```

## 🔧 Maintenance & Health

### Pre-flight Check
```bash
# Check for any issues before starting work
python tooling/gms_helpers/asset_helper.py maint lint
python tooling/gms_helpers/asset_helper.py maint dedupe-resources --dry-run
```

### Post-creation Cleanup
```bash
# After creating many assets, ensure project health
python tooling/gms_helpers/asset_helper.py maint fix-commas
python tooling/gms_helpers/asset_helper.py maint prune-missing
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

### Getting Help
1. Check command help: `python tooling/gms_helpers/<tool>.py --help`
2. Review relevant documentation section
3. Run maintenance commands to check project health
4. Examine the generated files for issues

## 🚀 Future Development

### Potential Phase 3+ Additions
- Sound assets (`GMSound`)
- Tileset management (`GMTileSet`)
- Path creation (`GMPath`)
- Timeline support (`GMTimeline`)
- Sequence editing (`GMSequence`)

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

# Room Management
room_layer_helper.py add-layer <room> <layer> --type <type> --depth <n>
room_instance_helper.py add-instance <room> <object> --layer <layer> --x <x> --y <y>
room_helper.py duplicate <source_room> <new_room>
room_helper.py rename <old_room> <new_room>
room_helper.py delete <room> [--dry-run]
room_helper.py list [--verbose]

# Maintenance
asset_helper.py maint lint
asset_helper.py maint dedupe-resources [--auto]
asset_helper.py maint fix-commas
```

---

**Current Version**: Phase 2 Complete - 8 asset types supported with comprehensive room management and maintenance tools.
