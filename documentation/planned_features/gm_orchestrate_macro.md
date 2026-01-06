# GM Orchestrate Macro

## Overview
A tool to create "standard components" or multi-asset systems in a single call. This abstracts away the need for an agent to create multiple files and link them manually.

## Goals
- Create a set of related assets (Script + Object + Sprite) in one transaction.
- Automatically link assets (e.g., assign the newly created Sprite to the new Object).
- Support "Design Patterns" like Health Systems, State Machines, or UI Buttons.

## Proposed MCP Tool
`gm_orchestrate_macro(template_name: str, base_name: str, folder_path: str)`

## Potential Implementation
1. Create a `gms_helpers/templates/macros/` directory.
2. Define JSON blueprints for macros.
3. Use the existing `AssetHelper` to create each component.
4. Patch the `.yy` files to establish relationships (references).
