"""Project runtime leases, native bundle identity and natural exit ownership."""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from gms_helpers import agent_locks, live_session, mac_runtime, snapshot_build


def wait_until(check, timeout=5):
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_bundle_and_staging_identity_is_project_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    original = tmp_path / "official.app"
    executable = original / "Contents/MacOS/Mac_Runner"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"runner")
    info = {"CFBundleIdentifier": "com.yoyogames.macyoyorunner", "CFBundleExecutable": "Mac_Runner"}
    plist = original / "Contents/Info.plist"
    plist.write_bytes(plistlib.dumps(info))
    calls = []
    monkeypatch.setattr(mac_runtime.subprocess, "run", lambda command, **options: calls.append(command))
    first = mac_runtime.prepare_mac_runtime(executable, tmp_path / "one/game", "same")
    second = mac_runtime.prepare_mac_runtime(executable, tmp_path / "two/game", "same")
    repeat = mac_runtime.prepare_mac_runtime(executable, tmp_path / "one/game", "same")
    assert first.save_dir != second.save_dir
    assert first.bundle_id != second.bundle_id
    assert first.save_dir == repeat.save_dir and first.staging != repeat.staging
    assert first.staging.parent == first.save_dir
    assert plistlib.loads(plist.read_bytes()) == info
    assert (
        plistlib.loads((first.runner.parents[1] / "Info.plist").read_bytes())["CFBundleIdentifier"] == first.bundle_id
    )
    assert len(calls) == 3 and all(str(original) not in call for call in calls)


def test_project_leases_exclude_other_agents_but_not_other_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    one = mac_runtime.project_run_lock(tmp_path / "one")
    same = mac_runtime.project_run_lock(tmp_path / "one")
    two = mac_runtime.project_run_lock(tmp_path / "two")
    with one, two:
        assert not same.try_acquire()
        owner = one.owner()
        one.bind_process(os.getpid())
        assert one.owner()["pid"] == os.getpid() and owner["token"] == one.owner()["token"]
    assert same.try_acquire()
    same.release()


def test_dead_supervisor_does_not_release_live_game_and_old_release_preserves_replacement(tmp_path, monkeypatch):
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    lease = mac_runtime.project_run_lock(tmp_path)
    lease.acquire()
    lease.bind_process(202)
    owner = lease.owner()
    owner["supervisor_pid"] = 101
    lease.owner_path.write_text(json.dumps(owner))
    monkeypatch.setattr(agent_locks, "_process_alive", lambda pid: pid == 202)
    replacement = mac_runtime.project_run_lock(tmp_path)
    assert not replacement.try_acquire()
    monkeypatch.setattr(agent_locks, "_process_alive", lambda pid: pid == os.getpid())
    assert replacement.try_acquire()
    lease.release()
    assert replacement.path.is_dir() and replacement.owner()["token"] == replacement._token
    replacement.release()


