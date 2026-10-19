#!/usr/bin/env python3
"""Tilemap codec, nested map operations and public MCP safety regressions."""

from __future__ import annotations

import json
import asyncio
import os
import shutil
import sys
import tempfile
import tracemalloc
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.exceptions import GMSError, ValidationError
from gms_helpers.tilemap_codec import (
    MAX_TILE_CELLS,
    TILE_EMPTY,
    compress_tile_data,
    decompress_tile_data,
    encode_tile,
    layer_tile_stream,
    tile_flags,
    tile_index,
    write_layer_tiles,
)
from gms_helpers.tilemap_ops import patch_tilemap, query_tilemap, validate_maps
from gms_helpers.utils import load_json_loose, save_json_loose


def _room(width: int, height: int, stream: list[int], fmt: int = 1) -> dict:
    tiles = {"SerialiseWidth": width, "SerialiseHeight": height, "TileDataFormat": fmt}
    if fmt == 1:
        tiles["TileCompressedData"] = stream
    else:
        tiles["TileSerialiseData"] = stream
    return {
        "$GMRoom": "v1",
        "%Name": "r_map",
        "name": "r_map",
        "layers": [
            {
                "$GMRTileLayer": "",
                "%Name": "Tiles_Details",
                "name": "Tiles_Details",
                "depth": 400,
                "resourceType": "GMRTileLayer",
                "tilesetId": {"name": "ts_details", "path": "tilesets/ts_details/ts_details.yy"},
                "tiles": tiles,
            }
        ],
        "resourceType": "GMRoom",
        "resourceVersion": "2.0",
    }


