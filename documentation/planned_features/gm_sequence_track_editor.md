# GM Sequence Track Editor

## Overview
Provides primitives to modify GameMaker Sequences, which are currently a "blind spot" for automated tools.

## Goals
- Add "Tracks" (Position, Rotation, Opacity) to an existing sequence.
- Add keyframes to tracks.
- Create automated UI animations (e.g., "Fade in then Slide up").

## Proposed MCP Tool
`gm_sequence_track_editor(sequence_name: str, track_data: list)`

## Potential Implementation
1. Analyze the deep JSON structure of `GMSequence`.
2. Map high-level "Animations" to low-level sequence tracks.
3. Ensure UUID consistency across the sequence tracks.
