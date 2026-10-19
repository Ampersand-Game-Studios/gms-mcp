"""Query, patch, and validate GameMaker room tilemaps."""

from __future__ import annotations

import json
from array import array
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exceptions import AssetNotFoundError, GMSError, ValidationError
from .path_safety import project_relative_path, validate_resource_name
from .room_instance_helper import _iter_layers
from .room_layer_helper import _find_room_file, _load_room_data, _save_room_data
from .tilemap_codec import (
    MAX_TILE_CELLS,
    TILE_EMPTY,
    encode_tile,
    is_empty_tile,
    iter_cells,
    layer_tile_dimensions,
    layer_tile_stream,
    tile_flags,
    tile_index,
    tile_integer,
    write_layer_tiles,
)
from .utils import find_yyp, load_json_loose


MAX_QUERY_LAYERS = 256
MAX_QUERY_HISTOGRAM_BINS = 65536


@dataclass
class _QueryBudget:
    """Output allowances shared by every layer in one query."""

    cells: int
    clusters: int
    histogram_bins: int = MAX_QUERY_HISTOGRAM_BINS


def _project_root(project_root: str | Path | None) -> Path:
    return Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()


def _tile_layers(room_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [layer for layer in _iter_layers(room_data.get("layers", [])) if layer.get("resourceType") == "GMRTileLayer"]


def _layer_by_name(room_data: dict[str, Any], layer_name: str) -> dict[str, Any]:
    for layer in _tile_layers(room_data):
        if layer.get("name") == layer_name or layer.get("%Name") == layer_name:
            return layer
    raise AssetNotFoundError(f"Tile layer not found: {layer_name}")


def _tileset_info(project_root: Path, layer: dict[str, Any]) -> dict[str, Any]:
    tileset_id = layer.get("tilesetId")
    if not isinstance(tileset_id, dict) or not tileset_id.get("path"):
        return {
            "name": None,
            "path": None,
            "exists": False,
            "tile_count": None,
            "tile_width": None,
            "tile_height": None,
        }
    rel = str(tileset_id["path"])
    path = project_relative_path(rel, project_root=project_root, kind="tileset")
    info: dict[str, Any] = {
        "name": tileset_id.get("name"),
        "path": rel,
        "exists": path.is_file(),
        "tile_count": None,
        "tile_width": None,
        "tile_height": None,
    }
    if not info["exists"]:
        return info
    data = load_json_loose(path)
    if not isinstance(data, dict) or data.get("resourceType") != "GMTileSet":
        raise ValidationError("Tile layer references an invalid tileset")
    info["tile_count"] = data.get("tile_count")
    info["tile_width"] = data.get("tileWidth")
    info["tile_height"] = data.get("tileHeight")
    return info


def _matches_filter(
    raw: int, *, index: int | None, index_min: int | None, index_max: int | None, include_empty: bool
) -> bool:
    if is_empty_tile(raw) and not include_empty:
        return False
    idx = -1 if is_empty_tile(raw) else tile_index(raw)
    if index is not None and idx != index:
        return False
    if index_min is not None and idx < index_min:
        return False
    if index_max is not None and idx > index_max:
        return False
    return True


def _clusters(matched: bytearray, width: int, *, x: int, y: int, max_clusters: int) -> tuple[list[dict[str, Any]], int]:
    """Count full components using bounded numeric storage; retain only requested summaries."""
    clusters: list[dict[str, Any]] = []
    count = 0
    for origin in range(len(matched)):
        if not matched[origin]:
            continue
        count += 1
        stack = array("I", [origin])
        matched[origin] = 0
        min_row, min_col = divmod(origin, width)
        max_col, max_row = min_col, min_row
        size = 0
        while stack:
            position = stack.pop()
            row, col = divmod(position, width)
            size += 1
            min_col, max_col = min(min_col, col), max(max_col, col)
            min_row, max_row = min(min_row, row), max(max_row, row)
            for neighbor, allowed in (
                (position - 1, col > 0),
                (position + 1, col + 1 < width),
                (position - width, row > 0),
                (position + width, position + width < len(matched)),
            ):
                if allowed and matched[neighbor]:
                    matched[neighbor] = 0
                    stack.append(neighbor)
        if len(clusters) < max_clusters:
            clusters.append(
                {
                    "size": size,
                    "bbox": {
                        "x": x + min_col,
                        "y": y + min_row,
                        "width": max_col - min_col + 1,
                        "height": max_row - min_row + 1,
                    },
                    "origin": {"col": x + min_col, "row": y + min_row},
                }
            )
    clusters.sort(key=lambda item: (item["origin"]["row"], item["origin"]["col"]))
    return clusters, count


def _describe_cell(col: int, row: int, raw: int) -> dict[str, Any]:
    empty = is_empty_tile(raw)
    payload = {"col": col, "row": row, "raw": raw, "index": 0 if empty else tile_index(raw), "empty": empty}
    payload.update(tile_flags(raw))
    return payload


def _query_layer(
    project_root: Path,
    layer: dict[str, Any],
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    index: int | None,
    index_min: int | None,
    index_max: int | None,
    include_cells: bool,
    include_clusters: bool,
    include_empty: bool,
    budget: _QueryBudget,
) -> dict[str, Any]:
    tiles_obj = layer.get("tiles") or {}
    issues: list[dict[str, Any]] = []
    try:
        layer_w, layer_h = layer_tile_dimensions(tiles_obj)
        tiles, fmt = layer_tile_stream(tiles_obj)
    except ValidationError as exc:
        return {
            "name": layer.get("name"),
            "depth": layer.get("depth"),
            "ok": False,
            "issues": [{"code": "decode_failed", "message": str(exc)}],
        }
    region_w = layer_w if width <= 0 else width
    region_h = layer_h if height <= 0 else height
    x2 = min(layer_w, x + region_w)
    y2 = min(layer_h, y + region_h)
    x1 = min(layer_w, x)
    y1 = min(layer_h, y)
    region_width, region_height = x2 - x1, y2 - y1
    cells_out: list[dict[str, Any]] = []
    matched = bytearray(region_width * region_height) if include_clusters else None
    histogram: Counter[int] = Counter()
    empty_count = 0
    match_count = 0
    for row in range(y1, y2):
        for col in range(x1, x2):
            raw = tiles[row * layer_w + col]
            empty = is_empty_tile(raw)
            empty_count += empty
            idx = -1 if empty else tile_index(raw)
            if idx not in histogram:
                if budget.histogram_bins == 0:
                    raise ValidationError("Tilemap query exceeds the histogram limit; select a smaller region or layer")
                budget.histogram_bins -= 1
            histogram[idx] += 1
            if _matches_filter(raw, index=index, index_min=index_min, index_max=index_max, include_empty=include_empty):
                match_count += 1
                if include_cells and budget.cells > 0:
                    cells_out.append(_describe_cell(col, row, raw))
                    budget.cells -= 1
                if matched is not None:
                    matched[(row - y1) * region_width + col - x1] = 1
    tileset = _tileset_info(project_root, layer)
    result: dict[str, Any] = {
        "name": layer.get("name"),
        "depth": layer.get("depth"),
        "ok": True,
        "format": fmt,
        "width": layer_w,
        "height": layer_h,
        "region": {"x": x1, "y": y1, "width": max(0, x2 - x1), "height": max(0, y2 - y1)},
        "tileset": tileset,
        "empty_count": empty_count,
        "filled_count": (x2 - x1) * (y2 - y1) - empty_count if x2 > x1 and y2 > y1 else 0,
        "match_count": match_count,
        "histogram": {str(k): v for k, v in sorted(histogram.items(), key=lambda item: item[0])},
        "issues": issues,
    }
    if include_cells:
        result["cells"] = cells_out
        result["truncated"] = match_count > len(cells_out)
    if matched is not None:
        result["clusters"], result["cluster_count"] = _clusters(
            matched, region_width, x=x1, y=y1, max_clusters=budget.clusters
        )
        budget.clusters -= len(result["clusters"])
        result["clusters_truncated"] = result["cluster_count"] > len(result["clusters"])
    return result


def query_tilemap(
    room_name: str,
    *,
    layer_name: str = "",
    x: int = 0,
    y: int = 0,
    width: int = 0,
    height: int = 0,
    index: int | None = None,
    index_min: int | None = None,
    index_max: int | None = None,
    include_cells: bool = True,
    include_clusters: bool = True,
    include_empty: bool = False,
    max_cells: int = 4096,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    for field, value in (("x", x), ("y", y), ("width", width), ("height", height)):
        if tile_integer(value, field) < 0:
            raise ValidationError(f"{field} cannot be negative")
    if not 1 <= tile_integer(max_cells, "max_cells") <= 65536:
        raise ValidationError("max_cells must be between 1 and 65536")
    if index_min is not None and index_max is not None and index_min > index_max:
        raise ValidationError("index_min cannot exceed index_max")
    room_name = validate_resource_name(room_name, "room")
    room_path = _find_room_file(room_name, root)
    room_data = _load_room_data(room_path)
    layers = [_layer_by_name(room_data, layer_name)] if layer_name else _tile_layers(room_data)
    if len(layers) > MAX_QUERY_LAYERS:
        raise ValidationError("Tilemap query exceeds the layer limit; select a layer")
    total_cells = 0
    for layer in layers:
        try:
            layer_w, layer_h = layer_tile_dimensions(layer.get("tiles") or {})
        except ValidationError:
            # Preserve per-layer decode diagnostics without expanding invalid dimensions.
            continue
        total_cells += layer_w * layer_h
        if total_cells > MAX_TILE_CELLS:
            raise ValidationError(f"Tilemap query exceeds the {MAX_TILE_CELLS} cell limit; select a layer")
    budget = _QueryBudget(cells=max_cells, clusters=max_cells)
    payload = [
        _query_layer(
            root,
            layer,
            x=x,
            y=y,
            width=width,
            height=height,
            index=index,
            index_min=index_min,
            index_max=index_max,
            include_cells=include_cells,
            include_clusters=include_clusters,
            include_empty=include_empty,
            budget=budget,
        )
        for layer in layers
    ]
    return {
        "ok": all(layer["ok"] for layer in payload),
        "room": room_name,
        "layer_count": len(payload),
        "data": payload,
        "issues": [issue for layer in payload for issue in layer.get("issues") or []],
    }


def _coerce_tile(value: int, *, use_raw: bool) -> int:
    value = tile_integer(value)
    if use_raw:
        if not -(2**31) <= value < 2**32:
            raise ValidationError("Raw tile must fit in 32 bits")
        return value
    return encode_tile(value)


def _apply_patch(
    tiles: list[int],
    width: int,
    height: int,
    *,
    op: str,
    x: int,
    y: int,
    region_w: int,
    region_h: int,
    tile: int,
    from_index: int | None,
    to_tile: int | None,
    stamp: list[list[int | None]] | None,
    cells: list[dict[str, Any]] | None,
    use_raw: bool,
) -> tuple[list[int], list[dict[str, Any]]]:
    changed: list[dict[str, Any]] = []

    def write_cell(col: int, row: int, new_raw: int) -> None:
        if col < 0 or row < 0 or col >= width or row >= height:
            raise ValidationError(f"Tile coordinate out of bounds: ({col},{row}) for {width}x{height}")
        idx = row * width + col
        old = tiles[idx]
        if old == new_raw:
            return
        tiles[idx] = new_raw
        changed.append(
            {
                "col": col,
                "row": row,
                "from": old,
                "to": new_raw,
                "from_index": 0 if is_empty_tile(old) else tile_index(old),
                "to_index": 0 if is_empty_tile(new_raw) else tile_index(new_raw),
            }
        )

    if op == "set":
        if cells is not None:
            for cell in cells:
                if not isinstance(cell, dict) or "col" not in cell or "row" not in cell:
                    raise ValidationError("Every cell needs col and row")
                raw_flag = cell.get("use_raw", use_raw)
                if not isinstance(raw_flag, bool):
                    raise ValidationError("use_raw must be a boolean")
                write_cell(
                    tile_integer(cell["col"], "col"),
                    tile_integer(cell["row"], "row"),
                    _coerce_tile(cell.get("tile", tile), use_raw=raw_flag),
                )
        else:
            for row in range(y, y + max(1, region_h)):
                for col in range(x, x + max(1, region_w)):
                    write_cell(col, row, _coerce_tile(tile, use_raw=use_raw))
    elif op == "fill":
        raw = _coerce_tile(tile, use_raw=use_raw)
        for row in range(y, y + max(1, region_h)):
            for col in range(x, x + max(1, region_w)):
                write_cell(col, row, raw)
    elif op == "clear":
        for row in range(y, y + max(1, region_h)):
            for col in range(x, x + max(1, region_w)):
                write_cell(col, row, TILE_EMPTY)
    elif op == "replace":
        if from_index is None:
            raise ValidationError("replace requires from_index")
        new_raw = _coerce_tile(to_tile if to_tile is not None else tile, use_raw=use_raw)
        x1, y1 = x, y
        x2 = width if region_w <= 0 else min(width, x + max(1, region_w))
        y2 = height if region_h <= 0 else min(height, y + max(1, region_h))
        if region_w <= 0:
            x1, x2 = 0, width
        if region_h <= 0:
            y1, y2 = 0, height
        for row in range(y1, y2):
            for col in range(x1, x2):
                raw = tiles[row * width + col]
                current = -1 if is_empty_tile(raw) else tile_index(raw)
                if current == from_index:
                    write_cell(col, row, new_raw)
    elif op == "stamp":
        if not stamp:
            raise ValidationError("stamp requires a 2D tiles array")
        for row_offset, row_tiles in enumerate(stamp):
            if not isinstance(row_tiles, list):
                raise ValidationError("stamp_json must contain rows of tiles")
            for col_offset, value in enumerate(row_tiles):
                if value is None:
                    continue
                write_cell(x + col_offset, y + row_offset, _coerce_tile(value, use_raw=use_raw))
    else:
        raise ValidationError(f"Unknown tilemap op: {op}")
    return tiles, changed


def _patch_tilemap(
    room_name: str,
    layer_name: str,
    op: str,
    *,
    x: int = 0,
    y: int = 0,
    width: int = 1,
    height: int = 1,
    tile: int = 0,
    from_index: int | None = None,
    to_tile: int | None = None,
    stamp_json: str = "",
    cells_json: str = "",
    use_raw: bool = False,
    dry_run: bool = True,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    for field, value in (("x", x), ("y", y), ("width", width), ("height", height)):
        if tile_integer(value, field) < 0:
            raise ValidationError(f"{field} cannot be negative")
    if not isinstance(use_raw, bool) or not isinstance(dry_run, bool):
        raise ValidationError("use_raw and dry_run must be booleans")
    room_name = validate_resource_name(room_name, "room")
    layer_name = validate_resource_name(layer_name, "layer")
    op = (op or "").strip().lower()
    room_path = _find_room_file(room_name, root)
    room_data = _load_room_data(room_path)
    layer = _layer_by_name(room_data, layer_name)
    tiles_obj = layer.get("tiles") or {}
    layer_w, layer_h = layer_tile_dimensions(tiles_obj)
    tiles, fmt = layer_tile_stream(tiles_obj)
    try:
        stamp = json.loads(stamp_json) if stamp_json else None
        cells = json.loads(cells_json) if cells_json else None
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid patch JSON: {exc}") from exc
    if stamp_json and not isinstance(stamp, list):
        raise ValidationError("stamp_json must be a JSON 2D array")
    if cells_json and not isinstance(cells, list):
        raise ValidationError("cells_json must be a JSON array")
    if cells is not None and op != "set":
        raise ValidationError("cells_json is only supported by set")
    if stamp is not None and op != "stamp":
        raise ValidationError("stamp_json is only supported by stamp")
    if op == "replace" and from_index is not None:
        encode_tile(from_index)
    new_tiles, changed = _apply_patch(
        list(tiles),
        layer_w,
        layer_h,
        op=op,
        x=x,
        y=y,
        region_w=width,
        region_h=height,
        tile=tile,
        from_index=from_index,
        to_tile=to_tile,
        stamp=stamp,
        cells=cells,
        use_raw=use_raw,
    )
    # Confirm the patched buffer still round-trips before touching disk.
    write_layer_tiles(dict(tiles_obj), new_tiles, fmt)
    tile_count = _tileset_info(root, layer).get("tile_count")
    if isinstance(tile_count, int) and tile_count > 0:
        if any(not is_empty_tile(cell["to"]) and tile_index(cell["to"]) >= tile_count for cell in changed):
            raise ValidationError("Patched tile index exceeds the tileset tile_count")
    result = {
        "ok": True,
        "dry_run": dry_run,
        "room": room_name,
        "layer": layer_name,
        "op": op,
        "changes": {"count": len(changed), "samples": changed[:50]},
        "issues": [],
    }
    if dry_run:
        return result

    write_layer_tiles(tiles_obj, new_tiles, fmt)
    layer["tiles"] = tiles_obj
    _save_room_data(room_path, room_data)
    reloaded = _load_room_data(room_path)
    relayer = _layer_by_name(reloaded, layer_name)
    check, _ = layer_tile_stream(relayer.get("tiles") or {})
    if check != new_tiles:
        raise GMSError("Reloaded tilemap did not match patched buffer")
    result["written"] = True
    return result


def patch_tilemap(
    room_name: str,
    layer_name: str,
    op: str,
    *,
    x: int = 0,
    y: int = 0,
    width: int = 1,
    height: int = 1,
    tile: int = 0,
    from_index: int | None = None,
    to_tile: int | None = None,
    stamp_json: str = "",
    cells_json: str = "",
    use_raw: bool = False,
    dry_run: bool = True,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Preview or atomically patch a tilemap, reusing the MCP transaction when present."""
    from .operation_policy import validate_project_operation
    from .transactions import (
        GameMakerProjectTransaction,
        TransactionValidationError,
        transaction_is_active,
        should_compile_verify_after_mutation,
    )

    root = _project_root(project_root)
    kwargs: dict[str, Any] = dict(
        x=x,
        y=y,
        width=width,
        height=height,
        tile=tile,
        from_index=from_index,
        to_tile=to_tile,
        stamp_json=stamp_json,
        cells_json=cells_json,
        use_raw=use_raw,
        dry_run=dry_run,
        project_root=root,
    )
    if dry_run is True or transaction_is_active(root):
        return _patch_tilemap(room_name, layer_name, op, **kwargs)
    validate_project_operation(root, {"room_name": room_name})
    tx = GameMakerProjectTransaction(root, "gm_room_tilemap_patch")
    tx.begin()
    try:
        result = _patch_tilemap(room_name, layer_name, op, **kwargs)
        tx.capture_mutation_state()
        result["transaction"] = tx.commit(verify_compile=should_compile_verify_after_mutation())
        return result
    except BaseException as exc:
        if not tx.committed:
            tx.capture_mutation_state()
            if not tx.rollback():
                raise TransactionValidationError(
                    "Tilemap patch failed and safe rollback was incomplete.", details={"transaction": tx.to_dict()}
                ) from exc
        raise
    finally:
        tx.cleanup()


def _validate_layer(project_root: Path, room_name: str, layer: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    name = layer.get("name") or layer.get("%Name")
    tiles_obj = layer.get("tiles") or {}
    width = int(tiles_obj.get("SerialiseWidth") or 0)
    height = int(tiles_obj.get("SerialiseHeight") or 0)
    if width <= 0 or height <= 0:
        issues.append(
            {
                "code": "invalid_size",
                "room": room_name,
                "layer": name,
                "message": f"Invalid SerialiseWidth/Height {width}x{height}",
            }
        )
        return issues
    try:
        tiles, _fmt = layer_tile_stream(tiles_obj)
    except ValidationError as exc:
        issues.append({"code": "decode_failed", "room": room_name, "layer": name, "message": str(exc)})
        return issues
    if len(tiles) != width * height:
        issues.append(
            {
                "code": "size_mismatch",
                "room": room_name,
                "layer": name,
                "message": f"{len(tiles)} tiles != {width}x{height}",
            }
        )
    tileset = _tileset_info(project_root, layer)
    if not tileset["path"]:
        issues.append(
            {"code": "tileset_missing", "room": room_name, "layer": name, "message": "Layer has no tilesetId.path"}
        )
    elif not tileset["exists"]:
        issues.append(
            {
                "code": "tileset_path",
                "room": room_name,
                "layer": name,
                "message": f"Tileset file missing: {tileset['path']}",
            }
        )
    tile_count = tileset.get("tile_count")
    if isinstance(tile_count, int) and tile_count > 0:
        for col, row, raw in iter_cells(tiles, width, height):
            if is_empty_tile(raw):
                continue
            idx = tile_index(raw)
            if idx >= tile_count:
                issues.append(
                    {
                        "code": "index_oob",
                        "room": room_name,
                        "layer": name,
                        "col": col,
                        "row": row,
                        "index": idx,
                        "tile_count": tile_count,
                        "message": f"Tile index {idx} >= tileset tile_count {tile_count}",
                    }
                )
                if len([issue for issue in issues if issue["code"] == "index_oob"]) >= 25:
                    break
    return issues


def validate_maps(
    *,
    room_name: str = "",
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    rooms: list[str]
    if room_name:
        rooms = [validate_resource_name(room_name, "room")]
    else:
        from .introspection import list_assets_by_type

        rooms = sorted(asset["name"] for asset in list_assets_by_type(root, "room").get("room", []))
    issues: list[dict[str, Any]] = []
    checked = 0
    for name in rooms:
        room_path = _find_room_file(name, root)
        room_data = _load_room_data(room_path)
        for layer in _tile_layers(room_data):
            checked += 1
            issues.extend(_validate_layer(root, name, layer))
    return {
        "ok": not issues,
        "rooms": rooms,
        "layers_checked": checked,
        "issue_count": len(issues),
        "issues": issues,
        "data": {"rooms": rooms, "layers_checked": checked},
    }
