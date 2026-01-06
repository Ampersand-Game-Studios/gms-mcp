# GM Analyze Logic

## Overview
Provides a high-level summary of a script's behavior to reduce the token cost of an agent reading hundreds of lines of code.

## Goals
- Identify the "Intent" of a script (e.g., "Physics Controller", "UI Handler").
- List key variables being read or modified.
- Identify external asset dependencies (which sprites/sounds are referenced).

## Proposed MCP Tool
`gm_analyze_logic(script_name: str)`

## Potential Implementation
1. Use regex or a lightweight GML parser to extract symbols.
2. Summarize function calls (e.g., "Uses `move_and_collide` and `audio_play_sound`").
3. Return a concise text/JSON summary.
