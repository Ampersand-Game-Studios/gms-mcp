# GM Generate JSDoc

## Status
**Planned** | Claude Code Skill: Available

## Overview
Automatically generates IDE-compliant documentation headers (`@param`, `@returns`, `@description`) for GML scripts.

## Claude Code Skill
A workflow skill (`generate-jsdoc.md`) is available via `gms skills install`. This skill provides:
- JSDoc format reference for GameMaker
- GML type reference table (Real, String, Bool, Id.Instance, Asset.*, etc.)
- Before/after examples
- Best practices for documentation

The skill guides agents to manually write JSDoc. The MCP tool would auto-generate it.

## Goals
- Scan script body for argument usage (`argument0`, `var _val = argument[0]`, or named parameters).
- Detect return types from return statements.
- Format results as a standard GameMaker JSDoc comment block.

## Proposed MCP Tool
`gm_generate_jsdoc(script_name: str, apply: bool = False)`

**Parameters:**
- `script_name`: Script or function to document
- `apply`: If True, write the JSDoc to the file. If False, return the generated JSDoc.

## Potential Implementation
1. Read the `.gml` file content.
2. Parse function signature to extract parameter names.
3. Analyze function body for:
   - Parameter type hints from usage patterns
   - Return statements and their types
   - Side effects (global modifications, instance creation)
4. Generate JSDoc block with detected information.
5. If `apply=True`, prepend to file. Otherwise, return for review.