def test_screenshot_cleanup_never_reads_another_save_directory(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        (directory / "__agent_shot_same.png").write_bytes(directory.name.encode())
    shots = snapshot_build.collect_screenshots(tmp_path / "shots", "__agent_shot_", time.time(), first)
    assert shots[0].read_bytes() == b"one"
    assert (second / "__agent_shot_same.png").read_bytes() == b"two"
    snapshot_build.clear_stale_screenshots("__agent_shot_", first)
    assert (second / "__agent_shot_same.png").exists()


def test_two_games_same_label_run_independently_and_natural_exit_releases(tmp_path, monkeypatch):
    from gms_helpers.runner import GameMakerRunner

    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    children = []

    def compile_game(root, **options):
        work = root / "work"
        work.mkdir(parents=True, exist_ok=True)
        archive = work / "game.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("game.ios", b"data")
        return (
            {"ok": True, "label": options["label"]},
            snapshot_build.BuildResult(True, "COMPILE_OK", game_archive=archive),
            work,
            None,
        )

    def prepare(runner, root, label):
        save = root / "save"
        staging = save / "stage"
        staging.mkdir(parents=True)
        return mac_runtime.MacRuntime(runner, staging, save, root.name)

    def launch(runner, staging, game_file, run_dir, environment):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        children.append(process)
        log = staging / "debug.txt"
        log.write_text("owned " + staging.parent.parent.name)
        return process, log

    monkeypatch.setattr(snapshot_build, "snapshot_compile", compile_game)
    monkeypatch.setattr(snapshot_build, "require_mac_runner", lambda tools: Path("runner"))
    monkeypatch.setattr(live_session, "prepare_mac_runtime", prepare)
    monkeypatch.setattr(snapshot_build, "launch_mac_runner", launch)
    monkeypatch.setattr(
        GameMakerRunner,
        "_snapshot_macos_processes",
        lambda self: {
            child.pid: SimpleNamespace(command="fixture runner", started="fixture start") for child in children
        },
    )
    roots = [tmp_path / "one", tmp_path / "two"]
    try:
        for root in roots:
            result = live_session.start(root, label="same", connect_timeout_seconds=0)
            assert result["running"]
            (root / "save/__agent_shot_same.png").write_bytes(root.name.encode())
        one, two = [live_session.get_session(root) for root in roots]
        with pytest.raises(live_session.LiveSessionError, match="already running"):
            live_session.start(roots[0], label="different", connect_timeout_seconds=0)
        contender = mac_runtime.project_run_lock(roots[0])
        assert not contender.try_acquire()
        assert not snapshot_build.pipeline_lock(roots[0], "same").try_acquire()
        # Simulate closing just the first game's window.
        children[0].terminate()
        children[0].wait()
        wait_until(lambda: one.cleaned)
        assert not one.lock.path.exists() and not one.label_lock.path.exists()
        assert (one.run_dir / "shots/__agent_shot_same.png").read_bytes() == b"one"
        assert children[1].poll() is None and two.lock.path.exists()
        assert (roots[1] / "save/__agent_shot_same.png").read_bytes() == b"two"
        assert live_session.game_log(roots[0])["lines"] == ["owned one"]
        live_session.stop(roots[1])
        assert children[1].poll() is not None and not two.lock.path.exists()
        assert (two.run_dir / "shots/__agent_shot_same.png").read_bytes() == b"two"
    finally:
        for root in roots:
            live_session.stop(root)
        for process in children:
            if process.poll() is None:
                process.terminate()
                process.wait()


def test_dead_server_recovery_archives_and_cleans_only_matching_session(tmp_path, monkeypatch):
    from gms_helpers.run_session import RunSessionManager
    from gms_helpers.runner import GameMakerRunner

    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    work_root = tmp_path / "work"
    work = work_root / "owned_snapshot"
    work.mkdir(parents=True)
    monkeypatch.setattr(snapshot_build, "_work_root", lambda: work_root)
    root = tmp_path / "project"
    save = tmp_path / "Library/Application Support" / f"com.gmsmcp.game.p{mac_runtime.project_identity(root)}"
    staging = save / "session_dead"
    staging.mkdir(parents=True)
    game = staging / "game.ios"
    game.write_bytes(b"data")
    log = staging / "debug.txt"
    log.write_text("owned game log")
    (save / "__agent_shot_owned.png").write_bytes(b"owned screenshot")
    unrelated = save.parent / "foreign_game"
    unrelated.mkdir()
    (unrelated / "__agent_shot_owned.png").write_bytes(b"foreign screenshot")
    manager = RunSessionManager(root)
    persisted = manager.create_session(
        pid=987654321,
        exe_path=str(game),
        platform_target="macOS",
        isolated_runtime=True,
        runtime_label=None,
        runtime_work_dir=str(work),
        runtime_save_dir=str(save),
        log_file=str(log),
    )
    for lease in (mac_runtime.project_run_lock(root), snapshot_build.pipeline_lock(root, "run")):
        lease.acquire()
        owner = lease.owner()
        owner["pid"] = 987654321
        lease.owner_path.write_text(json.dumps(owner))
    monkeypatch.setattr(GameMakerRunner, "_snapshot_macos_processes", lambda self: {})
    result = live_session.stop_persisted(root, persisted)
    assert result["ok"]
    assert (snapshot_build.runs_directory(root, "run") / "run.log").read_text() == "owned game log"
    assert (
        snapshot_build.runs_directory(root, "run") / "shots/__agent_shot_owned.png"
    ).read_bytes() == b"owned screenshot"
    assert not staging.exists() and not work.exists()
    assert (unrelated / "__agent_shot_owned.png").read_bytes() == b"foreign screenshot"
    assert manager.get_current_session() is None
    assert not mac_runtime.project_run_lock(root).path.exists()
    replacement = manager.create_session(pid=os.getpid(), exe_path="replacement", isolated_runtime=True)
    replacement_lease = mac_runtime.project_run_lock(root)
    replacement_lease.acquire()
    try:
        live_session.stop_persisted(root, persisted)
        assert manager.get_current_session().run_id == replacement.run_id
        assert replacement_lease.path.exists()
    finally:
        replacement_lease.release()


def test_nested_project_run_uses_canonical_lease_and_session_root(tmp_path):
    from unittest.mock import patch
    from gms_helpers.runner import GameMakerRunner

    nested = tmp_path / "gamemaker"
    nested.mkdir()
    (nested / "game.yyp").write_text('{"name":"game","resources":[]}')
    runner = GameMakerRunner(tmp_path)
    with patch("gms_helpers.live_session.start", return_value={"ok": False, "running": False}) as start:
        assert not runner.run_project_direct("macOS")
    assert start.call_args.args[0] == nested.resolve()
    assert runner._session_manager.project_root == nested.resolve()


@pytest.mark.parametrize("failure", ["identity", "persistence"])
def test_registration_failure_stops_owned_game_before_releasing_leases(tmp_path, monkeypatch, failure):
    from gms_helpers.runner import GameMakerRunner
    from gms_helpers.run_session import RunSessionManager

    root = tmp_path / "project"
    work = root / "work"
    work.mkdir(parents=True)
    archive = work / "game.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("game.ios", b"data")
    save = root / "save"
    staging = save / "stage"
    staging.mkdir(parents=True)
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(
        snapshot_build,
        "snapshot_compile",
        lambda root, **options: (
            {"ok": True, "label": "failure"},
            snapshot_build.BuildResult(True, "COMPILE_OK", game_archive=archive),
            work,
            None,
        ),
    )
    monkeypatch.setattr(snapshot_build, "require_mac_runner", lambda tools: Path("runner"))
    monkeypatch.setattr(
        live_session,
        "prepare_mac_runtime",
        lambda *args: mac_runtime.MacRuntime(
            Path("runner"),
            staging,
            save,
            "test.bundle",
        ),
    )
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    log = staging / "debug.txt"
    log.write_text("owned log")
    monkeypatch.setattr(snapshot_build, "launch_mac_runner", lambda *args: (process, log))
    if failure == "identity":
        monkeypatch.setattr(
            GameMakerRunner, "_snapshot_macos_processes", lambda self: (_ for _ in ()).throw(OSError("identity failed"))
        )
    else:
        monkeypatch.setattr(
            GameMakerRunner,
            "_snapshot_macos_processes",
            lambda self: {process.pid: SimpleNamespace(command="fixture runner", started="fixture start")},
        )
        monkeypatch.setattr(
            RunSessionManager,
            "create_session",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("persistence failed")),
        )
    try:
        with pytest.raises(OSError, match="failed"):
            live_session.start(root, label="failure", connect_timeout_seconds=0)
        assert process.poll() is not None
        assert not staging.exists() and not work.exists()
        assert not mac_runtime.project_run_lock(root).path.exists()
        assert not snapshot_build.pipeline_lock(root, "failure").path.exists()
        assert live_session.get_session(root) is None
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()


