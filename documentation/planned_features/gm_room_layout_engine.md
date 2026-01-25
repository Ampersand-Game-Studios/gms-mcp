# GM Room Layout Engine

## Status
**Partially Implemented** | Claude Code Skill: Available

## Overview
Simplifies room automation by providing grid-based and relative placement tools, abstracting away the complex `GMRoom` JSON structure.

## Current Implementation
Basic room operations are implemented:
- `gms room layer add/remove/list` - Layer management
- `gms room instance add/remove/list` - Instance placement
- `gms room ops duplicate/rename/delete` - Room operations
- `gms asset create room` - Room creation with dimensions

## Claude Code Skill
A workflow skill (`room-layout-engine.md`) is available via `gms skills install`. This skill provides:
- Guidance on basic instance placement
- Grid-based placement patterns (calculate positions manually)
- Layer management best practices
- Room duplication for level variants

The skill guides agents through manual placement. The MCP tool would provide automated grid/relative placement.

## Goals (Remaining)
- ~~Place individual instances.~~ ✓ Implemented
- ~~Manage layers.~~ ✓ Implemented
- Place instances in a grid (`o_floor` from x=0 to 1024).
- Relative placement ("Place `o_player` 32px above `o_spawn`").
- Bulk layer operations (fill, clear, copy).

## Proposed MCP Tool
`gm_room_layout_engine(room_name: str, operation: str, params: dict)`

**Operations:**
- `grid_fill` - Fill area with instances at grid intervals
- `relative_place` - Place relative to existing instance
- `layer_fill` - Fill layer with pattern
- `clear_instances` - Remove all instances of type from layer

## Potential Implementation
1. ~~Create a helper that parses room `.yy` files.~~ ✓ Done
2. Add coordinate calculation for grid operations.
3. Add instance lookup for relative placement.
4. Add bulk operations with transaction support.
5. Validate objects exist before placement.