class TestTilemapCodec(unittest.TestCase):
    def test_raw32_boundaries_round_trip_in_both_formats(self):
        values = [TILE_EMPTY, -(2**31) + 1, -1, 0, 0x10000004, 0x70000004, 2**32 - 1]
        for fmt in (0, 1):
            with self.subTest(fmt=fmt):
                obj = {"SerialiseWidth": len(values), "SerialiseHeight": 1, "TileDataFormat": fmt}
                write_layer_tiles(obj, values)
                self.assertEqual(layer_tile_stream(obj), (values, fmt))
        self.assertEqual(tile_index(TILE_EMPTY), 0)
        self.assertEqual(tile_flags(TILE_EMPTY), {"mirror": False, "flip": False, "rotate": False})
        self.assertEqual(tile_flags(0x70000004), {"mirror": True, "flip": True, "rotate": True})

    def test_raw32_invalid_values_are_rejected_by_every_codec_path(self):
        for invalid in (-(2**31) - 1, 2**32, True, False, 1.0, "1"):
            for values in ([invalid], [1, invalid]):
                with self.subTest(values=values), self.assertRaises(ValidationError):
                    compress_tile_data(values)
                for fmt, stream in ((0, values), (1, [len(values), *values]), (1, [-1, invalid])):
                    obj = {
                        "SerialiseWidth": len(values) if fmt == 0 or stream[0] > 0 else 1,
                        "SerialiseHeight": 1,
                        "TileDataFormat": fmt,
                        "TileSerialiseData" if fmt == 0 else "TileCompressedData": stream,
                    }
                    with self.subTest(invalid=invalid, fmt=fmt, stream=stream), self.assertRaises(ValidationError):
                        layer_tile_stream(obj)
                for fmt in (0, 1):
                    obj = {"SerialiseWidth": len(values), "SerialiseHeight": 1, "TileDataFormat": fmt}
                    before = deepcopy(obj)
                    with self.subTest(invalid=invalid, write_fmt=fmt), self.assertRaises(ValidationError):
                        write_layer_tiles(obj, values)
                    self.assertEqual(obj, before)

    def test_zero_dimension_cannot_bypass_limits_but_empty_layers_remain_valid(self):
        for width, height in ((0, 10**12), (10**12, 0), (0, 1), (1, 0)):
            with self.subTest(width=width, height=height), self.assertRaises(ValidationError):
                layer_tile_stream({"SerialiseWidth": width, "SerialiseHeight": height, "TileCompressedData": []})
        self.assertEqual(
            layer_tile_stream({"SerialiseWidth": 0, "SerialiseHeight": 0, "TileSerialiseData": []}), ([], 0)
        )

    def test_malformed_runs_and_dimensions_fail_before_expansion(self):
        for stream in ([-2147483647, 1], [2, 1], [-1], [True, 1]):
            with self.subTest(stream=stream), self.assertRaises(ValidationError):
                decompress_tile_data(stream, 1)
        for tiles in (
            {"SerialiseWidth": -1, "SerialiseHeight": 1},
            {"SerialiseWidth": 2147483647, "SerialiseHeight": 2147483647},
            {"SerialiseWidth": 1, "SerialiseHeight": 1, "TileDataFormat": 8},
            {"SerialiseWidth": 0, "SerialiseHeight": 0, "TileSerialiseData": [1]},
        ):
            with self.subTest(tiles=tiles), self.assertRaises(ValidationError):
                layer_tile_stream(tiles)

    def test_plain_tiles_and_flags_round_trip(self):
        tiles = [encode_tile(4, flip=True, rotate=True), encode_tile(-1), 0]
        decoded, fmt = layer_tile_stream({"SerialiseWidth": 3, "SerialiseHeight": 1, "TileSerialiseData": tiles})
        self.assertEqual(decoded, tiles)
        self.assertEqual(fmt, 0)
        self.assertEqual(tile_flags(tiles[0]), {"flip": True, "mirror": False, "rotate": True})
        for value in (True, "3", 524288, -2):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                encode_tile(value)

    def test_round_trip_mixed_runs(self):
        tiles = [TILE_EMPTY, TILE_EMPTY, 116, 117, 118, TILE_EMPTY, 0, 0, 0, 132]
        stream = compress_tile_data(tiles)
        self.assertEqual(decompress_tile_data(stream, len(tiles)), tiles)

    def test_empty_layer_matches_gamemaker(self):
        stream = [-1400, TILE_EMPTY]
        tiles = decompress_tile_data(stream, 1400)
        self.assertEqual(len(tiles), 1400)
        self.assertTrue(all(v == TILE_EMPTY for v in tiles))
        self.assertEqual(compress_tile_data(tiles), stream)

    def test_truncated_stream_raises(self):
        with self.assertRaises(ValidationError):
            decompress_tile_data([3, 1, 2], expected_len=3)

    def test_tile_flags(self):
        raw = 0x10000090
        self.assertEqual(tile_index(raw), 0x90)
        self.assertTrue(tile_flags(raw)["mirror"])
        self.assertFalse(tile_flags(raw)["flip"])
        self.assertEqual(encode_tile(144, mirror=True), raw)


