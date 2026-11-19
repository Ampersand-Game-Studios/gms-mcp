"""Builds and test runs that can be followed, and stopped, by a call other than the one that started them.

A client may show an agent nothing while a call is pending, and a build takes minutes. Started
in the background, the same work runs on a thread of this server: the caller gets its label back
at once and follows it with gm_build_status. A blocking run is recorded the same way, so a status
call made beside it, or from another session, sees where it has got to.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict

from gms_helpers import run_status

# How many of a log's last lines a status report carries by default.
DEFAULT_LOG_LINES = 12
MAX_LOG_LINES = 200
MAX_WAIT_SECONDS = 300.0
_WAITING_FOR_LABEL = "waiting for an earlier run with this label to finish"
_KEPT_WHEN_STOPPED = ("build_log", "run_log")


@dataclass
class ActiveRun:
    """One labelled run this server started, while it runs and after it has ended."""

    operation: str
    label: str
    directory: Path
    tracker: run_status.RunTracker | None = None
    # The work raised instead of returning: the tool broke, as opposed to the build failing.
    crashed: bool = False
    # Ends work that a stop request alone does not reach (a compile running outside the snapshot pipeline).
    cancel: Callable[[], None] | None = None
    result: Dict[str, Any] | None = None
    done: threading.Event = field(default_factory=threading.Event)


_RUNS: dict[tuple[str, str], ActiveRun] = {}
_RUNS_LOCK = threading.Lock()


def _key(directory: Path) -> tuple[str, str]:
    # .../<project>/.gms_mcp/runs/<label>
    return (str(directory.parent.parent.parent), directory.name)


def _stopped(label: str, stage: Any = None) -> Dict[str, Any]:
    result = {
        "ok": False,
        "status": "STOPPED",
        "label": label,
        "message": "The run was stopped on request before it finished.",
    }
    if isinstance(stage, str):
        result["stopped_during"] = stage
    return result


def _execute(run: ActiveRun | None, directory: Path, label: str, operation: str, work: Callable[[], Dict[str, Any]]):
    """Do the work as a tracked run. Returns the result and the exception to re-raise, if any."""
    failure: Exception | None = None
    with run_status.track_run(directory, label, operation) as tracker:
        if run is not None:
            run.tracker = tracker
        try:
            result = work()
        except run_status.RunStopped:
            result = _stopped(label, tracker.snapshot().get("stage"))
        except Exception as exc:  # noqa: BLE001 - recorded as the run's result; the caller decides what to raise
            failure = exc
            result = {"ok": False, "tool": operation, "error": str(exc), "error_type": type(exc).__name__}
        if tracker.stop_requested and not result.get("ok") and result.get("status") != "STOPPED":
            kept = {key: result[key] for key in _KEPT_WHEN_STOPPED if key in result}
            result = {**_stopped(label, tracker.snapshot().get("stage")), **kept}
            failure = None
        if run is not None:
            run.crashed = failure is not None
        tracker.finish(result)
    if run is not None:
        run.result = result
        run.done.set()
    return result, failure


def _start(
    directory: Path,
    label: str,
    operation: str,
    work: Callable[[], Dict[str, Any]],
    cancel: Callable[[], None] | None = None,
):
    """Start ``work`` on a thread of this server. One run per label at a time; returns the run or a refusal."""
    key = _key(directory)
    with _RUNS_LOCK:
        existing = _RUNS.get(key)
        if existing is not None and not existing.done.is_set():
            return None, {
                "ok": False,
                "status": "ALREADY_RUNNING",
                "label": label,
                "error": (
                    f"A {existing.operation} with label '{label}' is still running in this session. "
                    "Follow it with gm_build_status, stop it with gm_build_stop, or use another label."
                ),
            }
        run = ActiveRun(operation, label, directory, cancel=cancel)
        _RUNS[key] = run

    # A fresh context: the run must not inherit this request's cancellation or telemetry scope.
    threading.Thread(
        target=contextvars.Context().run,
        args=(_execute, run, directory, label, operation, work),
        name=f"gms-mcp-{operation}-{label}",
        daemon=True,
    ).start()
    return run, None


async def run(
    directory: Path,
    label: str,
    operation: str,
    work: Callable[[], Dict[str, Any]],
    *,
    wait_seconds: float | None,
    cancel: Callable[[], None] | None = None,
) -> Dict[str, Any]:
    """Start ``work`` and answer within ``wait_seconds``: with its result, or with where it has got to.

    0 answers at once. None waits for the result however long it takes. Either way the work carries on
    to its end on its own thread, and gm_build_status follows it.
    """
    started, refusal = _start(directory, label, operation, work, cancel)
    if started is None:
        return refusal
    if wait_seconds is not None and wait_seconds <= 0:
        return {
            "ok": True,
            "status": "STARTED",
            "label": label,
            "operation": operation,
            "next": (
                f'Call gm_build_status(label="{label}"). It waits up to wait_seconds for the run to end and '
                "returns the result when it has; until then it reports the stage and the last log lines. "
                'until="compiling" (any stage name) returns as soon as the run is at that stage.'
            ),
        }
    deadline = None if wait_seconds is None else time.monotonic() + wait_seconds
    while not started.done.is_set():
        if deadline is not None and time.monotonic() >= deadline:
            state = started.tracker.snapshot() if started.tracker is not None else {"operation": operation}
            return {
                **_running_report(state, label, DEFAULT_LOG_LINES, own=True),
                "status": "STILL_RUNNING",
                "next": (
                    f"Still going after {int(wait_seconds)} s, and it carries on. Call "
                    f'gm_build_status(label="{label}") to follow it to its result.'
                ),
            }
        await asyncio.sleep(0.05)
    result = started.result if started.result is not None else {"ok": False, "tool": operation, "error": "no result"}
    if started.crashed or started.tracker is None:
        return result
    # The same shape gm_build_status returns for this run: a build that failed is still a call that worked.
    return _finished_report(label, started.tracker.snapshot(), result)


def call_wait_seconds(project_root: Path, background: bool) -> float | None:
    """How long a build tool's own call waits before handing over to gm_build_status."""
    from gms_helpers.project_config import project_setting

    if background:
        return 0.0
    configured = float(project_setting(project_root, "build.call_wait_seconds", 20))
    return configured if configured > 0 else None


