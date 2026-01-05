# GM Safe Delete

## Overview
A tool that prevents project corruption or logical breakages by checking dependencies before deleting an asset.

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