def test_cleanup_preserves_replacement_session_even_with_same_pid(tmp_path, monkeypatch):
    from gms_helpers.run_session import RunSessionManager

    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    root = tmp_path / "project"
    staging = root / "staging"
    work = root / "work"
    save = root / "save"
    for directory in (staging, work, save):
        directory.mkdir(parents=True)
    lease = mac_runtime.project_run_lock(root)
    label_lease = snapshot_build.pipeline_lock(root, "old")
    lease.acquire()
    label_lease.acquire()
    manager = RunSessionManager(root)
    replacement = manager.create_session(pid=4242, exe_path="replacement", isolated_runtime=True)
    session = live_session.LiveSession(
        project_root=root,
        label="old",
        process=SimpleNamespace(pid=4242),
        bridge=SimpleNamespace(stop=lambda: None),
        lock=lease,
        label_lock=label_lease,
        save_dir=save,
        staging=staging,
        debug_log=staging / "debug.txt",
        run_dir=snapshot_build.runs_directory(root, "old"),
        work_dir=work,
        run_id="old-run-id",
    )
    live_session._cleanup(session)
    assert manager.get_current_session().run_id == replacement.run_id
    assert not lease.path.exists() and not label_lease.path.exists()


def test_bridge_screenshot_cannot_collect_another_sessions_file(tmp_path, monkeypatch):
    root = tmp_path / "project"
    save = root / "save"
    save.mkdir(parents=True)
    foreign = tmp_path / "foreign.png"
    foreign.write_bytes(b"foreign screenshot")
    monkeypatch.setitem(live_session._SESSIONS, str(root.resolve()), SimpleNamespace(save_dir=save))
    monkeypatch.setattr(live_session, "command", lambda *args: {"ok": True, "data": {"file": str(foreign)}})
    result = live_session.screenshot(root)
    assert not result["ok"] and "outside" in result["error"]
    assert foreign.read_bytes() == b"foreign screenshot"