def find(directory: Path) -> ActiveRun | None:
    with _RUNS_LOCK:
        return _RUNS.get(_key(directory))


def stop(directory: Path) -> Dict[str, Any]:
    """Ask a run this server started to stop, and end its build if one is running."""
    from gms_helpers.snapshot_build import stop_builds

    run = find(directory)
    label = directory.name
    if run is not None and run.done.is_set() and run.result is not None:
        return {
            "ok": True,
            "label": label,
            "stopped": False,
            "already_finished": True,
            "status": run.result.get("status"),
            "message": f"'{label}' had already ended; there is nothing to stop. gm_build_status has its result.",
        }
    if run is None or run.done.is_set():
        return {
            "ok": False,
            "label": label,
            "error": f"No run labelled '{label}' is running in this session.",
            "hint": "Only a run this session started can be stopped. gm_game_stop stops a running game.",
        }
    deadline = time.monotonic() + 2.0
    while run.tracker is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if run.tracker is not None:
        run.tracker.request_stop()
        stop_builds(run.tracker)
    if run.cancel is not None:
        with contextlib.suppress(Exception):
            run.cancel()
    finished = run.done.wait(timeout=20)
    return {
        "ok": True,
        "label": label,
        "stopped": finished,
        "message": (
            "The run was stopped: its compiler process has ended and its build slot is free."
            if finished
            else "Stop requested; the run is still winding down. Check gm_build_status."
        ),
    }


def stop_all() -> None:
    """End every build this process started. Called when the server is about to exit."""
    from gms_helpers.snapshot_build import stop_builds

    with _RUNS_LOCK:
        runs = list(_RUNS.values())
    cancelled = []
    for run in runs:
        if run.done.is_set():
            continue
        if run.tracker is not None:
            run.tracker.request_stop()
        if run.cancel is not None:
            with contextlib.suppress(Exception):
                run.cancel()
            cancelled.append(run)
    stop_builds(None, grace_seconds=1.0)
    # A cancelled compile ends its compiler from the event loop; give that the moment it needs.
    deadline = time.monotonic() + 8.0
    for run in cancelled:
        run.done.wait(timeout=max(0.0, deadline - time.monotonic()))


def _tail(path_text: Any, lines: int) -> list[str]:
    if not isinstance(path_text, str) or lines <= 0:
        return []
    path = Path(path_text)
    try:
        if path.is_symlink() or not path.is_file():
            return []
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 32_768))
            text = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [line.rstrip()[:400] for line in text.splitlines() if line.strip()][-lines:]


