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