def test_checkout_cannot_supply_process_or_cleanup_authority(tmp_path, monkeypatch):
    from gms_helpers.run_session import RunSessionManager, RunSession
    from gms_helpers.runner import GameMakerRunner

    root = tmp_path / "untrusted-project"
    state = root / ".gms_mcp/sessions/current.json"
    state.parent.mkdir(parents=True)
    foreign = tmp_path / "private.txt"
    foreign.write_text("private fixture")
    work = tmp_path / "someone-elses-build"
    work.mkdir()
    (work / "keep").write_text("keep")
    forged = RunSession(
        run_id="forged",
        pid=os.getpid(),
        exe_path="unused",
        project_root=str(root),
        started_at="now",
        isolated_runtime=True,
        log_file=str(foreign),
        runtime_work_dir=str(work),
        macos_runner_commands={str(os.getpid()): "unrelated application"},
        macos_runner_starts={str(os.getpid()): "now"},
    )
    state.write_text(json.dumps(forged.to_dict()))
    monkeypatch.setattr(GameMakerRunner, "_terminate_pid", lambda *args: pytest.fail("unowned process signalled"))
    assert RunSessionManager(root).get_current_session() is None
    assert not live_session.status(root)["running"]
    assert not live_session.stop(root)["stopped"]
    assert not live_session.stop_persisted(root, forged)["stopped"]
    assert foreign.read_text() == "private fixture" and (work / "keep").exists()
    assert not (root / ".gms_mcp/runs").exists()


@pytest.mark.parametrize("bad_path", ["log", "work", "log_symlink"])
def test_invalid_persisted_paths_preserve_files_and_processes(tmp_path, monkeypatch, bad_path):
    from gms_helpers.run_session import RunSessionManager
    from gms_helpers.runner import GameMakerRunner

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "project"
    save = tmp_path / "Library/Application Support" / f"com.gmsmcp.game.p{mac_runtime.project_identity(root)}"
    staging = save / "session_owned"
    staging.mkdir(parents=True)
    work_root = tmp_path / "work"
    work_root.mkdir()
    monkeypatch.setattr(snapshot_build, "_work_root", lambda: work_root)
    foreign = tmp_path / "private.txt"
    foreign.write_text("keep")
    log = staging / "debug.txt"
    work = work_root / "owned"
    work.mkdir()
    if bad_path == "log":
        log = foreign
    elif bad_path == "log_symlink":
        log.symlink_to(foreign)
    else:
        (work_root / "alias").symlink_to(work_root, target_is_directory=True)
        work = work_root / "alias/.."
    persisted = RunSessionManager(root).create_session(
        pid=os.getpid(),
        exe_path=str(staging / "game.ios"),
        isolated_runtime=True,
        runtime_save_dir=str(save),
        runtime_work_dir=str(work),
        log_file=str(log),
    )
    monkeypatch.setattr(GameMakerRunner, "_terminate_pid", lambda *args: pytest.fail("signalled before validation"))
    with pytest.raises(live_session.LiveSessionError, match="paths"):
        live_session.stop_persisted(root, persisted)
    assert foreign.read_text() == "keep" and staging.is_dir() and work_root.is_dir()


