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
        process=SimpleNamespace(pid=4242, poll=lambda: 0),
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


@pytest.mark.parametrize(
    "path",
    [
        "../game.ios",
        "/game.ios",
        "C:game.ios",
        "C:/game.ios",
        "\\game.ios",
        "//server/share/game.ios",
        "Runner.app/Contents/Info.plist",
    ],
)
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


@pytest.mark.parametrize("failure", ["bridge", "preparation", "launch"])
def test_startup_rollback_closes_bridge_and_releases_both_leases(tmp_path, monkeypatch, failure):
    root = tmp_path / "project"
    work = tmp_path / "work"
    work.mkdir()
    archive = work / "game.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("game.ios", b"data")
    save = tmp_path / "save"
    staging = save / "session_test"
    staging.mkdir(parents=True)
    (save / "existing-save.txt").write_text("keep")
    closed = []
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(
        snapshot_build,
        "snapshot_compile",
        lambda *args, **kwargs: (
            {"ok": True, "label": "rollback"},
            snapshot_build.BuildResult(True, "COMPILE_OK", game_archive=archive),
            work,
            None,
        ),
    )
    monkeypatch.setattr(snapshot_build, "require_mac_runner", lambda tools: Path("runner"))
    monkeypatch.setattr(
        live_session,
        "BridgeServer",
        lambda **kwargs: SimpleNamespace(
            start=lambda: failure != "bridge",
            stop=lambda: closed.append(True),
            port=0,
        ),
    )

    def prepare(*args):
        if failure == "preparation":
            raise OSError("runner preparation failed")
        return mac_runtime.MacRuntime(Path("runner"), staging, save, "fixture.bundle")

    monkeypatch.setattr(live_session, "prepare_mac_runtime", prepare)
    monkeypatch.setattr(
        snapshot_build, "launch_mac_runner", lambda *args: (_ for _ in ()).throw(OSError("launch failed"))
    )
    with pytest.raises(snapshot_build.SnapshotError if failure == "bridge" else OSError):
        live_session.start(root, label="rollback", connect_timeout_seconds=0)
    assert closed == [True]
    assert not work.exists()
    if failure == "launch":
        assert not staging.exists()
    assert (save / "existing-save.txt").read_text() == "keep"
    assert not mac_runtime.project_run_lock(root).path.exists()
    assert not snapshot_build.pipeline_lock(root, "rollback").path.exists()
    assert live_session.get_session(root) is None


@pytest.mark.parametrize("name", ["build.log", "run.log", "runner_stderr.log", "shot.png", "build.zip"])
def test_artifact_replacement_never_truncates_hardlinks(tmp_path, name):
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"retain")
    target = tmp_path / name
    os.link(sentinel, target)
    with snapshot_build.artifact_writer(target) as stream:
        stream.write(b"new artifact")
    assert sentinel.read_bytes() == b"retain"
    assert target.read_bytes() == b"new artifact"
    assert sentinel.stat().st_ino != target.stat().st_ino


