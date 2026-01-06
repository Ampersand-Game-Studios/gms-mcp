# Resource Caching Strategy

## Overview
Implements a performance-optimizing cache for project indices and asset graphs to ensure "instant" responses on massive projects.

## Goals
- Avoid re-parsing the entire project on every request.
- Use file modification timestamps (`mtime`) to detect changes.
- Store cache in `.gms_mcp/cache/`.

## Implementation Details
1. Create a `gms_helpers/cache.py` module.
2. Implement a `ProjectCache` class that stores a serialized version of the project graph.
3. Integrate with the MCP resources (`gms://project/index` and `gms://project/asset-graph`).