@pytest.mark.parametrize("prefix", ["../foreign/", "escape/", "*", "", "..\\foreign\\"])
def test_screenshot_prefix_cannot_escape_or_expand(tmp_path, prefix):
    save = tmp_path / "save"
    foreign = tmp_path / "foreign"
    save.mkdir()
    foreign.mkdir()
    (foreign / "keep.png").write_bytes(b"keep")
    (save / "escape").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(snapshot_build.SnapshotError, match="prefix"):
        snapshot_build.clear_stale_screenshots(prefix, save)
    with pytest.raises(snapshot_build.SnapshotError, match="prefix"):
        snapshot_build.collect_screenshots(tmp_path / "shots", prefix, 0, save)
    assert (foreign / "keep.png").read_bytes() == b"keep"


def test_screenshot_symlinks_are_not_collected(tmp_path):
    save = tmp_path / "save"
    save.mkdir()
    foreign = tmp_path / "private.png"
    foreign.write_bytes(b"keep")
    (save / "__agent_shot_link.png").symlink_to(foreign)
    assert snapshot_build.collect_screenshots(tmp_path / "shots", "__agent_shot_", 0, save) == []
    snapshot_build.clear_stale_screenshots("__agent_shot_", save)
    assert foreign.read_bytes() == b"keep"


def test_bundle_symlinks_never_write_into_original(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    original = tmp_path / "official.app"
    executable = original / "Contents/MacOS/Mac_Runner"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"runner")
    external = tmp_path / "original.plist"
    before = plistlib.dumps({"CFBundleIdentifier": "original", "CFBundleExecutable": "Mac_Runner"})
    external.write_bytes(before)
    (original / "Contents/Info.plist").symlink_to(external)
    monkeypatch.setattr(mac_runtime.subprocess, "run", lambda *args, **kwargs: None)
    runtime = mac_runtime.prepare_mac_runtime(executable, tmp_path / "game", "test")
    assert external.read_bytes() == before
    assert not (runtime.runner.parents[1] / "Info.plist").is_symlink()


@pytest.mark.parametrize("path", ["../game.ios", "/game.ios", "Runner.app/Contents/Info.plist"])
def test_game_archive_cannot_overwrite_runner_or_escape(tmp_path, path):
    archive = tmp_path / "game.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(path, b"bad")
    with pytest.raises(snapshot_build.SnapshotError, match="unsafe"):
        snapshot_build.stage_game_archive(archive, tmp_path / "stage")


def test_foreground_exit_preserves_replacement_session(tmp_path, monkeypatch):
    from gms_helpers.runner import GameMakerRunner
    from gms_helpers.run_session import RunSessionManager

    (tmp_path / "game.yyp").write_text('{"name":"game","resources":[]}')
    persisted = RunSessionManager(tmp_path).create_session(pid=123, exe_path="old", isolated_runtime=True)
    replacement = SimpleNamespace(process=SimpleNamespace(terminate=lambda: pytest.fail("replacement stopped")))
    process = SimpleNamespace(returncode=0)
    process.wait = lambda: live_session._SESSIONS.__setitem__(str(tmp_path.resolve()), replacement)
    original = SimpleNamespace(process=process, run_id=persisted.run_id)
    monkeypatch.setitem(live_session._SESSIONS, str(tmp_path.resolve()), original)
    monkeypatch.setattr(live_session, "start", lambda *args, **kwargs: {"running": True, "run_id": persisted.run_id})
    cleaned = []
    monkeypatch.setattr(live_session, "_cleanup", lambda session: cleaned.append(session))
    assert GameMakerRunner(tmp_path).run_project_direct("macOS", background=False)
    assert cleaned == [original]
    assert live_session.get_session(tmp_path) is replacement
    assert RunSessionManager(tmp_path).get_current_session().run_id == persisted.run_id


