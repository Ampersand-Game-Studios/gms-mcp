"""Room operations must accept root aliases without accepting project escapes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gms_helpers.project_validation import validate_project_after_mutation
from gms_helpers.room_helper import delete_room, duplicate_room, rename_room
from gms_helpers.synthetic_project import create_synthetic_project
from gms_helpers.utils import load_json_loose


OPERATIONS = {"duplicate": duplicate_room, "rename": rename_room, "delete": delete_room}


@pytest.fixture
def aliased_project(tmp_path, monkeypatch, request):
    root = tmp_path / "canonical_project"
    alias = tmp_path / "project_alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")
    create_synthetic_project(root, project_name="alias_fixture", ide_version=getattr(request, "param", "2024.14.3.217"))
    assert alias.samefile(root)
    assert alias.resolve() == root.resolve()
    monkeypatch.chdir(root)
    # POSIX getcwd normally erases symlink aliases. Model the Windows filesystem
    # boundary returning an alternate spelling of the actual working directory.
    monkeypatch.setattr(os, "getcwd", lambda: str(alias))
    # Python 3.10 caches os.getcwd in pathlib's filesystem accessor. Patch the
    # public boundary too so every supported interpreter sees the same alias.
    monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: alias))
    assert Path.cwd() == alias
    return root, alias


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("aliased_project", ["2024.14.3.217", "2026.0.0.16"], indirect=True)
def test_room_mutation_accepts_equivalent_root_alias(aliased_project, operation):
    root, alias = aliased_project
    yyp = root / "alias_fixture.yyp"
    assert alias.samefile(root)
    args = ("r_mcp_smoke",) if operation == "delete" else ("r_mcp_smoke", "r_updated")

    assert OPERATIONS[operation](*args)

    project = load_json_loose(yyp)
    expected_names = {
        "duplicate": {"r_mcp_smoke", "r_updated"},
        "rename": {"r_updated"},
        "delete": set(),
    }[operation]
    assert {entry["id"]["name"] for entry in project["resources"]} == expected_names
    assert {entry["roomId"]["name"] for entry in project["RoomOrderNodes"]} == expected_names
    for entry in project["resources"]:
        name = entry["id"]["name"]
        assert entry["id"]["path"] == f"rooms/{name}/{name}.yy"
        assert load_json_loose(root / entry["id"]["path"])["name"] == name
    assert validate_project_after_mutation(root).success


@pytest.mark.parametrize("operation", OPERATIONS)
def test_room_mutation_rejects_escaped_room_under_aliased_root(aliased_project, operation, tmp_path):
    root, _ = aliased_project
    room_dir = root / "rooms" / "r_mcp_smoke"
    outside = tmp_path / "external_room"
    room_dir.rename(outside)
    try:
        room_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")
    before = {p.relative_to(outside): p.read_bytes() for p in outside.rglob("*") if p.is_file()}
    yyp_before = (root / "alias_fixture.yyp").read_bytes()
    args = ("r_mcp_smoke",) if operation == "delete" else ("r_mcp_smoke", "r_updated")

    assert not OPERATIONS[operation](*args)

    assert {p.relative_to(outside): p.read_bytes() for p in outside.rglob("*") if p.is_file()} == before
    assert (root / "alias_fixture.yyp").read_bytes() == yyp_before
    assert not (root / "rooms" / "r_updated").exists()
