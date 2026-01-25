# GM Safe Delete

## Status
**Planned** | Claude Code Skill: Available

## Overview
A tool that prevents project corruption or logical breakages by checking dependencies before deleting an asset.

## Claude Code Skill
A workflow skill (`safe-delete.md`) is available via `gms skills install`. This skill guides agents through the manual process using existing tools:
- `gms symbol find-references` to check dependencies
- `gms asset delete` to perform deletion
- `gms maintenance auto` to verify integrity

The skill provides workflow guidance but requires multiple tool calls. The MCP tool below would automate this into a single operation.

## Goals
- Use the **Deep Asset Graph** to identify all dependencies of an asset.
- Warn the agent/user: "Cannot delete `o_player` because 12 scripts and 3 rooms depend on it."
- Offer "Force Delete" (with risk warning) or "Clean Delete" (removes broken references too).

## Proposed MCP Tool
`gm_safe_delete(asset_type: str, asset_name: str, force: bool = False)`

## Potential Implementation
1. Integrate with `introspection.py` to get the asset graph.
2. Filter the graph for incoming edges to the target asset.
3. Return a structured list of dependent assets.
4. If no dependencies (or force=True), call existing delete logic.
5. Return summary of deleted asset and any broken references cleaned.