@pytest.mark.parametrize("entry", [live_session.start, snapshot_build.run_test])
def test_yyc_is_rejected_before_compilation_or_launch(tmp_path, monkeypatch, entry):
    monkeypatch.setattr(snapshot_build, "snapshot_compile", lambda *args, **kwargs: pytest.fail("YYC compiled"))
    with pytest.raises(snapshot_build.SnapshotError, match="VM.*only"):
        entry(tmp_path, runtime="YYC")


def test_yyc_data_archive_is_not_a_successful_native_build(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "game.yyp").write_text('{"name":"game","resources":[]}')
    work = tmp_path / "work"
    tools = snapshot_build.Toolchain(Path("Igor"), tmp_path, Path("license"), None, "test")

    def compile_data(command, log, timeout):
        log.write_text("Final Compile finished.\nIgor complete.\n")
        with zipfile.ZipFile(work / "out/game.zip", "w") as archive:
            archive.writestr("game.ios", b"data without native code")
        return 0

    result = snapshot_build.compile_snapshot(project, work, tools, runtime="YYC", run_igor=compile_data)
    assert not result.ok and "native macOS YYC" in result.errors[0]


def test_start_rechecks_predecessor_after_waiting_for_lease(tmp_path, monkeypatch):
    from gms_helpers.run_session import RunSessionManager
    from gms_helpers.runner import GameMakerRunner

    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    manager = RunSessionManager(tmp_path)
    lock = mac_runtime.project_run_lock(tmp_path)
    acquire = lock.acquire
    events = []

    def acquire_after_other_launcher(**kwargs):
        manager.create_session(pid=987654321, exe_path="old", isolated_runtime=True)
        return acquire(**kwargs)

    def archive(root, predecessor):
        events.append("archived")
        manager.clear_session()

    def start(root, **kwargs):
        assert manager.get_current_session() is None
        events.append("started")
        return {"running": False}

    monkeypatch.setattr(lock, "acquire", acquire_after_other_launcher)
    monkeypatch.setattr(live_session, "project_run_lock", lambda root: lock)
    monkeypatch.setattr(live_session, "_archive_persisted", archive)
    monkeypatch.setattr(live_session, "_start", start)
    monkeypatch.setattr(GameMakerRunner, "_snapshot_macos_processes", lambda self: {})
    live_session.start(tmp_path)
    assert events == ["archived", "started"]


def test_force_stop_waits_for_exit_before_returning():
    calls = []

    def wait(timeout):
        calls.append("wait")
        if calls.count("wait") == 1:
            raise subprocess.TimeoutExpired("runner", timeout)

    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: calls.append("terminate"),
        kill=lambda: calls.append("kill"),
        wait=wait,
    )
    snapshot_build.stop_process(process)
    assert calls == ["terminate", "wait", "kill", "wait"]


def test_run_artifacts_cannot_follow_checkout_symlinks(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (root / ".gms_mcp").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(snapshot_build.SnapshotError, match="symlinks"):
        snapshot_build.runs_directory(root, "live")
    assert not list(foreign.iterdir())


@pytest.mark.parametrize("name", ["runner_stderr.log", "build.log", "run.log"])
def test_log_writes_do_not_follow_artifact_symlinks(tmp_path, name):
    foreign = tmp_path / "private.txt"
    foreign.write_text("keep")
    target = tmp_path / name
    target.symlink_to(foreign)
    with pytest.raises(snapshot_build.SnapshotError, match="symlink"):
        with snapshot_build.artifact_writer(target) as stream:
            stream.write(b"overwrite")
    assert foreign.read_text() == "keep"


@pytest.mark.parametrize("name", ["../escape", "/absolute/escape", "bad\\name", 'bad"name'])
def test_configured_test_script_name_cannot_escape_snapshot(tmp_path, name):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / ".gms-mcp-snapshot").write_text("snapshot")
    with pytest.raises(snapshot_build.SnapshotError, match="identifier"):
        snapshot_build.inject_test_script(snapshot, "function agent_test_step(_frame) {}", script_name=name)
    assert list(snapshot.iterdir()) == [snapshot / ".gms-mcp-snapshot"]


