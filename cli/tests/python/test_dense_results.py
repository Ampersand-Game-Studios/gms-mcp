"""Dense result encodings: each must say everything the long form said, in fewer characters."""

from __future__ import annotations

import re
from pathlib import Path

from gms_helpers import snapshot_build
from gms_helpers.commands.diagnostics_commands import dense_diagnostics
from gms_helpers.dense import (
    asset_folders,
    assets_by_settings,
    by_folder,
    links_by_relation,
    name_ranges,
    repeat_counts,
    shared_fields,
    yy_content,
)
from gms_mcp.server.results import _within_new_folders, _without_repeated_lines

_RANGE = re.compile(r"^(.*)\{(\d+)\.\.(\d+)\}(.*)$")


def _expand(entries: list[str]) -> list[str]:
    """Expand {first..last} the way zsh does: every number, as wide as the ends are written."""
    names: list[str] = []
    for entry in entries:
        match = _RANGE.match(entry)
        if not match:
            names.append(entry)
            continue
        prefix, first, last, suffix = match.groups()
        width = len(first) if first.startswith("0") or last.startswith("0") else 0
        names.extend(f"{prefix}{number:0{width}d}{suffix}" for number in range(int(first), int(last) + 1))
    return names


def test_name_ranges_join_numbered_runs_and_expand_back_exactly():
    padded = [f"shot_f{index:05d}.png" for index in range(4756)]
    plain = ["Keyboard_8", "Keyboard_9", "Keyboard_10", "Keyboard_11"]
    others = ["menu.png", "Keyboard_A", "s1", "s2"]
    names = padded + plain + others

    written = name_ranges(names)

    assert "shot_f{00000..04755}.png" in written and "Keyboard_{8..11}" in written
    assert "s1" in written and "s2" in written  # two in a row stay as they are
    assert sorted(_expand(written)) == sorted(names)
    # A padded number never joins an unpadded one: the range could not say both widths.
    assert name_ranges(["a9", "a010", "a011", "a012"]) == ["a9", "a{010..012}"]


def test_repeat_counts_write_a_run_once_with_its_count():
    assert repeat_counts(["wait", "wait", "wait", "go", "wait"]) == ["wait [×3]", "go", "wait"]


def test_asset_folders_and_by_folder_keep_every_path():
    paths = ["objects/o_a/o_a.yy", "objects/o_b/o_b.yy", "scripts/s/s.yy", "notes/odd/other.yy"]
    groups, other = asset_folders(paths)
    assert groups == {"objects": ["o_a", "o_b"], "scripts": ["s"]} and other == ["notes/odd/other.yy"]
    rebuilt = [f"{folder}/{name}/{name}.yy" for folder, names in groups.items() for name in names] + other
    assert sorted(rebuilt) == sorted(paths)
    assert by_folder(["datafiles/a/x.json", "datafiles/a/y.json", "top.txt"]) == {
        "datafiles/a": ["x.json", "y.json"],
        "": ["top.txt"],
    }


def test_shared_fields_state_common_values_once_and_rebuild_each_record():
    records = [
        {"name": "Default", "border": 2, "autocrop": True},
        {"name": "ui", "border": 4, "autocrop": True},
        {"name": "fonts", "autocrop": True, "border": 2},
        {"name": "bare", "border": 2},
    ]
    shared, rows = shared_fields(records)
    assert shared == {"border": 2, "autocrop": True}
    assert rows[0] == {"name": "Default"} and rows[1] == {"name": "ui", "border": 4}
    assert rows[3] == {"name": "bare", "unset": ["autocrop"]}
    for record, row in zip(records, rows):
        rebuilt = {**{k: v for k, v in shared.items() if k not in row.get("unset", [])}, **row}
        rebuilt.pop("unset", None)
        assert rebuilt == record


def test_assets_by_settings_lists_each_combination_once():
    rows = [
        {"path": "sprites/a/a.yy", "group": "ui"},
        {"path": "sprites/b/b.yy", "group": "ui"},
        {"path": "fonts/f/f.yy", "group": "Default"},
    ]
    assert assets_by_settings(rows, lambda row: {"group": row["group"]}) == [
        {"group": "ui", "assets": {"sprites": ["a", "b"]}},
        {"group": "Default", "assets": {"fonts": ["f"]}},
    ]


