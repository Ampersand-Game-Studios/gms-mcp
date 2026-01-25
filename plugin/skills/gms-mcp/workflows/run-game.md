---
name: run-game
description: Compile and run GameMaker projects
---

## When to use

- Testing changes to a GameMaker project
- Compiling for different platforms
- Managing runtime versions
- Debugging with live game output

## Quick Start

```bash
# Run the game (compiles automatically)
gms run start

# Check if game is running
gms run status

# Stop the running game
gms run stop
```

## Compilation Options

### Platforms
```bash
gms run start --platform Windows    # Default
gms run start --platform HTML5
gms run start --platform macOS
gms run start --platform Linux
gms run start --platform Android
gms run start --platform iOS
```

### Runtime Types
```bash
gms run start --runtime VM     # Virtual Machine (default, faster compile)
gms run start --runtime YYC    # YoYo Compiler (slower compile, faster runtime)
```

### Specific Runtime Version
```bash
gms run start --runtime-version 2024.1100.0.625
```

### Output Location
```bash
gms run start --output-location temp      # IDE-style, in AppData (default)
gms run start --output-location project   # Classic, in project folder
```

### Background Mode
```bash
gms run start --background    # Don't capture output (for long sessions)
```

## Compile Only (No Run)

```bash
gms run compile --platform Windows --runtime VM
gms run compile --platform HTML5
```

## Workflow: Development Cycle

1. **Make changes** to code/assets

2. **Run quick diagnostics**
   ```bash
   gms diagnostics --depth quick
   ```

3. **Start the game**
   ```bash
   gms run start
   ```

4. **Test and observe** output in terminal

5. **Stop when done**
   ```bash
   gms run stop
   ```

6. **Iterate**

## Workflow: Testing on Multiple Platforms

```bash
# Test on Windows first
gms run start --platform Windows
# ... test ...
gms run stop

# Test HTML5 build
gms run start --platform HTML5
# ... test in browser ...
gms run stop
```

## Workflow: Performance Testing (YYC)

```bash
# Development: use VM for fast iteration
gms run start --runtime VM

# Performance testing: use YYC
gms run start --runtime YYC
```

## Checking Status

```bash
# Is game running?
gms run status

# Output example:
# Game is running (PID: 12345)
# or
# No game is currently running
```

## Tips

- VM compiles faster but runs slower - use for development
- YYC compiles slower but runs faster - use for testing/release
- Use `--output-location temp` (default) to avoid cluttering project folder
- Check `gms run status` before starting if unsure whether game is running
- The terminal shows game output (debug messages, errors) when not in background mode

## Common Issues

### "Runtime not found"
```bash
# Check environment setup
gms maintenance health

# Specify exact version if needed
gms run start --runtime-version 2024.1100.0.625
```

### Game won't stop
```bash
# Force stop
gms run stop

# If still running, check PID from status and kill manually
gms run status
```

### Compile errors
```bash
# Run diagnostics first
gms diagnostics --depth deep

# Fix any project issues
gms maintenance auto --fix
```

## Never Do

- Start a new game while one is already running (stop first)
- Use YYC for rapid iteration (too slow to compile)
- Ignore compile errors in output (fix them before continuing)
