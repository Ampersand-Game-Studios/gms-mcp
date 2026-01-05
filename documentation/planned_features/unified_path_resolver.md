# Unified Path Resolver

## Overview
Centralizes the logic that maps "Logical Folders" to "Physical Paths" across the entire codebase.

## Goals
- Single source of truth for where `folders/Scripts.yy` lives on disk.
- Simplify adding new asset types (e.g., Particle Systems).
- Reduce duplicated path-joining logic in `AssetHelper`, `Workflow`, and `Introspection`.

## Implementation Details
1. Create `gms_helpers/path_resolver.py`.
2. Centralize the `ASSET_TYPE_MAP` and directory naming conventions.
3. Refactor existing helpers to use this resolver.