def test_cached_run_directory_replacement_cannot_redirect_artifacts(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    run = snapshot_build.runs_directory(root, "live")
    run.mkdir(parents=True)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    sentinel = foreign / "run.log"
    sentinel.write_text("retain")
    run.rmdir()
    run.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(snapshot_build.SnapshotError, match="symlinks"):
        with snapshot_build.artifact_writer(run / "run.log") as stream:
            stream.write(b"overwrite")
    with pytest.raises(snapshot_build.SnapshotError, match="symlinks"):
        snapshot_build.collect_screenshots(run / "shots", "__agent_shot_", 0, tmp_path)
    with pytest.raises(snapshot_build.SnapshotError, match="symlinks"):
        snapshot_build.clear_artifact_directory(run / "shots")
    assert sentinel.read_text() == "retain" and list(foreign.iterdir()) == [sentinel]


def _exited_session_fixture(tmp_path, monkeypatch):
    from gms_helpers.run_session import RunSessionManager

    root = tmp_path / "project"
    staging, work, save = root / "staging", root / "work", root / "save"
    for directory in (staging, work, save):
        directory.mkdir(parents=True)
    log = staging / "debug.txt"
    log.write_text("unique recovery log")
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(RunSessionManager, "_state_root", lambda self: tmp_path / "sessions")
    manager = RunSessionManager(root)
    persisted = manager.create_session(pid=4242, exe_path=str(staging / "game.ios"), isolated_runtime=True)
    lease = mac_runtime.project_run_lock(root)
    label = snapshot_build.pipeline_lock(root, "live")
    lease.acquire()
    label.acquire()
    session = live_session.LiveSession(
        project_root=root,
        label="live",
        process=SimpleNamespace(pid=4242, poll=lambda: 0),
        bridge=None,
        lock=lease,
        label_lock=label,
        save_dir=save,
        staging=staging,
        debug_log=log,
        run_dir=snapshot_build.runs_directory(root, "live"),
        work_dir=work,
        run_id=persisted.run_id,
    )
    return session, manager


@pytest.mark.parametrize("failure", ["copy", "screenshots", "ancestor"])
def test_archive_failure_preserves_evidence_and_can_retry(tmp_path, monkeypatch, failure):
    session, manager = _exited_session_fixture(tmp_path, monkeypatch)
    original_log = session.debug_log
    copier, collector = snapshot_build.copy_artifact, snapshot_build.collect_screenshots
    if failure == "ancestor":
        session.run_dir.parent.mkdir(parents=True)
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        session.run_dir.symlink_to(foreign, target_is_directory=True)
    else:
        method = "copy_artifact" if failure == "copy" else "collect_screenshots"
        monkeypatch.setattr(snapshot_build, method, lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises((OSError, snapshot_build.SnapshotError)):
        live_session._cleanup(session)
    assert original_log.read_text() == "unique recovery log"
    assert session.staging.is_dir() and session.work_dir.is_dir() and not session.cleaned
    assert manager.get_current_session().run_id == session.run_id
    assert not session.lock.held and not session.label_lock.held
    if failure == "ancestor":
        assert not list(foreign.iterdir())
        session.run_dir.unlink()
    monkeypatch.setattr(snapshot_build, "copy_artifact", copier)
    monkeypatch.setattr(snapshot_build, "collect_screenshots", collector)
    live_session._cleanup(session)
    assert session.cleaned and not session.staging.exists() and not session.work_dir.exists()
    assert session.debug_log.read_text() == "unique recovery log"
    assert manager.get_current_session() is None


def test_cleanup_keeps_leases_until_runner_exits(tmp_path, monkeypatch):
    session, manager = _exited_session_fixture(tmp_path, monkeypatch)
    session.process.poll = lambda: None
    try:
        with pytest.raises(live_session.LiveSessionError, match="still running"):
            live_session._cleanup(session)
        assert session.lock.held and session.label_lock.held
        assert session.staging.exists() and manager.get_current_session() is not None
    finally:
        session.process.poll = lambda: 0
        live_session._cleanup(session)


@pytest.mark.parametrize("failure", ["discovery", "config", "compile", "copy"])
def test_compile_exception_cleans_untransferred_work_even_when_retention_requested(tmp_path, monkeypatch, failure):
    root = tmp_path / "project"
    root.mkdir()
    (root / "game.yyp").write_text('{"name":"game","resources":[]}')
    workroot = tmp_path / "snapshots"
    monkeypatch.setattr(snapshot_build, "_work_root", lambda: workroot)
    tools = snapshot_build.Toolchain(Path("igor"), Path("runtime"), Path("license"), None, "test")
    monkeypatch.setattr(snapshot_build, "discover_toolchain", lambda *a: tools)

    def fail(*args, **kwargs):
        raise RuntimeError("fixture failure")

    if failure == "discovery":
        monkeypatch.setattr(snapshot_build, "discover_toolchain", fail)
    elif failure == "config":
        monkeypatch.setattr(snapshot_build, "project_setting", fail)
    elif failure == "compile":
        monkeypatch.setattr(snapshot_build, "compile_snapshot", fail)
    else:

        def failed_copy(source, destination):
            destination.mkdir(parents=True)
            (destination / "partial").write_text("partial copy")
            fail()

        monkeypatch.setattr(snapshot_build, "_copy_tree", failed_copy)
    with pytest.raises(RuntimeError, match="fixture failure"):
        snapshot_build.snapshot_compile(root, keep_work_dir=True)
    assert not list(workroot.iterdir())
    assert (root / "game.yyp").is_file()


@pytest.mark.parametrize(
    "exit_code,complete,artifacts,expected",
    [
        (-9, True, "fresh", False),
        (1, True, "fresh", False),
        (0, False, "fresh", False),
        (0, True, "partial", False),
        (0, True, "stale", False),
        (0, True, "fresh", True),
    ],
)
def test_html5_requires_export_success_and_fresh_complete_artifacts(
    tmp_path, monkeypatch, exit_code, complete, artifacts, expected
):
    root, work = tmp_path / "project", tmp_path / "work"
    root.mkdir()
    (root / "game.yyp").write_text('{"name":"game","resources":[]}')
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(tmp_path / "locks"))
    output = work / "html5"

    def write_output():
        output.mkdir(parents=True, exist_ok=True)
        (output / "index.html").write_text("<script src='game.js'></script>")
        if artifacts != "partial":
            (output / "game.js").write_text("window.game=true;")

    if artifacts == "stale":
        write_output()

    def igor(command, log, timeout):
        log.write_text("Stats : GMA : Elapsed=2.0\n" + ("Igor complete.\n" if complete else ""))
        if artifacts != "stale":
            write_output()
        return exit_code

    tools = snapshot_build.Toolchain(Path("igor"), Path("runtime"), Path("license"), None, "test")
    result = snapshot_build.compile_snapshot(root, work, tools, platform="HTML5", attempts=1, run_igor=igor)
    assert result.ok is expected


def test_failed_cleanup_retry_does_not_touch_replacement_screenshots_or_metadata(tmp_path, monkeypatch):
    session, manager = _exited_session_fixture(tmp_path, monkeypatch)
    copier = snapshot_build.copy_artifact
    monkeypatch.setattr(snapshot_build, "copy_artifact", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        live_session._cleanup(session)
    replacement = manager.create_session(pid=4242, exe_path="replacement", isolated_runtime=True)
    new_shot = session.save_dir / "__agent_shot_new.png"
    new_shot.write_bytes(b"replacement")
    monkeypatch.setattr(snapshot_build, "copy_artifact", copier)
    live_session._cleanup(session)
    assert manager.get_current_session().run_id == replacement.run_id
    assert new_shot.read_bytes() == b"replacement"
    assert session.debug_log.read_text() == "unique recovery log"
    assert not session.cleaned and session.staging.is_dir() and session.work_dir.is_dir()


def test_start_recovers_dead_session_before_acquiring_replacement_leases(tmp_path, monkeypatch):
    session, manager = _exited_session_fixture(tmp_path, monkeypatch)
    monkeypatch.setitem(live_session._SESSIONS, str(session.project_root.resolve()), session)
    copier = snapshot_build.copy_artifact
    monkeypatch.setattr(snapshot_build, "copy_artifact", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        live_session.stop(session.project_root)
    assert live_session.get_session(session.project_root) is session
    monkeypatch.setattr(snapshot_build, "copy_artifact", copier)
    monkeypatch.setattr(live_session, "_start", lambda *a, **kw: {"ok": True, "running": False})
    result = live_session.start(session.project_root)
    assert result["ok"] and session.cleaned
    assert live_session.get_session(session.project_root) is None
    assert manager.get_current_session() is None


@pytest.mark.skipif(os.name == "nt", reason="Windows pins source ancestors against rename")
def test_screenshot_move_copies_the_original_pinned_source_when_parent_changes(tmp_path, monkeypatch):
    import contextlib

    save, previous = tmp_path / "save", tmp_path / "previous"
    save.mkdir()
    source = save / "shot.png"
    source.write_bytes(b"unique original")
    destination = tmp_path / "shots/shot.png"
    writer = snapshot_build.artifact_writer

    @contextlib.contextmanager
    def replace_parent(path):
        save.rename(previous)
        save.mkdir()
        source.write_bytes(b"attacker replacement")
        with writer(path) as stream:
            yield stream

    monkeypatch.setattr(snapshot_build, "artifact_writer", replace_parent)
    snapshot_build.move_artifact(source, destination)
    assert destination.read_bytes() == b"unique original"
    assert source.read_bytes() == b"attacker replacement"
    assert not (previous / "shot.png").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows pinned-handle artifact implementation")
def test_windows_artifact_ancestors_are_pinned_until_publication(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    moved = tmp_path / "moved"
    with snapshot_build.artifact_writer(root / "run.log") as outgoing:
        with pytest.raises(OSError):
            root.rename(moved)
        outgoing.write(b"normal output")
    assert (root / "run.log").read_bytes() == b"normal output"


@pytest.mark.skipif(os.name != "nt", reason="Windows pinned-handle artifact implementation")
def test_windows_artifact_reader_prevents_source_replacement(tmp_path):
    from gms_helpers.artifact_windows import read_source

    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    with read_source(source) as incoming:
        with pytest.raises(OSError):
            source.rename(tmp_path / "replacement.png")
        assert incoming.read() == b"source"


@pytest.mark.skipif(os.name != "nt", reason="Windows pinned-handle artifact implementation")
def test_windows_artifact_move_deletes_original_handle_after_publication(tmp_path):
    source = tmp_path / "source.png"
    destination = tmp_path / "shots/moved.png"
    source.write_bytes(b"original")
    snapshot_build.move_artifact(source, destination)
    assert not source.exists() and destination.read_bytes() == b"original"


@pytest.fixture
def windows_kernel_handles(monkeypatch):
    """Exercise Win32 decisions with real files/descriptors and an explicit API fake."""
    import ctypes
    import stat
    from ctypes import wintypes
    from gms_helpers import artifact_windows

    if os.name == "nt":
        pytest.skip("Native Windows checks exercise the real kernel handles")
    active, calls, failure = {}, [], {}

    def create(path, access, share, security, disposition, flags, template):
        calls.append((str(path), access, share, flags))
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return ctypes.c_void_p(-1).value
        active[descriptor] = str(path)
        return descriptor

    def close(handle):
        os.close(handle)
        active.pop(handle)
        return True

    def information(handle, kind, output, size):
        if failure.get("information"):
            return False
        info = os.lstat(active[handle])
        attributes = (0x10 if stat.S_ISDIR(info.st_mode) else 0) | (0x400 if stat.S_ISLNK(info.st_mode) else 0)
        ctypes.cast(output, ctypes.POINTER(wintypes.DWORD))[0] = attributes
        return True

    def duplicate(process, handle, target, output, access, inherit, options):
        if failure.get("duplicate"):
            return False
        duplicated = os.dup(handle)
        ctypes.cast(output, ctypes.POINTER(wintypes.HANDLE))[0] = duplicated
        return True

    def dispose(handle, kind, information, size):
        assert kind == 4 and size == 1
        assert ctypes.cast(information, ctypes.POINTER(ctypes.c_ubyte))[0] == 1
        if failure.get("disposition"):
            return False
        os.unlink(active[handle])
        return True

    def process():
        return 1

    def file_type(handle):
        return 1

    kernel = SimpleNamespace(
        CreateFileW=create,
        CloseHandle=close,
        GetFileType=file_type,
        GetFileInformationByHandleEx=information,
        DuplicateHandle=duplicate,
        GetCurrentProcess=process,
        SetFileInformationByHandle=dispose,
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 2, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda error: FileNotFoundError("fake Win32 failure"), raising=False)
    monkeypatch.setattr(os, "O_BINARY", getattr(os, "O_BINARY", 0), raising=False)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=lambda handle, flags: handle))
    original_lstat = Path.lstat

    class FileAttributes:
        def __init__(self, original):
            self.original = original
            self.st_file_attributes = (0x10 if stat.S_ISDIR(original.st_mode) else 0) | (
                0x400 if stat.S_ISLNK(original.st_mode) else 0
            )

        def __getattr__(self, name):
            return getattr(self.original, name)

    monkeypatch.setattr(Path, "lstat", lambda self: FileAttributes(original_lstat(self)))
    yield artifact_windows, active, calls, failure
    assert not active, "Every Windows-owned original handle must close, including error paths"


def test_windows_helper_pins_real_ancestors_and_closes_owned_sources(tmp_path, windows_kernel_handles):
    windows, active, calls, failure = windows_kernel_handles
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    with windows.read_source(source) as incoming:
        assert incoming.read() == b"original" and source.exists()
    with windows.read_source(source, delete_on_success=True) as incoming:
        assert incoming.read() == b"original" and source.exists()
    assert not source.exists()
    assert all(share == 3 and flags & 0x00200000 for _, _, share, flags in calls)
    assert any(access & 0x10000 for _, access, _, _ in calls)


@pytest.mark.parametrize("failure_name", ["information", "duplicate", "disposition"])
def test_windows_helper_failure_preserves_source_and_releases_handles(tmp_path, windows_kernel_handles, failure_name):
    windows, active, calls, failure = windows_kernel_handles
    source = tmp_path / "source.bin"
    source.write_bytes(b"unique")
    failure[failure_name] = True
    with pytest.raises(OSError):
        with windows.read_source(source, delete_on_success=True) as incoming:
            assert incoming.read() == b"unique"
    assert source.read_bytes() == b"unique"


def test_windows_helper_failed_publication_preserves_source(tmp_path, windows_kernel_handles):
    windows, active, calls, failure = windows_kernel_handles
    source = tmp_path / "source.bin"
    source.write_bytes(b"unique")
    with pytest.raises(RuntimeError, match="publication"):
        with windows.read_source(source, delete_on_success=True):
            raise RuntimeError("publication failed")
    assert source.read_bytes() == b"unique"


def test_windows_helper_rejects_reparse_points_and_wrong_file_kinds(tmp_path, windows_kernel_handles):
    windows, active, calls, failure = windows_kernel_handles
    file = tmp_path / "file"
    file.write_bytes(b"retain")
    directory = tmp_path / "directory"
    directory.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(directory, target_is_directory=True)
    for path, is_directory in [(linked, True), (file, True), (directory, False)]:
        with pytest.raises(OSError, match="reparse"):
            with windows._pinned(path, directory=is_directory):
                pytest.fail("Unsafe handle accepted")
    with pytest.raises(OSError, match="reparse"):
        with windows.pinned_parent(linked / "run.log"):
            pytest.fail("Reparse ancestor accepted")
    with pytest.raises(OSError, match="streams"):
        with windows.pinned_parent(tmp_path / "file:stream"):
            pytest.fail("Alternate stream accepted")
    assert file.read_bytes() == b"retain"


def test_windows_helper_creates_and_clears_literal_nested_directories(tmp_path, windows_kernel_handles):
    windows, active, calls, failure = windows_kernel_handles
    target = tmp_path / "runs/live/shots"
    with windows.pinned_parent(target / "shot.png", create=True) as (descriptor, name):
        assert descriptor is None and name == str(target / "shot.png")
        (target / "shot.png").write_bytes(b"shot")
    (target / "nested").mkdir()
    (target / "nested/other.png").write_bytes(b"other")
    windows.clear_directory(target)
    assert not target.exists()
    windows.clear_directory(target)
    assert not target.exists()
