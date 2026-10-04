"""File-state fault injection for atomic bookkeeping and interrupted recovery."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from gms_helpers import transactions
from gms_helpers.bridge_installer import BridgeInstaller
from gms_helpers.results import OperationResult
from gms_helpers.utils import atomic_write_text
from gms_mcp import gamemaker_mcp_server as server
from gms_mcp.server import verification_policy


@pytest.fixture
def project(tmp_path):
    (tmp_path / "test.yyp").write_text(json.dumps({"name": "test", "resources": [], "Folders": []}))
    (tmp_path / "tracked.txt").write_text("original")
    return tmp_path


def crash_writer(project, *, owned=True, committed=False):
    code = "\n".join(
        [
            "import os, sys",
            "from pathlib import Path",
            "from gms_helpers.transactions import GameMakerProjectTransaction, mark_transaction_path_owned",
            "root = Path(sys.argv[1])",
            "tx = GameMakerProjectTransaction(root, 'crash-test')",
            "tx.begin()",
            "(root / 'tracked.txt').write_text('interrupted')",
            "mark_transaction_path_owned(root / 'tracked.txt')" if owned else "pass",
            "tx.commit()" if committed else "pass",
            "os._exit(73)",
        ]
    )
    result = subprocess.run([sys.executable, "-c", code, str(project)], env={**os.environ, "PYTHONPATH": "src"})
    assert result.returncode == 73


def test_restart_recovers_owned_write_after_process_exit(project):
    crash_writer(project)
    assert (project / "tracked.txt").read_text() == "interrupted"
    tx = transactions.GameMakerProjectTransaction(project, "restart")
    tx.begin()
    try:
        assert (project / "tracked.txt").read_text() == "original"
        tx.commit()
    finally:
        tx.cleanup()
    assert not list((project / ".gms_mcp/transactions").iterdir())


def test_bogus_transaction_environment_cannot_bypass_standalone_cli_rollback(project):
    (project / "broken.yy").write_text("not JSON")
    for directory in ("scripts", "objects", "sprites", "rooms", "folders"):
        (project / directory).mkdir()
    environment = {
        **os.environ,
        "PYTHONPATH": "src",
        "GMS_MCP_TRANSACTION_ROOT": str(project),
        "GMS_MCP_TRANSACTION_JOURNAL": "bogus",
        "GMS_MCP_TRANSACTION_BACKUP_ROOT": "bogus",
    }
    command = [
        sys.executable,
        "-m",
        "gms_helpers.gms",
        "--project-root",
        str(project),
        "--telemetry",
        "off",
        "asset",
        "create",
        "script",
        "audit_script",
        "--skip-maintenance",
    ]
    result = subprocess.run(command, env=environment, capture_output=True, timeout=15)
    assert result.returncode == 9  # Post-mutation validation, not an unrelated CLI/setup error.
    assert not (project / "scripts/audit_script").exists()
    assert (project / "broken.yy").read_text() == "not JSON"


def test_valid_inherited_journal_cli_writes_remain_parent_owned(project):
    for directory in ("scripts", "objects", "sprites", "rooms", "folders"):
        (project / directory).mkdir()
    tx = transactions.GameMakerProjectTransaction(project, "inherited-cli-positive")
    tx.begin()
    try:
        environment = {**os.environ, "PYTHONPATH": "src", **transactions.transaction_subprocess_environment()}
        command = transactions.journaled_gms_cli_command(
            [
                "--project-root",
                str(project),
                "--telemetry",
                "off",
                "asset",
                "create",
                "script",
                "audit_script",
                "--skip-maintenance",
            ]
        )
        result = subprocess.run(command, env=environment, capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr + result.stdout
        assert (project / "scripts/audit_script/audit_script.yy").is_file()
        tx.capture_mutation_state()
        assert tx.rollback()
        assert not (project / "scripts/audit_script").exists()
    finally:
        tx.cleanup()


def test_active_transaction_matches_only_its_established_project_root(project, tmp_path):
    tx = transactions.GameMakerProjectTransaction(project, "active-context-root")
    tx.begin()
    try:
        assert transactions.transaction_is_active(project)
        assert not transactions.transaction_is_active(tmp_path / "unrelated-project")
    finally:
        tx.cleanup()


@pytest.mark.parametrize("owned,external", [(False, False), (True, True)])
def test_restart_preserves_unproven_or_external_change_and_recovery_data(project, owned, external):
    crash_writer(project, owned=owned)
    if external:
        (project / "tracked.txt").write_text("external editor")
    expected = (project / "tracked.txt").read_text()
    tx = transactions.GameMakerProjectTransaction(project, "restart")
    with pytest.raises(transactions.TransactionValidationError) as error:
        tx.begin()
    assert (project / "tracked.txt").read_text() == expected
    recovery = Path(error.value.details["transaction"]["recovery_path"])
    assert (recovery / "project/tracked.txt").read_text() == "original"


def test_restart_does_not_undo_durably_committed_write(project):
    crash_writer(project, committed=True)
    tx = transactions.GameMakerProjectTransaction(project, "restart")
    tx.begin()
    try:
        assert (project / "tracked.txt").read_text() == "interrupted"
        tx.commit()
    finally:
        tx.cleanup()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        False,
        {"ok": False},
        {"success": False},
        {"status": "failed"},
        {"status": "error"},
        OperationResult.fail("failed"),
    ],
)
def test_failure_contract_rolls_back_sync_and_async(project, asynchronous, failure, monkeypatch):
    monkeypatch.setenv("GMS_MCP_POST_MUTATION_VERIFY", "off")

    def call():
        atomic_write_text(project / "tracked.txt", "mutation")
        return failure

    async def async_call():
        return call()

    if asynchronous:
        result = asyncio.run(
            server._run_transactional_async("gm_event_add", {"project_root": str(project)}, async_call)
        )
    else:
        result = server._run_transactional_sync("gm_event_add", {"project_root": str(project)}, call)
    assert server._result_from_value(result) == "error"
    assert result["transaction"]["rolled_back"] is True
    assert (project / "tracked.txt").read_text() == "original"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_pending_marker_failure_rolls_back_project_and_marker(project, asynchronous, monkeypatch):
    monkeypatch.setenv("GMS_MCP_POST_MUTATION_VERIFY", "smart")
    state = project / ".gms_mcp/verification_state.json"
    state.parent.mkdir()
    state.write_text('{"version": 1, "existing": true}')
    original_state = state.read_bytes()

    def broken_write(root, data):
        atomic_write_text(state, json.dumps(data))
        raise OSError("injected bookkeeping failure after replace")

    def call():
        atomic_write_text(project / "tracked.txt", "mutation")
        return {"ok": True}

    async def async_call():
        return call()

    with patch.object(verification_policy, "_write_state", side_effect=broken_write):
        with pytest.raises(OSError, match="bookkeeping"):
            if asynchronous:
                asyncio.run(server._run_transactional_async("gm_event_add", {"project_root": str(project)}, async_call))
            else:
                server._run_transactional_sync("gm_event_add", {"project_root": str(project)}, call)
    assert (project / "tracked.txt").read_text() == "original"
    assert state.read_bytes() == original_state
    assert not list((project / ".gms_mcp/transactions").iterdir())


def test_standalone_bridge_partial_deletion_restores_all_files(project):
    installer = BridgeInstaller(project)
    assert installer.install()["ok"]
    before = {
        p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file() and ".gms_mcp" not in p.parts
    }
    unlink = transactions.transactional_unlink
    removed = []

    def fail_second(path, **kwargs):
        if "objects" in Path(path).parts:
            if removed:
                raise OSError("injected partial deletion")
            removed.append(str(path))
        return unlink(path, **kwargs)

    with patch.object(transactions, "transactional_unlink", side_effect=fail_second):
        result = installer.uninstall()
    assert removed
    assert result["ok"] is False
    assert result["transaction"]["rolled_back"] is True
    after = {
        p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file() and ".gms_mcp" not in p.parts
    }
    assert after == before


@pytest.mark.parametrize(
    "path",
    [
        "../tracked.txt",
        "/tmp/outside",
        ".",
        ".gms_mcp/locks/project-mutation.lock",
        "C:/outside",
        "folder/../tracked.txt",
        "folder\\tracked.txt",
    ],
)
def test_tampered_journal_paths_block_recovery_without_writes(project, path):
    crash_writer(project)
    recovery = next((project / ".gms_mcp/transactions").iterdir())
    journal = recovery / "writes.jsonl"
    with journal.open("a") as stream:
        stream.write(json.dumps({"event": "open", "path": path, "original": ["absent"]}) + "\n")
    tx = transactions.GameMakerProjectTransaction(project, "unsafe-restart")
    with pytest.raises(transactions.ValidationError, match="journal"):
        tx.begin()
    assert (project / "tracked.txt").read_text() == "interrupted"
    assert recovery.is_dir()


@pytest.mark.parametrize(
    "damage",
    [
        "truncated-journal",
        "missing-state",
        "corrupt-state",
        "unknown-status",
        "changed-backup",
        "linked-journal",
        "linked-backup",
    ],
)
def test_damaged_recovery_data_is_preserved_and_blocks_next_mutation(project, damage):
    crash_writer(project)
    recovery = next((project / ".gms_mcp/transactions").iterdir())
    journal = recovery / "writes.jsonl"
    backup = recovery / "project/tracked.txt"
    state_file = recovery / "state.json"
    if damage == "truncated-journal":
        with journal.open("a") as stream:
            stream.write('{"event":')
    elif damage == "missing-state":
        state_file.unlink()
    elif damage == "corrupt-state":
        state_file.write_text("[]")
    elif damage == "unknown-status":
        state = json.loads(state_file.read_text())
        state["status"] = "unknown"
        state_file.write_text(json.dumps(state))
    elif damage == "changed-backup":
        backup.write_text("tampered original")
    elif damage == "linked-journal":
        target = project / "journal-copy.jsonl"
        target.write_bytes(journal.read_bytes())
        journal.unlink()
        journal.symlink_to(target)
    elif damage == "linked-backup":
        backup.unlink()
        backup.symlink_to(project / "tracked.txt")
    for _attempt in range(2):
        tx = transactions.GameMakerProjectTransaction(project, "unsafe-restart")
        with pytest.raises(transactions.ValidationError):
            tx.begin()
        assert (project / "tracked.txt").read_text() == "interrupted"
        assert recovery.is_dir()


def test_pending_marker_failure_with_new_marker_leaves_no_marker(project, monkeypatch):
    monkeypatch.setenv("GMS_MCP_POST_MUTATION_VERIFY", "smart")
    state = project / ".gms_mcp/verification_state.json"

    def broken_write(root, data):
        atomic_write_text(state, json.dumps(data))
        raise OSError("new marker failure")

    def call():
        atomic_write_text(project / "tracked.txt", "mutation")
        return {"ok": True}

    with patch.object(verification_policy, "_write_state", side_effect=broken_write):
        with pytest.raises(OSError):
            server._run_transactional_sync("gm_event_add", {"project_root": str(project)}, call)
    assert not state.exists()
    assert (project / "tracked.txt").read_text() == "original"


def test_compile_failure_rolls_back_compile_generated_changes(project):
    tx = transactions.GameMakerProjectTransaction(project, "compile-failure")
    tx.begin()
    try:
        atomic_write_text(project / "tracked.txt", "mutation")

        def failed_compile(root):
            atomic_write_text(root / "generated.txt", "compile output")
            return {"ok": False}

        with patch.object(transactions, "compile_verify_project", side_effect=failed_compile):
            with pytest.raises(transactions.TransactionValidationError):
                tx.commit(verify_compile=True)
        assert tx.rolled_back
        assert not (project / "generated.txt").exists()
        assert (project / "tracked.txt").read_text() == "original"
    finally:
        tx.cleanup()


def test_standalone_bridge_install_failure_restores_preexisting_files(project):
    object_dir = project / "objects/__mcp_bridge"
    object_dir.mkdir(parents=True)
    existing = object_dir / "Create_0.gml"
    existing.write_text("existing custom file")
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    installer = BridgeInstaller(project)
    with patch.object(installer, "_create_object_asset", side_effect=OSError("injected install failure")):
        result = installer.install()
    assert result["ok"] is False
    assert result["transaction"]["rolled_back"]
    after = {
        p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file() and ".gms_mcp" not in p.parts
    }
    assert after == before


def test_recovery_waits_for_orphan_journaled_subprocess_before_restoring(project):
    ready = project.parent / f"{project.name}-child-ready"
    release = project.parent / f"{project.name}-child-release"
    child_code = "\n".join(
        [
            "import sys,time",
            "from pathlib import Path",
            "from gms_helpers.transactions import inherited_transaction_context",
            "from gms_helpers.utils import atomic_write_text",
            "root,ready,release=map(Path,sys.argv[1:])",
            "with inherited_transaction_context():",
            "    atomic_write_text(root/'tracked.txt','child first write')",
            "    ready.touch()",
            "    deadline=time.monotonic()+10",
            "    while not release.exists() and time.monotonic()<deadline: time.sleep(0.01)",
            "    atomic_write_text(root/'tracked.txt','child final write')",
        ]
    )
    parent_code = "\n".join(
        [
            "import os,sys,time,subprocess",
            "from pathlib import Path",
            "from gms_helpers.transactions import GameMakerProjectTransaction, transaction_subprocess_environment",
            "root,ready,release=map(Path,sys.argv[1:4])",
            "tx=GameMakerProjectTransaction(root,'orphan-parent'); tx.begin()",
            "subprocess.Popen([sys.executable,'-c',sys.argv[4],str(root),str(ready),str(release)],",
            "    env={**os.environ,**transaction_subprocess_environment()},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)",
            "deadline=time.monotonic()+5",
            "while not ready.exists() and time.monotonic()<deadline: time.sleep(0.01)",
            "os._exit(73 if ready.exists() else 74)",
        ]
    )
    parent = subprocess.run(
        [sys.executable, "-c", parent_code, str(project), str(ready), str(release), child_code],
        env={**os.environ, "PYTHONPATH": "src"},
        timeout=10,
    )
    assert parent.returncode == 73
    started = threading.Event()
    finished = threading.Event()
    errors = []

    def recover():
        tx = transactions.GameMakerProjectTransaction(project, "orphan-recovery")
        started.set()
        try:
            tx.begin()
            assert (project / "tracked.txt").read_text() == "original"
            tx.commit()
        except BaseException as error:
            errors.append(error)
        finally:
            tx.cleanup()
            finished.set()

    thread = threading.Thread(target=recover)
    thread.start()
    try:
        assert started.wait(5)
        assert not finished.wait(0.1), "recovery raced the live orphan child"
    finally:
        release.touch()
        thread.join(10)
    assert finished.is_set()
    assert not errors
    assert (project / "tracked.txt").read_text() == "original"


@pytest.mark.parametrize("partial", [False, True])
def test_restart_restores_recursively_deleted_files_including_partial_delete(project, partial):
    directory = project / "assets/nested"
    directory.mkdir(parents=True)
    (directory / "a.txt").write_text("asset a")
    (directory / "b.txt").write_text("asset b")
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    code = "\n".join(
        [
            "import os,sys",
            "from pathlib import Path",
            "from gms_helpers import transactions as t",
            "root=Path(sys.argv[1])",
            "tx=t.GameMakerProjectTransaction(root,'delete-crash'); tx.begin()",
            "unlink=t.transactional_unlink",
            "def interrupted_unlink(path,**kwargs):",
            "    unlink(path,**kwargs)",
            "    os._exit(73)",
            "t.transactional_unlink=interrupted_unlink" if partial else "pass",
            "t.transactional_rmtree(root/'assets')",
            "os._exit(73)",
        ]
    )
    result = subprocess.run([sys.executable, "-c", code, str(project)], env={**os.environ, "PYTHONPATH": "src"})
    assert result.returncode == 73
    tx = transactions.GameMakerProjectTransaction(project, "delete-recovery")
    tx.begin()
    try:
        after = {
            p.relative_to(project): p.read_bytes()
            for p in project.rglob("*")
            if p.is_file() and ".gms_mcp" not in p.parts
        }
        assert after == before
        tx.commit()
    finally:
        tx.cleanup()


def test_verification_flush_marker_failure_preserves_pending_batch(project):
    decision = verification_policy.MutationVerificationDecision("smart", "defer", "batchable", "test")
    verification_policy.mark_compile_verification_pending(
        project, tool_name="gm_event_add", decision=decision, transaction={"changes": {"changed_count": 1}}
    )
    state = project / ".gms_mcp/verification_state.json"
    before = state.read_bytes()

    def broken_write(root, data):
        atomic_write_text(state, json.dumps(data))
        raise OSError("flush marker failure")

    with (
        patch.object(verification_policy, "compile_verify_project", return_value={"ok": True}),
        patch.object(verification_policy, "_write_state", side_effect=broken_write),
    ):
        with pytest.raises(OSError, match="flush marker"):
            verification_policy.flush_pending_compile_verification(project)
    assert state.read_bytes() == before
    assert verification_policy.get_pending_compile_verification(project)["required"]


def test_runtime_marker_is_included_in_transaction_rollback(project):
    runtime = project / ".gms_mcp/runtime.json"
    runtime.parent.mkdir()
    runtime.write_text('{"runtime": "original"}')
    original = runtime.read_bytes()
    tx = transactions.GameMakerProjectTransaction(project, "gm_runtime_pin")
    tx.begin()
    try:
        atomic_write_text(runtime, '{"runtime": "replacement"}')
        tx.capture_mutation_state()
        assert tx.rollback()
        assert runtime.read_bytes() == original
    finally:
        tx.cleanup()


@pytest.mark.parametrize("name", ["output", "__pycache__", ".gms_mcp"])
def test_nested_asset_names_matching_infrastructure_are_journaled(project, name):
    path = project / "scripts" / name / f"{name}.gml"
    tx = transactions.GameMakerProjectTransaction(project, "nested-infrastructure-name")
    tx.begin()
    try:
        atomic_write_text(path, "asset contents")
        tx.capture_mutation_state()
        assert tx.rollback()
        assert not path.exists()
    finally:
        tx.cleanup()


@pytest.mark.parametrize("operation", ["write", "unlink", "copy", "replace"])
def test_external_save_between_write_and_owned_marker_is_not_claimed(project, operation):
    path = project / "tracked.txt"
    source = project / "source.txt"
    source.write_text("operation output")
    tx = transactions.GameMakerProjectTransaction(project, "ownership-race")
    tx.begin()
    original_mark = transactions.mark_transaction_path_owned
    raced = []

    def mark_after_editor_save(target, **kwargs):
        if Path(target) == path:

            def save():
                path.write_text("external save wins")

            thread = threading.Thread(target=save)
            thread.start()
            thread.join(5)
            raced.append(True)
        return original_mark(target, **kwargs)

    try:
        with patch.object(transactions, "mark_transaction_path_owned", side_effect=mark_after_editor_save):
            if operation == "write":
                atomic_write_text(path, "operation output")
            elif operation == "unlink":
                transactions.transactional_unlink(path)
            elif operation == "copy":
                transactions.transactional_copy2(source, path)
            else:
                transactions.transactional_replace(source, path)
        assert raced
        tx.capture_mutation_state()
        assert not tx.rollback()
        assert path.read_text() == "external save wins"
        assert tx.to_dict()["recovery_path"]
    finally:
        tx.cleanup()


@pytest.mark.parametrize("tree", [False, True])
def test_partial_copy_failure_rolls_back_every_completed_output(project, tree):
    source = project / "source"
    source.mkdir()
    (source / "a.txt").write_text("source a")
    (source / "b.txt").write_text("source b")
    tx = transactions.GameMakerProjectTransaction(project, "copy-failure")
    tx.begin()
    try:
        if tree:
            original_copy = transactions.transactional_copy2
            copied = []

            def fail_next(source, destination, **kwargs):
                if copied:
                    raise OSError("second copy failure")
                copied.append(True)
                return original_copy(source, destination, **kwargs)

            with patch.object(transactions, "transactional_copy2", side_effect=fail_next):
                with pytest.raises(Exception, match="copy failure"):
                    transactions.transactional_copytree(source, project / "destination")
            assert copied
        else:

            def fail_mid_copy(source, destination, **kwargs):
                Path(destination).write_text("partially copied")
                raise OSError("copy failure")

            with patch.object(transactions.shutil, "copy2", side_effect=fail_mid_copy):
                with pytest.raises(OSError, match="copy failure"):
                    transactions.transactional_copy2(source / "a.txt", project / "tracked.txt")
        tx.capture_mutation_state()
        assert tx.rollback(), tx.rollback_conflicts
        assert (project / "tracked.txt").read_text() == "original"
        assert not (project / "destination").exists()
        assert not list(project.glob(".*.copy-*"))
    finally:
        tx.cleanup()


@pytest.mark.parametrize(
    "read_only,tool",
    [(True, "server.start"), (True, "gm_project_info"), (False, "gm_project_info"), (False, "gm_doc_lookup")],
)
def test_server_read_and_read_only_startup_never_initialize_telemetry(read_only, tool, monkeypatch):
    monkeypatch.setenv("GMS_MCP_READ_ONLY", "1" if read_only else "0")
    with (
        patch.object(server, "resolve_state") as resolve,
        patch.object(server, "queue_event") as queue,
        patch.object(server, "maybe_start_background_flush") as flush,
    ):
        server._record_mcp_event(
            event_type="mcp.server_start" if tool == "server.start" else "mcp.tool",
            action=tool,
            tool_name=tool,
            tool_family="test",
            result="ok",
            duration_ms=0,
        )
    resolve.assert_not_called()
    queue.assert_not_called()
    flush.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("preview", ["dry_run", "fix", "delete"])
@pytest.mark.parametrize("positional", [False, True])
def test_actual_wrappers_suppress_all_preview_telemetry(
    project, asynchronous, failure, preview, positional, monkeypatch
):
    from gms_mcp.server.project import ProjectAccessPolicy

    monkeypatch.setenv("GMS_MCP_READ_ONLY", "0")
    monkeypatch.setenv("GMS_MCP_POST_MUTATION_VERIFY", "off")

    class FakeMCP:
        def tool(self, *args, **kwargs):
            return lambda function: function

    mcp = FakeMCP()
    server._wrap_tool_registration(
        mcp,
        project_access_policy=ProjectAccessPolicy(project_root=project, lexical_root=project),
        expose_host_diagnostics=True,
        runtime=None,
    )

    def produce():
        if failure:
            raise ValueError("preview failure")
        return {"ok": True}

    if preview == "dry_run":

        def handler(project_root=".", dry_run=True):
            return produce()

        tool_name = "gm_event_add"
        argument = True
    elif preview == "fix":

        def handler(project_root=".", fix=False):
            return produce()

        tool_name = "gm_maintenance_lint"
        argument = False
    else:

        def handler(project_root=".", delete=False):
            return produce()

        tool_name = "gm_maintenance_clean_orphans"
        argument = False
    if asynchronous:
        sync_handler = handler

        async def async_handler(*args, **kwargs):
            return sync_handler(*args, **kwargs)

        import inspect

        async_handler.__signature__ = inspect.signature(handler)
        handler = async_handler
    wrapped = mcp.tool(name=tool_name)(handler)
    with (
        patch.object(server, "resolve_state") as resolve,
        patch.object(server, "queue_event") as queue,
        patch.object(server, "maybe_start_background_flush") as flush,
        patch.object(server, "validate_mcp_tool_arguments", return_value=[]),
    ):

        def call():
            result = wrapped(str(project), argument) if positional else wrapped(project_root=str(project))
            return asyncio.run(result) if asynchronous else result

        if failure:
            with pytest.raises(ValueError, match="preview failure"):
                call()
        else:
            call()
    resolve.assert_not_called()
    queue.assert_not_called()
    flush.assert_not_called()
