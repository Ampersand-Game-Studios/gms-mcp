"""Reject absolute/rooted journal paths regardless of the host path flavour."""

import json
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from gms_helpers import transactions


UNSAFE_PATHS = [
    "/tmp/outside",
    "/objects/outside.yy",
    "/",
    "\\tmp\\outside",
    "C:/outside",
    "C:outside",
    "//server/share/outside",
    "\\\\server\\share\\outside",
    "\\\\?\\C:\\outside",
    "\\\\.\\C:\\outside",
    "folder/../outside",
    "folder\\outside",
]


@pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
@pytest.mark.parametrize("path", UNSAFE_PATHS)
def test_foreign_rooted_journal_paths_are_rejected_before_resolution(tmp_path, monkeypatch, flavour, path):
    # Model both pathlib flavours on every host without touching outside paths.
    monkeypatch.setattr(transactions, "Path", flavour)
    assert not transactions._valid_relative_path(path)
    assert transactions._safe_relative_path(tmp_path, path) is None
    assert transactions._safe_backup_path(tmp_path, path) is None


@pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
@pytest.mark.parametrize("path", UNSAFE_PATHS)
def test_foreign_rooted_journal_records_fail_closed_before_recovery(tmp_path, monkeypatch, flavour, path):
    journal = tmp_path / "writes.jsonl"
    journal.write_text(json.dumps({"event": "open", "path": path, "original": ["absent"]}) + "\n")
    monkeypatch.setattr(transactions, "Path", flavour)
    with pytest.raises(transactions.ValidationError, match="journal path"):
        transactions._load_journal_records(journal)


@pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
@pytest.mark.parametrize("path", ["objects/o_test/o_test.yy", "nested/output/script.gml", ".gms_mcp/runtime.json"])
def test_canonical_project_relative_paths_remain_valid_on_both_flavours(monkeypatch, flavour, path):
    monkeypatch.setattr(transactions, "Path", flavour)
    assert transactions._valid_relative_path(path)
