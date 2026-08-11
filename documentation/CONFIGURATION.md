# GMS-MCP Configuration Guide

GMS-MCP supports per-project configuration for naming conventions and linting rules. This allows different GameMaker projects to have different standards without conflicts.

## Configuration File

Configuration is stored in `.gms-mcp.json` at the root of your GameMaker project (same directory as the `.yyp` file).

### Creating Configuration

When you run `gms-mcp-init`, you'll be prompted to create a configuration file:

```bash
# Interactive setup (will prompt for config creation)
gms-mcp-init

# Non-interactive with defaults
gms-mcp-init --non-interactive --use-defaults

# Skip config file creation
gms-mcp-init --skip-config
```

You can also create the config file manually or by copying the example below.

## Configuration Options

### Full Example

```json
{
  "$schema": "gms-mcp-config-v1",
  "naming": {
    "enabled": true,
    "rules": {
      "object": {
        "prefix": "o_",
        "pattern": "^o_[a-z0-9_]*$",
        "description": "Objects should start with o_ prefix"
      },
      "sprite": {
        "prefix": "spr_",
        "pattern": "^spr_[a-z0-9_]*$",
        "description": "Sprites should start with spr_ prefix"
      },
      "script": {
        "prefix": "",
        "pattern": "^[a-z][a-z0-9_]*$",
        "allow_pascal_constructors": true,
        "description": "Scripts should be snake_case (constructors can be PascalCase)"
      },
      "room": {
        "prefix": "r_",
        "pattern": "^r_[a-z0-9_]*$",
        "description": "Rooms should start with r_ prefix"
      },
      "font": {
        "prefix": "fnt_",
        "pattern": "^fnt_[a-z0-9_]*$",
        "description": "Fonts should start with fnt_ prefix"
      },
      "shader": {
        "prefix": ["sh_", "shader_"],
        "pattern": "^(sh_|shader_)[a-z0-9_]*$",
        "description": "Shaders should start with sh_ or shader_ prefix"
      },
      "sound": {
        "prefix": ["snd_", "sfx_"],
        "pattern": "^(snd_|sfx_)[a-z0-9_]*$",
        "description": "Sounds should start with snd_ or sfx_ prefix"
      },
      "animcurve": {
        "prefix": ["curve_", "ac_"],
        "pattern": "^(curve_|ac_)[a-z0-9_]*$",
        "description": "Animation curves should start with curve_ or ac_ prefix"
      },
      "path": {
        "prefix": ["pth_", "path_"],
        "pattern": "^(pth_|path_)[a-z0-9_]*$",
        "description": "Paths should start with pth_ or path_ prefix"
      },
      "tileset": {
        "prefix": ["ts_", "tile_"],
        "pattern": "^(ts_|tile_)[a-z0-9_]*$",
        "description": "Tilesets should start with ts_ or tile_ prefix"
      },
      "timeline": {
        "prefix": ["tl_", "timeline_"],
        "pattern": "^(tl_|timeline_)[a-z0-9_]*$",
        "description": "Timelines should start with tl_ or timeline_ prefix"
      },
      "sequence": {
        "prefix": ["seq_", "sequence_"],
        "pattern": "^(seq_|sequence_)[a-z0-9_]*$",
        "description": "Sequences should start with seq_ or sequence_ prefix"
      },
      "note": {
        "prefix": "",
        "pattern": "^[a-zA-Z0-9_\\- ]+$",
        "description": "Notes can contain letters, numbers, underscores, hyphens, and spaces"
      }
    }
  },
  "linting": {
    "block_on_critical_errors": true,
    "require_inherited_event": true
  }
}
```

### Naming Rules

Each asset type can have its own naming rule with:

| Property | Type | Description |
|----------|------|-------------|
| `prefix` | string or string[] | Required prefix(es) for this asset type |
| `pattern` | string | Regex pattern for full name validation |
| `description` | string | Human-readable description for error messages |
| `allow_pascal_constructors` | boolean | (scripts only) Allow PascalCase for constructor scripts |

#### Multiple Prefixes

You can allow multiple prefixes by using an array:

```json
{
  "naming": {
    "rules": {
      "sound": {
        "prefix": ["snd_", "sfx_", "mus_"],
        "pattern": "^(snd_|sfx_|mus_)[a-z0-9_]*$"
      }
    }
  }
}
```

### Disabling Naming Validation

To disable all naming validation:

```json
{
  "naming": {
    "enabled": false
  }
}
```

### Partial Configuration

You only need to include the rules you want to override. Missing rules will use factory defaults:

```json
{
  "naming": {
    "rules": {
      "object": {
        "prefix": "obj_",
        "pattern": "^obj_[a-z0-9_]*$"
      }
    }
  }
}
```

This only changes object naming - sprites, scripts, etc. will still use default prefixes.

## Configuration Resolution Order

Configuration is loaded in this order, with later sources overriding earlier ones:

1. **Factory Defaults** - Built into gms-mcp
2. **Global Config** - `~/.gms-mcp/config.json` (user-wide defaults)
3. **Project Config** - `.gms-mcp.json` in project root (takes precedence)

This allows you to:
- Set organization-wide defaults in the global config
- Override specific rules per-project

## Common Customizations

### Using Uppercase Prefixes

