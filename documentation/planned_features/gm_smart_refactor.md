# GM Smart Refactor

## Overview
An atomic "Search-and-Replace" rename tool that goes beyond just renaming a file. It ensures the entire project remains consistent after a rename.

## Goals
- Rename an asset and update all GML code references.
- Update all `.yy` file pointers (e.g., `spriteId` in objects).
- Update resource order and project file entries.
- Provide "Dry Run" with a diff summary of affected files.

## Proposed MCP Tool
`gm_smart_refactor(asset_type: str, old_name: str, new_name: str)`

## Potential Implementation
1. Leverage and expand the existing `reference_scanner.py`.
2. Implement a multi-file "transaction" logic.
3. Record changes so a "Rollback" can be performed if one step fails.
