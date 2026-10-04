"""Portable Windows FlushFileBuffers access-right regressions."""

import json
import os
from pathlib import Path
import stat
import sys

import pytest

from gms_helpers import transactions
from gms_helpers.utils import atomic_write_text


@pytest.fixture
def strict_file_flush(tmp_path, monkeypatch):
    """Apply Windows' writable-handle flush requirement on every host."""
    original_open = Path.open
    original_fsync = os.fsync
    descriptors = {}
    rejected = []

    def tracked_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        descriptors[stream.fileno()] = (path, stream.writable())
        return stream

    def checked_fsync(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            path, writable = descriptors[descriptor]
            if not writable:
                rejected.append(path)
                raise OSError(9, "FlushFileBuffers requires GENERIC_WRITE")
        return original_fsync(descriptor)

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(os, "fsync", checked_fsync)
    monkeypatch.setattr(sys, "platform", "win32")
    (tmp_path / "test.yyp").write_text(json.dumps({"name": "test", "resources": [], "Folders": []}))
    (tmp_path / "tracked.txt").write_bytes(b"original\r\n")
    return tmp_path, rejected


def test_existing_file_mutation_commits_under_windows_flush_contract(strict_file_flush):
    root, rejected = strict_file_flush
    tx = transactions.GameMakerProjectTransaction(root, "portable-windows-commit")
    tx.begin()
    try:
        atomic_write_text(root / "tracked.txt", "changed\r\n")
        tx.commit()
        assert tx.committed
        assert (root / "tracked.txt").read_bytes() == b"changed\r\n"
        assert rejected == []
    finally:
        tx.cleanup()


def test_existing_file_mutation_rolls_back_under_windows_flush_contract(strict_file_flush):
    root, rejected = strict_file_flush
    tx = transactions.GameMakerProjectTransaction(root, "portable-windows-rollback")
    tx.begin()
    try:
        atomic_write_text(root / "tracked.txt", "changed\n")
        tx.capture_mutation_state()
        assert tx.rollback()
        assert (root / "tracked.txt").read_bytes() == b"original\r\n"
        assert rejected == []
    finally:
        tx.cleanup()


def test_interrupted_transaction_recovers_under_windows_flush_contract(strict_file_flush):
    root, rejected = strict_file_flush
    interrupted = transactions.GameMakerProjectTransaction(root, "portable-windows-interrupted")
    interrupted.begin()
    try:
        atomic_write_text(root / "tracked.txt", "interrupted\n")
    finally:
        # Leave the active durable journal just as an exited process would.
        interrupted.cleanup()
    restarted = transactions.GameMakerProjectTransaction(root, "portable-windows-restart")
    restarted.begin()
    try:
        assert (root / "tracked.txt").read_bytes() == b"original\r\n"
        restarted.commit()
        assert rejected == []
    finally:
        restarted.cleanup()


@pytest.mark.skipif(os.name == "nt", reason="POSIX read-only descriptor behavior")
def test_posix_read_only_original_can_still_be_durably_restored(tmp_path):
    (tmp_path / "test.yyp").write_text(json.dumps({"name": "test", "resources": [], "Folders": []}))
    original = tmp_path / "tracked.txt"
    original.write_bytes(b"original\n")
    original.chmod(0o444)
    tx = transactions.GameMakerProjectTransaction(tmp_path, "posix-read-only-backup")
    tx.begin()
    try:
        atomic_write_text(original, "changed\n")
        tx.capture_mutation_state()
        assert tx.rollback()
        assert original.read_bytes() == b"original\n"
        assert stat.S_IMODE(original.stat().st_mode) == 0o444
    finally:
        tx.cleanup()
