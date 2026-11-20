"""Builds that are followed by label: stages, a result that outlives the call, and a stop."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from gms_helpers import run_status, snapshot_build
from gms_mcp.gamemaker_mcp_server import build_server
from gms_mcp.server import background_runs
from gms_mcp.server import project as project_module
from gms_mcp.server.results import unwrap_call_tool_result


@pytest.fixture(autouse=True)
def _fresh_registry():
    background_runs._RUNS.clear()
    yield
    background_runs.stop_all()
    background_runs._RUNS.clear()


def _run_dir(tmp_path: Path, label: str = "compile") -> Path:
    return tmp_path / "game" / ".gms_mcp" / "runs" / label


def _start(directory: Path, work) -> dict:
    return asyncio.run(background_runs.run(directory, "compile", "gm_snapshot_compile", work, wait_seconds=0))


def _wait_until(condition, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "condition was not met in time"
        time.sleep(0.02)


# --- the record a run keeps ------------------------------------------------------------------


def test_a_run_records_nothing_until_it_holds_its_label(tmp_path: Path):
    directory = _run_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / run_status.RESULT_FILE).write_text('{"ok": true, "status": "EARLIER"}', encoding="utf-8")

    with run_status.track_run(directory, "compile", "gm_snapshot_compile") as tracker:
        # Another run with this label may still be writing here.
        assert run_status.read_status(directory) is None
        assert run_status.read_result(directory) == {"ok": True, "status": "EARLIER"}

        run_status.report_stage("compiling", attempt=2, attempts=10, live_log="/somewhere/build.log")
        saved = run_status.read_status(directory)
        assert saved["state"] == "running"
        assert (saved["stage"], saved["attempt"], saved["attempts"]) == ("compiling", 2, 10)
        assert saved["pid"] == os.getpid()
        assert run_status.read_result(directory) is None, "the earlier run's result must not read as this run's"

        run_status.report_stage("reading the build result")
        assert "attempt" not in run_status.read_status(directory), "details belong to one stage"

        tracker.finish({"ok": False, "status": "BUILD_FAILED", "errors": ["boom"]})

    saved = run_status.read_status(directory)
    assert saved["state"] == "finished"
    assert saved["outcome"] == {"ok": False, "status": "BUILD_FAILED"}
    assert run_status.read_result(directory)["errors"] == ["boom"]
    assert run_status.current() is None


def test_a_run_that_never_got_its_label_leaves_the_directory_alone(tmp_path: Path):
    directory = _run_dir(tmp_path)
    with run_status.track_run(directory, "compile", "gm_snapshot_compile") as tracker:
        tracker.finish({"ok": False, "error": "could not get the label"})
    assert not directory.exists()


def test_stage_reports_outside_a_tracked_run_do_nothing(tmp_path: Path):
    run_status.report_stage("compiling")
    run_status.raise_if_stopped()
    assert run_status.stop_requested() is False


def test_status_files_are_never_written_through_a_link(tmp_path: Path):
    directory = _run_dir(tmp_path)
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("untouched", encoding="utf-8")
    try:
        (directory / run_status.STATUS_FILE).symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available here")
    with run_status.track_run(directory, "compile", "gm_snapshot_compile"):
        run_status.report_stage("compiling")
    assert outside.read_text(encoding="utf-8") == "untouched"
    assert not (directory / run_status.STATUS_FILE).is_symlink()


# --- following and stopping a run --------------------------------------------------------------


def test_background_run_reports_its_stage_then_its_result(tmp_path: Path):
    directory = _run_dir(tmp_path)
    log = tmp_path / "build.log"
    log.write_text("Loading project\n\nCompiling scripts\n", encoding="utf-8")
    release = threading.Event()

    def work():
        run_status.report_stage("compiling", attempt=1, attempts=10, live_log=str(log))
        assert release.wait(10)
        return {"ok": True, "status": "COMPILED", "label": "compile"}

    started = _start(directory, work)
    assert (started["ok"], started["status"]) == (True, "STARTED")
    assert 'gm_build_status(label="compile")' in started["next"]

    _wait_until(lambda: background_runs.status(directory).get("stage") == "compiling")
    report = background_runs.status(directory, log_lines=1)
    assert report["finished"] is False
    assert (report["attempt"], report["max_attempts"]) == (1, 10)
    assert report["log_tail"] == ["Compiling scripts"]
    assert 0 <= report["log_quiet_seconds"] < 30
    assert "live_log" not in report, "the log's host path stays out of the report"

    again = _start(directory, work)
    assert (again["ok"], again["status"]) == (False, "ALREADY_RUNNING")

    release.set()
    _wait_until(lambda: background_runs.status(directory)["finished"])
    report = background_runs.status(directory)
    run_seconds = report.pop("run_seconds")
    assert 0 <= run_seconds < 30, "the whole run, by the clock the running reports used"
    assert list(report.pop("stages")) == ["compiling"], "where the time went"
    assert report == {
        "finished": True,
        "operation": "gm_snapshot_compile",
        "ok": True,
        "status": "COMPILED",
        "label": "compile",
    }
    assert run_status.read_result(directory)["status"] == "COMPILED"


def test_a_run_waiting_for_its_label_says_so(tmp_path: Path):
    directory = _run_dir(tmp_path)
    release = threading.Event()

    def work():
        assert release.wait(10)  # holds no label yet, so has reported no stage
        return {"ok": True}

    _start(directory, work)
    _wait_until(lambda: background_runs.find(directory).tracker is not None)
    report = background_runs.status(directory)
    assert report["finished"] is False
    assert report["stage"] == "waiting for an earlier run with this label to finish"
    release.set()
    _wait_until(lambda: background_runs.status(directory)["finished"])


def test_a_background_run_can_be_stopped(tmp_path: Path):
    directory = _run_dir(tmp_path)

    def work():
        run_status.report_stage("waiting for a build slot")
        run_status.sleep_unless_stopped(60)
        return {"ok": True}

    _start(directory, work)
    _wait_until(lambda: background_runs.status(directory).get("stage") == "waiting for a build slot")
    stopped = background_runs.stop(directory)
    assert (stopped["ok"], stopped["stopped"]) == (True, True)
    report = background_runs.status(directory)
    assert (report["finished"], report["ok"], report["status"]) == (True, False, "STOPPED")
    assert report["stopped_during"] == "waiting for a build slot"
    again = background_runs.stop(directory)
    assert (again["ok"], again["stopped"], again["already_finished"], again["status"]) == (True, False, True, "STOPPED")
    assert background_runs.stop(_run_dir(tmp_path, "never"))["ok"] is False


def test_a_failed_background_run_is_reported_not_lost(tmp_path: Path):
    directory = _run_dir(tmp_path)

    def work():
        run_status.report_stage("copying the project")
        raise RuntimeError("the copy failed")

    _start(directory, work)
    _wait_until(lambda: background_runs.status(directory)["finished"])
    report = background_runs.status(directory)
    assert (report["ok"], report["error"], report["error_type"]) == (False, "the copy failed", "RuntimeError")


def test_a_waited_run_returns_its_result_or_hands_over(tmp_path: Path):
    directory = _run_dir(tmp_path)
    release = threading.Event()

    def quick():
        run_status.report_stage("compiling")
        return {"ok": True, "status": "COMPILED"}

    # The whole wait is allowed: the caller gets the result itself, in the shape a status call gives.
    done = asyncio.run(background_runs.run(directory, "compile", "gm_snapshot_compile", quick, wait_seconds=None))
    assert (done["finished"], done["ok"], done["status"], done["label"]) == (True, True, "COMPILED", "compile")
    assert list(done["stages"]) == ["compiling"] and done["run_seconds"] >= 0

    def slow():
        run_status.report_stage("compiling", attempt=1, attempts=10)
        assert release.wait(20)
        return {"ok": True, "status": "COMPILED"}

    handed_over = asyncio.run(background_runs.run(directory, "compile", "gm_snapshot_compile", slow, wait_seconds=0.3))
    assert (handed_over["ok"], handed_over["finished"], handed_over["status"]) == (True, False, "STILL_RUNNING")
    assert handed_over["stage"] == "compiling" and 'gm_build_status(label="compile")' in handed_over["next"]
    release.set()
    _wait_until(lambda: background_runs.status(directory)["finished"])
    assert background_runs.status(directory)["status"] == "COMPILED"

    def broken():
        raise ValueError("bad input")

    failed = asyncio.run(background_runs.run(directory, "compile", "gm_snapshot_compile", broken, wait_seconds=None))
    assert (failed["ok"], failed["error"], failed["error_type"]) == (False, "bad input", "ValueError")


# --- runs recorded by another process --------------------------------------------------------------


def _record(directory: Path, **state) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    (directory / run_status.STATUS_FILE).write_text(
        json.dumps(
            {
                "state": "running",
                "operation": "gm_test_run",
                "started_at": now - 40,
                "stage_started_at": now - 5,
                **state,
            }
        ),
        encoding="utf-8",
    )


def test_another_sessions_run_is_followed_without_reading_the_log_it_names(tmp_path: Path):
    directory = _run_dir(tmp_path, "test")
    secret = tmp_path / "secret.txt"
    secret.write_text("do not show this\n", encoding="utf-8")
    # The status file is inside the project: anyone can write one that names any path.
    _record(directory, pid=os.getpid(), stage="running the test", live_log=str(secret))

    report = background_runs.status(directory)
    assert (report["finished"], report["stage"], report["operation"]) == (False, "running the test", "gm_test_run")
    assert report["run_seconds"] >= 39 and 4 <= report["stage_seconds"] < 30
    assert "log_tail" not in report
    assert "do not show this" not in json.dumps(report)


def test_a_run_whose_process_died_is_reported_as_interrupted(tmp_path: Path):
    directory = _run_dir(tmp_path, "test")
    _record(directory, pid=2**22 + 12345, stage="compiling")
    with patch("gms_helpers.agent_locks._process_alive", return_value=False):
        report = background_runs.status(directory)
    assert (report["finished"], report["ok"], report["status"]) == (True, False, "INTERRUPTED")
    assert "compiling" in report["message"]


def test_another_sessions_finished_run_returns_its_saved_result(tmp_path: Path):
    directory = _run_dir(tmp_path, "test")
    _record(directory, state="finished", pid=1, outcome={"ok": True, "status": "TEST_PASSED"})
    (directory / run_status.RESULT_FILE).write_text(
        json.dumps({"ok": True, "status": "TEST_PASSED", "test_lines": ["[TEST] PASS moved"]}), encoding="utf-8"
    )
    report = background_runs.status(directory)
    assert (report["finished"], report["status"], report["test_lines"]) == (True, "TEST_PASSED", ["[TEST] PASS moved"])


def test_an_unknown_label_names_the_ones_that_exist(tmp_path: Path):
    _record(_run_dir(tmp_path, "test"), pid=os.getpid(), stage="compiling")
    report = background_runs.status(_run_dir(tmp_path, "nope"))
    assert (report["ok"], report["finished"], report["known_labels"]) == (False, False, ["test"])
    assert not _run_dir(tmp_path, "nope").exists(), "looking must not create the run directory"


# --- the compiler process ---------------------------------------------------------------------------


def test_stopping_a_run_ends_its_compiler_process(tmp_path: Path):
    log = tmp_path / "build.log"
    outcome: dict = {}

    def build():
        with run_status.track_run(_run_dir(tmp_path), "compile", "gm_snapshot_compile") as tracker:
            outcome["tracker"] = tracker
            started = time.monotonic()
            outcome["code"] = snapshot_build._default_run_igor(
                [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(120)"], log, 300.0
            )
            outcome["seconds"] = time.monotonic() - started

    thread = threading.Thread(target=build)
    thread.start()
    try:
        _wait_until(lambda: log.exists() and "started" in log.read_text(encoding="utf-8", errors="replace"), 20)
        outcome["tracker"].request_stop()
        assert snapshot_build.stop_builds(outcome["tracker"]) == 1
    finally:
        thread.join(timeout=30)
    assert not thread.is_alive()
    assert outcome["code"] != 0
    assert outcome["seconds"] < 30
    assert "stopped on request" in log.read_text(encoding="utf-8", errors="replace")
    assert snapshot_build.stop_builds() == 0, "no build is left registered"


def test_the_compiler_still_returns_its_own_exit_code(tmp_path: Path):
    log = tmp_path / "build.log"
    code = snapshot_build._default_run_igor([sys.executable, "-c", "print('done'); raise SystemExit(3)"], log, 60.0)
    assert code == 3
    assert "done" in log.read_text(encoding="utf-8", errors="replace")


# --- through the server --------------------------------------------------------------------------


@contextmanager
def _server(tmp_path: Path):
    project = tmp_path / "workspace" / "gamemaker"
    project.mkdir(parents=True)
    (project / "game.yyp").write_text(json.dumps({"name": "game", "resources": []}), encoding="utf-8")
    start = project.resolve()
    environment = {
        "GM_PROJECT_ROOT": str(project),
        "GMS_MCP_TOOLSETS": "core",
        "GMS_MCP_LOCK_DIR": str(tmp_path / "locks"),
    }
    with (
        patch.dict(os.environ, environment, clear=False),
        patch.object(project_module, "_SERVER_START_DIRECTORY", start),
        patch("gms_mcp.server.tools.project_health._SERVER_START_DIRECTORY", start),
    ):
        os.environ.pop("GMS_MCP_READ_ONLY", None)
        yield build_server(), project


def _call(server, tool: str, **arguments):
    return unwrap_call_tool_result(asyncio.run(server.call_tool(tool, arguments)))


def test_a_background_compile_is_followed_and_finished_through_the_tools(tmp_path: Path):
    release = threading.Event()
    log = tmp_path / "build.log"

    def fake_compile(root, *, label, **_options):
        log.write_text("Compiling scripts\n", encoding="utf-8")
        run_status.report_stage("compiling", attempt=1, attempts=10, live_log=str(log))
        assert release.wait(20)
        work = tmp_path / "work"
        work.mkdir()
        return {"ok": True, "status": "COMPILED", "label": label, "errors": []}, None, work, None

    with _server(tmp_path) as (server, project), patch.object(snapshot_build, "snapshot_compile", fake_compile):
        started = _call(server, "gm_snapshot_compile", label="mine", background=True)
        assert (started["ok"], started["status"], started["label"]) == (True, "STARTED", "mine")

        _wait_until(lambda: _call(server, "gm_build_status", label="mine", wait_seconds=0).get("stage") == "compiling")
        running = _call(server, "gm_build_status", label="mine", wait_seconds=0)
        assert running["finished"] is False
        assert running["log_tail"] == ["Compiling scripts"]
        assert str(tmp_path) not in json.dumps(running)

        release.set()
        finished = _call(server, "gm_build_status", label="mine", wait_seconds=20)
        assert (finished["finished"], finished["ok"], finished["status"]) == (True, True, "COMPILED")
        assert (project / ".gms_mcp" / "runs" / "mine" / "result.json").is_file()

        unknown = _call(server, "gm_build_status", label="other", wait_seconds=30)
        assert unknown["ok"] is False and unknown["known_labels"] == ["mine"]


def test_a_background_build_is_stopped_through_the_tools(tmp_path: Path):
    def fake_compile(root, *, label, **_options):
        run_status.report_stage("waiting for a build slot", attempt=1, attempts=10)
        run_status.sleep_unless_stopped(120)
        raise AssertionError("the build should have been stopped")

    with _server(tmp_path) as (server, _project), patch.object(snapshot_build, "snapshot_compile", fake_compile):
        assert _call(server, "gm_snapshot_compile", background=True)["status"] == "STARTED"
        _wait_until(lambda: _call(server, "gm_build_status", wait_seconds=0).get("stage") == "waiting for a build slot")
        assert _call(server, "gm_build_stop")["stopped"] is True
        raw = asyncio.run(server.call_tool("gm_build_status", {"wait_seconds": 0}))
        # The look succeeded; it is the run that did not. A client must not read this as the tool failing.
        assert raw.is_error is False
        report = unwrap_call_tool_result(raw)
        assert (report["finished"], report["ok"], report["status"]) == (True, False, "STOPPED")
        assert "error_code" not in report and "total_seconds" not in report
        assert _call(server, "gm_build_stop")["already_finished"] is True
        assert _call(server, "gm_lock_status")["this_session_runs"] == []


def test_status_can_return_when_the_stage_changes(tmp_path: Path):
    step = threading.Event()
    done = threading.Event()

    def fake_compile(root, *, label, **_options):
        run_status.report_stage("waiting for a build slot", attempt=1, attempts=10)
        assert step.wait(20)
        run_status.report_stage(
            "compiling", attempt=2, attempts=10, previous_attempt="Attempt 1 hit Igor's random crash."
        )
        assert done.wait(20)
        work = tmp_path / "work"
        work.mkdir()
        return {"ok": True, "status": "COMPILED", "label": label}, None, work, None

    with _server(tmp_path) as (server, _project), patch.object(snapshot_build, "snapshot_compile", fake_compile):
        _call(server, "gm_snapshot_compile", background=True)
        _wait_until(lambda: _call(server, "gm_build_status", wait_seconds=0).get("stage") == "waiting for a build slot")
        threading.Timer(0.5, step.set).start()
        started = time.monotonic()
        changed = _call(server, "gm_build_status", wait_seconds=30, until="change")
        assert time.monotonic() - started < 15
        assert (changed["stage"], changed["attempt"], changed["max_attempts"]) == ("compiling", 2, 10)
        assert changed["status"] == "RUNNING"
        assert list(changed["stages_done"]) == ["starting", "waiting for a build slot"], "nothing passes unseen"
        assert "random crash" in changed["previous_attempt"]
        # A named stage the run is already at returns at once, however long the wait allowed.
        started = time.monotonic()
        at_stage = _call(server, "gm_build_status", wait_seconds=30, until="compiling")
        assert at_stage["stage"] == "compiling" and time.monotonic() - started < 10
        assert _call(server, "gm_lock_status")["this_session_runs"] == ["compile"]
        done.set()
        assert _call(server, "gm_build_status", wait_seconds=20)["status"] == "COMPILED"


def test_a_blocking_build_hands_over_instead_of_staying_silent(tmp_path: Path):
    release = threading.Event()

    def fake_compile(root, *, label, **_options):
        run_status.report_stage("compiling", attempt=1, attempts=10)
        assert release.wait(20)
        work = tmp_path / "work"
        work.mkdir()
        return {"ok": True, "status": "COMPILED", "label": label}, None, work, None

    with (
        _server(tmp_path) as (server, _project),
        patch.object(snapshot_build, "snapshot_compile", fake_compile),
        patch.dict(os.environ, {"GMS_MCP_BUILD_CALL_WAIT_SECONDS": "1"}),
    ):
        started = time.monotonic()
        raw = asyncio.run(server.call_tool("gm_snapshot_compile", {"label": "slow"}))
        assert time.monotonic() - started < 10
        assert raw.is_error is False
        handed_over = unwrap_call_tool_result(raw)
        assert (handed_over["status"], handed_over["finished"], handed_over["stage"]) == (
            "STILL_RUNNING",
            False,
            "compiling",
        )
        assert 'gm_build_status(label="slow")' in handed_over["next"]
        release.set()
        assert _call(server, "gm_build_status", label="slow", wait_seconds=20)["status"] == "COMPILED"


def test_a_failed_build_is_a_result_not_a_tool_error(tmp_path: Path):
    def fake_compile(root, *, label, **_options):
        run_status.report_stage("copying the project")
        run_status.report_stage("compiling", attempt=1, attempts=10)
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        return {"ok": False, "status": "BUILD_FAILED", "label": label, "errors": ["boom"]}, None, work, None

    def broken_compile(root, *, label, **_options):
        raise RuntimeError("the snapshot could not be made")

    with _server(tmp_path) as (server, _project):
        with patch.object(snapshot_build, "snapshot_compile", fake_compile):
            direct = asyncio.run(server.call_tool("gm_snapshot_compile", {"label": "my-build"}))
            followed = asyncio.run(server.call_tool("gm_build_status", {"label": "my-build", "wait_seconds": 0}))
        # The compiler rejected the code; the tool did its job. Both ways of asking say the same.
        assert direct.is_error is False and followed.is_error is False
        direct, followed = unwrap_call_tool_result(direct), unwrap_call_tool_result(followed)
        assert direct == followed
        assert (direct["finished"], direct["ok"], direct["status"], direct["errors"]) == (
            True,
            False,
            "BUILD_FAILED",
            ["boom"],
        )
        assert direct["label"] == "my_build", "one name for the run, in every reply"
        assert list(direct["stages"]) == ["starting", "copying the project", "compiling"]
        assert "error_code" not in direct and "total_seconds" not in direct

        with patch.object(snapshot_build, "snapshot_compile", broken_compile):
            crashed = asyncio.run(server.call_tool("gm_snapshot_compile", {"label": "broken"}))
        assert crashed.is_error is True, "the tool itself failing is still an error"
        assert unwrap_call_tool_result(crashed)["error_type"] == "RuntimeError"


def test_a_stage_can_gain_its_log_without_changing(tmp_path: Path):
    log = tmp_path / "compile.log"
    log.write_text("Compile Scripts...\n", encoding="utf-8")
    release = threading.Event()

    def work():
        run_status.report_detail(live_log=str(log))  # no stage yet: nothing to add to
        run_status.report_stage("compiling")
        run_status.report_detail(live_log=str(log))
        assert release.wait(10)
        return {"ok": True}

    directory = _run_dir(tmp_path)
    _start(directory, work)
    _wait_until(lambda: "log_tail" in background_runs.status(directory))
    report = background_runs.status(directory)
    assert (report["stage"], report["log_tail"]) == ("compiling", ["Compile Scripts..."])
    release.set()
    _wait_until(lambda: background_runs.status(directory)["finished"])


def test_a_child_build_tells_its_parent_where_the_compiler_log_is(tmp_path: Path):
    hint = tmp_path / "private" / "live_log.json"
    hint.parent.mkdir()
    log = tmp_path / "work" / "build.log"

    run_status.publish_live_log(log)  # nobody asked: nothing is written anywhere
    assert not hint.exists() and run_status.read_live_log_hint(hint) is None

    with patch.dict(os.environ, {run_status.LIVE_LOG_HINT_ENV: str(hint)}):
        run_status.publish_live_log(log)
    assert run_status.read_live_log_hint(hint) == str(log)

    hint.write_text("[]", encoding="utf-8")
    assert run_status.read_live_log_hint(hint) is None


def test_a_wait_is_named_as_a_stage_only_when_there_is_one(tmp_path: Path):
    with run_status.track_run(_run_dir(tmp_path), "compile", "gm_snapshot_compile") as tracker:
        run_status.report_stage("copying the project")
        waiting = run_status.waiting_sleep("waiting for a build slot", attempt=1, attempts=10)
        assert tracker.snapshot()["stage"] == "copying the project", "a free slot is not a wait"
        waiting(0)
        assert tracker.snapshot()["stage"] == "waiting for a build slot"
        tracker.request_stop()
        with pytest.raises(run_status.RunStopped):
            waiting(5)


# --- the working-tree compile -------------------------------------------------------------------------


def test_a_working_tree_compile_hands_over_and_still_holds_up_changes(tmp_path: Path):
    from mcp import Client

    from gms_mcp.gamemaker_mcp_server import _request_holds_mutation_lock, _requires_mutation_lock

    # Still serialised with changes to the project, but by the tool, for longer than its request.
    assert _requires_mutation_lock("gm_compile", {}) is True
    assert _request_holds_mutation_lock("gm_compile", {}) is False
    assert _request_holds_mutation_lock("gm_safe_delete", {}) is True

    async def scenario(server) -> None:
        gate = asyncio.Event()

        compiler_log = tmp_path / "igor.log"

        async def fake_compile(**options):
            # What the compile's child process does once Igor is writing somewhere.
            compiler_log.write_text("Compile Scripts...\n", encoding="utf-8")
            with patch.dict(os.environ, options["extra_environment"]):
                run_status.publish_live_log(compiler_log)
            await gate.wait()
            return {
                "ok": False,
                "stdout": "Error : scripts/a.gml(3) : unknown variable",
                "exit_code": 1,
                "elapsed_seconds": 41.2345,
            }

        with patch("gms_mcp.server.tools.runner._run_with_fallback", fake_compile):
            async with Client(server, mode="2026-07-28") as client:

                async def call(tool: str, **arguments):
                    return await client.call_tool(tool, arguments)

                handed_over = unwrap_call_tool_result(await call("gm_compile"))
                assert (handed_over["status"], handed_over["stage"], handed_over["label"]) == (
                    "STILL_RUNNING",
                    "compiling",
                    "working_tree",
                )

                # The request is over, the compiler is not: a change to the project must still wait.
                change = asyncio.create_task(call("gm_safe_delete", asset_type="script", asset_name="scr_none"))
                done, _pending = await asyncio.wait({change}, timeout=1.0)
                assert not done, "a change ran while the compiler was reading the project"

                running = unwrap_call_tool_result(await call("gm_build_status", label="working_tree", wait_seconds=2))
                assert running["log_tail"] == ["Compile Scripts..."], "the compiler's own lines are shown"

                gate.set()
                raw = await call("gm_build_status", label="working_tree", wait_seconds=20)
                result = unwrap_call_tool_result(raw)
                # The compiler rejected the code; that is the compile's result, not a tool failure.
                assert raw.is_error is False
                assert (result["finished"], result["ok"], result["exit_code"]) == (True, False, 1)
                assert result["status"] == "BUILD_FAILED"
                # Nothing was changing the project, so the compile never waited for it and does not say it did.
                assert list(result["stages"]) == ["starting", "compiling"]
                # One name for the build's own time, whichever tool built; run_seconds is the whole run.
                assert result["build_seconds"] == 41.2 and "elapsed_seconds" not in result
                assert "run_seconds" in result
                await asyncio.wait_for(change, timeout=20)

    with _server(tmp_path) as (server, _project), patch.dict(os.environ, {"GMS_MCP_BUILD_CALL_WAIT_SECONDS": "1"}):
        asyncio.run(scenario(server))


def test_a_working_tree_compile_can_be_stopped_and_frees_the_project(tmp_path: Path):
    from mcp import Client

    cancelled = []

    async def scenario(server) -> None:
        async def fake_compile(**_options):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        with patch("gms_mcp.server.tools.runner._run_with_fallback", fake_compile):
            async with Client(server, mode="2026-07-28") as client:
                started = unwrap_call_tool_result(await client.call_tool("gm_compile", {"background": True}))
                assert (started["status"], started["label"]) == ("STARTED", "working_tree")
                at_stage = unwrap_call_tool_result(
                    await client.call_tool(
                        "gm_build_status",
                        {"label": "working_tree", "until": "compiling", "wait_seconds": 20},
                    )
                )
                assert at_stage["stage"] == "compiling"

                # No label: the one run this session has going, whatever tool started it.
                stopped = unwrap_call_tool_result(await client.call_tool("gm_build_stop", {}))
                assert (stopped["stopped"], stopped["label"]) == (True, "working_tree")
                report = unwrap_call_tool_result(await client.call_tool("gm_build_status", {"wait_seconds": 0}))
                assert (report["finished"], report["status"], report["label"]) == (True, "STOPPED", "working_tree")
                # The lock went with the compile: a change to the project is not left waiting.
                await asyncio.wait_for(
                    client.call_tool("gm_safe_delete", {"asset_type": "script", "asset_name": "scr_none"}), timeout=20
                )

    with _server(tmp_path) as (server, _project):
        asyncio.run(scenario(server))
    assert cancelled == [True], "the compile itself was ended, not just abandoned"


def test_status_is_a_reader_and_stop_is_not_offered_read_only(tmp_path: Path):
    from gms_helpers.operation_policy import operation_scope

    assert operation_scope("gm_build_status") == "read"
    assert operation_scope("gm_build_stop") == "runtime"
    with _server(tmp_path) as (_server_instance, _project), patch.dict(os.environ, {"GMS_MCP_READ_ONLY": "1"}):
        names = {tool.name for tool in asyncio.run(build_server().list_tools())}
    assert "gm_build_status" in names
    assert "gm_build_stop" not in names and "gm_snapshot_compile" not in names


# --- no label named ------------------------------------------------------------------------------


def test_status_and_stop_without_a_label_mean_this_sessions_run(tmp_path: Path):
    def fake_compile(root, *, label, **_options):
        run_status.report_stage("compiling", attempt=1, attempts=10)
        run_status.sleep_unless_stopped(120)
        raise AssertionError("the build should have been stopped")

    with _server(tmp_path) as (server, project), patch.object(snapshot_build, "snapshot_compile", fake_compile):
        nothing = _call(server, "gm_build_status", wait_seconds=0)
        assert nothing["ok"] is False and "No build or test run has been recorded" in nothing["error"]
        assert "started no build" in _call(server, "gm_build_stop")["error"]

        _call(server, "gm_snapshot_compile", label="first", background=True)
        _wait_until(lambda: _call(server, "gm_build_status", label="first", wait_seconds=0).get("stage") == "compiling")
        _call(server, "gm_snapshot_compile", label="second", background=True)
        _wait_until(
            lambda: _call(server, "gm_build_status", label="second", wait_seconds=0).get("stage") == "compiling"
        )

        # The latest one started is the one followed.
        assert _call(server, "gm_build_status", wait_seconds=0)["label"] == "second"
        # Stopping is not guessed at when more than one is going.
        refused = _call(server, "gm_build_stop")
        assert refused["ok"] is False and refused["running_labels"] == ["first", "second"]

        assert _call(server, "gm_build_stop", label="first")["stopped"] is True
        only = _call(server, "gm_build_stop")
        assert (only["stopped"], only["label"]) == (True, "second")
        assert _call(server, "gm_build_stop")["already_finished"] is True


def test_status_without_a_label_falls_to_the_projects_latest_recorded_run(tmp_path: Path):
    with _server(tmp_path) as (server, project):
        for label, started in (("older", 100.0), ("newer", 200.0)):
            directory = project / ".gms_mcp" / "runs" / label
            directory.mkdir(parents=True)
            state = {"state": "finished", "operation": "gm_test_run", "started_at": started, "finished_at": started + 5}
            (directory / run_status.STATUS_FILE).write_text(json.dumps(state), encoding="utf-8")
            (directory / run_status.RESULT_FILE).write_text(json.dumps({"ok": True, "status": label}), encoding="utf-8")
        report = _call(server, "gm_build_status", wait_seconds=0)
    assert (report["label"], report["status"], report["finished"]) == ("newer", "newer", True)


# --- a test run's frame --------------------------------------------------------------------------


def test_a_followed_test_shows_the_frame_it_has_reached_not_the_frame_lines(tmp_path: Path):
    assert snapshot_build.TEST_FRAME_MARKER in snapshot_build.DEFAULT_TEST_PRELUDE
    assert snapshot_build.last_test_frame("boot\n[TEST_FRAME] 60\n[TEST] hello\n[TEST_FRAME] 121\n") == 121
    assert snapshot_build.last_test_frame("boot\n[TEST] hello\n") is None
    assert snapshot_build.last_test_frame("[TEST_FRAME] 12") == 12, "a line still being written"

    log = tmp_path / "game.log"
    log.write_text("room started\n[TEST_FRAME] 60\n[TEST] hello\n[TEST_FRAME] 121\n", encoding="utf-8")
    seen = threading.Event()
    release = threading.Event()

    def work() -> dict:
        run_status.report_stage("running the test", live_log=str(log), timeout_seconds=120)
        run_status.report_detail(test_frame=121)
        seen.set()
        assert release.wait(20)
        return {"ok": True, "status": "TEST_PASSED"}

    directory = _run_dir(tmp_path, "test")
    asyncio.run(background_runs.run(directory, "test", "gm_test_run", work, wait_seconds=0))
    assert seen.wait(5)
    running = background_runs.status(directory)
    release.set()
    assert running["test_frame"] == 121
    assert running["log_tail"] == ["room started", "[TEST] hello"]
    # The saved log keeps every line; reading it leaves the frame reports out unless they are asked for.
    assert snapshot_build.tail_lines(log, 10) == ["room started", "[TEST] hello"]


def test_reading_a_run_log_leaves_out_frame_reports_unless_searched_for(tmp_path: Path):
    project = tmp_path / "game"
    run_dir = project / ".gms_mcp" / "runs" / "test"
    run_dir.mkdir(parents=True)
    (run_dir / "run.log").write_text("boot\n[TEST_FRAME] 60\n[TEST] PASS ok\n", encoding="utf-8")
    assert snapshot_build.read_run_artifact(project, "test")["lines"] == ["boot", "[TEST] PASS ok"]
    assert snapshot_build.read_run_artifact(project, "test", pattern="TEST_FRAME")["lines"] == ["[TEST_FRAME] 60"]


# --- warnings left out of a build result ---------------------------------------------------------


def test_warnings_about_other_targets_are_counted_not_listed():
    log = "\n".join(
        [
            "Compile Scripts...Warning : reference to extension macro iap_no_error which is not available for this "
            "target - macro is in extension AppleIAP and file AppleIAP.ext",
            "Warning : reference to extension macro ugc_match_Items which is not available for this target - macro "
            "is in extension Steamworks and file Steamworks.ext",
            "Warning : variable used before it is set in scr_thing",
        ]
    )
    _errors, warnings, _packaging = snapshot_build.classify_build_log(log)
    assert warnings == ["Warning : variable used before it is set in scr_thing"]
    assert snapshot_build.count_other_target_warnings(log) == 2


# --- leaving ---------------------------------------------------------------------------------


def test_a_build_is_stopped_when_the_server_leaves_with_nothing_else_running(tmp_path: Path):
    from gms_mcp import gamemaker_mcp_server

    stopped = threading.Event()

    def work() -> dict:
        run_status.report_stage("compiling", attempt=1, attempts=10)
        try:
            run_status.sleep_unless_stopped(60)
        finally:
            stopped.set()
        raise AssertionError("the build should have been stopped")

    directory = _run_dir(tmp_path)
    _start(directory, work)
    _wait_until(lambda: background_runs.status(directory).get("stage") == "compiling")

    # A build's thread is a daemon: on its own it neither keeps the process alive nor counts as
    # work in progress, so the ordinary exit must still end it and its compiler.
    with patch.object(gamemaker_mcp_server, "_wait_for_mutations_then_exit") as forced_exit:
        gamemaker_mcp_server._leave_after_client_disconnect(set(threading.enumerate()))

    assert stopped.wait(5)
    forced_exit.assert_not_called()
    _wait_until(lambda: background_runs.status(directory).get("finished") is True)
    assert background_runs.status(directory)["status"] == "STOPPED"


def test_stopping_a_windows_build_ends_the_tools_igor_started(monkeypatch):
    calls = []

    class Igor:
        pid = 4242
        killed = False
        ended = False

        def poll(self):
            return 0 if self.ended else None

        def kill(self):
            self.killed = True
            self.ended = True

    def taskkill_that_works(command, **_options):
        calls.append(command)
        igor.ended = True

    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    igor = Igor()
    monkeypatch.setattr(snapshot_build.subprocess, "run", taskkill_that_works)
    snapshot_build._end_windows_process_tree(igor)
    # /T takes the whole tree: the compiler and packaging tools, not Igor alone.
    assert calls == [["C:\\Windows\\System32\\taskkill.exe", "/PID", "4242", "/T", "/F"]]
    assert igor.killed is False

    def taskkill_that_is_missing(command, **_options):
        raise FileNotFoundError(command[0])

    igor = Igor()
    monkeypatch.setattr(snapshot_build.subprocess, "run", taskkill_that_is_missing)
    snapshot_build._end_windows_process_tree(igor)
    assert igor.killed is True, "Igor itself is still ended when the tree cannot be"


@pytest.mark.skipif(os.name == "nt", reason="process groups are a POSIX notion")
def test_igor_leaves_the_callers_process_group_only_when_this_process_can_stop_it(tmp_path: Path):
    report_group = [sys.executable, "-c", "import os; print(os.getpgid(0))"]

    # Run as a command (how gm_compile builds): whoever ends this process's group must end Igor with it.
    assert snapshot_build._default_run_igor(report_group, tmp_path / "untracked.log", 30) == 0
    assert int((tmp_path / "untracked.log").read_text().split()[0]) == os.getpgid(0)

    # Tracked here: stopped by signalling a group of its own, tools and all.
    with run_status.track_run(_run_dir(tmp_path), "compile", "gm_snapshot_compile"):
        assert snapshot_build._default_run_igor(report_group, tmp_path / "tracked.log", 30) == 0
    assert int((tmp_path / "tracked.log").read_text().split()[0]) != os.getpgid(0)


@pytest.mark.skipif(os.name == "nt", reason="process groups are a POSIX notion")
def test_a_command_line_build_that_times_out_ends_the_tools_its_compiler_started(tmp_path: Path):
    from gms_helpers.agent_locks import _process_alive

    tool_pid_file = tmp_path / "tool.pid"
    # A stand-in Igor that starts a tool of its own and then never finishes.
    stand_in = (
        "import subprocess, sys, time\n"
        "tool = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"open({str(tool_pid_file)!r}, 'w').write(str(tool.pid))\n"
        "time.sleep(300)\n"
    )

    # Long enough for the stand-in to have started its tool on a slow machine.
    assert snapshot_build._default_run_igor([sys.executable, "-c", stand_in], tmp_path / "build.log", 5.0) == -9

    tool_pid = int(tool_pid_file.read_text())
    _wait_until(lambda: not _process_alive(tool_pid), seconds=10)
    assert "without finishing" in (tmp_path / "build.log").read_text()


@pytest.mark.skipif(os.name == "nt", reason="process groups are a POSIX notion")
@pytest.mark.parametrize("own_group", [True, False], ids=["its own process group", "this process's group"])
def test_a_stop_is_not_over_while_a_tool_that_ignores_it_is_still_running(tmp_path: Path, own_group: bool):
    import subprocess

    from gms_helpers.agent_locks import _process_alive

    ready = tmp_path / "tool.ready"
    # A stand-in Igor that leaves when asked, with a tool that does not.
    tool = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(ready)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(300)\n"
    )
    stand_in = f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {tool!r}])\ntime.sleep(300)\n"
    compiler = subprocess.Popen([sys.executable, "-c", stand_in], start_new_session=own_group)
    try:
        _wait_until(lambda: ready.is_file() and ready.read_text().isdigit(), seconds=20)
        tool_pid = int(ready.read_text())

        snapshot_build._end_process_tree(compiler, grace_seconds=1.0)

        assert compiler.poll() is not None
        assert not _process_alive(tool_pid), "the build slot would be released with the tool still writing"
    finally:
        compiler.kill()
        if ready.is_file() and ready.read_text().isdigit():
            with contextlib.suppress(OSError):
                os.kill(int(ready.read_text()), 9)


@pytest.mark.skipif(os.name == "nt", reason="process groups are a POSIX notion")
def test_ending_a_compiler_that_shares_this_process_group_ends_only_the_compiler(tmp_path: Path):
    import subprocess

    compiler = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert os.getpgid(compiler.pid) == os.getpgid(0)
        snapshot_build._end_process_tree(compiler, grace_seconds=5)
        assert compiler.poll() is not None
    finally:
        compiler.kill()


# --- found by review -----------------------------------------------------------------------------


def test_an_exiting_server_waits_for_its_runs_to_end_what_they_started(tmp_path: Path):
    cleaned_up = []

    def test_run() -> dict:
        run_status.report_stage("running the test")
        try:
            while not run_status.stop_requested():
                time.sleep(0.01)
            raise run_status.RunStopped("stopped")
        finally:
            time.sleep(0.4)  # ending the game, giving back the lease, removing the project copy
            cleaned_up.append(True)

    directory = _run_dir(tmp_path, "test")
    asyncio.run(background_runs.run(directory, "test", "gm_test_run", test_run, wait_seconds=0))
    _wait_until(lambda: background_runs.status(directory).get("stage") == "running the test")

    background_runs.stop_all()

    assert cleaned_up == [True], "the server would have exited with the game still running"


def test_the_server_stops_its_builds_when_it_is_told_to_terminate():
    from gms_mcp import gamemaker_mcp_server

    installed = {}
    left = threading.Event()
    with (
        patch.object(
            gamemaker_mcp_server.signal, "signal", lambda number, handler: installed.update({number: handler})
        ),
        patch.object(gamemaker_mcp_server, "_wait_for_mutations_then_exit", left.set),
    ):
        gamemaker_mcp_server._leave_when_told_to_terminate()
        assert gamemaker_mcp_server.signal.SIGTERM in installed
        handler_returned_at = time.monotonic()
        installed[gamemaker_mcp_server.signal.SIGTERM](gamemaker_mcp_server.signal.SIGTERM, None)
        # The handler hands over and returns: the event loop it interrupted must keep running.
        assert time.monotonic() - handler_returned_at < 1
        assert left.wait(5)


def test_a_status_file_is_still_written_while_a_follower_has_it_open(tmp_path: Path, monkeypatch):
    from gms_helpers import agent_locks

    target = tmp_path / "status.json"
    target.write_text("{}", encoding="utf-8")
    real_replace = os.replace
    refusals = [PermissionError("in use"), PermissionError("in use")]

    def replace_like_windows(source, destination):
        if refusals:
            raise refusals.pop()
        return real_replace(source, destination)

    monkeypatch.setattr(agent_locks, "_WINDOWS", True)
    monkeypatch.setattr(run_status.os, "replace", replace_like_windows)
    run_status._write_json(target, {"state": "finished"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "finished"}
    assert refusals == [] and list(tmp_path.iterdir()) == [target]


def test_a_stop_that_came_too_late_does_not_claim_to_have_stopped_anything(tmp_path: Path):
    release = threading.Event()

    def game_start() -> dict:
        run_status.report_stage("connecting to the game")
        assert release.wait(20)
        return {"ok": True, "status": "RUNNING", "running": True}

    directory = _run_dir(tmp_path, "live")
    asyncio.run(background_runs.run(directory, "live", "gm_game_start", game_start, wait_seconds=0))
    _wait_until(lambda: background_runs.status(directory).get("stage") == "connecting to the game")
    threading.Timer(0.2, release.set).start()

    report = background_runs.stop(directory)

    assert (report["stopped"], report["already_finished"], report["status"]) == (False, True, "RUNNING")
    assert "gm_game_stop" in report["message"]


def test_a_status_file_holding_nonsense_is_reported_not_raised(tmp_path: Path):
    directory = _run_dir(tmp_path)
    directory.mkdir(parents=True)
    for nonsense in (
        {"state": "running", "started_at": "yesterday", "stage_started_at": [], "pid": 10**40, "stage": "compiling"},
        {"state": "running", "started_at": None, "pid": -5, "stage": 7},
        {"state": "running", "started_at": True, "pid": "1", "stages_done": "x"},
        {"state": "running", "started_at": "soon", "pid": os.getpid(), "stage": "compiling", "attempt": "two"},
    ):
        (directory / run_status.STATUS_FILE).write_text(json.dumps(nonsense), encoding="utf-8")
        report = background_runs.status(directory)
        assert "finished" in report and report["label"] == "compile"
    assert report["status"] == "RUNNING", "a live process with unreadable times is still a running run"


def test_housekeeping_under_another_label_does_not_start_the_current_runs_record(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    directory = _run_dir(tmp_path, "live")
    with patch.dict(os.environ, {"GMS_MCP_LOCK_DIR": str(tmp_path / "locks")}):
        with run_status.track_run(directory, "live", "gm_game_start") as tracker:
            with snapshot_build.label_pipeline(project, "earlier", timeout_seconds=5, is_run=False):
                pass
            assert "stage" not in tracker.snapshot() and not directory.exists()
            with snapshot_build.label_pipeline(project, "live", timeout_seconds=5):
                assert tracker.snapshot()["stage"] == "starting"


@pytest.mark.parametrize("stop_arrives", ["while taking the label", "as the compile is handed over"])
def test_a_working_tree_compile_stopped_as_it_starts_ends_at_once(tmp_path: Path, stop_arrives: str):
    from contextlib import contextmanager as make_context_manager

    from mcp import Client

    from gms_mcp.server.tools import runner as runner_tools

    compiled = []
    ended = []
    hand_over = asyncio.run_coroutine_threadsafe

    @make_context_manager
    def label_taken(_root, _label, *args, **kwargs):
        if stop_arrives == "while taking the label":
            run_status.current().request_stop()
        yield

    def handed_over_as_the_stop_arrives(coroutine, loop):
        # Too late for the first check, too early for the stop to have found anything to cancel.
        future = hand_over(coroutine, loop)
        run_status.current().request_stop()
        return future

    async def scenario(server) -> None:
        async def fake_compile(**_options):
            compiled.append(True)
            try:
                await asyncio.Event().wait()
            finally:
                ended.append(True)

        patches = [
            patch("gms_mcp.server.tools.runner._run_with_fallback", fake_compile),
            patch.object(snapshot_build, "label_pipeline", label_taken),
        ]
        if stop_arrives == "as the compile is handed over":
            patches.append(
                patch.object(runner_tools.asyncio, "run_coroutine_threadsafe", handed_over_as_the_stop_arrives)
            )
        for each in patches:
            each.start()
        try:
            async with Client(server, mode="2026-07-28") as client:
                # Well inside the time the call waits before handing over: a run that hung would not make it.
                result = unwrap_call_tool_result(await asyncio.wait_for(client.call_tool("gm_compile", {}), timeout=10))
                assert (result["finished"], result["status"]) == (True, "STOPPED")
                # The project is free again: a change is not left waiting behind a compile nobody wants.
                await asyncio.wait_for(
                    client.call_tool("gm_safe_delete", {"asset_type": "script", "asset_name": "scr_none"}), timeout=10
                )
        finally:
            for each in reversed(patches):
                each.stop()

    with _server(tmp_path) as (server, _project):
        asyncio.run(scenario(server))
    if stop_arrives == "while taking the label":
        assert compiled == [], "no compiler was started"
    # Handed over a moment before the stop, the compile may have begun; whatever began was ended.
    assert ended == compiled
