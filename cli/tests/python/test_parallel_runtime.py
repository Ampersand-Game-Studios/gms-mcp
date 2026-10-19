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
