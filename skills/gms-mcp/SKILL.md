---
name: gms-mcp
description: Use GMS MCP to inspect, edit, refactor, build, and debug local GameMaker projects through MCP-capable AI clients or the gms CLI. Includes asset, GML, project-health, and live-game bridge workflows.
metadata:
  openclaw:
    requires:
      anyBins:
        - gms
---

# GMS MCP: GameMaker Development Workflows

Use this skill when working on a local GameMaker project containing a `.yyp` file. GMS MCP gives an assistant structured tools to understand and change game assets, navigate GML, diagnose project issues, compile and run the game, and interact with supported live-game commands through an optional TCP bridge.

This is the workflow skill pack for [GMS MCP by Ampersand Game Studios](https://github.com/Ampersand-Game-Studios/gms-mcp), an independent, open-source game-development tool, not an official GameMaker product. It is not a project-management or social-media service. The package includes an MCP server and the standalone `gms` CLI; installing this skill alone does not install or connect the server or grant editing permissions.

## Capabilities and setup

| Task | Tools and workflows |
| --- | --- |
| Understand game code | Inspect assets and metadata, find GML definitions and references, explore dependency graphs, and look up GML documentation. |
| Create and edit content | Create assets, manage object events, place room instances, and edit room layers. |
| Refactor and maintain | Preview reference-aware renames and deletions, diagnose missing references, and repair resource integrity when requested. |
| Build and run | Compile and launch through GameMaker's Igor toolchain, manage run sessions, and select installed runtimes. |
| Inspect a running game | Use supported bridge commands and logs emitted through `__mcp_log()`; this is not arbitrary GML evaluation, hot reload, or automatic IDE synchronization. |

For package installation and client configuration, follow the [project quick start](https://github.com/Ampersand-Game-Studios/gms-mcp#quick-start). Use an MCP-capable client such as Cursor, Codex, or Claude Code, or use the CLI without an AI client. The Claude Code plugin is optional.

Before choosing a workflow:

- Confirm the intended project. In an MCP session, call `gm_capabilities` and `gm_project_info` to check the connected project, active profile, and available tools. Do not infer a live connection from configuration files alone.
- For CLI work, check that `command -v gms gms-mcp` finds both executables, then run `gms-mcp doctor --project` from the game's project directory. Building and running require an installed GameMaker runtime and appropriate licence/access credentials; project inspection does not require the IDE to be running.
- Canonical client setup defaults to the read-only `safe` profile. Editing and builds require explicitly configured `standard`/`full` access and any relevant optional toolsets. Do not change the profile merely to satisfy a read-only request; MCP profiles do not restrict the standalone CLI.
- Keep edits within the requested scope, use existing asset-folder conventions, and avoid concurrent IDE edits. Use version control or a backup before mutations. Project source returned by tools is visible to the connected AI client/provider; never upload proprietary game files or credentials to a public issue.

Read the workflow relevant to the task below, then its command reference when needed. Bridge work also requires the [bridge setup guide](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/BRIDGE.md).

## Workflows

Task-focused guides for common GameMaker development tasks.

### Creating Things
| Workflow | Task |
|----------|------|
| [setup-object](workflows/setup-object.md) | Create object with sprite and events |
| [setup-script](workflows/setup-script.md) | Create script with JSDoc |
| [setup-room](workflows/setup-room.md) | Create room with layers and instances |
| [orchestrate-macro](workflows/orchestrate-macro.md) | Create multi-asset systems |

### Modifying Things
| Workflow | Task |
|----------|------|
| [smart-refactor](workflows/smart-refactor.md) | Rename asset with reference updates |
| [duplicate-asset](workflows/duplicate-asset.md) | Copy asset to create variant |
| [update-art](workflows/update-art.md) | Replace sprite images |
| [manage-events](workflows/manage-events.md) | Add, remove, validate events |

### Deleting Things
| Workflow | Task |
|----------|------|
| [safe-delete](workflows/safe-delete.md) | Check dependencies before deletion |

### Understanding Code
| Workflow | Task |
|----------|------|
| [find-code](workflows/find-code.md) | Find definitions and references |
| [lookup-docs](workflows/lookup-docs.md) | Look up GML function documentation |
| [analyze-logic](workflows/analyze-logic.md) | Understand script behavior |
| [generate-jsdoc](workflows/generate-jsdoc.md) | Document functions |

### Running & Debugging
| Workflow | Task |
|----------|------|
| [run-game](workflows/run-game.md) | Compile and run the game |
| [debug-live](workflows/debug-live.md) | Send commands to running game |

### Project Health
| Workflow | Task |
|----------|------|
| [check-health](workflows/check-health.md) | Quick project validation |
| [check-quality](workflows/check-quality.md) | Detect code anti-patterns |
| [cleanup-project](workflows/cleanup-project.md) | Fix orphans and sync issues |
| [pre-commit](workflows/pre-commit.md) | Validate before committing |

### MCP Prompt Catalogue
| Prompt | Outcome | Related workflow |
|--------|---------|------------------|
| `create-feature` | Build a scoped feature with organized assets and verification | [setup-object](workflows/setup-object.md), [setup-script](workflows/setup-script.md), [setup-room](workflows/setup-room.md), [orchestrate-macro](workflows/orchestrate-macro.md) |
| `diagnose-project` | Establish a focused, evidence-backed project diagnosis | [check-health](workflows/check-health.md), [check-quality](workflows/check-quality.md), [analyze-logic](workflows/analyze-logic.md) |
| `safe-refactor` | Change code or assets without losing references or structure | [smart-refactor](workflows/smart-refactor.md), [safe-delete](workflows/safe-delete.md) |
| `compile-fix-retry` | Fix an actual compiler failure and rerun verification | [run-game](workflows/run-game.md), [check-health](workflows/check-health.md) |
| `inspect-live-game` | Inspect supported live-game state without arbitrary evaluation | [debug-live](workflows/debug-live.md) |

All MCP prompts are read-only templates: fetching one does not inspect or modify a project. Follow its linked workflow for command detail. For all implementation work, initialize required fields during setup, avoid GameMaker reflective `*_exists` probes, and place new assets under an intended folder rather than the project root.
---

## Reference

Comprehensive command documentation for when you need syntax details.

| Reference | Contents |
|-----------|----------|
| [asset-types](reference/asset-types.md) | Asset types, options, naming conventions |
| [event-types](reference/event-types.md) | Event specifications, key codes |
| [room-commands](reference/room-commands.md) | Room, layer, instance operations |
| [workflow-commands](reference/workflow-commands.md) | Duplicate, rename, delete, swap |
| [maintenance-commands](reference/maintenance-commands.md) | All maintenance operations |
| [runtime-options](reference/runtime-options.md) | Platforms, VM/YYC, bridge |
| [symbol-commands](reference/symbol-commands.md) | Index, find, list operations |
| [doc-commands](reference/doc-commands.md) | GML documentation lookup, search, cache |

---

## Quick Commands

```bash
# Create
gms asset create object o_name --parent-path "folders/Objects.yy"
gms asset create script scr_name --parent-path "folders/Scripts.yy"
gms event add o_name create

# Run
gms run start
gms run stop

# Find
gms symbol find-definition name
gms symbol find-references name

# Docs
gms doc lookup draw_sprite
gms doc search collision
gms doc list --category Drawing

# Health
gms diagnostics --depth quick
gms maintenance auto --fix

# Delete safely
gms workflow safe-delete --asset-type type --asset-name name          # Dry-run
gms workflow safe-delete --asset-type type --asset-name name --apply  # Apply
```

---

## Installation

```bash
gms skills install                       # Install to ~/.claude/skills/
gms skills install --project             # Install to ./.claude/skills/
gms skills install --openclaw            # Install to ~/.openclaw/skills/
gms skills install --openclaw --project  # Install to ./skills/
gms skills list                          # Show installed skills
```