def test_run_return_cannot_attach_to_replacement_session(tmp_path, monkeypatch):
    from gms_helpers.runner import GameMakerRunner

    (tmp_path / "game.yyp").write_text('{"name":"game","resources":[]}')
    replacement = SimpleNamespace(run_id="new", process=SimpleNamespace(pid=222))
    monkeypatch.setattr(live_session, "start", lambda *args, **kwargs: {"running": True, "pid": 111, "run_id": "old"})
    monkeypatch.setattr(live_session, "get_session", lambda root: replacement)
    result = GameMakerRunner(tmp_path).run_project_direct("macOS", background=True)
    assert not result["ok"] and "session ended" in result["message"]


@pytest.mark.parametrize("failure", ["codesign", "../foreign", "/absolute", "bad\\name", "", 42])
def test_runner_preparation_failure_removes_only_its_staging(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    original = tmp_path / "official.app"
    runner = original / "Contents/MacOS/Mac_Runner"
    runner.parent.mkdir(parents=True)
    runner.write_bytes(b"runner")
    before = plistlib.dumps(
        {"CFBundleIdentifier": "original", "CFBundleExecutable": "Mac_Runner" if failure == "codesign" else failure}
    )
    (original / "Contents/Info.plist").write_bytes(before)
    root = tmp_path / "game"
    save = tmp_path / "Library/Application Support" / f"com.gmsmcp.game.p{mac_runtime.project_identity(root)}"
    save.mkdir(parents=True)
    (save / "existing-save.txt").write_text("keep")

    def fail_sign(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "codesign")

    monkeypatch.setattr(mac_runtime.subprocess, "run", fail_sign)
    with pytest.raises(subprocess.CalledProcessError if failure == "codesign" else ValueError):
        mac_runtime.prepare_mac_runtime(runner, root, "test")
    assert not list(save.glob("session_*"))
    assert (save / "existing-save.txt").read_text() == "keep"
    assert (original / "Contents/Info.plist").read_bytes() == before


@pytest.mark.parametrize("attack", ["shots_directory", "target_file", "source_link", "non_image", "missing_source"])
def test_bridge_screenshot_preserves_foreign_files(tmp_path, monkeypatch, attack):
    root = tmp_path / "project"
    save = root / "save"
    run = root / "run"
    save.mkdir(parents=True)
    run.mkdir()
    foreign = tmp_path / "private.png"
    foreign.write_bytes(b"keep")
    source = save / "capture.png"
    source.write_bytes(b"image")
    shots = run / "shots"
    if attack == "shots_directory":
        shots.symlink_to(tmp_path, target_is_directory=True)
    elif attack == "target_file":
        shots.mkdir()
        (shots / "shot.png").symlink_to(foreign)
    elif attack == "source_link":
        source.unlink()
        source.symlink_to(foreign)
    elif attack == "non_image":
        source = save / "data.txt"
        source.write_text("data")
    elif attack == "missing_source":
        source = None
    monkeypatch.setitem(
        live_session._SESSIONS, str(root.resolve()), SimpleNamespace(save_dir=save, run_dir=run, project_root=root)
    )
    monkeypatch.setattr(
        live_session,
        "command",
        lambda *args: {"ok": True, "command": "screenshot shot", "data": {"file": str(source)} if source else {}},
    )
    if attack in {"shots_directory", "target_file"}:
        with pytest.raises(live_session.LiveSessionError, match="symlink"):
            live_session.screenshot(root, timeout_seconds=0)
    else:
        assert not live_session.screenshot(root, timeout_seconds=0)["ok"]
    assert foreign.read_bytes() == b"keep"
