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
    name_ranges,
    repeat_counts,
    shared_fields,
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
