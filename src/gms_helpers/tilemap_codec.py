"""GameMaker tilemap compress/decompress (TileDataFormat 0 and 1)."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .exceptions import ValidationError

TILE_EMPTY = -2147483648
TILE_INDEX_MASK = 0x7FFFF
TILE_MIRROR = 0x10000000
TILE_FLIP = 0x20000000
TILE_ROTATE = 0x40000000
MAX_TILE_CELLS = 4_194_304


def tile_integer(value: Any, name: str = "tile") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer")
    return value


def raw_tile_integer(value: Any) -> int:
    """Accept GameMaker's signed or unsigned 32-bit raw tile representation."""
    value = tile_integer(value)
    if not -(2**31) <= value < 2**32:
        raise ValidationError("Raw tile must fit in 32 bits")
    return value


def is_empty_tile(raw: int) -> bool:
    return raw == TILE_EMPTY


def tile_index(raw: int) -> int:
    if is_empty_tile(raw):
        return 0
    return int(raw) & TILE_INDEX_MASK


def tile_flags(raw: int) -> dict[str, bool]:
    if is_empty_tile(raw):
        return {"mirror": False, "flip": False, "rotate": False}
    value = int(raw)
    return {
        "mirror": bool(value & TILE_MIRROR),
        "flip": bool(value & TILE_FLIP),
        "rotate": bool(value & TILE_ROTATE),
    }


def encode_tile(index: int, *, mirror: bool = False, flip: bool = False, rotate: bool = False) -> int:
    index = tile_integer(index)
    if not -1 <= index <= TILE_INDEX_MASK:
        raise ValidationError(f"Tile index must be between -1 and {TILE_INDEX_MASK}")
    if index <= 0 and not (mirror or flip or rotate):
        return TILE_EMPTY if index < 0 else 0
    value = int(index) & TILE_INDEX_MASK
    if mirror:
        value |= TILE_MIRROR
    if flip:
        value |= TILE_FLIP
    if rotate:
        value |= TILE_ROTATE
    return value


def decompress_tile_data(stream: Sequence[int], expected_len: int | None = None) -> list[int]:
    """Decode GameMaker TileCompressedData (TileDataFormat 1)."""
    out: list[int] = []
    i = 0
    n = len(stream)
    limit = MAX_TILE_CELLS if expected_len is None else expected_len
    if not 0 <= limit <= MAX_TILE_CELLS:
        raise ValidationError(f"Tilemap exceeds the {MAX_TILE_CELLS} cell limit")
    while i < n:
        count = tile_integer(stream[i], "run length")
        i += 1
        if count == 0:
            continue
        if len(out) + abs(count) > limit:
            raise ValidationError("Compressed tile run exceeds the declared layer size")
        if count < 0:
            if i >= n:
                raise ValidationError("Compressed tile stream ended inside a repeat run")
            out.extend([raw_tile_integer(stream[i])] * (-count))
            i += 1
            continue
        if i + count > n:
            raise ValidationError("Compressed tile stream ended inside a literal run")
        out.extend(raw_tile_integer(v) for v in stream[i : i + count])
        i += count
    if expected_len is not None and len(out) != expected_len:
        raise ValidationError(f"Decompressed tile count {len(out)} != expected {expected_len}")
    return out


def compress_tile_data(tiles: Sequence[int]) -> list[int]:
    """Encode tiles as GameMaker TileCompressedData (TileDataFormat 1)."""
    # Validate every value, including repeats equal to an earlier valid integer.
    for value in tiles:
        raw_tile_integer(value)
    out: list[int] = []
    i = 0
    n = len(tiles)
    while i < n:
        if i + 1 < n and tiles[i] == tiles[i + 1]:
            value = int(tiles[i])
            run = 1
            while i + run < n and tiles[i + run] == value:
                run += 1
            out.extend([-run, value])
            i += run
            continue
        start = i
        i += 1
        while i < n:
            if i + 1 < n and tiles[i] == tiles[i + 1]:
                break
            i += 1
        length = i - start
        out.append(length)
        out.extend(int(v) for v in tiles[start:i])
    return out