def test_diagnostics_are_grouped_by_message_and_the_message_names_each_file(tmp_path: Path):
    def diagnostic(name: str, folder: str = "animcurves") -> dict:
        return {
            "severity": "warning",
            "category": "naming",
            "file_path": str(tmp_path / folder / name / f"{name}.yy"),
            "message": f"Animcurve name '{name}' invalid: Animation curves are ac_<name>",
            "code": "GM002",
            "line": None,
            "column": None,
            "source": "lint",
            "can_auto_fix": False,
            "suggested_fix": None,
        }

    report = {
        "ok": True,
        "depth": "quick",
        "project_root": str(tmp_path),
        "summary": {"error": 0, "warning": 3, "info": 0, "hint": 0},
        "diagnostics": [diagnostic("curve_a"), diagnostic("curve_b"), diagnostic("curve_c")],
    }
    dense = dense_diagnostics(report)

    assert dense["summary"] == {"warning": 3}
    (issue,) = dense["issues"]
    assert issue["message"] == "Animcurve name '{name}' invalid: Animation curves are ac_<name>"
    assert issue["assets"] == {"animcurves": ["curve_a", "curve_b", "curve_c"]}
    rebuilt = {issue["message"].replace("{name}", name) for name in issue["assets"]["animcurves"]}
    assert rebuilt == {item["message"] for item in report["diagnostics"]}


def test_change_lists_name_a_new_folder_once():
    created = [
        "sprites/spr_a",
        "sprites/spr_a/spr_a.yy",
        "sprites/spr_a/layers",
        "sprites/spr_a/layers/1/2.png",
        "sprites/spr_a-b.yy",
        "notes/n.txt",
    ]
    assert _within_new_folders(created) == ["notes/n.txt", "sprites/spr_a/", "sprites/spr_a-b.yy"]


def test_printed_output_drops_boilerplate_and_lines_the_change_list_repeats():
    stdout = (
        "[OK] Found GameMaker project: game.yyp\n"
        "Created sprites/spr_a/spr_a.yy\n"
        "Created 0fa6.png (dummy image)\n"
        "[WARN]  Replace dummy PNG files with actual artwork before using in GameMaker!\n"
    )
    listed = {"changes": {"created": ["sprites/spr_a"]}}
    assert _without_repeated_lines(stdout, listed) == (
        "[WARN]  Replace dummy PNG files with actual artwork before using in GameMaker!\n"
    )
    # Without a change list the "Created" lines are the only record, so they stay.
    assert "Created sprites/spr_a/spr_a.yy" in _without_repeated_lines(stdout, None)


def test_screenshots_are_a_pattern_and_the_part_each_file_fills_in(tmp_path: Path):
    shots = tmp_path / ".gms_mcp" / "runs" / "t" / "shots"
    shots.mkdir(parents=True)
    names = [f"__agent_shot_f{index:04d}.png" for index in range(1, 241)] + ["__agent_shot_menu.png"]
    for name in names:
        (shots / name).write_bytes(b"")

    listing = snapshot_build.screenshot_listing(tmp_path.resolve(), shots.resolve())

    assert listing == {
        "screenshot_files": ".gms_mcp/runs/t/shots/__agent_shot_*.png",
        "screenshots": ["f{0001..0240}", "menu"],
    }
    pattern = listing["screenshot_files"]
    assert sorted(pattern.replace("*", part).rsplit("/", 1)[1] for part in _expand(listing["screenshots"])) == sorted(
        names
    )
    assert snapshot_build.screenshot_listing(tmp_path, tmp_path / "none") == {"screenshots": []}


def test_run_log_verdict_is_written_once_and_densely():
    log = "\n".join(
        ["[TEST_SAVE_DIR] x"]
        + ["[TEST] waiting"] * 12
        + [f"[TEST] shot __agent_shot_f{index:04d}.png" for index in range(15, 75)]
        + ["[TEST] FAIL one", "[TEST] PASS two"]
        + [
            "############################################################################################",
            "ERROR in action number 1",
            "of Step Event0 for object o_x:",
            "Variable not set",
            "############################################################################################",
        ]
        * 3
        + ["[TEST_RESULT] FAIL failures=1"]
    )
    verdict = snapshot_build.parse_run_log(log, runtime_error_patterns=["ERROR in action number"])

    assert verdict["test_lines"] == ["waiting [×12]", "shot __agent_shot_f{0015..0074}.png", "FAIL one", "PASS two"]
    assert verdict["result_line"] == "FAIL failures=1" and verdict["failed_checks"] == ["one"]
    assert verdict["runtime_errors"] == [
        "ERROR in action number 1\nof Step Event0 for object o_x:\nVariable not set\n[logged 3 times]"
    ]


