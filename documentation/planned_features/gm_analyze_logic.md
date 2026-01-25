# GM Analyze Logic

## Status
**Planned** | Claude Code Skill: Available

## Overview
Provides a high-level summary of a script's behavior to reduce the token cost of an agent reading hundreds of lines of code.

## Current Implementation
The symbol index tools provide foundational support:
- `gms symbol find-definition` - Locate asset files
- `gms symbol list --file-filter` - List symbols in a file
- `gms symbol find-references` - Find what depends on an asset

## Claude Code Skill
A workflow skill (`analyze-logic.md`) is available via `gms skills install`. This skill guides agents through:
- Using symbol tools to understand code structure
- Creating manual summaries (purpose, inputs, outputs, side effects)
- Documenting dependencies and call chains

The skill provides a methodology but requires the agent to read and analyze the code. The MCP tool would automate the analysis.

## Goals
- Identify the "Intent" of a script (e.g., "Physics Controller", "UI Handler").
- List key variables being read or modified.
- Identify external asset dependencies (which sprites/sounds are referenced).

## Proposed MCP Tool
`gm_analyze_logic(script_name: str, depth: str = "summary")`

## Potential Implementation
1. Use regex or a lightweight GML parser to extract symbols.
2. Categorize function calls by type (physics, audio, drawing, etc.).
3. Detect instance variables being read/written.
4. Return a concise JSON summary with:
   - Detected purpose/category
   - Input parameters
   - Return type (if detected)
   - Variables modified
   - Asset dependencies (sprites, sounds, objects referenced)
   - Functions called
