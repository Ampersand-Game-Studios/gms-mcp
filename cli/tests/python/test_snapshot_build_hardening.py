#!/usr/bin/env python3
"""Snapshot copies: git filters, LFS pointers, locking, skipped folders, BOMs and test settings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers import snapshot_build, transactions  # noqa: E402
from gms_helpers.exceptions import ValidationError  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        capture_output=True,
        check=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "game"
    (root / "scripts" / "s").mkdir(parents=True)
    (root / "game.yyp").write_text('{"resources":[],"Folders":[]}', encoding="utf-8")
    (root / "scripts" / "s" / "s.gml").write_bytes(b"a = 1;\nb = 2;\n")
    return root


def _commit(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")


def test_git_snapshot_applies_end_of_line_filters(project: Path, tmp_path: Path):
    (project / ".gitattributes").write_text("*.gml text eol=crlf\n", encoding="utf-8")
    _commit(project)
    snapshot_build.create_snapshot(project, tmp_path / "snap", base_only=True)
    assert (tmp_path / "snap" / "scripts" / "s" / "s.gml").read_bytes() == b"a = 1;\r\nb = 2;\r\n"


def test_git_snapshot_refuses_unsmudged_lfs_pointer(project: Path, tmp_path: Path):
    (project / "scripts" / "s" / "s.gml").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 12\n"
    )
    _commit(project)
    with pytest.raises(snapshot_build.SnapshotError, match="Git LFS pointer"):
        snapshot_build.create_snapshot(project, tmp_path / "snap", base_only=True)


def test_git_context_matches_toplevel_with_different_letter_case(project: Path, monkeypatch: pytest.MonkeyPatch):
    respelled = Path(str(project.resolve()).swapcase())
    if not respelled.exists():
        pytest.skip("case-sensitive volume")
    monkeypatch.setattr(
        snapshot_build,
        "_git",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, str(respelled.parent).encode(), b""),
    )
    assert snapshot_build.git_context(project)[1] == "game"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_working_tree_preflight_skips_folders_the_copy_skips(project: Path, tmp_path: Path):
    for name in ("output", ".git", ".gms_mcp"):
        (project / name).mkdir(exist_ok=True)
        (project / name / "dangling").symlink_to(tmp_path / "missing")
    snapshot_build.create_snapshot(project, tmp_path / "snap")
    assert (tmp_path / "snap" / "scripts" / "s" / "s.gml").is_file()
    assert not (tmp_path / "snap" / "output").exists()


def test_working_tree_copy_holds_project_mutation_lock(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    events: list[str] = []

    class Recorder:
        def __init__(self, root: Path, tool_name: str):
            assert root == project.resolve() and tool_name == "snapshot"

        def acquire(self) -> None:
            events.append("acquire")

        def release(self) -> None:
            events.append("release")

    copy_tree = snapshot_build._copy_tree
    monkeypatch.setattr(transactions, "_ProjectMutationLock", Recorder)
    monkeypatch.setattr(snapshot_build, "_copy_tree", lambda *a: (events.append("copy"), copy_tree(*a)))
    snapshot_build.create_snapshot(project, tmp_path / "snap")
    assert events == ["acquire", "copy", "release"]


def test_test_sources_drop_byte_order_mark(project: Path):
    (project / "t.gml").write_bytes("﻿function agent_test_step(_f) {}".encode())
    assert snapshot_build.load_test_source(project, "t.gml", None).startswith("function")
    assert snapshot_build.load_test_source(project, None, "﻿x").startswith("x")


@pytest.mark.parametrize(
    "settings,match",
    [
        ({"runtime_error_patterns": "FATAL ERROR"}, "test.runtime_error_patterns"),
        ({"runtime_error_patterns": ["ok", ""]}, "test.runtime_error_patterns"),
        ({"result_marker": ""}, "test.result_marker"),
        ({"line_marker": 7}, "test.line_marker"),
    ],
)
def test_test_settings_are_type_checked(project: Path, settings: dict, match: str):
    (project / ".gms-mcp.json").write_text(json.dumps({"test": settings}), encoding="utf-8")
    with pytest.raises(ValidationError, match=match):
        snapshot_build._run_test_pipeline(project, test_code="function agent_test_step(_f) {}")