class TestTilemapOps(unittest.TestCase):
    def test_patch_samples_are_bounded_for_every_operation_in_preview_and_write(self):
        values = [1] * 64
        operations = (
            ("clear", {}, TILE_EMPTY),
            ("fill", {"tile": 2}, 2),
            ("replace", {"from_index": 1, "to_tile": 3}, 3),
            ("stamp", {"stamp_json": json.dumps([[4] * 64])}, 4),
            ("set", {"tile": 5}, 5),
            ("set", {"cells_json": json.dumps([{"col": col, "row": 0, "tile": 6} for col in range(64)])}, 6),
        )
        for fmt in (0, 1):
            for op, extra, expected in operations:
                with self.subTest(fmt=fmt, op=op, extra=extra):
                    save_json_loose(self.room_path(), _room(64, 1, compress_tile_data(values) if fmt else values, fmt))
                    before = self.room_path().read_bytes()
                    args = dict(width=64, height=1, project_root=self.temp, **extra)
                    preview = patch_tilemap("r_map", "Tiles_Details", op, **args)
                    self.assertEqual(self.room_path().read_bytes(), before)
                    written = patch_tilemap("r_map", "Tiles_Details", op, dry_run=False, **args)
                    self.assertEqual(preview["changes"], written["changes"])
                    self.assertEqual(written["changes"]["count"], 64)
                    samples = written["changes"]["samples"]
                    self.assertEqual(len(samples), 50)
                    self.assertEqual([cell["col"] for cell in samples], list(range(50)))
                    self.assertTrue(all(cell["to"] == expected for cell in samples))
                    obj = load_json_loose(self.room_path())["layers"][0]["tiles"]
                    self.assertEqual(layer_tile_stream(obj), ([expected] * 64, fmt))
                    unchanged = patch_tilemap("r_map", "Tiles_Details", op, **args)
                    self.assertEqual(unchanged["changes"], {"count": 0, "samples": []})

    def test_patch_checks_every_changed_cell_even_after_sample_limit(self):
        cases = (
            ("stamp", {"stamp_json": json.dumps([[2] * 63 + [900]])}),
            (
                "set",
                {
                    "cells_json": json.dumps(
                        [{"col": col, "row": 0, "tile": 2 if col < 63 else 900} for col in range(64)]
                    )
                },
            ),
            # Invalid intermediate writes cannot be hidden by a later overwrite.
            ("set", {"cells_json": json.dumps([{"col": 0, "row": 0, "tile": 900}, {"col": 0, "row": 0, "tile": 2}])}),
        )
        save_json_loose(self.room_path(), _room(64, 1, [-64, 1]))
        before = self.room_path().read_bytes()
        for dry_run in (True, False):
            for op, extra in cases:
                with self.subTest(dry_run=dry_run, op=op), self.assertRaisesRegex(ValidationError, "tile_count"):
                    patch_tilemap("r_map", "Tiles_Details", op, dry_run=dry_run, project_root=self.temp, **extra)
                self.assertEqual(self.room_path().read_bytes(), before)

    def test_patch_preview_memory_uses_buffers_and_only_fifty_sample_objects(self):
        count = 65536
        save_json_loose(self.room_path(), _room(256, 256, [-count, 1]))
        before = self.room_path().read_bytes()
        tracemalloc.start()
        try:
            result = patch_tilemap("r_map", "Tiles_Details", "clear", width=256, height=256, project_root=self.temp)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(result["changes"]["count"], count)
        self.assertEqual(len(result["changes"]["samples"]), 50)
        # Allows buffer copies and round-trip validation, excluding a dict per change (~20 MB).
        self.assertLess(peak, 6_000_000)
        self.assertEqual(self.room_path().read_bytes(), before)

    def test_map_validation_accepts_only_well_formed_empty_dimensions_and_streams(self):
        for fmt in (0, 1):
            save_json_loose(self.room_path(), _room(0, 0, [], fmt))
            self.assertTrue(validate_maps(room_name="r_map", project_root=self.temp)["ok"])
            for width, height in (
                ("bad", 1),
                (True, 1),
                (None, 1),
                (1.0, 1),
                (-1, 1),
                (0, 1),
                (1, 0),
                (0, 10**12),
                (MAX_TILE_CELLS, 2),
            ):
                save_json_loose(self.room_path(), _room(width, height, [], fmt))
                with self.subTest(fmt=fmt, width=width, height=height):
                    result = validate_maps(room_name="r_map", project_root=self.temp)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["issues"][0]["code"], "invalid_size")
            for stream in ([1], None, False, "", {}):
                save_json_loose(self.room_path(), _room(0, 0, stream, fmt))
                with self.subTest(fmt=fmt, stream=stream):
                    result = validate_maps(room_name="r_map", project_root=self.temp)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["issues"][0]["code"], "decode_failed")
        for malformed in ([], "bad", False, None):
            room = _room(0, 0, [])
            room["layers"][0]["tiles"] = malformed
            save_json_loose(self.room_path(), room)
            with self.subTest(tiles=malformed):
                self.assertFalse(validate_maps(room_name="r_map", project_root=self.temp)["ok"])
                self.assertFalse(query_tilemap("r_map", project_root=self.temp)["ok"])

    def test_raw32_read_failures_are_structured_and_writes_preserve_signed_flags(self):
        for fmt in (0, 1):
            for invalid in (-(2**31) - 1, 2**32, True):
                save_json_loose(self.room_path(), _room(1, 1, [-1, invalid] if fmt else [invalid], fmt))
                before = self.room_path().read_bytes()
                with self.subTest(fmt=fmt, invalid=invalid):
                    self.assertFalse(query_tilemap("r_map", project_root=self.temp)["ok"])
                    result = validate_maps(room_name="r_map", project_root=self.temp)
                    self.assertEqual(result["issues"][0]["code"], "decode_failed")
                    with self.assertRaises(ValidationError):
                        patch_tilemap("r_map", "Tiles_Details", "clear", dry_run=False, project_root=self.temp)
                    self.assertEqual(self.room_path().read_bytes(), before)
            for raw in (TILE_EMPTY, -(2**31) + 1, 0x70000004):
                save_json_loose(self.room_path(), _room(1, 1, [-1, 0] if fmt else [0], fmt))
                patch_tilemap(
                    "r_map", "Tiles_Details", "set", tile=raw, use_raw=True, dry_run=False, project_root=self.temp
                )
                self.assertTrue(validate_maps(room_name="r_map", project_root=self.temp)["ok"])
                query = query_tilemap("r_map", include_empty=True, project_root=self.temp)
                self.assertEqual(query["data"][0]["cells"][0]["raw"], raw)

    def test_query_allocates_only_requested_cell_details(self):
        from gms_helpers import tilemap_ops as ops

        save_json_loose(self.room_path(), _room(64, 64, [-4096, 1]))
        with patch.object(ops, "_describe_cell", wraps=ops._describe_cell) as describe:
            result = query_tilemap("r_map", max_cells=2, include_clusters=False, project_root=self.temp)
        self.assertEqual(describe.call_count, 2)
        layer = result["data"][0]
        self.assertEqual(layer["match_count"], 4096)
        self.assertEqual(layer["histogram"], {"1": 4096})
        self.assertEqual(len(layer["cells"]), 2)
        self.assertTrue(layer["truncated"])

    def test_summary_query_does_not_allocate_cell_or_cluster_details(self):
        save_json_loose(self.room_path(), _room(512, 512, [-262144, 1]))
        with (
            patch("gms_helpers.tilemap_ops._describe_cell", side_effect=AssertionError("Unexpected cell details")),
            patch("gms_helpers.tilemap_ops._clusters", side_effect=AssertionError("Unexpected cluster work")),
        ):
            result = query_tilemap(
                "r_map", max_cells=1, include_cells=False, include_clusters=False, project_root=self.temp
            )
        layer = result["data"][0]
        self.assertEqual(layer["match_count"], 262144)
        self.assertEqual(layer["histogram"], {"1": 262144})
        self.assertNotIn("cells", layer)
        self.assertNotIn("clusters", layer)

    def test_mcp_cluster_output_is_capped_but_counts_cover_the_whole_region(self):
        cells = [1 if (row + col) % 2 == 0 else TILE_EMPTY for row in range(8) for col in range(8)]
        save_json_loose(self.room_path(), _room(8, 8, compress_tile_data(cells)))
        result = self.call_tool("gm_room_tilemap_query", {"room_name": "r_map", "max_cells": 2})
        layer = result["data"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(layer["cluster_count"], 32)
        self.assertEqual(layer["match_count"], 32)
        self.assertEqual(len(layer["cells"]), 2)
        self.assertEqual(len(layer["clusters"]), 2)
        self.assertTrue(layer["clusters_truncated"])
        self.assertTrue(all(cluster["size"] == 1 for cluster in layer["clusters"]))

    def test_large_connected_cluster_keeps_full_size_and_region_coordinates(self):
        save_json_loose(self.room_path(), _room(64, 64, [-4096, 1]))
        result = query_tilemap("r_map", x=3, y=4, width=50, height=51, max_cells=1, project_root=self.temp)
        layer = result["data"][0]
        self.assertEqual(layer["cluster_count"], 1)
        self.assertFalse(layer["clusters_truncated"])
        self.assertEqual(
            layer["clusters"],
            [{"size": 2550, "bbox": {"x": 3, "y": 4, "width": 50, "height": 51}, "origin": {"col": 3, "row": 4}}],
        )

    def test_cell_and_cluster_limits_are_shared_by_nested_layers(self):
        room = _room(1, 1, [-1, 1])
        second = deepcopy(room["layers"][0])
        second["name"] = second["%Name"] = "Tiles_Second"
        room["layers"].append({"name": "Group", "resourceType": "GMRLayer", "layers": [second]})
        save_json_loose(self.room_path(), room)
        layers = query_tilemap("r_map", max_cells=1, project_root=self.temp)["data"]
        self.assertEqual(sum(len(layer["cells"]) for layer in layers), 1)
        self.assertEqual(sum(len(layer["clusters"]) for layer in layers), 1)
        self.assertEqual([layer["cluster_count"] for layer in layers], [1, 1])
        self.assertTrue(layers[1]["truncated"])
        self.assertTrue(layers[1]["clusters_truncated"])

    def test_query_rejects_aggregate_work_before_decoding(self):
        room = _room(MAX_TILE_CELLS, 1, [-MAX_TILE_CELLS, 1])
        room["layers"].extend(_room(1, 1, [-1, 1])["layers"])
        save_json_loose(self.room_path(), room)
        with (
            patch("gms_helpers.tilemap_ops.layer_tile_stream", side_effect=AssertionError("Expanded over-budget data")),
            self.assertRaisesRegex(ValidationError, "query.*cell limit"),
        ):
            query_tilemap("r_map", project_root=self.temp)

    def test_query_bounds_histogram_and_layer_counts(self):
        save_json_loose(self.room_path(), _room(65537, 1, [65537, *range(65537)]))
        with self.assertRaisesRegex(ValidationError, "histogram"):
            query_tilemap("r_map", include_cells=False, include_clusters=False, project_root=self.temp)
        room = _room(0, 0, [])
        room["layers"] *= 257
        save_json_loose(self.room_path(), room)
        with self.assertRaisesRegex(ValidationError, "layer limit"):
            query_tilemap("r_map", project_root=self.temp)

    def test_mcp_rejects_malformed_dimensions_and_accepts_a_normal_empty_layer(self):
        save_json_loose(self.room_path(), _room(0, 10**12, []))
        before = self.room_path().read_bytes()
        # A regression must fail promptly instead of entering the old trillion-row loop.
        with patch("gms_helpers.tilemap_ops.iter_cells", side_effect=AssertionError("Invalid layer was iterated")):
            result = self.call_tool("gm_room_tilemap_query", {"room_name": "r_map"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"][0]["code"], "decode_failed")
        self.assertEqual(self.room_path().read_bytes(), before)
        save_json_loose(self.room_path(), _room(0, 0, []))
        result = self.call_tool("gm_room_tilemap_query", {"room_name": "r_map"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"][0]["match_count"], 0)
        self.assertEqual(result["data"][0]["cluster_count"], 0)
        self.assertEqual(result["data"][0]["cells"], [])
        self.assertEqual(result["data"][0]["clusters"], [])

    def room_path(self):
        return self.temp / "rooms/r_map/r_map.yy"

    def nested_layer(self):
        data = load_json_loose(self.room_path())
        layer = data["layers"][0]
        data["layers"] = [{"name": "Group", "resourceType": "GMRLayer", "layers": [layer]}]
        save_json_loose(self.room_path(), data)

    def call_tool(self, name, arguments, *, mode="off"):
        from gms_mcp.gamemaker_mcp_server import build_server
        from gms_mcp.server.results import unwrap_call_tool_result

        with patch.dict(
            os.environ,
            {"GM_PROJECT_ROOT": str(self.temp), "GMS_MCP_TOOLSETS": "map", "GMS_MCP_POST_MUTATION_VERIFY": mode},
        ):
            server = build_server()
            return unwrap_call_tool_result(asyncio.run(server.call_tool(name, arguments)))

    def test_nested_query_patch_and_validation_use_the_same_layers(self):
        self.nested_layer()
        self.assertEqual(query_tilemap("r_map", project_root=self.temp)["layer_count"], 1)
        result = patch_tilemap("r_map", "Tiles_Details", "clear", dry_run=False, project_root=self.temp)
        self.assertTrue(result["transaction"]["committed"])
        self.assertEqual(validate_maps(project_root=self.temp)["layers_checked"], 1)
        data = load_json_loose(self.room_path())
        data["layers"][0]["layers"][0]["tiles"]["TileCompressedData"] = [999999999, 1]
        save_json_loose(self.room_path(), data)
        self.assertFalse(validate_maps(project_root=self.temp)["ok"])
        self.assertFalse(query_tilemap("r_map", project_root=self.temp)["ok"])

    def test_fill_stamp_explicit_cells_and_plain_format(self):
        for operation, extra in (
            ("fill", {"width": 2, "height": 2, "tile": 2}),
            ("stamp", {"stamp_json": "[[3,null],[4,5]]"}),
            ("set", {"cells_json": '[{"col":0,"row":0,"tile":7}]'}),
        ):
            with self.subTest(operation=operation):
                result = patch_tilemap(
                    "r_map", "Tiles_Details", operation, dry_run=False, project_root=self.temp, **extra
                )
                self.assertTrue(result["written"])
        data = load_json_loose(self.room_path())
        data["layers"][0]["tiles"] = {"SerialiseWidth": 8, "SerialiseHeight": 2, "TileSerialiseData": [0] * 16}
        save_json_loose(self.room_path(), data)
        patch_tilemap("r_map", "Tiles_Details", "set", tile=3, dry_run=False, project_root=self.temp)
        self.assertEqual(query_tilemap("r_map", project_root=self.temp)["data"][0]["format"], 0)

    def test_invalid_inputs_never_change_the_room(self):
        before = self.room_path().read_bytes()
        cases = [
            ("set", {"x": -1}),
            ("fill", {"width": -1}),
            ("set", {"tile": 900}),
            ("set", {"tile": True}),
            ("set", {"tile": 524288}),
            ("set", {"tile": 2**32, "use_raw": True}),
            ("replace", {}),
            ("stamp", {}),
            ("stamp", {"stamp_json": "[1]"}),
            ("stamp", {"stamp_json": "null"}),
            ("set", {"cells_json": "null"}),
            ("stamp", {"stamp_json": "["}),
            ("set", {"cells_json": "{}"}),
            ("set", {"cells_json": "[{}]"}),
            ("set", {"cells_json": '[{"col":0,"row":0,"use_raw":"yes"}]'}),
            ("fill", {"cells_json": "[]"}),
            ("fill", {"stamp_json": "[]"}),
            ("bad", {}),
        ]
        for operation, arguments in cases:
            with self.subTest(operation=operation, arguments=arguments), self.assertRaises(ValidationError):
                patch_tilemap("r_map", "Tiles_Details", operation, dry_run=False, project_root=self.temp, **arguments)
            self.assertEqual(self.room_path().read_bytes(), before)

    def test_query_limits_filters_and_empty_cells(self):
        result = query_tilemap("r_map", include_empty=True, index=-1, max_cells=2, project_root=self.temp)
        self.assertEqual(result["data"][0]["match_count"], 10)
        self.assertTrue(result["data"][0]["truncated"])
        self.assertEqual(len(result["data"][0]["cells"]), 2)
        for arguments in ({"x": -1}, {"max_cells": 0}, {"index_min": 4, "index_max": 1}):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                query_tilemap("r_map", project_root=self.temp, **arguments)

    def test_mcp_profiles_annotations_preview_policy_and_full_replace(self):
        from gms_mcp.gamemaker_mcp_server import build_server

        with patch.dict(os.environ, {"GM_PROJECT_ROOT": str(self.temp), "GMS_MCP_TOOLSETS": "map"}):
            specs = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
        self.assertTrue(specs["gm_room_tilemap_query"].annotations.read_only_hint)
        self.assertTrue(specs["gm_room_map_validate"].annotations.read_only_hint)
        self.assertTrue(specs["gm_room_tilemap_patch"].annotations.destructive_hint)
        before = {str(p.relative_to(self.temp)): p.read_bytes() for p in self.temp.rglob("*") if p.is_file()}
        args = {
            "room_name": "r_map",
            "layer_name": "Tiles_Details",
            "op": "replace",
            "width": 0,
            "height": 0,
            "from_index": 100,
            "to_tile": 132,
        }
        preview = self.call_tool("gm_room_tilemap_patch", args)
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["changes"]["count"], 2)
        self.assertEqual(
            {str(p.relative_to(self.temp)): p.read_bytes() for p in self.temp.rglob("*") if p.is_file()}, before
        )
        with patch.dict(os.environ, {"GMS_MCP_REQUIRE_DRY_RUN": "1", "GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST": ""}):
            denied = self.call_tool("gm_room_tilemap_patch", {**args, "dry_run": False})
        self.assertTrue(denied["blocked_by_policy"])
        changed = self.call_tool("gm_room_tilemap_patch", {**args, "dry_run": False})
        self.assertTrue(changed["ok"])
        self.assertTrue(changed["transaction"]["committed"])
        self.assertEqual(query_tilemap("r_map", index=132, project_root=self.temp)["data"][0]["match_count"], 2)
        self.assertTrue(self.call_tool("gm_room_tilemap_query", {"room_name": "r_map"})["ok"])
        self.assertTrue(self.call_tool("gm_room_map_validate", {})["ok"])

    def test_mcp_compile_failure_rolls_back_tile_edits(self):
        before = self.room_path().read_bytes()
        with patch(
            "gms_helpers.transactions.compile_verify_project",
            return_value={"ok": False, "message": "fixture compile failed"},
        ) as compile_check:
            result = self.call_tool(
                "gm_room_tilemap_patch",
                {"room_name": "r_map", "layer_name": "Tiles_Details", "op": "clear", "dry_run": False},
                mode="smart",
            )
        compile_check.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(self.room_path().read_bytes(), before)

    def test_mcp_rejects_bad_names_and_values_before_writing(self):
        before = self.room_path().read_bytes()
        for arguments in ({"layer_name": "../Tiles"}, {"width": -1}, {"tile": 524288}):
            with self.subTest(arguments=arguments):
                result = self.call_tool(
                    "gm_room_tilemap_patch",
                    {"room_name": "r_map", "layer_name": "Tiles_Details", "op": "set", "dry_run": False, **arguments},
                )
                self.assertFalse(result["ok"])
        self.assertEqual(self.room_path().read_bytes(), before)

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        room_dir = self.temp / "rooms" / "r_map"
        room_dir.mkdir(parents=True)
        tileset_dir = self.temp / "tilesets" / "ts_details"
        tileset_dir.mkdir(parents=True)
        # 8x2 map: two 3-cell trees on the first row, empties elsewhere
        cells = [100, 101, 102, TILE_EMPTY, 100, 101, 102, TILE_EMPTY] + [TILE_EMPTY] * 8
        save_json_loose(room_dir / "r_map.yy", _room(8, 2, compress_tile_data(cells)))
        save_json_loose(
            tileset_dir / "ts_details.yy",
            {"name": "ts_details", "tile_count": 256, "tileWidth": 16, "tileHeight": 16, "resourceType": "GMTileSet"},
        )
        (self.temp / "game.yyp").write_text(
            json.dumps(
                {
                    "name": "game",
                    "resources": [
                        {"id": {"name": "r_map", "path": "rooms/r_map/r_map.yy"}},
                        {"id": {"name": "ts_details", "path": "tilesets/ts_details/ts_details.yy"}},
                    ],
                    "RoomOrderNodes": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_query_clusters_and_histogram(self):
        result = query_tilemap(
            "r_map",
            layer_name="Tiles_Details",
            index_min=100,
            index_max=102,
            project_root=self.temp,
        )
        self.assertTrue(result["ok"])
        layer = result["data"][0]
        self.assertEqual(layer["match_count"], 6)
        self.assertEqual(layer["cluster_count"], 2)
        self.assertEqual(layer["histogram"]["100"], 2)

    def test_dry_run_does_not_write(self):
        room_path = self.temp / "rooms" / "r_map" / "r_map.yy"
        before = room_path.read_text(encoding="utf-8")
        result = patch_tilemap(
            "r_map", "Tiles_Details", "clear", x=0, y=0, width=3, height=1, dry_run=True, project_root=self.temp
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changes"]["count"], 3)
        self.assertEqual(room_path.read_text(encoding="utf-8"), before)

    def test_write_round_trip_and_replace(self):
        result = patch_tilemap(
            "r_map",
            "Tiles_Details",
            "replace",
            from_index=100,
            to_tile=132,
            width=0,
            height=0,
            dry_run=False,
            project_root=self.temp,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["changes"]["count"], 2)
        queried = query_tilemap("r_map", layer_name="Tiles_Details", index=132, project_root=self.temp)
        self.assertEqual(queried["data"][0]["match_count"], 2)

    def test_out_of_bounds_does_not_write(self):
        room_path = self.temp / "rooms" / "r_map" / "r_map.yy"
        before = room_path.read_text(encoding="utf-8")
        with self.assertRaises(ValidationError):
            patch_tilemap("r_map", "Tiles_Details", "set", x=90, y=0, tile=1, dry_run=False, project_root=self.temp)
        self.assertEqual(room_path.read_text(encoding="utf-8"), before)

    def test_rollback_on_reload_failure(self):
        room_path = self.temp / "rooms" / "r_map" / "r_map.yy"
        before = room_path.read_text(encoding="utf-8")
        from gms_helpers import tilemap_ops as ops

        original_load = ops._load_room_data
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            data = original_load(path)
            if calls["n"] > 1:
                raise GMSError("reload failed")
            return data

        with patch.object(ops, "_load_room_data", side_effect=flaky):
            with self.assertRaises(GMSError):
                ops.patch_tilemap(
                    "r_map",
                    "Tiles_Details",
                    "clear",
                    x=0,
                    y=0,
                    width=1,
                    height=1,
                    dry_run=False,
                    project_root=self.temp,
                )
        self.assertEqual(room_path.read_text(encoding="utf-8"), before)
        self.assertFalse(room_path.with_suffix(".yy.mcpbak").exists())

    def test_validate_ok_and_index_oob(self):
        ok = validate_maps(room_name="r_map", project_root=self.temp)
        self.assertTrue(ok["ok"])
        room_path = self.temp / "rooms/r_map/r_map.yy"
        from gms_helpers.utils import load_json_loose

        data = load_json_loose(room_path)
        data["layers"][0]["tiles"]["TileCompressedData"] = compress_tile_data([900] + [TILE_EMPTY] * 15)
        save_json_loose(room_path, data)
        bad = validate_maps(room_name="r_map", project_root=self.temp)
        self.assertFalse(bad["ok"])
        self.assertTrue(any(issue["code"] == "index_oob" for issue in bad["issues"]))