```json
{
  "naming": {
    "rules": {
      "object": {
        "prefix": "OBJ_",
        "pattern": "^OBJ_[A-Z0-9_]*$",
        "description": "Objects should use OBJ_ prefix with UPPERCASE"
      }
    }
  }
}
```

### Allowing No Prefix

```json
{
  "naming": {
    "rules": {
      "object": {
        "prefix": "",
        "pattern": "^[a-zA-Z][a-zA-Z0-9_]*$",
        "description": "Objects can use any valid identifier"
      }
    }
  }
}
```

### Project-Specific Migration

If you're adopting naming conventions on an existing project, you can initially disable validation:

```json
{
  "naming": {
    "enabled": false
  }
}
```

Then gradually enable it and fix violations as you refactor assets.

## Validation

The linter uses your configuration when checking naming conventions:

```bash
gms maintenance lint
```

Invalid names will be reported as warnings with the configured description message.

## Global Configuration

You can set user-wide defaults by creating `~/.gms-mcp/config.json`:

```json
{
  "naming": {
    "rules": {
      "object": {
        "prefix": "obj_",
        "pattern": "^obj_[a-z0-9_]*$"
      }
    }
  }
}
```

This applies to all projects that don't have their own `.gms-mcp.json` override.

## MCP Server Runtime

The generated client configurations use the default `stdio` transport. This is the recommended mode for Cursor, Codex, Claude Code, VS Code, and other desktop MCP clients because the client starts and owns one server process for the selected project.

```bash
gms-mcp server
```

The explicit equivalent is:

```bash
gms-mcp server --transport stdio
```

### Local Streamable HTTP

Use Streamable HTTP only when a local MCP client needs to connect to an already-running server:

```bash
gms-mcp server \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000 \
  --path /mcp
```

| Option | Default | Constraint |
|---|---|---|
| `--transport` | `stdio` | `stdio` or `streamable-http` |
| `--host` | `127.0.0.1` | HTTP accepts only `localhost` or a loopback IP address |
| `--port` | `8000` | Integer from 1 through 65535 |
| `--path` | `/mcp` | Absolute URL path with no whitespace |

Streamable HTTP is stateless and local-only. It has no remote-user authentication and must not be exposed through `0.0.0.0`, a LAN address, a public interface, or a reverse proxy. The server enables DNS-rebinding protection and accepts only the configured loopback Host and Origin values. `Mcp-Param-*` routing headers are validated by the MCP SDK.

The HTTP endpoint for the example above is `http://127.0.0.1:8000/mcp`. Starting the server does not update client configuration automatically; configure that URL only in clients that support Streamable HTTP.

### Project and Tool Profile

Transport selection does not change project access. Pin each server process to one GameMaker project with `GM_PROJECT_ROOT`, and select optional tool domains with `GMS_MCP_TOOLSETS`:

```bash
GM_PROJECT_ROOT=/absolute/path/to/project \
GMS_MCP_TOOLSETS=all \
gms-mcp server
```

Use `GMS_MCP_TOOLSETS=assets,events,rooms` for selected optional domains. The default curated core profile remains active when the variable is omitted. `gm_capabilities` reports the effective profile and available domains.

### MCP SDK v2 Capability Negotiation

The server supports the modern MCP `2026-07-28` protocol and the legacy `2025-11-25` mode. The base tool surface remains available in both modes. Modern clients can additionally negotiate cache hints, structured tool errors, resource subscriptions, RFC6570 resource templates, MCP Apps metadata, and Resolve/input-required workflows.

Unsupported optional features degrade to their documented base result where possible. For example, `gm_project_dashboard` still returns text and structured data without MCP Apps rendering. Resolve-dependent exceptional mutations cannot silently bypass a missing input capability; they remain cancelled or unresolved rather than forcing a write.

## Prefabs Support

Projects that use GameMaker prefabs (indicated by `ForcedPrefabProjectReferences` in the `.yyp` file) require the prefabs library path to be specified when running or compiling via Igor.

### Automatic Detection

GMS-MCP automatically detects the prefabs library location:

- **Windows**: `C:/ProgramData/GameMakerStudio2/Prefabs`
- **macOS**: `/Users/Shared/GameMakerStudio2/Prefabs`, `/Library/Application Support/GameMakerStudio2/Prefabs`, or `~/Library/Application Support/GameMakerStudio2/Prefabs`
- **Linux**: `~/.config/GameMakerStudio2/Prefabs` or `/opt/GameMakerStudio2/Prefabs`

### Custom Prefabs Path

If your prefabs are stored in a custom location, set the `GMS_PREFABS_PATH` environment variable:

```bash
# Windows (PowerShell)
$env:GMS_PREFABS_PATH = "D:\GameMaker\Prefabs"

# Windows (Command Prompt)
set GMS_PREFABS_PATH=D:\GameMaker\Prefabs

# macOS/Linux
export GMS_PREFABS_PATH="/custom/path/to/Prefabs"
```

### How It Works

When running or compiling a project, GMS-MCP will:

1. Check if `GMS_PREFABS_PATH` environment variable is set and the path exists
2. If not, check the default platform-specific locations
3. If a valid prefabs path is found, add the `--pf` flag to Igor commands

This ensures projects with prefab dependencies compile and run correctly via MCP.
