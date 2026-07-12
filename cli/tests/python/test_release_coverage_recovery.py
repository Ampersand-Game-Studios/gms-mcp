"""Focused release tests for isolation, journaling, and bounded subprocess helpers."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gms_helpers import transactions
from gms_mcp.server import direct, direct_worker, subprocess_runner


def _importable_handler(_args: argparse.Namespace) -> bool:
    return True


def _journal_context(root: Path) -> transactions._TransactionJournalContext:
    journal = root / "journal.jsonl"
    journal.write_text("", encoding="utf-8")
    backup = root / "backup"
    backup.mkdir()
    return transactions._TransactionJournalContext(root, journal, backup)


def test_journal_tree_and_rename_capture_every_implicit_path(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "one.txt").write_text("one", encoding="utf-8")
    (nested / "two.txt").write_text("two", encoding="utf-8")
    destination = tmp_path / "destination"
    context = _journal_context(tmp_path)

    transactions._append_journal_tree(context, source, "shutil.rmtree")
    transactions._append_rename_tree(context, source, destination)

    records = [json.loads(line) for line in context.journal_path.read_text().splitlines()]
    paths = {record["path"] for record in records}
    assert {
        "source",
        "source/one.txt",
        "source/nested",
        "source/nested/two.txt",
        "destination",
        "destination/one.txt",
        "destination/nested",
        "destination/nested/two.txt",
    } <= paths
    assert (context.backup_root / "source" / "nested" / "two.txt").read_text() == "two"


def test_journal_helpers_reject_unsafe_paths_and_snapshot_failures(tmp_path: Path) -> None:
    context = _journal_context(tmp_path)
    context.journal_path.write_text('{"event":"open","path":"seen.txt"}\n', encoding="utf-8")

    assert transactions._audit_absolute_path(object()) is None
    assert transactions._journal_relative_path(context, tmp_path.parent / "outside.txt") is None
    assert transactions._journal_relative_path(context, tmp_path / ".git" / "config") is None

    transactions._append_journal_path(context, tmp_path / "seen.txt", "open")
    assert "seen.txt" in context.seen_paths
    before = context.journal_path.read_text(encoding="utf-8")
    transactions._append_journal_path(context, tmp_path / "seen.txt", "open")
    assert context.journal_path.read_text(encoding="utf-8") == before

    with (
        patch.object(transactions, "_capture_original_path", return_value=False),
        pytest.raises(RuntimeError, match="Cannot safely snapshot"),
    ):
        transactions._append_journal_path(context, tmp_path / "unsafe.txt", "open")


def test_audit_hook_routes_all_supported_mutations(tmp_path: Path) -> None:
    context = _journal_context(tmp_path)
    token = transactions._ACTIVE_TRANSACTION.set(context)
    try:
        with (
            patch.object(transactions, "_append_journal_path") as append_path,
            patch.object(transactions, "_append_journal_tree") as append_tree,
            patch.object(transactions, "_append_rename_tree") as append_rename,
        ):
            transactions._transaction_audit_hook("open", ("file", "w", 0))
            transactions._transaction_audit_hook("os.remove", ("file", 4))
            transactions._transaction_audit_hook("os.mkdir", ("dir", 0o755, 5))
            transactions._transaction_audit_hook("os.truncate", ("file", 0))
            transactions._transaction_audit_hook("os.rename", ("old", "new", 6, 7))
            transactions._transaction_audit_hook("shutil.rmtree", ("tree", 8))
            transactions._transaction_audit_hook("shutil.copyfile", ("source", "copy"))
            transactions._transaction_audit_hook("os.symlink", ("source", "link"))

        assert append_path.call_count == 6
        append_rename.assert_called_once_with(context, "old", "new", 6, 7)
        append_tree.assert_called_once_with(context, "tree", "shutil.rmtree", 8)
    finally:
        transactions._ACTIVE_TRANSACTION.reset(token)

    with patch.object(transactions, "_append_journal_path") as append_path:
        transactions._transaction_audit_hook("open", ("ignored", "w", 0))
    append_path.assert_not_called()


def test_inherited_transaction_context_requires_complete_environment(tmp_path: Path) -> None:
    names = (
        transactions._TRANSACTION_ROOT_ENV,
        transactions._TRANSACTION_JOURNAL_ENV,
        transactions._TRANSACTION_BACKUP_ENV,
    )
    empty = {name: "" for name in names}
    with patch.dict(os.environ, empty, clear=False):
        with transactions.inherited_transaction_context():
            assert transactions._ACTIVE_TRANSACTION.get() is None
        with pytest.raises(RuntimeError, match="incomplete"):
            with patch.dict(os.environ, {names[0]: str(tmp_path)}, clear=False):
                with transactions.inherited_transaction_context():
                    pass
        with pytest.raises(RuntimeError, match="requires an active transaction"):
            transactions.run_journaled_cli()


def test_transactional_file_wrappers_record_resulting_ownership(tmp_path: Path) -> None:
    source_file = tmp_path / "source.txt"
    source_file.write_text("content", encoding="utf-8")
    source_tree = tmp_path / "source-tree"
    source_tree.mkdir()
    (source_tree / "nested.txt").write_text("nested", encoding="utf-8")

    with (
        patch.object(transactions, "mark_transaction_path_owned") as mark_path,
        patch.object(transactions, "mark_transaction_tree_owned") as mark_tree,
    ):
        copied_file = tmp_path / "copied.txt"
        assert transactions.transactional_copy2(source_file, copied_file) == str(copied_file)
        copied_tree = tmp_path / "copied-tree"
        assert transactions.transactional_copytree(source_tree, copied_tree) == str(copied_tree)
        transactions.transactional_unlink(copied_file)
        empty = tmp_path / "empty"
        empty.mkdir()
        transactions.transactional_rmdir(empty)
        transactions.transactional_rmtree(copied_tree)
        renamed = transactions.transactional_rename(source_file, tmp_path / "renamed.txt")
        replacement_source = tmp_path / "replacement.txt"
        replacement_source.write_text("replacement", encoding="utf-8")
        replaced = transactions.transactional_replace(replacement_source, renamed)

    assert replaced.read_text(encoding="utf-8") == "replacement"
    assert mark_path.call_count == 5
    assert mark_tree.call_count == 4


def test_subprocess_discovery_timeout_and_windows_rendering_branches(tmp_path: Path) -> None:
    override = tmp_path / "gms"
    override.write_text("", encoding="utf-8")
    with patch.dict(os.environ, {"GMS_MCP_GMS_PATH": str(override)}):
        assert subprocess_runner._select_gms_executable() == (str(override), [str(override)])

    completed = SimpleNamespace(returncode=0, stdout="shim\nreal\n")
    with patch.object(subprocess_runner.subprocess, "run", return_value=completed):
        assert subprocess_runner._resolve_gms_candidates_windows() == ["shim", "real"]
    with patch.object(subprocess_runner.subprocess, "run", side_effect=OSError("missing")):
        assert subprocess_runner._resolve_gms_candidates_windows() == []

    with (
        patch.object(subprocess_runner.os, "name", "nt"),
        patch.object(
            subprocess_runner,
            "_resolve_gms_candidates_windows",
            return_value=["C:/WindowsApps/gms.exe", "C:/tools/gms.exe"],
        ),
    ):
        assert subprocess_runner._select_gms_executable()[0] == "C:/tools/gms.exe"
    with (
        patch.object(subprocess_runner.os, "name", "nt"),
        patch.object(subprocess_runner.subprocess, "list2cmdline", return_value="rendered"),
    ):
        assert subprocess_runner._cmd_to_str(["a", "b"]) == "rendered"
    with (
        patch.object(subprocess_runner.os, "name", "nt"),
        patch.object(subprocess_runner.subprocess, "list2cmdline", side_effect=ValueError),
    ):
        assert subprocess_runner._cmd_to_str(["a", "b"]) == "a b"

    with patch.dict(os.environ, {"GMS_MCP_DEFAULT_TIMEOUT_SECONDS": "17"}):
        assert subprocess_runner._default_timeout_seconds_for_cli_args(["asset"]) == 17
    with patch.dict(os.environ, {"GMS_MCP_DEFAULT_TIMEOUT_SECONDS": "invalid"}):
        assert subprocess_runner._default_timeout_seconds_for_cli_args(["maintenance"]) == 1800
        assert subprocess_runner._default_timeout_seconds_for_cli_args(["run", "status"]) == 120
        assert subprocess_runner._default_timeout_seconds_for_cli_args(["run", "background-start"]) == 1800
        assert subprocess_runner._default_timeout_seconds_for_cli_args(["run", "compile"]) == 7200
        assert subprocess_runner._default_timeout_seconds_for_cli_args([]) == 600


def test_bounded_log_writer_and_marker_failures_are_best_effort(tmp_path: Path) -> None:
    log_path = tmp_path / "bounded.log"
    writer = subprocess_runner._BoundedLogWriter(log_path, 12)
    writer.append("abcdefghijklmnopqrstuvwxyz")
    original = log_path.read_bytes()
    writer.append("ignored")
    assert log_path.read_bytes() == original
    assert len(original) == 12

    with patch.object(Path, "write_bytes", side_effect=OSError("readonly")):
        failed_writer = subprocess_runner._BoundedLogWriter(tmp_path / "failed.log", 5)
    with patch.object(Path, "open", side_effect=OSError("readonly")):
        failed_writer.append("value")

    marker = tmp_path / "tool.log"
    with patch.object(Path, "write_text", side_effect=OSError("readonly")):
        subprocess_runner._mark_log_active(marker)
    with (
        patch.object(Path, "unlink", side_effect=OSError("readonly")),
        patch.object(subprocess_runner, "_prune_log_dir") as prune,
    ):
        subprocess_runner._finalize_log(marker)
    prune.assert_called_once_with(tmp_path, keep=marker)


def test_process_group_helpers_cover_exit_permission_and_fallbacks() -> None:
    with patch.object(subprocess_runner.os, "killpg", side_effect=ProcessLookupError):
        assert not subprocess_runner._posix_process_group_exists(123)
    with patch.object(subprocess_runner.os, "killpg", side_effect=PermissionError):
        assert subprocess_runner._posix_process_group_exists(123)

    process = Mock(pid=321)
    process.poll.return_value = 0
    with patch.object(subprocess_runner.os, "getpgid", side_effect=ProcessLookupError):
        assert subprocess_runner._terminate_process_tree(process)

    process = Mock(pid=321)
    process.poll.return_value = 0
    process.wait.side_effect = [subprocess.TimeoutExpired("wait", 1), None]
    with (
        patch.object(subprocess_runner.os, "getpgid", return_value=999),
        patch.object(subprocess_runner.os, "name", "posix"),
    ):
        assert subprocess_runner._terminate_process_tree(process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()

    process = Mock(pid=321)
    process.poll.return_value = None
    process.kill.side_effect = OSError("denied")
    with patch.object(subprocess_runner.os, "getpgid", side_effect=OSError("denied")):
        assert not subprocess_runner._terminate_process_tree(process)


def test_direct_value_conversion_and_failure_messages() -> None:
    class Result:
        message = "attribute failure"

    class MappingResult:
        def to_dict(self) -> dict[str, object]:
            return {"error": {"message": "nested failure"}}

    assert direct._result_failure_message(MappingResult()) == "nested failure"
    assert direct._result_failure_message({"error": "flat failure"}) == "flat failure"
    assert direct._result_failure_message({"message": "message failure"}) == "message failure"
    assert direct._result_failure_message({}) is None
    assert direct._result_failure_message(Result()) == "attribute failure"
    assert direct._result_failure_message(object()) is None
    assert direct._request_value((Path("a"), {1: [object()]}))[0] == "a"

    with patch.object(direct.inspect, "getsourcefile", return_value=None):
        nameless = Mock(__module__="", __qualname__="")
        with pytest.raises(TypeError, match="importable top-level"):
            direct._handler_reference(nameless)


@pytest.mark.parametrize("response", [None, "not-json"])
def test_direct_worker_fails_closed_for_missing_or_invalid_response(tmp_path: Path, response: str | None) -> None:
    process = Mock(pid=42, returncode=7)
    process.wait.return_value = 7

    def popen(*_args: object, **_kwargs: object) -> Mock:
        if response is not None:
            response_path = Path(_args[0][-1])  # type: ignore[index]
            response_path.write_text(response, encoding="utf-8")
        return process

    with (
        patch.object(direct, "_resolve_project_directory", return_value=tmp_path),
        patch.object(direct, "_handler_reference", return_value=("module", "handler", None)),
        patch.object(direct.subprocess, "Popen", side_effect=popen),
    ):
        result = direct._run_direct(_importable_handler, argparse.Namespace(path=tmp_path), str(tmp_path))

    assert not result.ok
    if response is None:
        assert "without a response" in (result.error or "")
    else:
        assert "invalid response" in (result.error or "")


def test_direct_worker_timeout_reports_verified_termination(tmp_path: Path) -> None:
    process = Mock(pid=42, returncode=None)
    process.wait.side_effect = subprocess.TimeoutExpired("worker", 1)
    with (
        patch.object(direct, "_resolve_project_directory", return_value=tmp_path),
        patch.object(direct, "_handler_reference", return_value=("module", "handler", None)),
        patch.object(direct.subprocess, "Popen", return_value=process),
        patch.object(subprocess_runner, "_terminate_process_tree", return_value=True),
    ):
        result = direct._run_direct(
            _importable_handler,
            argparse.Namespace(),
            str(tmp_path),
            timeout_seconds=1,
        )

    assert result.timed_out
    assert result.result == {"terminated": True}


def test_direct_worker_system_exit_and_request_validation(tmp_path: Path) -> None:
    def exiting() -> None:
        print("before exit")
        print("problem", file=os.sys.stderr)
        raise SystemExit(9)

    ok, stdout, stderr, _result, error, exit_code = direct_worker._capture_output(exiting)
    assert not ok
    assert exit_code == 9
    assert "before exit" in stdout
    assert "problem" in stderr
    assert "SystemExit: 9" in (error or "")

    with pytest.raises(TypeError, match="args must be an object"):
        direct_worker._run_request(
            {
                "project_root": str(tmp_path),
                "handler_module": __name__,
                "handler_qualname": "_importable_handler",
                "args": [],
            }
        )
    with pytest.raises(TypeError, match="not callable"):
        direct_worker._resolve_handler(__name__, "os")


def test_direct_worker_main_serializes_bad_requests_and_write_fallback(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    request_path.write_text("[]", encoding="utf-8")
    assert direct_worker.main([str(request_path), str(response_path)]) == 0
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    assert not payload["ok"]
    assert "request must be an object" in payload["error"]

    request_path.write_text("{}", encoding="utf-8")
    real_write = direct_worker._write_response
    calls = 0

    def fail_once(path: Path, payload: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("first write failed")
        real_write(path, payload)

    with patch.object(direct_worker, "_write_response", side_effect=fail_once):
        assert direct_worker.main([str(request_path), str(response_path)]) == 1
    fallback = json.loads(response_path.read_text(encoding="utf-8"))
    assert fallback["exit_code"] == 1
    assert "first write failed" in fallback["error"]
