---
name: runtime-options
description: Complete runtime and compilation options reference
---

# Runtime Options Reference

## Run Commands

### Start Game
```bash
gms run start [options]
```

### Stop Game
```bash
gms run stop
```

### Check Status
```bash
gms run status
```

### Compile Only
```bash
gms run compile [options]
```

## Platform Options

```bash
--platform <PLATFORM>
```

| Platform | Description |
|----------|-------------|
| `Windows` | Windows desktop (default) |
| `HTML5` | Web browser |
| `macOS` | macOS desktop |
| `Linux` | Linux desktop |
| `Android` | Android mobile |
| `iOS` | iOS mobile |

## Runtime Types

```bash
--runtime <TYPE>
```

| Type | Description |
|------|-------------|
| `VM` / `GMS2 VM` | GMS2 virtual machine (default) - faster compile, slower runtime |
| `YYC` / `GMS2 YYC` | GMS2 YoYo Compiler - slower compile, faster runtime |
| `GMRT` / `GMRT VM` | Recognized but not supported by the current Igor CLI path |

**When to use:**
- `VM` - Development and iteration (faster builds)
- `YYC` - Performance testing and release (faster execution)
- `GMRT` - Use the GameMaker IDE until YoYo publishes command-line syntax for GMRT targets

## Runtime Version

```bash
--runtime-version <VERSION>
```

Specify exact runtime version:
```bash
gms run start --runtime-version 2024.1100.0.625
```

## Output Location

```bash
--output-location <LOCATION>
```

| Location | Description |
|----------|-------------|
| `temp` | IDE-style, in AppData (default) |
| `project` | Classic, in project folder |

## Background Mode

```bash
--background
```

Run without capturing output. Useful for long sessions.

## Examples

### Development Build
```bash
gms run start --runtime VM
```

### Performance Test
```bash
gms run start --runtime YYC
```

### HTML5 Build
```bash
gms run start --platform HTML5
```

### Specific Runtime
```bash
gms run start --runtime-version 2024.1100.0.625
```

### Compile Only
```bash
gms run compile --platform Windows --runtime VM
```

### Full Options
```bash
gms run start --platform Windows --runtime VM --output-location temp
```

## Bridge Tools

Bridge operations are exposed through MCP tools in the current package, not plain `gms` CLI subcommands:

- `gm_bridge_install`
- `gm_bridge_status`
- `gm_run_command`
- `gm_run_logs`
