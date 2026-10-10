#!/usr/bin/env python3
"""Native-layout writes, registry edits, differential validation, locks, snapshot builds and the runtime bridge."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import sys
import time
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers import agent_locks, gm_json, gm_order, live_reload, live_session, snapshot_build, yyp_registry  # noqa: E402
from gms_helpers.bridge_server import BridgeServer  # noqa: E402
from gms_helpers.event_model import parse_event_spec  # noqa: E402
from gms_helpers.exceptions import ValidationError  # noqa: E402
from gms_helpers.project_validation import errors_introduced_by_mutation, validate_project_after_mutation  # noqa: E402
from gms_helpers.transactions import GameMakerProjectTransaction, TransactionValidationError  # noqa: E402
from gms_helpers.utils import insert_into_folders, insert_into_resources, load_json_loose, save_json  # noqa: E402
from gms_helpers.vcs_stage import stage_paths  # noqa: E402


def _script_yy(name: str, parent: str = "folders/Scripts.yy", parent_name: str = "Scripts") -> str:
    return (
        "{\n"
        '  "$GMScript":"v1",\n'
        f'  "%Name":"{name}",\n'
        '  "isCompatibility":false,\n'
        '  "isDnD":false,\n'
        f'  "name":"{name}",\n'
        '  "parent":{\n'
        f'    "name":"{parent_name}",\n'
        f'    "path":"{parent}",\n'
        "  },\n"
        '  "resourceType":"GMScript",\n'
        '  "resourceVersion":"2.0",\n'
        "}"
    )


def _yyp(resources: list[str], included: list[str] = ()) -> str:
    lines = [
        "{",
        '  "$GMProject":"v1",',
        '  "%Name":"game",',
        '  "AudioGroups":[',
        '    {"$GMAudioGroup":"v1","%Name":"audiogroup_default","exportDir":"","name":"audiogroup_default","resourceType":"GMAudioGroup","resourceVersion":"2.0","targets":-1,},',
        "  ],",
        '  "configs":{',
        '    "children":[],',
        '    "name":"Default",',
        "  },",
        '  "Folders":[',
        '    {"$GMFolder":"","%Name":"Scripts","folderPath":"folders/Scripts.yy","name":"Scripts","resourceType":"GMFolder","resourceVersion":"2.0",},',
        "  ],",
    ]
    if included:
        lines.append('  "IncludedFiles":[')
        for name in included:
            lines.append(
                f'    {{"$GMIncludedFile":"","%Name":"{name}","CopyToMask":-1,"filePath":"datafiles","name":"{name}","resourceType":"GMIncludedFile","resourceVersion":"2.0",}},'
            )
        lines.append("  ],")
    else:
        lines.append('  "IncludedFiles":[],')
    lines += ['  "name":"game",', '  "resources":[']
    for name in resources:
        lines.append(f'    {{"id":{{"name":"{name}","path":"scripts/{name}/{name}.yy",}},}},')
    lines += [
        "  ],",
        '  "resourceType":"GMProject",',
        '  "resourceVersion":"2.0",',
        '  "RoomOrderNodes":[],',
        '  "TextureGroups":[],',
        "}",
    ]
    return "\n".join(lines)


def _add_script(root: Path, name: str, body: str = "") -> None:
    directory = root / "scripts" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.yy").write_text(_script_yy(name), encoding="utf-8")
    (directory / f"{name}.gml").write_text(body or f"function {name}() {{}}\n", encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    for name in ("alpha", "beta", "zeta"):
        _add_script(root, name)
    (root / "datafiles").mkdir()
    (root / "datafiles" / "a.json").write_text("{}", encoding="utf-8")
    (root / "game.yyp").write_text(_yyp(["alpha", "beta", "zeta"], ["a.json"]), encoding="utf-8")
    return root


@pytest.fixture
def lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "locks"
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(directory))
    return directory


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        capture_output=True,
        check=True,
        text=True,
    ).stdout


@pytest.fixture
def repo(project: Path) -> Path:
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "t@example.com")
    _git(project, "config", "user.name", "t")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "base")
    return project


# ----------------------------------------------------------------------
# Native layout
# ----------------------------------------------------------------------
NATIVE_SAMPLE = (
    "{\n"
    '  "$GMSprite":"v2",\n'
    '  "bbox":0,\n'
    '  "ConfigValues":{\n'
    '    "desktop":{\n'
    '      "textureGroupId":"{ \\"name\\":\\"run\\" }",\n'
    "    },\n"
    "  },\n"
    '  "empty":[],\n'
    '  "frames":[\n'
    '    {"$GMSpriteFrame":"v1","name":"a","nested":{"name":"x","path":"y",},"args":[1,2,],"Channels":{\n'
    '        "0":{"Id":{"name":"a","path":"b",},},\n'
    '      },"opacity":100.0,},\n'
    "  ],\n"
    '  "glyphs":{\n'
    '    "32":{"character":32,"h":1,},\n'
    "  },\n"
    '  "opacity":1E-05,\n'
    '  "parent":{\n'
    '    "name":"A",\n'
    '    "path":"folders/A.yy",\n'
    "  },\n"
    '  "tileMode":[\n'
    "    0,\n"
    "    1,\n"
    "  ],\n"
    "}"
)


def test_native_layout_round_trips_byte_for_byte():
    layout = gm_json.detect_layout(NATIVE_SAMPLE)
    assert layout is not None and not layout.inline_scalar_arrays
    assert gm_json.dumps(gm_json.loads(NATIVE_SAMPLE), layout) == NATIVE_SAMPLE


def test_native_layout_keeps_float_spelling_newlines_and_final_newline():
    text = NATIVE_SAMPLE.replace("\n", "\r\n") + "\r\n"
    layout = gm_json.detect_layout(text)
    assert layout == gm_json.Layout(newline="\r\n", final_newline=True)
    assert gm_json.dumps(gm_json.loads(text), layout) == text
    assert '"opacity":1E-05' in gm_json.dumps(gm_json.loads(text), layout)


def test_legacy_layout_variants_are_detected():
    older = '{\n  "$GMX":"",\n  "list":[\n    {"Channels":{"0":{"a":1,},},"tiles":[1,2,],},\n  ],\n}'
    layout = gm_json.detect_layout(older)
    assert layout is not None and layout.inline_scalar_arrays and layout.inline_channels


def test_pretty_printed_json_is_not_native():
    assert gm_json.detect_layout(json.dumps({"$GMScript": "v1", "a": [1]}, indent=2)) is None
    assert gm_json.detect_layout("") is None
    assert gm_json.detect_layout("[1]") is None
    with pytest.raises(ValueError):
        gm_json.dumps({"a": float("nan")})


def test_save_json_changes_only_the_inserted_lines(project: Path):
    yyp = project / "game.yyp"
    before = yyp.read_text(encoding="utf-8")
    data = load_json_loose(yyp)
    assert insert_into_resources(data["resources"], "gamma", "scripts/gamma/gamma.yy")
    assert insert_into_folders(data["Folders"], "Actors", "folders/Actors.yy")
    save_json(data, str(yyp))
    after = yyp.read_text(encoding="utf-8")
    added = [line for line in after.split("\n") if line not in before.split("\n")]
    removed = [line for line in before.split("\n") if line not in after.split("\n")]
    assert removed == []
    assert len(added) == 2
    names = [entry["id"]["name"] for entry in load_json_loose(yyp)["resources"]]
    assert names == ["alpha", "beta", "gamma", "zeta"]


def test_new_modern_resource_is_written_natively_and_old_format_is_left_alone(tmp_path: Path):
    target = tmp_path / "scripts" / "s.yy"
    save_json({"$GMScript": "v1", "name": "s", "parent": {"name": "A", "path": "folders/A.yy"}}, str(target))
    assert (
        target.read_text()
        == '{\n  "$GMScript":"v1",\n  "name":"s",\n  "parent":{\n    "name":"A",\n    "path":"folders/A.yy",\n  },\n}'
    )
    legacy = tmp_path / "legacy.yy"
    legacy.write_text('{\n  "name": "a",\n  "list": [],\n}', encoding="utf-8")
    save_json({"name": "b", "list": []}, str(legacy))
    assert '"name": "b"' in legacy.read_text()


# ----------------------------------------------------------------------
# Ordering
# ----------------------------------------------------------------------
def test_ide_2026_order_puts_punctuation_before_digits_before_letters():
    values = ["scripts/b/b.yy", "scripts/_a/_a.yy", "scripts/B2/B2.yy", "scripts/1x/1x.yy", "scripts/a/a.yy"]
    assert sorted(values, key=gm_order.ide_2026_key) == [
        "scripts/_a/_a.yy",
        "scripts/1x/1x.yy",
        "scripts/a/a.yy",
        "scripts/b/b.yy",
        "scripts/B2/B2.yy",
    ]
    assert gm_order.ide_2026_key("a") < gm_order.ide_2026_key("A")


def test_insert_ordered_never_moves_existing_entries_of_an_unordered_list():
    entries = [{"id": {"name": n, "path": f"scripts/{n}/{n}.yy"}} for n in ("zeta", "alpha", "mid")]
    index, label = gm_order.insert_ordered(
        entries, {"id": {"name": "beta", "path": "scripts/beta/beta.yy"}}, gm_order.RESOURCE_ORDERINGS
    )
    assert label == "unordered"
    assert [e["id"]["name"] for e in entries if e["id"]["name"] != "beta"] == ["zeta", "alpha", "mid"]
    assert entries[index]["id"]["name"] == "beta"


def test_name_ordered_project_keeps_its_own_rule():
    entries = [
        {"id": {"name": "a_obj", "path": "objects/a_obj/a_obj.yy"}},
        {"id": {"name": "b_script", "path": "scripts/b_script/b_script.yy"}},
        {"id": {"name": "c_obj", "path": "objects/c_obj/c_obj.yy"}},
    ]
    _index, label = gm_order.insert_ordered(
        entries, {"id": {"name": "bb", "path": "sprites/bb/bb.yy"}}, gm_order.RESOURCE_ORDERINGS
    )
    assert label == "name-lowercase"
    assert [e["id"]["name"] for e in entries] == ["a_obj", "b_script", "bb", "c_obj"]


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------
def test_register_unregister_and_explained_refusals(project: Path):
    _add_script(project, "gamma")
    result = yyp_registry.register_assets(project, ["scripts/gamma/gamma.yy"])
    assert result["registered"] == ["scripts/gamma/gamma.yy"]
    assert yyp_registry.register_assets(project, ["scripts/gamma/gamma.yy"])["already_registered"]
    assert gm_json.is_native_layout((project / "game.yyp").read_text())

    with pytest.raises(ValidationError, match="does not exist"):
        yyp_registry.register_assets(project, ["scripts/nope/nope.yy"])
    with pytest.raises(ValidationError, match="not an asset path"):
        yyp_registry.register_assets(project, ["nonsense.txt"])
    _add_script(project, "wrong")
    (project / "scripts/wrong/wrong.yy").write_text(_script_yy("other"), encoding="utf-8")
    with pytest.raises(ValidationError, match="name"):
        yyp_registry.register_assets(project, ["scripts/wrong/wrong.yy"])
    (project / "scripts/wrong/wrong.yy").write_text(
        _script_yy("wrong", "folders/Missing.yy", "Missing"), encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="parent folder"):
        yyp_registry.register_assets(project, ["scripts/wrong/wrong.yy"])

    (project / "game.resource_order").write_text(
        '{\n  "ResourceOrderSettings":[\n    {"name":"gamma","order":1,"path":"scripts/gamma/gamma.yy",},\n  ],\n}',
        encoding="utf-8",
    )
    removed = yyp_registry.unregister_assets(project, ["scripts/gamma/gamma.yy", "scripts/zzz/zzz.yy"])
    assert removed["unregistered"] == ["scripts/gamma/gamma.yy"]
    assert removed["not_registered"] == ["scripts/zzz/zzz.yy"]
    assert "gamma" not in (project / "game.resource_order").read_text()


def test_included_files_configs_audio_groups_and_move(project: Path):
    (project / "datafiles" / "data").mkdir()
    (project / "datafiles" / "data" / "x.json").write_text("{}", encoding="utf-8")
    (project / "datafiles" / "data" / "y.json").write_text("{}", encoding="utf-8")
    added = yyp_registry.add_included_files(project, ["datafiles/data"])
    assert added["added"] == ["datafiles/data/x.json", "datafiles/data/y.json"]
    assert yyp_registry.add_included_files(project, ["datafiles/data/x.json"])["already_included"]
    assert yyp_registry.list_included_files(project, "datafiles/data")["count"] == 2
    with pytest.raises(ValidationError):
        yyp_registry.add_included_files(project, ["datafiles/missing.json"])
    with pytest.raises(ValidationError):
        yyp_registry.add_included_files(project, ["scripts/alpha/alpha.gml"])
    assert yyp_registry.remove_included_files(project, ["datafiles/data"])["removed"] == [
        "datafiles/data/x.json",
        "datafiles/data/y.json",
    ]

    assert yyp_registry.add_config(project, "ios")["added"]
    assert not yyp_registry.add_config(project, "ios")["added"]
    assert yyp_registry.add_config(project, "ios_dev", "ios")["added"]
    assert yyp_registry.list_configs(project)["configs"] == ["Default", "Default/ios", "Default/ios/ios_dev"]
    with pytest.raises(ValidationError):
        yyp_registry.add_config(project, "x", "missing")

    assert yyp_registry.add_audio_group(project, "audiogroup_music")["added"]
    assert not yyp_registry.add_audio_group(project, "audiogroup_music")["added"]
    assert yyp_registry.list_audio_groups(project)["count"] == 2
    with pytest.raises(ValidationError):
        yyp_registry.add_audio_group(project, "bad name")

    data = load_json_loose(project / "game.yyp")
    insert_into_folders(data["Folders"], "Actors", "folders/Actors.yy")
    save_json(data, str(project / "game.yyp"))
    moved = yyp_registry.move_asset(project, "scripts/alpha/alpha.yy", "folders/Actors.yy")
    assert moved["moved"] and load_json_loose(project / "scripts/alpha/alpha.yy")["parent"]["name"] == "Actors"
    assert not yyp_registry.move_asset(project, "scripts/alpha/alpha.yy", "folders/Actors.yy")["moved"]
    with pytest.raises(ValidationError, match="not in the project"):
        yyp_registry.move_asset(project, "scripts/alpha/alpha.yy", "folders/Nope.yy")
    assert gm_json.is_native_layout((project / "game.yyp").read_text())


def test_check_registry_reports_each_problem_with_a_fix(project: Path):
    clean = yyp_registry.check_registry(project)
    assert clean["ok"] and clean["native_layout"] and clean["ordering"]["resources"] == "ide-2026-path"

    _add_script(project, "orphan")
    (project / "scripts" / "beta" / "beta.yy").unlink()
    (project / "datafiles" / "loose.json").write_text("{}", encoding="utf-8")
    (project / "scripts/zeta/zeta.yy").write_text(_script_yy("zeta", "game.yyp", "game"), encoding="utf-8")
    report = yyp_registry.check_registry(project)
    kinds = {p["kind"] for p in report["problems"]} | {w["kind"] for w in report["warnings"]}
    assert {"unregistered_on_disk", "missing_on_disk", "included_file_unregistered", "root_asset"} <= kinds
    assert not report["ok"] and all(p["fix"] for p in report["problems"])
    allowed = yyp_registry.check_registry(project, allow_root_assets=["zet*"])
    assert "root_asset" not in {w["kind"] for w in allowed["warnings"]}


def test_normalize_order_repairs_a_shuffled_project(project: Path):
    (project / "game.yyp").write_text(_yyp(["zeta", "alpha", "beta"], ["a.json"]), encoding="utf-8")
    assert "unordered" in {w["kind"] for w in yyp_registry.check_registry(project)["warnings"]}
    assert yyp_registry.normalize_order(project)["changed"]
    assert yyp_registry.check_registry(project)["ordering"]["resources"] == "ide-2026-path"
    assert not yyp_registry.normalize_order(project)["changed"]


def test_compose_yyp_takes_only_named_registrations(project: Path):
    base = (project / "game.yyp").read_text()
    for name in ("mine", "theirs"):
        _add_script(project, name)
    yyp_registry.register_assets(project, ["scripts/mine/mine.yy", "scripts/theirs/theirs.yy"])
    (project / "datafiles" / "mine.json").write_text("{}", encoding="utf-8")
    yyp_registry.add_included_files(project, ["datafiles/mine.json"])
    working = (project / "game.yyp").read_text()

    entries = yyp_registry.derive_yyp_entries(project, base, ["scripts/mine", "datafiles/mine.json", "scripts/zeta"])
    assert entries == ["scripts/mine/mine.yy", "included:datafiles/mine.json", "scripts/zeta/zeta.yy"]
    composed = yyp_registry.compose_yyp(base, working, entries)
    assert "mine" in composed and "theirs" not in composed and "mine.json" in composed
    assert gm_json.is_native_layout(composed)
    # An entry that no longer exists in the working copy is removed from the base.
    without_alpha = yyp_registry.compose_yyp(
        base,
        base.replace('    {"id":{"name":"alpha","path":"scripts/alpha/alpha.yy",},},\n', ""),
        ["scripts/alpha/alpha.yy"],
    )
    assert "alpha" not in without_alpha


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def test_introduced_errors_ignore_shifted_array_indices():
    before = ["TextureGroups[0].x: bad", "rooms/a.yy.layers[2]: broken", "same", "same"]
    after = ["TextureGroups[1].x: bad", "rooms/a.yy.layers[3]: broken", "same", "same", "same", "new"]
    introduced, preexisting = errors_introduced_by_mutation(before, after)
    assert introduced == ["same", "new"] and len(preexisting) == 4


def test_ide_written_values_are_not_validation_errors(project: Path):
    data = load_json_loose(project / "game.yyp")
    data["TextureGroups"] = [
        {
            "$GMTextureGroup": "",
            "%Name": "Default",
            "ConfigValues": {"desktop": {"groupParent": "null"}},
            "groupParent": None,
            "name": "Default",
            "resourceType": "GMTextureGroup",
            "resourceVersion": "2.0",
        }
    ]
    save_json(data, str(project / "game.yyp"))
    assert validate_project_after_mutation(project).errors == []


def test_preexisting_errors_do_not_block_a_mutation_but_new_ones_do(project: Path, monkeypatch: pytest.MonkeyPatch):
    (project / "scripts" / "beta" / "beta.yy").unlink()  # an old, unrelated problem
    assert validate_project_after_mutation(project).errors

    tx = GameMakerProjectTransaction(project, "gm_yyp_register")
    tx.begin()
    try:
        _add_script(project, "gamma")
        yyp_registry.register_assets(project, ["scripts/gamma/gamma.yy"])
        tx.capture_mutation_state()
        committed = tx.commit()
    finally:
        tx.cleanup()
    assert committed["committed"] and committed["validation"]["preexisting_error_count"] == 1
    assert (project / ".gms_mcp" / "cache" / "validation-baseline.json").is_file()

    tx = GameMakerProjectTransaction(project, "gm_yyp_register")
    tx.begin()
    try:
        data = load_json_loose(project / "game.yyp")
        insert_into_resources(data["resources"], "ghost", "scripts/ghost/ghost.yy")
        save_json(data, str(project / "game.yyp"))
        tx.capture_mutation_state()
        with pytest.raises(TransactionValidationError) as failure:
            tx.commit()
    finally:
        tx.cleanup()
    assert any("ghost" in error for error in failure.value.details["validation"]["errors"])
    assert "ghost" not in (project / "game.yyp").read_text()

    monkeypatch.setenv("GMS_MCP_STRICT_PROJECT_VALIDATION", "1")
    tx = GameMakerProjectTransaction(project, "gm_yyp_register")
    tx.begin()
    try:
        _add_script(project, "delta")
        yyp_registry.register_assets(project, ["scripts/delta/delta.yy"])
        tx.capture_mutation_state()
        with pytest.raises(TransactionValidationError):
            tx.commit()
    finally:
        tx.cleanup()


def test_named_events_resolve_to_their_numbers():
    assert parse_event_spec("draw_gui").canonical == "draw:64"
    assert parse_event_spec("End Step").canonical == "step:2"
    assert parse_event_spec("async_networking").canonical == "other:68"
    assert parse_event_spec("user_event_3").canonical == "other:13"
    assert parse_event_spec("room_start").canonical == "other:4"
    with pytest.raises(ValidationError, match="begin_step"):
        parse_event_spec("drawgui")


# ----------------------------------------------------------------------
# Locks
# ----------------------------------------------------------------------
def test_directory_lock_is_exclusive_and_script_compatible(lock_dir: Path):
    first = agent_locks.DirectoryLock("gamerun.lock", purpose="one")
    assert first.try_acquire() and (lock_dir / "gamerun.lock").is_dir()
    assert list((lock_dir / "gamerun.lock").iterdir()) == []  # rmdir from a shell script must work
    second = agent_locks.DirectoryLock("gamerun.lock")
    assert not second.try_acquire()
    with pytest.raises(agent_locks.LockTimeoutError, match="held by process"):
        second.acquire(timeout_seconds=0, sleep=lambda _s: None)
    assert agent_locks.lock_status(2)["locks"][1]["owner"]["purpose"] == "one"
    first.release()
    assert second.try_acquire()
    second.release()
    assert not (lock_dir / "gamerun.lock").exists()


def test_stale_locks_are_reclaimed(lock_dir: Path):
    lock_dir.mkdir()
    (lock_dir / "repo.lock").mkdir()
    (lock_dir / "repo.lock.owner").write_text(
        json.dumps({"pid": 2**30, "host": socket.gethostname()}), encoding="utf-8"
    )
    assert agent_locks.DirectoryLock("repo.lock").try_acquire()  # dead owner on this host

    (lock_dir / "old.lock").mkdir()
    os.utime(lock_dir / "old.lock", (time.time() - 5000, time.time() - 5000))
    assert not agent_locks.DirectoryLock("old.lock", stale_seconds=9000).try_acquire()
    assert agent_locks.DirectoryLock("old.lock", stale_seconds=100).try_acquire()


def test_build_slots_count(lock_dir: Path):
    one = agent_locks.BuildSlot(2).acquire()
    two = agent_locks.BuildSlot(2).acquire()
    with pytest.raises(agent_locks.LockTimeoutError, match="build slots"):
        agent_locks.BuildSlot(2).acquire(timeout_seconds=0, sleep=lambda _s: None)
    one.release()
    with agent_locks.BuildSlot(2) as three:
        assert three.waited_seconds < 5
    two.release()
    assert not any(lock_dir.glob("build_slot_*"))


# ----------------------------------------------------------------------
# Snapshots, compile retry, test verdicts
# ----------------------------------------------------------------------
def _toolchain(tmp_path: Path) -> snapshot_build.Toolchain:
    return snapshot_build.Toolchain(
        igor=tmp_path / "Igor",
        runtime_path=tmp_path / "runtime-2026.0.0.23",
        license_file=tmp_path / "user" / "licence.plist",
        prefabs_path=None,
        runtime_version="2026.0.0.23",
    )


def test_working_tree_snapshot_copies_everything_but_infrastructure(repo: Path, tmp_path: Path):
    (repo / ".gms_mcp").mkdir(exist_ok=True)
    (repo / ".gms_mcp" / "x").write_text("x")
    (repo / "scripts" / "alpha" / "alpha.gml").write_text("// edited\n")
    info = snapshot_build.create_snapshot(repo, tmp_path / "snap")
    assert info["mode"] == "working-tree"
    assert (tmp_path / "snap" / "scripts/alpha/alpha.gml").read_text() == "// edited\n"
    assert not (tmp_path / "snap" / ".gms_mcp").exists() and not (tmp_path / "snap" / ".git").exists()
    with pytest.raises(snapshot_build.SnapshotError, match="yyp_entries only applies"):
        snapshot_build.create_snapshot(repo, tmp_path / "snap2", yyp_entries=["scripts/a/a.yy"])


def test_isolated_snapshot_is_base_revision_plus_named_paths(repo: Path, tmp_path: Path):
    for name in ("mine", "theirs"):
        _add_script(repo, name)
    yyp_registry.register_assets(repo, ["scripts/mine/mine.yy", "scripts/theirs/theirs.yy"])
    (repo / "scripts" / "alpha" / "alpha.gml").write_text("// someone else's half-written edit\n")
    import shutil

    shutil.rmtree(repo / "scripts" / "zeta")
    yyp_registry.unregister_assets(repo, ["scripts/zeta/zeta.yy"])

    info = snapshot_build.create_snapshot(repo, tmp_path / "snap", isolate_paths=["scripts/mine", "scripts/zeta"])
    snap = tmp_path / "snap"
    assert info["mode"] == "isolated" and "scripts/mine/mine.yy" in info["yyp_entries"]
    assert (snap / "scripts/mine/mine.yy").is_file() and not (snap / "scripts/theirs").exists()
    assert (snap / "scripts/alpha/alpha.gml").read_text() == "function alpha() {}\n"
    assert not (snap / "scripts/zeta").exists()
    yyp_text = (snap / "game.yyp").read_text()
    assert "mine" in yyp_text and "theirs" not in yyp_text and "zeta" not in yyp_text

    base = snapshot_build.create_snapshot(repo, tmp_path / "base", base_only=True)
    assert base["isolated_paths"] == [] and (tmp_path / "base" / "scripts/zeta/zeta.yy").is_file()
    with pytest.raises(snapshot_build.SnapshotError, match="not a path inside the project"):
        snapshot_build.create_snapshot(repo, tmp_path / "bad", isolate_paths=["../outside"])
    with pytest.raises(snapshot_build.SnapshotError, match="could not read revision"):
        snapshot_build.create_snapshot(repo, tmp_path / "bad", isolate_paths=["scripts/mine"], ref="no-such-ref")


def test_isolation_needs_git(project: Path, tmp_path: Path):
    with pytest.raises(snapshot_build.SnapshotError, match="not inside a git repository"):
        snapshot_build.create_snapshot(project, tmp_path / "snap", isolate_paths=["scripts/alpha"])


def test_test_injection_only_ever_touches_a_snapshot(repo: Path, tmp_path: Path):
    code = "function agent_test_step(_frame) { test_end(); }"
    with pytest.raises(snapshot_build.SnapshotError, match="Refusing to inject"):
        snapshot_build.inject_test_script(repo, code)
    snapshot_build.create_snapshot(repo, tmp_path / "snap")
    snap = tmp_path / "snap"
    (snap / ".gms-mcp-snapshot").write_text("snapshot\n")
    with pytest.raises(snapshot_build.SnapshotError, match="agent_test_step"):
        snapshot_build.inject_test_script(snap, "function nope() {}")
    relative = snapshot_build.inject_test_script(snap, code)
    assert relative == "scripts/__agent_test/__agent_test.yy"
    text = (snap / "scripts/__agent_test/__agent_test.gml").read_text()
    assert "[TEST_RESULT]" in text and code in text
    assert "__agent_test" in (snap / "game.yyp").read_text() and "__agent_test" not in (repo / "game.yyp").read_text()
    assert yyp_registry.check_registry(snap, allow_root_assets=["__agent_*"])["ok"]

    with pytest.raises(snapshot_build.SnapshotError, match="exactly one"):
        snapshot_build.load_test_source(repo, None, None)
    with pytest.raises(snapshot_build.SnapshotError, match="not found"):
        snapshot_build.load_test_source(repo, "missing.gml", None)
    (repo / "t.gml").write_text(code)
    assert snapshot_build.load_test_source(repo, "t.gml", None) == code


def _fake_igor(outcomes: list[str]):
    calls: list[list[str]] = []

    def run(command: list[str], log_path: Path, _timeout: float) -> int:
        calls.append(command)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        out_dir = Path(next(arg for arg in command if arg.startswith("/of=")).removeprefix("/of=")).parent
        if outcome == "crash":
            log_path.write_text("Loading project\nFatal error. System.AccessViolationException: boom\n   at System.X\n")
        elif outcome == "error":
            log_path.write_text("Error : gml_GlobalScript_foo(3) : unknown variable\nFinal Compile finished.\n")
        elif outcome == "nothing":
            log_path.write_text("Licence problem\n")
        else:
            log_path.write_text("Warning : unused thing\nFinal Compile finished.\nIgor complete.\n")
            with zipfile.ZipFile(out_dir / "game.zip", "w") as archive:
                archive.writestr("game.ios", "data")
                archive.writestr("assets/extra.txt", "x")
        return 0

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_igor_access_violation_is_retried_until_it_compiles(repo: Path, tmp_path: Path, lock_dir: Path):
    igor = _fake_igor(["crash", "crash", "ok"])
    result = snapshot_build.compile_snapshot(repo, tmp_path / "work", _toolchain(tmp_path), attempts=5, run_igor=igor)
    assert result.ok and result.attempts == 3 and result.access_violation_retries == 2
    assert result.warnings == ["Warning : unused thing"] and result.game_archive.name == "game.zip"
    assert "/project=" in " ".join(igor.calls[0]) and igor.calls[0][-3:] == ["--", "Mac", "PackageZip"]
    assert not any(lock_dir.glob("build_slot_*"))
    for platform, action in (("Android", "Package"), ("ios", "Package"), ("Windows", "PackageZip")):
        mobile = _fake_igor(["ok"])
        snapshot_build.compile_snapshot(
            repo, tmp_path / f"work_{platform}", _toolchain(tmp_path), platform=platform, run_igor=mobile
        )
        assert mobile.calls[0][-3:] == ["--", platform, action]


def test_signing_errors_after_the_compile_do_not_fail_a_desktop_snapshot(repo: Path, tmp_path: Path, lock_dir: Path):
    def igor(command: list[str], log_path: Path, _timeout: float) -> int:
        out_dir = Path(next(a for a in command if a.startswith("/of=")).removeprefix("/of=")).parent
        log_path.write_text(
            "Final Compile...Final Compile finished.\nSaving IFF file\n"
            "Error : Could not find matching certificate for Developer ID Application:\nIgor complete.\n"
        )
        with zipfile.ZipFile(out_dir / "game.zip", "w") as archive:
            archive.writestr("game.ios", "data")
        return 1

    desktop = snapshot_build.compile_snapshot(repo, tmp_path / "d", _toolchain(tmp_path), run_igor=igor)
    assert desktop.ok and desktop.errors == [] and len(desktop.packaging_errors) == 1
    assert "no distributable package" in desktop.message
    mobile = snapshot_build.compile_snapshot(
        repo, tmp_path / "m", _toolchain(tmp_path), platform="Android", run_igor=igor
    )
    assert not mobile.ok and mobile.errors == desktop.packaging_errors


def test_non_native_project_files_still_compose_and_normalize(project: Path):
    pretty = json.dumps(load_json_loose(project / "game.yyp"), indent=2)
    (project / "game.yyp").write_text(pretty, encoding="utf-8")
    assert "non_native_layout" in {w["kind"] for w in yyp_registry.check_registry(project)["warnings"]}
    assert "alpha" in yyp_registry.compose_yyp(pretty, pretty, ["scripts/alpha/alpha.yy"])
    assert yyp_registry.normalize_order(project)["changed"]
    assert gm_json.is_native_layout((project / "game.yyp").read_text())
    assert gm_json.detect_newline("a\r\nb") == "\r\n" and gm_json.detect_newline("a\nb") == "\n"


def test_compiler_errors_are_final_and_crash_exhaustion_is_explained(repo: Path, tmp_path: Path, lock_dir: Path):
    igor = _fake_igor(["error"])
    failed = snapshot_build.compile_snapshot(repo, tmp_path / "w1", _toolchain(tmp_path), attempts=5, run_igor=igor)
    assert not failed.ok and failed.attempts == 1 and "isolate_paths" in failed.message
    assert failed.errors == ["Error : gml_GlobalScript_foo(3) : unknown variable"]

    crashed = snapshot_build.compile_snapshot(
        repo, tmp_path / "w2", _toolchain(tmp_path), attempts=3, run_igor=_fake_igor(["crash"])
    )
    assert not crashed.ok and crashed.attempts == 3 and "not an error in the project" in crashed.message

    silent = snapshot_build.compile_snapshot(
        repo, tmp_path / "w3", _toolchain(tmp_path), attempts=3, run_igor=_fake_igor(["nothing"])
    )
    assert not silent.ok and silent.attempts == 1 and "no compiler error" in silent.message
    assert snapshot_build.tail_lines(tmp_path / "w2" / "build.log", 5)[-1].startswith("Fatal error")


def test_run_log_verdicts():
    patterns = ["ERROR in action number", "FATAL ERROR"]
    passed = snapshot_build.parse_run_log(
        "[TEST_SAVE_DIR] x\n[TEST] PASS a\n[TEST] shot s.png\n[TEST_RESULT] PASS failures=0\n",
        runtime_error_patterns=patterns,
    )
    assert passed["status"] == "TEST_PASSED" and passed["passed"] and len(passed["test_lines"]) == 3
    failed = snapshot_build.parse_run_log("[TEST_SAVE_DIR] x\n[TEST] FAIL b\n[TEST_RESULT] FAIL failures=1\n")
    assert failed["status"] == "TEST_FAILED" and failed["failed_checks"] == ["[TEST] FAIL b"]
    errored = snapshot_build.parse_run_log(
        "[TEST_SAVE_DIR] x\nERROR in action number 1\nof Step Event\n[TEST_RESULT] PASS failures=0\n",
        runtime_error_patterns=patterns,
    )
    assert errored["status"] == "TEST_FAILED" and errored["runtime_errors"] and "runtime error" in errored["note"]
    timeout = snapshot_build.parse_run_log("[TEST_SAVE_DIR] x\n", timed_out=True)
    assert timeout["status"] == "TEST_TIMEOUT" and "test_end()" in timeout["note"]
    never = snapshot_build.parse_run_log("boot\n")
    assert never["status"] == "TEST_FAILED" and "never started" in never["note"]


def test_run_test_pipeline_reports_pass_fail_and_build_failure(repo: Path, tmp_path: Path, lock_dir: Path, monkeypatch):
    monkeypatch.setenv("GMS_MCP_SNAPSHOT_WORK_DIR", str(tmp_path / "work"))
    code = 'function agent_test_step(_frame) { test_check(true, "ok"); test_end(); }'
    seen: dict = {}

    def run_game(archive: Path, _tools, *, label, run_dir: Path, **options):
        seen["snapshot_has_test"] = (archive.parent.parent / "project/scripts/__agent_test/__agent_test.gml").is_file()
        seen["timeout"] = options["timeout_seconds"]
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.log").write_text("[TEST_SAVE_DIR] d\n[TEST] PASS ok\n[TEST_RESULT] PASS failures=0\n")
        shot = run_dir / "shots" / "__agent_shot_a.png"
        shot.parent.mkdir(exist_ok=True)
        shot.write_bytes(b"png")
        return {
            "timed_out": False,
            "waited_seconds": 1.0,
            "waited_for_lock_seconds": 0.0,
            "run_log": run_dir / "run.log",
            "screenshots": [shot],
        }

    (repo / ".gms-mcp.json").write_text(json.dumps({"test": {"timeout_seconds": 33}}))
    result = snapshot_build.run_test(
        repo,
        test_code=code,
        label="unit test!",
        run_igor=_fake_igor(["crash", "ok"]),
        run_game=run_game,
        toolchain=_toolchain(tmp_path),
    )
    assert result["status"] == "TEST_PASSED" and result["ok"] and result["igor_crash_retries"] == 1
    assert result["label"] == "unit_test" and seen == {"snapshot_has_test": True, "timeout": 33.0}
    assert result["screenshots"] == [".gms_mcp/runs/unit_test/shots/__agent_shot_a.png"]
    assert result["run_log"] == ".gms_mcp/runs/unit_test/run.log" and result["build_log"].endswith("build.log")
    assert not (repo / "scripts" / "__agent_test").exists() and not list((tmp_path / "work").glob("*"))

    log = snapshot_build.read_run_artifact(repo, "unit test!", "run", 10, r"\[TEST\]")
    assert log["lines"] == ["[TEST] PASS ok"] and log["screenshots"]
    with pytest.raises(snapshot_build.SnapshotError, match="Labels with saved runs: unit_test"):
        snapshot_build.read_run_artifact(repo, "other")
    with pytest.raises(snapshot_build.SnapshotError):
        snapshot_build.read_run_artifact(repo, "unit test!", "bogus")

    broken = snapshot_build.run_test(
        repo,
        test_code=code,
        label="broken",
        run_igor=_fake_igor(["error"]),
        run_game=run_game,
        toolchain=_toolchain(tmp_path),
    )
    assert broken["status"] == "BUILD_FAILED" and not broken["ok"] and broken["errors"]


def test_platform_names_and_runner_staging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    assert snapshot_build.igor_platform("macOS") == "Mac" and snapshot_build.igor_platform("iOS") == "ios"
    assert snapshot_build.igor_platform("Android") == "Android"
    with pytest.raises(snapshot_build.SnapshotError, match="Unknown platform"):
        snapshot_build.igor_platform("Dreamcast")
    monkeypatch.setenv("GMS_MCP_RUN_STAGING_DIR", str(tmp_path / "my-game" / "runs"))
    assert "-game" not in str(snapshot_build._runner_staging_root()).lower()
    monkeypatch.setenv("GMS_MCP_RUN_STAGING_DIR", str(tmp_path / "fine"))
    assert snapshot_build._runner_staging_root() == tmp_path / "fine"


# ----------------------------------------------------------------------
# Partial commits
# ----------------------------------------------------------------------
def test_stage_paths_commits_only_named_registrations(repo: Path, lock_dir: Path):
    for name in ("mine", "theirs"):
        _add_script(repo, name)
    yyp_registry.register_assets(repo, ["scripts/mine/mine.yy", "scripts/theirs/theirs.yy"])
    working_before = (repo / "game.yyp").read_text()

    staged = stage_paths(repo, ["scripts/mine"])
    assert staged["yyp_entries"] == ["scripts/mine/mine.yy"] and not staged["committed"]
    index_yyp = _git(repo, "show", ":game.yyp")
    assert "mine" in index_yyp and "theirs" not in index_yyp
    assert (repo / "game.yyp").read_text() == working_before
    assert not (lock_dir / "repo.lock").exists()

    committed = stage_paths(repo, ["scripts/mine"], commit_message="Add mine")
    assert committed["committed"] and "Add mine" in committed["commit"]
    assert "theirs" not in _git(repo, "show", "HEAD:game.yyp")
    assert "scripts/theirs/" in _git(repo, "status", "--short")

    from gms_helpers.vcs_stage import VcsError

    with pytest.raises(VcsError, match="No paths"):
        stage_paths(repo, [])
    with pytest.raises(VcsError, match=r"\.\."):
        stage_paths(repo, ["../x"])
    whole = stage_paths(repo, ["game.yyp"])
    assert whole["yyp_mode"] == "whole file" and "theirs" in _git(repo, "show", ":game.yyp")


# ----------------------------------------------------------------------
# Runtime bridge and live reload
# ----------------------------------------------------------------------
def test_bridge_results_are_parsed():
    assert live_session.parse_bridge_result("pong") == {"ok": True, "result": "pong"}
    assert live_session.parse_bridge_result('{"a":1}')["data"] == {"a": 1}
    failed = live_session.parse_bridge_result("ERR:unknown_command nope (send help)")
    assert not failed["ok"] and failed["error_code"] == "unknown_command" and failed["error"].startswith("nope")
    assert live_session.parse_bridge_result("{not json")["ok"]


def test_bridge_server_picks_a_free_port_and_records_the_handshake():
    server = BridgeServer(port=0)
    assert server.start() and server.port != 0
    client = socket.create_connection(("127.0.0.1", server.port), timeout=2)
    try:
        client.sendall(b'HELLO:{"protocol":2,"commands":["ping"]}\n')
        deadline = time.time() + 3
        while server.hello is None and time.time() < deadline:
            time.sleep(0.02)
        assert server.hello == {"protocol": 2, "commands": ["ping"]}
        assert server.get_status()["hello"]["protocol"] == 2

        def answer() -> None:
            line = client.recv(4096).decode()
            command_id = line[4:].split("|", 1)[0]
            client.sendall(f'RSP:{command_id}|{{"room":"r_menu"}}\n'.encode())

        import threading

        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        result = server.send_command("state", timeout=3)
        assert live_session.parse_bridge_result(result.result)["data"] == {"room": "r_menu"}
    finally:
        client.close()
        server.stop()


def test_live_session_requests_without_a_game_explain_what_to_do(project: Path):
    assert live_session.status(project)["running"] is False
    assert live_session.stop(project)["stopped"] is False
    with pytest.raises(live_session.LiveSessionError, match="gm_game_start"):
        live_session.command(project, "ping")


def test_live_reload_is_driven_by_project_configuration(project: Path):
    assert live_reload.status(project)["configured"] is False
    with pytest.raises(live_reload.LiveReloadError, match="live_reload"):
        live_reload.start(project)
    (project / "status.json").write_text('{"serving": true}')
    (project / ".gms-mcp.json").write_text(
        json.dumps(
            {
                "live_reload": {
                    "start": [sys.executable, "-c", "print('started {project}')"],
                    "stop": [sys.executable, "-c", "print('stopped')"],
                    "status": [sys.executable, "-c", 'print(\'{"serving": true, "clients": 1}\')'],
                    "status_file": "status.json",
                }
            }
        )
    )
    assert live_reload.start(project)["ok"]
    assert "started" in (project / ".gms_mcp" / "live_reload.log").read_text()
    assert live_reload.status(project)["status"] == {"serving": True, "clients": 1}
    assert live_reload.stop(project)["stopped"]
    (project / ".gms-mcp.json").write_text(json.dumps({"live_reload": {"stop": "gms-fire stop"}}))
    with pytest.raises(live_reload.LiveReloadError, match="list of strings"):
        live_reload.stop(project)
    (project / ".gms-mcp.json").write_text(json.dumps({"live_reload": {"stop": ["definitely-not-installed-tool"]}}))
    with pytest.raises(live_reload.LiveReloadError, match="not installed"):
        live_reload.stop(project)


def test_project_can_choose_its_verification_mode(project: Path, monkeypatch: pytest.MonkeyPatch):
    from gms_helpers.project_config import project_setting
    from gms_mcp.server.verification_policy import current_verification_mode, decide_mutation_verification

    monkeypatch.delenv("GMS_MCP_POST_MUTATION_VERIFY", raising=False)
    monkeypatch.delenv("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", raising=False)
    assert current_verification_mode(project) == "smart"
    (project / ".gms-mcp.json").write_text(
        json.dumps({"verification": {"post_mutation": "off"}, "build": {"igor_attempts": 30}})
    )
    assert current_verification_mode(project) == "off"
    assert decide_mutation_verification("gm_create_script", project).action == "skip"
    assert decide_mutation_verification("gm_create_script").action == "compile"
    monkeypatch.setenv("GMS_MCP_POST_MUTATION_VERIFY", "always")
    assert current_verification_mode(project) == "always"
    assert project_setting(project, "build.igor_attempts") == 30
    monkeypatch.setenv("GMS_MCP_SNAPSHOT_IGOR_ATTEMPTS", "7")
    assert project_setting(project, "build.igor_attempts") == 7
    assert project_setting(project, "test.script_name") == "__agent_test"
    assert project_setting(project, "nope.missing", "fallback") == "fallback"


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.pid = 4242

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def _fake_game_endpoint(port: int, save_dir: Path, stop: threading.Event) -> None:
    """A minimal protocol 2 endpoint: handshake, then answer commands until told to stop."""
    client = socket.create_connection(("127.0.0.1", port), timeout=3)
    client.settimeout(0.2)
    client.sendall(b'HELLO:{"protocol":2,"game":"Fake","commands":["ping","state","screenshot"]}\n')
    buffer = ""
    while not stop.is_set():
        try:
            data = client.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        if not data:
            break
        buffer += data.decode()
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            command_id, _, command = line[4:].partition("|")
            if command == "ping":
                answer = "pong"
            elif command == "state":
                answer = '{"room":"r_menu","fps":60}'
            elif command.startswith("screenshot"):
                shot = save_dir / f"__agent_shot_{command.split(' ', 1)[1]}.png"
                shot.write_bytes(b"png")
                answer = json.dumps({"file": str(shot)})
            else:
                answer = "ERR:unknown_command " + command
            client.sendall(f"RSP:{command_id}|{answer}\n".encode())
    client.close()


def test_live_session_start_command_screenshot_and_stop(repo: Path, tmp_path: Path, lock_dir: Path, monkeypatch):
    import threading

    save_dir = tmp_path / "save"
    save_dir.mkdir()
    staging = tmp_path / "staging"
    stop_endpoint = threading.Event()
    process = _FakeProcess()

    def fake_compile(root, **options):
        work = tmp_path / "work"
        (work / "out").mkdir(parents=True, exist_ok=True)
        archive = work / "out" / "game.zip"
        archive.write_bytes(b"zip")
        build = snapshot_build.BuildResult(ok=options["label"] != "broken", status="COMPILE_OK", game_archive=archive)
        public = {
            "ok": build.ok,
            "status": "COMPILE_OK" if build.ok else "BUILD_FAILED",
            "label": options["label"],
            "errors": [],
        }
        return public, build, work, _toolchain(tmp_path)

    def fake_launch(_runner, staging_dir, _game_file, run_dir, environment):
        port = int(environment[live_session.BRIDGE_PORT_ENVIRONMENT_VARIABLE])
        threading.Thread(target=_fake_game_endpoint, args=(port, save_dir, stop_endpoint), daemon=True).start()
        log = staging_dir / "debug.txt"
        log.write_text("boot\nrunning\nERROR nothing\n")
        return process, log

    def fake_stage(_archive, _label):
        staging.mkdir(exist_ok=True)
        return staging, staging / "game.ios"

    monkeypatch.setattr(snapshot_build, "snapshot_compile", fake_compile)
    monkeypatch.setattr(snapshot_build, "require_mac_runner", lambda _tools: tmp_path / "Mac_Runner")
    monkeypatch.setattr(snapshot_build, "stage_game_archive", fake_stage)
    monkeypatch.setattr(snapshot_build, "launch_mac_runner", fake_launch)
    monkeypatch.setattr(snapshot_build, "_mac_save_directory", lambda: save_dir)

    failed = live_session.start(repo, label="broken")
    assert failed["connected"] is False and failed["status"] == "BUILD_FAILED"
    assert live_session.get_session(repo) is None

    try:
        started = live_session.start(repo, label="live", connect_timeout_seconds=5)
        assert started["status"] == "RUNNING" and started["connected"] and started["endpoint"]["game"] == "Fake"
        assert (lock_dir / "gamerun.lock").is_dir()
        with pytest.raises(live_session.LiveSessionError, match="already running"):
            live_session.start(repo, label="second")

        assert live_session.command(repo, "ping")["result"] == "pong"
        assert live_session.command(repo, "state")["data"] == {"room": "r_menu", "fps": 60}
        unknown = live_session.command(repo, "dance")
        assert not unknown["ok"] and unknown["error_code"] == "unknown_command"
        with pytest.raises(live_session.LiveSessionError, match="single line"):
            live_session.command(repo, "a\nb")

        shot = live_session.screenshot(repo, "menu view")
        assert shot == {"ok": True, "screenshot": ".gms_mcp/runs/live/shots/menu_view.png", "message": shot["message"]}
        assert (repo / shot["screenshot"]).read_bytes() == b"png"

        status = live_session.status(repo)
        assert status["running"] and status["connected"] and status["label"] == "live"
        log = live_session.game_log(repo, 10, "ERROR")
        assert log["lines"] == ["ERROR nothing"] and log["running"]
        with pytest.raises(live_session.LiveSessionError, match="regular expression"):
            live_session.game_log(repo, 10, "(")
    finally:
        stop_endpoint.set()
        stopped = live_session.stop(repo)
    assert stopped["stopped"] and stopped["run_log"] == ".gms_mcp/runs/live/run.log"
    assert stopped["screenshots"] == [".gms_mcp/runs/live/shots/menu_view.png"]
    assert process.returncode == -15 and not (lock_dir / "gamerun.lock").exists() and not staging.exists()
    assert live_session.status(repo)["running"] is False


def test_live_session_reports_a_game_that_exits_or_never_connects(
    repo: Path, tmp_path: Path, lock_dir: Path, monkeypatch
):
    process = _FakeProcess()
    staging = tmp_path / "staging"

    def fake_compile(root, **options):
        work = tmp_path / "work"
        (work / "out").mkdir(parents=True, exist_ok=True)
        archive = work / "out" / "game.zip"
        archive.write_bytes(b"zip")
        return (
            {"ok": True, "status": "COMPILE_OK", "label": options["label"], "errors": []},
            snapshot_build.BuildResult(ok=True, status="COMPILE_OK", game_archive=archive),
            work,
            _toolchain(tmp_path),
        )

    def fake_stage(_archive, _label):
        staging.mkdir(exist_ok=True)
        return staging, staging / "game.ios"

    def fake_launch(_runner, staging_dir, _game_file, _run_dir, _environment):
        log = staging_dir / "debug.txt"
        log.write_text("ERROR in action number 1\n")
        return process, log

    monkeypatch.setattr(snapshot_build, "snapshot_compile", fake_compile)
    monkeypatch.setattr(snapshot_build, "require_mac_runner", lambda _tools: tmp_path / "Mac_Runner")
    monkeypatch.setattr(snapshot_build, "stage_game_archive", fake_stage)
    monkeypatch.setattr(snapshot_build, "launch_mac_runner", fake_launch)
    monkeypatch.setattr(snapshot_build, "_mac_save_directory", lambda: tmp_path / "nosave")

    silent = live_session.start(repo, label="silent", connect_timeout_seconds=0.3)
    assert silent["status"] == "RUNNING_NOT_CONNECTED" and "GMS_MCP_BRIDGE_PORT" in silent["message"]
    with pytest.raises(live_session.LiveSessionError, match="not connected"):
        live_session.command(repo, "ping")
    process.returncode = 1
    with pytest.raises(live_session.LiveSessionError, match="has exited"):
        live_session.command(repo, "ping")
    assert live_session.stop(repo)["exited_before_stop"]

    exited = live_session.start(repo, label="crash", connect_timeout_seconds=0.3)
    assert exited["status"] == "GAME_EXITED" and not exited["ok"] and exited["log_tail"] == ["ERROR in action number 1"]
    assert live_session.get_session(repo) is None and not (lock_dir / "gamerun.lock").exists()
    live_session.stop_all()


def test_lock_liveness_never_signals_on_windows(monkeypatch):
    """os.kill(pid, 0) is CTRL_C_EVENT on Windows and would interrupt the server itself."""
    from gms_helpers import agent_locks

    calls: list[int] = []
    monkeypatch.setattr(agent_locks.os, "name", "nt")
    monkeypatch.setattr(agent_locks.os, "kill", lambda *_args: (_ for _ in ()).throw(AssertionError("signalled")))
    monkeypatch.setattr(agent_locks, "_windows_process_alive", lambda pid: calls.append(pid) or True)
    assert agent_locks._process_alive(4321) is True
    assert calls == [4321]
