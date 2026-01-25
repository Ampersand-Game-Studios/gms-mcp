# GM Orchestrate Macro

## Status
**Planned** | Claude Code Skill: Available

## Overview
A tool to create "standard components" or multi-asset systems in a single call. This abstracts away the need for an agent to create multiple files and link them manually.

## Current Implementation
The building blocks exist:
- `gms asset create folder` - Create folder structure
- `gms asset create script/object/sprite` - Create individual assets
- `gms event add` - Add events to objects

## Claude Code Skill
A workflow skill (`orchestrate-macro.md`) is available via `gms skills install`. This skill provides:
- Step-by-step workflow for creating multi-asset systems
- Example: Dialog System (folder → scripts → manager object → UI object → events)
- Best practices (folder organization, naming conventions, singleton patterns)

The skill guides agents to manually create related assets in sequence. The MCP tool would create entire systems atomically from templates.

## Goals
- Create a set of related assets (Script + Object + Sprite) in one transaction.
- Automatically link assets (e.g., assign the newly created Sprite to the new Object).
- Support "Design Patterns" like Health Systems, State Machines, or UI Buttons.

## Proposed MCP Tool
`gm_orchestrate_macro(template_name: str, base_name: str, folder_path: str)`

**Template Examples:**
- `state_machine` - Creates state enum, base state script, manager object
- `ui_button` - Creates sprite, object with events, controller script
- `health_system` - Creates HP variables script, damage handlers, UI display

## Potential Implementation
1. Create a `gms_helpers/templates/macros/` directory.
2. Define JSON blueprints for macros specifying:
   - Assets to create (with naming patterns)
   - Default code templates for each asset
   - Relationships between assets (sprite → object, parent → child)
3. Use the existing `AssetHelper` to create each component.
4. Patch the `.yy` files to establish relationships (references).
5. Return summary of all created assets.
