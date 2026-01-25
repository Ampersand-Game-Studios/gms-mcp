---
name: asset-types
description: Complete asset type reference with naming conventions
---

# Asset Types Reference

## Asset Creation Commands

All assets are created with:
```bash
gms asset create <type> <name> [options]
```

## Asset Types

| Type | Command | Prefix | Example |
|------|---------|--------|---------|
| Script | `script` | `scr_` | `scr_player_move` |
| Constructor | `script --constructor` | PascalCase | `Player` |
| Object | `object` | `o_` | `o_player` |
| Sprite | `sprite` | `spr_` | `spr_player_idle` |
| Room | `room` | `r_` | `r_level_01` |
| Folder | `folder` | Any | `Enemies` |
| Font | `font` | `fnt_` | `fnt_main` |
| Shader | `shader` | `sh_` | `sh_blur` |
| Sound | `sound` | `snd_` | `snd_jump` |
| Path | `path` | `pth_` | `pth_patrol` |
| Tileset | `tileset` | `ts_` | `ts_dungeon` |
| Timeline | `timeline` | `tl_` | `tl_cutscene` |
| Sequence | `sequence` | `seq_` | `seq_intro` |
| AnimCurve | `animcurve` | `ac_` | `ac_bounce` |
| Note | `note` | Any | `Design Notes` |

## Common Options

All asset types support:
```
--parent-path PATH       # Folder to create in (e.g., "folders/Scripts.yy")
--skip-maintenance       # Skip pre/post validation
--no-auto-fix           # Don't auto-fix issues
--maintenance-verbose   # Show verbose maintenance output
```

## Type-Specific Options

### Script
```bash
gms asset create script <name> [--constructor] [--parent-path PATH]
```
- `--constructor` - Create constructor (allows PascalCase)

### Object
```bash
gms asset create object <name> [--sprite-id ID] [--parent-object NAME] [--parent-path PATH]
```
- `--sprite-id` - Assign sprite to object
- `--parent-object` - Set parent for inheritance

### Room
```bash
gms asset create room <name> [--width INT] [--height INT] [--parent-path PATH]
```
- `--width` - Room width (default: 1024)
- `--height` - Room height (default: 768)

### Font
```bash
gms asset create font <name> [--font-name STR] [--size INT] [--bold] [--italic] [--aa-level 0-3] [--uses-sdf]
```
- `--font-name` - Font family (default: Arial)
- `--size` - Font size (default: 12)
- `--bold` / `--italic` - Style flags
- `--aa-level` - Anti-aliasing 0-3 (default: 1)
- `--uses-sdf` - SDF rendering (default: true)

### Shader
```bash
gms asset create shader <name> [--shader-type 1-4]
```
- Shader types: 1=GLSL ES, 2=GLSL, 3=HLSL 9, 4=HLSL 11

### Sound
```bash
gms asset create sound <name> [--volume FLOAT] [--pitch FLOAT] [--sound-type 0-2] [--bitrate INT] [--sample-rate INT] [--format 0-2]
```
- `--volume` - 0.0-1.0 (default: 1.0)
- `--sound-type` - 0=Normal, 1=Background, 2=3D
- `--format` - 0=OGG, 1=MP3, 2=WAV

### Path
```bash
gms asset create path <name> [--closed] [--precision INT] [--path-type straight|smooth|circle]
```

### Tileset
```bash
gms asset create tileset <name> [--sprite-id ID] [--tile-width INT] [--tile-height INT] [--tile-xsep INT] [--tile-ysep INT]
```

### Sequence
```bash
gms asset create sequence <name> [--length FLOAT] [--playback-speed FLOAT]
```
- `--length` - Length in frames (default: 60.0)
- `--playback-speed` - FPS (default: 30.0)

### AnimCurve
```bash
gms asset create animcurve <name> [--curve-type linear|smooth|ease_in|ease_out] [--channel-name STR]
```

### Folder
```bash
gms asset create folder <name> --path PATH
```
- `--path` - Required. Full folder path (e.g., "folders/Scripts/Utils.yy")

## Asset Deletion

```bash
gms asset delete <type> <name> [--dry-run]
```

Types: script, object, sprite, room, folder, font, shader, animcurve, sound, path, tileset, timeline, sequence, note