def layer_tile_dimensions(tiles_obj: dict[str, Any]) -> tuple[int, int]:
    """Validate dimensions before any allocation or iteration, including empty layers."""
    if not isinstance(tiles_obj, dict):
        raise ValidationError("Tile layer tiles must be an object")
    width = tile_integer(tiles_obj.get("SerialiseWidth", 0), "SerialiseWidth")
    height = tile_integer(tiles_obj.get("SerialiseHeight", 0), "SerialiseHeight")
    if (
        not 0 <= width <= MAX_TILE_CELLS
        or not 0 <= height <= MAX_TILE_CELLS
        or (width == 0) != (height == 0)
        or width * height > MAX_TILE_CELLS
    ):
        raise ValidationError("Invalid or oversized tile layer dimensions")
    return width, height


def layer_tile_stream(tiles_obj: dict[str, Any]) -> tuple[list[int], int]:
    """Return (tiles, format) from a GMRTileLayer.tiles object."""
    width, height = layer_tile_dimensions(tiles_obj)
    expected = width * height
    fmt = tiles_obj.get("TileDataFormat", 1 if "TileCompressedData" in tiles_obj else 0)
    if isinstance(fmt, bool) or not isinstance(fmt, int) or fmt not in (0, 1):
        raise ValidationError(f"Unsupported TileDataFormat: {fmt}")
    if fmt == 1:
        stream = tiles_obj.get("TileCompressedData", [])
        if not isinstance(stream, list):
            raise ValidationError("TileCompressedData must be a list")
        return decompress_tile_data(stream, expected), 1
    serial = tiles_obj.get("TileSerialiseData", [])
    if not isinstance(serial, list):
        raise ValidationError("TileSerialiseData must be a list")
    if len(serial) != expected:
        raise ValidationError(f"TileSerialiseData length {len(serial)} != {expected}")
    return [raw_tile_integer(v) for v in serial], 0


def write_layer_tiles(tiles_obj: dict[str, Any], tiles: Sequence[int], fmt: int | None = None) -> dict[str, Any]:
    """Write tiles back into a tiles object, preserving format when possible."""
    width, height = layer_tile_dimensions(tiles_obj)
    expected = width * height
    if len(tiles) != expected:
        raise ValidationError(f"Cannot write {len(tiles)} tiles into {width}x{height} layer")
    use_fmt = fmt
    if use_fmt is None:
        use_fmt = tiles_obj.get("TileDataFormat", 1 if "TileCompressedData" in tiles_obj else 0)
    if isinstance(use_fmt, bool) or not isinstance(use_fmt, int) or use_fmt not in (0, 1):
        raise ValidationError(f"Unsupported TileDataFormat: {use_fmt}")
    for value in tiles:
        raw_tile_integer(value)
    if use_fmt == 1:
        stream = compress_tile_data(tiles)
        if decompress_tile_data(stream, len(tiles)) != list(tiles):
            raise ValidationError("Compressed tiles failed round-trip verification")
        tiles_obj["TileCompressedData"] = stream
        tiles_obj["TileDataFormat"] = 1
        if "TileSerialiseData" in tiles_obj:
            tiles_obj["TileSerialiseData"] = [int(v) for v in tiles]
    else:
        tiles_obj["TileSerialiseData"] = [int(v) for v in tiles]
        tiles_obj.pop("TileCompressedData", None)
        tiles_obj["TileDataFormat"] = 0
    return tiles_obj


def iter_cells(tiles: Sequence[int], width: int, height: int) -> Iterable[tuple[int, int, int]]:
    if width == 0 or height == 0:
        return
    for row in range(height):
        base = row * width
        for col in range(width):
            yield col, row, int(tiles[base + col])
