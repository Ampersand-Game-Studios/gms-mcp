# GM Room Layout Engine

## Overview
Simplifies room automation by providing grid-based and relative placement tools, abstracting away the complex `GMRoom` JSON structure.

## Goals
- Place instances in a grid (`o_floor` from x=0 to 1024).
- Relative placement ("Place `o_player` 32px above `o_spawn`").
- Bulk layer operations.

## Proposed MCP Tool
`gm_room_layout_engine(room_name: str, operation: str, params: dict)`

## Potential Implementation
1. Create a helper that parses and rebuilds the `layers` and `instances` arrays in room `.yy` files.
2. Implement coordinate calculation logic.
3. Validate that objects exist before placement.