def test_a_failed_runs_log_tail_leaves_out_the_runners_own_lines_in_the_same_window(tmp_path: Path):
    from gms_helpers.runner_output import is_runner_line

    runner = [
        "*     YoYo Games Mac Runner V0.1      *",
        "Process Chunk: CODE   1  (0.31MB)",
        "OpenGL: VBOs supported",
        "Room_Prepare() ",
        "Total memory used = 310850456 (0x12873398) bytes 296.45MB",
        "Entering main loop.",
        "Pause event has been registered for this frame",
    ]
    game = ["ScribbleDX: Welcome to Scribble Deluxe", "Error compiling shader:", "[app/debug] ready"]
    log = tmp_path / "run.log"
    log.write_text("\n".join(["older game line"] + runner + game) + "\n", encoding="utf-8")

    assert all(is_runner_line(line) for line in runner)
    assert not any(is_runner_line(line) for line in game)
    # The window is the last ten lines, as before; only the runner's lines in it are dropped.
    assert snapshot_build.tail_lines(log, 10, omit=is_runner_line) == game
    assert snapshot_build.tail_lines(log, 10) == runner + game


def test_the_full_asset_graph_groups_shared_parts_and_rebuilds_every_node_and_edge():
    from gms_helpers.introspection import dense_asset_graph

    nodes = [
        {"id": f"spr_tile_{index}", "type": "sprite", "path": f"sprites/spr_tile_{index}/spr_tile_{index}.yy"}
        for index in range(4)
    ]
    nodes += [
        {"id": "o_player", "type": "object", "path": "objects/o_player/o_player.yy"},
        {"id": "levels.json", "type": "includedfile", "path": "datafiles/data/levels.json"},
        {"id": "odd", "type": "note", "path": "notes/elsewhere/odd.yy"},
    ]
    edges = [{"from": "o_player", "to": f"spr_tile_{index}", "relation": "sprite"} for index in range(4)]
    edges.append({"from": "o_player", "to": "o_player", "relation": "code_reference"})
    graph = {"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges), "deep_scan": True}

    dense = dense_asset_graph(graph)

    assert dense["assets"]["sprite"] == {"sprites": ["spr_tile_{0..3}"]}
    assert dense["edges"]["sprite"] == {"o_player": ["spr_tile_{0..3}"]}
    rebuilt_nodes = {
        (name, kind, f"{folder}/{name}/{name}.yy")
        for kind, folders in dense["assets"].items()
        for folder, names in folders.items()
        for name in _expand(names)
    }
    rebuilt_nodes |= {
        (name, "includedfile", f"{folder}/{name}")
        for folder, names in dense["included_files"].items()
        for name in names
    }
    rebuilt_nodes |= {(node["id"], node["type"], node["path"]) for node in dense["other_nodes"]}
    assert rebuilt_nodes == {(node["id"], node["type"], node["path"]) for node in nodes}
    rebuilt_edges = {
        (source, target, relation)
        for relation, sources in dense["edges"].items()
        for source, targets in sources.items()
        for target in _expand(targets)
    }
    assert rebuilt_edges == {(edge["from"], edge["to"], edge["relation"]) for edge in edges}


def test_room_and_event_listings_return_their_data_densely():
    from gms_helpers.commands.event_commands import dense_event_list
    from gms_helpers.commands.room_commands import dense_instance_list, dense_layer_list, dense_room_list

    stack = ["Instances", "Background"]
    rooms = {
        "success": True,
        "data": {
            "rooms": [
                {"name": f"r_level_{index}", "width": 640, "height": 480, "layer_count": 2, "layers": stack}
                for index in range(3)
            ]
            + [{"name": "r_broken", "error": "Invalid JSON"}]
        },
    }
    assert dense_room_list(rooms)["rooms"]["r_level_0"] == "640x480, 2 layers"
    assert dense_room_list(rooms)["rooms"]["r_broken"] == "error: Invalid JSON"
    assert "layers" not in dense_room_list(rooms)
    assert dense_room_list(rooms, verbose=True)["layers"] == [{"rooms": ["r_level_{0..2}"], "layers": stack}]

    layers = {
        "success": True,
        "data": {
            "room_name": "r",
            "layers": [
                {"name": "Instances", "type": "Instance", "depth": 0, "visible": True},
                {"name": "Grid", "type": "Background", "depth": 100, "visible": False},
            ],
        },
    }
    assert dense_layer_list(layers)["layers"] == ["Instances Instance 0", "Grid Background 100 hidden"]

    instances = {
        "success": True,
        "data": {
            "room_name": "r",
            "instances": [
                {
                    "name": "inst_A",
                    "object": "o_wall",
                    "layer": "Instances",
                    "x": 32.0,
                    "y": 64.5,
                    "scale_x": 1.0,
                    "scale_y": 1.0,
                    "rotation": 0.0,
                },
                {
                    "name": "inst_B",
                    "object": "o_wall",
                    "layer": "Instances",
                    "x": 0.0,
                    "y": 0.0,
                    "scale_x": 2.0,
                    "scale_y": 0.5,
                    "rotation": 90.0,
                },
            ],
        },
    }
    assert dense_instance_list(instances)["instances"] == {
        "Instances": {"o_wall": ["inst_A 32,64.5", "inst_B 0,0 scale 2,0.5 rotation 90"]}
    }

    events = {
        "success": True,
        "data": {
            "object": "o_player",
            "events": [
                {"type": 0, "num": 0, "filename": "Create_0.gml"},
                {"type": 4, "num": 0, "filename": "Collision_o_wall.gml", "collision_object": "o_wall"},
            ],
        },
    }
    assert dense_event_list(events) == {
        "ok": True,
        "object": "o_player",
        "events": ["Create_0.gml", "Collision_o_wall.gml"],
        "collision_objects": {"Collision_o_wall.gml": "o_wall"},
    }
    # A failed handler's report comes back as it was.
    failure = {"success": False, "message": "Room 'r' not found"}
    assert dense_layer_list(failure) is failure and dense_event_list(failure) is failure


def test_rescaled_texture_warnings_name_each_sprite_and_its_sizes():
    warnings = [
        "Warning : resource spr_big_my_game_2f8943c9-16c6-4b9c-a0ba-c50ff242aa74 rescaled from 3682,1226 to 1841,613",
        "Warning : resource spr_big_my_game_be63c89e-72a0-4869-9205-855d7e044137 rescaled from 3682,1226 to 1841,613",
        "Warning : resource spr_wide_my_game_b9fe6ae8-63b0-444f-ac31-1795596bf382 rescaled from 4000,10 to 2000,5",
        "Warning : something else entirely",
    ]
    other, rescaled = snapshot_build.split_rescaled_warnings(warnings, "my_game")
    assert other == ["Warning : something else entirely"]
    assert rescaled == {"spr_big": "3682x1226 -> 1841x613", "spr_wide": "4000x10 -> 2000x5"}

    # Project names with spaces (either literal or underscore-sanitized by Igor) are handled too.
    spaced = [
        "Warning : resource spr_hero_My Game_2f8943c9-16c6-4b9c-a0ba-c50ff242aa74 rescaled from 4096,512 to 2048,256",
        "Warning : resource spr_boss_My_Game_be63c89e-72a0-4869-9205-855d7e044137 rescaled from 2048,2048 to 1024,1024",
    ]
    other_spaced, rescaled_spaced = snapshot_build.split_rescaled_warnings(spaced, "My Game")
    assert other_spaced == []
    assert rescaled_spaced == {"spr_hero": "4096x512 -> 2048x256", "spr_boss": "2048x2048 -> 1024x1024"}


def test_live_log_tail_leaves_out_other_platform_macro_warnings(tmp_path: Path):
    from gms_helpers.runner_output import is_runner_line
    from gms_mcp.server.background_runs import _tail

    log = tmp_path / "build.log"
    log.write_text(
        "Compiling scripts\n"
        + "Warning : extension macro STEAM_X is not available for this target\n" * 20
        + "Warning : resource spr_big_my_game_2f8943c9-16c6-4b9c-a0ba-c50ff242aa74 rescaled from 4096,10 to 2048,5\n"
        * 5
        + "OpenGL: VBOs supported\n"
        + "Process Chunk: CODE   1  (0.31MB)\n"
        + "OpenGL error: invalid enum\n"
        + "Writing chunk\n" * 3,
        encoding="utf-8",
    )
    assert is_runner_line("OpenGL: VBOs supported")
    assert is_runner_line("OpenGL version - detected 4.1")
    assert not is_runner_line("OpenGL error: invalid enum")
    assert _tail(str(log), 5) == ["Compiling scripts", "OpenGL error: invalid enum", "Writing chunk [×3]"]
    assert snapshot_build.tail_lines(log, 0) == []


def test_dense_validation_orphan_and_sprite_frame_count_shapers():
    from gms_helpers.commands.event_commands import dense_event_validate
    from gms_helpers.commands.maintenance_commands import dense_json_validation, dense_orphan_list
    from gms_helpers.commands.sprite_commands import dense_sprite_frame_count

    assert dense_sprite_frame_count({"success": True, "sprite": "sprites/s/s.yy", "frame_count": 4}) == {
        "ok": True,
        "sprite": "sprites/s/s.yy",
        "frame_count": 4,
    }
    assert dense_event_validate(
        {
            "success": False,
            "data": {
                "object": "o_player",
                "results": {"orphaned_found": 1, "orphaned_fixed": 0, "missing_found": 2, "missing_created": 0},
            },
        }
    ) == {"ok": False, "object": "o_player", "orphaned_found": 1, "missing_found": 2}
    assert dense_json_validation({"success": True, "data": {"files_checked": 12, "invalid_files": []}}) == {
        "ok": True,
        "files_checked": 12,
    }
    assert dense_json_validation(
        {"success": False, "data": {"files_checked": 12, "invalid_files": [{"file": "a.yy", "error": "bad"}]}}
    ) == {"ok": False, "files_checked": 12, "invalid_files": {"a.yy": "bad"}}
    assert dense_orphan_list(
        {
            "success": True,
            "data": {
                "orphaned": [
                    {"path": "sprites/spr_1/spr_1.yy", "type": "sprite"},
                    {"path": "sprites/spr_2/spr_2.yy", "type": "sprite"},
                    {"path": "sprites/spr_3/spr_3.yy", "type": "sprite"},
                ],
                "missing": [],
            },
        }
    ) == {
        "ok": True,
        "orphaned_count": 3,
        "missing_count": 0,
        "orphaned": {"assets": {"sprites": ["spr_{1..3}"]}},
    }


def test_room_creation_code_validation_and_fast_redaction(tmp_path: Path):
    import json
    from gms_helpers.project_validation import validate_project_after_mutation
    from gms_mcp.server.results import public_mcp_result

    room_dir = tmp_path / "rooms" / "r_main"
    room_dir.mkdir(parents=True)
    obj_dir = tmp_path / "objects" / "o_hero"
    obj_dir.mkdir(parents=True)
    (obj_dir / "o_hero.yy").write_text(
        json.dumps(
            {
                "resourceType": "GMObject",
                "name": "o_hero",
                "%Name": "o_hero",
                "parent": {"name": "Objects", "path": "folders/Objects.yy"},
                "eventList": [],
            }
        ),
        encoding="utf-8",
    )
    (room_dir / "InstanceCreationCode_inst_stray.gml").write_text("// stray\n", encoding="utf-8")
    (room_dir / "r_main.yy").write_text(
        json.dumps(
            {
                "resourceType": "GMRoom",
                "name": "r_main",
                "%Name": "r_main",
                "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
                "layers": [
                    {
                        "resourceType": "GMRInstanceLayer",
                        "name": "Instances",
                        "%Name": "Instances",
                        "instances": [
                            {
                                "resourceType": "GMRInstance",
                                "name": "inst_clean",
                                "%Name": "inst_clean",
                                "objectId": {"name": "o_hero", "path": "objects/o_hero/o_hero.yy"},
                                "hasCreationCode": False,
                            },
                            {
                                "resourceType": "GMRInstance",
                                "name": "inst_missing",
                                "%Name": "inst_missing",
                                "objectId": {"name": "o_hero", "path": "objects/o_hero/o_hero.yy"},
                                "hasCreationCode": True,
                            },
                            {
                                "resourceType": "GMRInstance",
                                "name": "inst_stray",
                                "%Name": "inst_stray",
                                "objectId": {"name": "o_hero", "path": "objects/o_hero/o_hero.yy"},
                                "hasCreationCode": False,
                            },
                        ],
                    }
                ],
                "instanceCreationOrder": [
                    {"name": "inst_clean", "path": "rooms/r_main/r_main.yy"},
                    {"name": "inst_missing", "path": "rooms/r_main/r_main.yy"},
                    {"name": "inst_stray", "path": "rooms/r_main/r_main.yy"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "Demo.yyp").write_text(
        json.dumps(
            {
                "resourceType": "GMProject",
                "name": "Demo",
                "Folders": [
                    {"folderPath": "folders/Objects.yy", "name": "Objects"},
                    {"folderPath": "folders/Rooms.yy", "name": "Rooms"},
                ],
                "resources": [
                    {"id": {"name": "o_hero", "path": "objects/o_hero/o_hero.yy"}},
                    {"id": {"name": "r_main", "path": "rooms/r_main/r_main.yy"}},
                ],
                "RoomOrderNodes": [{"roomId": {"name": "r_main", "path": "rooms/r_main/r_main.yy"}}],
            }
        ),
        encoding="utf-8",
    )
    validation = validate_project_after_mutation(tmp_path)
    assert any("InstanceCreationCode_inst_missing.gml is missing" in err for err in validation.errors)
    assert any("InstanceCreationCode_inst_stray.gml exists" in warn for warn in validation.warnings)
    assert not any("inst_clean" in msg for msg in (*validation.errors, *validation.warnings))

    sanitized = public_mcp_result(
        {
            "ok": True,
            "plain": "o_hero",
            "inside": str(tmp_path / "rooms" / "r_main" / "r_main.yy"),
            "outside": "/Users/someone/secret/file.txt",
            "trace": "Traceback (most recent call last):\n  boom",
        },
        project_root=tmp_path,
    )
    assert sanitized["plain"] == "o_hero"
    assert sanitized["inside"] == "rooms/r_main/r_main.yy"
    assert sanitized["outside"] == "<host-path>"
    assert sanitized["trace"] == "Internal tool error; host details were withheld."


def test_asset_links_group_by_relation_and_type():
    records = [
        {"asset": "scr_a1", "type": "script", "relation": "code_reference"},
        {"asset": "scr_a2", "type": "script", "relation": "code_reference"},
        {"asset": "scr_a3", "type": "script", "relation": "code_reference"},
        {"asset": "o_base", "type": "object", "relation": "parent"},
    ]
    grouped = links_by_relation(records, name="asset", kind="type")
    assert grouped == {"code_reference": {"script": ["scr_a{1..3}"]}, "parent": {"object": ["o_base"]}}
    back = {(n, t, r) for r, types in grouped.items() for t, names in types.items() for n in _expand(names)}
    assert back == {(x["asset"], x["type"], x["relation"]) for x in records}


def test_yy_content_drops_only_format_bookkeeping_and_empty_fields():
    raw = {
        "$GMObject": "",
        "%Name": "o_x",
        "name": "o_x",
        "resourceType": "GMObject",
        "resourceVersion": "2.0",
        "persistent": False,
        "physicsDensity": 0.5,
        "properties": [],
        "spriteMaskId": None,
        "spriteId": {"name": "spr_x", "path": "sprites/spr_x/spr_x.yy"},
        "eventList": [{"$GMEvent": "v1", "%Name": "", "eventNum": 0, "eventType": 0, "isDnD": False}],
    }
    assert yy_content(raw) == {
        "name": "o_x",
        "persistent": False,
        "physicsDensity": 0.5,
        "spriteId": {"name": "spr_x", "path": "sprites/spr_x/spr_x.yy"},
        "eventList": [{"eventNum": 0, "eventType": 0, "isDnD": False}],
    }
