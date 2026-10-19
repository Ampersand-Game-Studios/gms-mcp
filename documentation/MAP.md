# Map tools

Enable the optional tools with `GMS_MCP_TOOLSETS=map` or `GMS_MCP_TOOLSETS=all`, then restart the MCP server.

These tools read registered GameMaker rooms, including tile layers inside groups. Coordinates are tile cells. Both `TileCompressedData` and `TileSerialiseData` are supported. Decoding rejects malformed runs and layers larger than 4,194,304 cells before allocating their buffers. Dimensions must both be positive, or both zero for an empty layer; each dimension is bounded independently.

## Inspect

`gm_room_tilemap_query(room_name="r_map")` returns each tile layer's size, tileset, tile-index histogram, matching cells and connected clusters. Set `layer_name` to select a layer; use `index`, `index_min` or `index_max` to filter cells. `width=0` and `height=0` select the remaining layer extent. `max_cells` caps both the total returned cells and the total returned cluster summaries across all selected layers (default 4,096; maximum 65,536). Each layer's `truncated` and `clusters_truncated` flags indicate omitted details. Histograms, match counts, cluster counts and the sizes of returned clusters still cover the full region.

Queries count cells incrementally and use compact storage for cluster traversal. A single query permits at most 256 tile layers, 4,194,304 decoded cells across those layers, and 65,536 histogram entries across its results. Requests exceeding these budgets fail with a validation error; select a layer or, for the histogram limit, a smaller region.

`include_empty=true` includes the serialized empty sentinel; use `index=-1` to select it. Index zero remains distinct. `include_cells=false` and `include_clusters=false` omit those details.

## Edit

`gm_room_tilemap_patch` previews by default (`dry_run=true`).

| Operation | Behavior |
| --- | --- |
| `set` | Write `tile` into a rectangle, or apply `cells_json` entries containing `col`, `row`, and `tile`. |
| `fill` | Fill a rectangle with `tile`. |
| `clear` | Fill a rectangle with the empty sentinel. |
| `replace` | Replace cells matching `from_index` with `to_tile`. Use `width=0,height=0` for the entire layer. |
| `stamp` | Apply a two-dimensional `stamp_json` array at `x,y`; `null` skips a cell. |

Rectangle dimensions default to one cell. Tile values are indices; `-1` represents the empty sentinel. `use_raw=true` accepts 32-bit tile data including mirror, flip and rotate flags. Invalid coordinates, unrepresentable indices and new indices outside a known tileset's tile count are rejected before the room changes.

For example, preview replacing every index 100:

```text
gm_room_tilemap_patch(room_name="r_map", layer_name="Tiles_Details",
                     op="replace", from_index=100, to_tile=132,
                     width=0, height=0)
```

Set `dry_run=false` to apply. Writes use the project lock and durable transaction journal, preserve GameMaker's JSON layout, and verify the reloaded tile buffer. Structural validation or configured compile verification failures roll the edit back. MCP `smart` verification treats tile patches as high risk. `GMS_MCP_REQUIRE_DRY_RUN=1` blocks real edits unless allowlisted.

## Validate

`gm_room_map_validate()` checks tile layers in every registered room, including nested layers. Pass `room_name` to inspect one room. It reports malformed compressed data, invalid sizes, missing tilesets and tile indices outside the tileset's range. Failures return `ok=false` with structured issues.

Adapted from [ngocdh383's map contribution](https://github.com/ngocdh383/gms-mcp/commit/95140c44cc5ff8de9536141be1d5d8031c85349d), using the current project's safety and serialization systems.
