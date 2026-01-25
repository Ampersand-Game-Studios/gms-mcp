# GM Smart Refactor

## Status
**Partially Implemented** | Claude Code Skill: Available

## Overview
An atomic "Search-and-Replace" rename tool that goes beyond just renaming a file. It ensures the entire project remains consistent after a rename.

## Current Implementation
The `gms workflow rename` CLI command already handles:
- Renaming the .yy file and directory
- Updating the asset's internal name field
- Updating the project .yyp file
- Updating GML references automatically

## Claude Code Skill
A workflow skill (`smart-refactor.md`) is available via `gms skills install`. This skill guides agents through:
- `gms symbol find-definition` to locate assets
- `gms symbol find-references` to preview affected files
- `gms workflow rename` to execute the rename
- `gms symbol build --force` to rebuild the index

## Goals (Remaining)
- ~~Rename an asset and update all GML code references.~~ ✓ Implemented
- ~~Update all `.yy` file pointers (e.g., `spriteId` in objects).~~ ✓ Implemented
- ~~Update resource order and project file entries.~~ ✓ Implemented
- Provide "Dry Run" with a diff summary of affected files.
- Add rollback capability if rename fails mid-operation.

## Proposed MCP Tool
`gm_smart_refactor(asset_type: str, old_name: str, new_name: str, dry_run: bool = False)`

## Potential Implementation
1. ~~Leverage and expand the existing `reference_scanner.py`.~~ ✓ Done
2. Implement a multi-file "transaction" logic with rollback.
3. Add dry-run mode that returns diff summary without applying changes.