def _running_report(state: Dict[str, Any], label: str, log_lines: int, *, own: bool) -> Dict[str, Any]:
    now = time.time()
    started = float(state.get("started_at") or now)
    report: Dict[str, Any] = {
        "ok": True,
        "finished": False,
        "status": "RUNNING",
        "label": label,
        "operation": state.get("operation"),
        "stage": state.get("stage") or _WAITING_FOR_LABEL,
        "stage_seconds": round(max(0.0, now - float(state.get("stage_started_at") or started)), 1),
        "run_seconds": round(max(0.0, now - started), 1),
    }
    done = state.get("stages_done")
    if isinstance(done, dict) and done:
        report["stages_done"] = {str(key): value for key, value in done.items() if isinstance(value, (int, float))}
    if isinstance(state.get("previous_attempt"), str):
        report["previous_attempt"] = state["previous_attempt"][:300]
    # Named apart from a finished result's `attempts`, which is how many were used.
    # The timeout is the stage's own, on the clock stage_seconds shows.
    for key, name in (
        ("attempt", "attempt"),
        ("attempts", "max_attempts"),
        ("timeout_seconds", "stage_timeout_seconds"),
    ):
        if isinstance(state.get(key), (int, float)):
            report[name] = state[key]
    # A log path is followed only when this process recorded it. The status file sits inside the
    # project, so a path read from it could have been written by anyone to point anywhere.
    tail = _tail(state.get("live_log"), log_lines) if own else []
    if tail:
        report["log_tail"] = tail
        with contextlib.suppress(OSError):
            # How long the compiler or game has written nothing: the sign of a run that is stuck.
            report["log_quiet_seconds"] = round(max(0.0, now - Path(state["live_log"]).stat().st_mtime), 1)
    elif not own:
        report["note"] = "Another session is running this; its log lines are shown only to that session."
    return report


def _finished_report(label: str, state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    report = {"finished": True, "operation": state.get("operation"), **result, "label": label}
    started, ended = state.get("started_at"), state.get("finished_at")
    if isinstance(started, (int, float)) and isinstance(ended, (int, float)):
        # The whole run by the clock the running reports used; a result's own timers cover parts of it.
        report["run_seconds"] = round(max(0.0, ended - started), 1)
    if isinstance(state.get("stages"), dict) and state["stages"]:
        report["stages"] = state["stages"]
    return report


def running_labels(project_root: Path) -> list[str]:
    """The labels of the runs this server is still running for a project."""
    root = str(Path(project_root).resolve())
    with _RUNS_LOCK:
        return sorted(key[1] for key, run in _RUNS.items() if key[0] == root and not run.done.is_set())


def status(directory: Path, *, log_lines: int = DEFAULT_LOG_LINES) -> Dict[str, Any]:
    """Describe a labelled run once: what stage it is at, or its result if it has ended. Reads only."""
    from gms_helpers.agent_locks import _process_alive

    label = directory.name
    log_lines = max(0, min(int(log_lines), MAX_LOG_LINES))
    run = find(directory)
    saved = run_status.read_status(directory)
    if run is not None and run.done.is_set() and run.tracker is not None and saved is not None:
        # Another session has used the label since: what it recorded is the newer run.
        if float(saved.get("started_at") or 0) > run.tracker.started_at:
            run = None
    if run is not None:
        state = run.tracker.snapshot() if run.tracker is not None else {"operation": run.operation}
        if run.done.is_set() and run.result is not None:
            return _finished_report(label, state, run.result)
        return _running_report(state, label, log_lines, own=True)

    if saved is None:
        runs_root = directory.parent
        try:
            known = sorted(item.name for item in runs_root.iterdir() if item.is_dir())
        except OSError:
            known = []
        failure: Dict[str, Any] = {
            "ok": False,
            "finished": False,
            "label": label,
            "error": f"No run labelled '{label}' has been recorded for this project.",
        }
        if known:
            failure["known_labels"] = known[:40]
        return failure
    if saved.get("state") == "finished":
        outcome = saved.get("outcome") if isinstance(saved.get("outcome"), dict) else {}
        result = run_status.read_result(directory)
        if result is None:
            result = {"ok": bool(outcome.get("ok")), "status": outcome.get("status")}
        return _finished_report(label, saved, result)
    owner = saved.get("pid")
    if not (isinstance(owner, int) and not isinstance(owner, bool) and _process_alive(owner)):
        return _finished_report(
            label,
            saved,
            {
                "ok": False,
                "status": "INTERRUPTED",
                "message": (
                    f"The process running this ended while it was at the stage '{saved.get('stage')}', "
                    "so there is no result. Start it again."
                ),
            },
        )
    return _running_report(saved, label, log_lines, own=False)
