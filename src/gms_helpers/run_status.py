"""Where a labelled build, test or game start has got to, for callers that are not waiting on it.

A build can take minutes, and a client may show nothing while a tool call is pending. Each run
therefore records its current stage in its run directory (``.gms_mcp/runs/<label>/status.json``)
and, when it ends, its result (``result.json``). Anything can read them: the same session while
the build runs in the background, a second call made beside a blocking one, or another session.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterator

STATUS_FILE = "status.json"
RESULT_FILE = "result.json"
# Names a file, in a private folder of the process that started this one, where a build run in a
# child process says which log its compiler is writing, so the parent can show the log's last lines.
LIVE_LOG_HINT_ENV = "GMS_MCP_LIVE_LOG_HINT"
_VERSION = 1


class RunStopped(Exception):
    """Raised inside a run to unwind it after a stop was requested."""


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Replace ``path`` in one step, never writing through a link someone placed there."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class RunTracker:
    """Records one run's stages and result, and carries a stop request to it."""

    def __init__(self, directory: Path, label: str, operation: str) -> None:
        self.directory = Path(directory)
        self.label = label
        self.operation = operation
        self.started_at = time.time()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # A run owns its directory only once it holds its label. Until then another run with the
        # same label may be writing there, and this one records nothing.
        self._owns_directory = False
        self._stage_seconds: dict[str, float] = {}
        self._state: dict[str, Any] = {
            "version": _VERSION,
            "state": "running",
            "operation": operation,
            "label": label,
            "pid": os.getpid(),
            "started_at": self.started_at,
        }

    def stage(self, name: str, **details: Any) -> None:
        """Record what the run is doing now. Details replace those of the previous stage."""
        now = time.time()
        with self._lock:
            if self._state.get("state") != "running":
                return
            if not self._owns_directory:
                self._owns_directory = True
                # A result left by an earlier run with this label would otherwise read as this run's.
                with contextlib.suppress(OSError):
                    (self.directory / RESULT_FILE).unlink()
            self._close_stage(now)
            kept = {key: self._state[key] for key in ("version", "state", "operation", "label", "pid", "started_at")}
            self._state = {**kept, "stage": name, "stage_started_at": now, "updated_at": now, **details}
            if self._stage_seconds:
                # The stages already passed, so one that came and went between two looks is still seen.
                self._state["stages_done"] = {key: round(value, 1) for key, value in self._stage_seconds.items()}
            self._save()

    def detail(self, **details: Any) -> None:
        """Add to what is known about the current stage (for example where its log is) without leaving it."""
        with self._lock:
            if self._state.get("state") != "running" or "stage" not in self._state:
                return
            self._state.update(details, updated_at=time.time())
            self._save()

    def finish(self, result: dict[str, Any]) -> None:
        """Record the result. After this the run reads as finished wherever it is looked up."""
        now = time.time()
        with self._lock:
            if self._owns_directory:
                with contextlib.suppress(OSError, TypeError, ValueError):
                    self.directory.mkdir(parents=True, exist_ok=True)
                    _write_json(self.directory / RESULT_FILE, result)
            self._close_stage(now)
            self._state = {
                **{key: self._state[key] for key in ("version", "operation", "label", "pid", "started_at")},
                "state": "finished",
                "finished_at": now,
                "updated_at": now,
                "last_stage": self._state.get("stage"),
                # Where the run's time went, by stage, in the order the stages were first entered.
                "stages": {name: round(seconds, 1) for name, seconds in self._stage_seconds.items()},
                "outcome": {"ok": bool(result.get("ok")), "status": result.get("status")},
            }
            if self._owns_directory:
                self._save()

    def snapshot(self) -> dict[str, Any]:
        """The state as this process knows it, which is ahead of the file while the label is awaited."""
        with self._lock:
            return dict(self._state)

    def _close_stage(self, now: float) -> None:
        name, began = self._state.get("stage"), self._state.get("stage_started_at")
        if isinstance(name, str) and isinstance(began, (int, float)):
            self._stage_seconds[name] = self._stage_seconds.get(name, 0.0) + max(0.0, now - began)

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def _save(self) -> None:
        # Losing a status update must never fail the build it describes.
        with contextlib.suppress(OSError):
            self.directory.mkdir(parents=True, exist_ok=True)
            _write_json(self.directory / STATUS_FILE, self._state)


_CURRENT: contextvars.ContextVar[RunTracker | None] = contextvars.ContextVar("gms_run_tracker", default=None)


def current() -> RunTracker | None:
    return _CURRENT.get()


def report_stage(name: str, **details: Any) -> None:
    """Record the current stage of the run this code is part of, if it is being tracked.

    Call it only while holding the run's label: the first stage claims the run directory.
    """
    tracker = _CURRENT.get()
    if tracker is not None:
        tracker.stage(name, **details)


def report_detail(**details: Any) -> None:
    """Add a detail to the current stage of the run this code is part of, if it is being tracked."""
    tracker = _CURRENT.get()
    if tracker is not None:
        tracker.detail(**details)


def publish_live_log(log_path: Path | str) -> None:
    """Tell the process that started this one which log the compiler is writing, if it asked."""
    hint = os.environ.get(LIVE_LOG_HINT_ENV, "").strip()
    if hint:
        with contextlib.suppress(OSError):
            _write_json(Path(hint), {"live_log": str(log_path)})


def read_live_log_hint(hint: Path | str) -> str | None:
    data = _read_json(Path(hint))
    path = data.get("live_log") if data else None
    return path if isinstance(path, str) and path else None


def stop_requested() -> bool:
    tracker = _CURRENT.get()
    return tracker is not None and tracker.stop_requested


def raise_if_stopped() -> None:
    if stop_requested():
        raise RunStopped("The run was stopped on request.")


def sleep_unless_stopped(seconds: float) -> None:
    """Sleep in short steps so a stop request ends a long wait within half a second."""
    deadline = time.monotonic() + seconds
    while True:
        raise_if_stopped()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def waiting_sleep(stage: str, **details: Any):
    """A sleep function for a lock wait that names the wait as a stage only if there is one.

    A lock that is free is taken without sleeping, and a run that never waited should not say it did.
    """
    reported = False

    def sleep(seconds: float) -> None:
        nonlocal reported
        if not reported:
            reported = True
            report_stage(stage, **details)
        sleep_unless_stopped(seconds)

    return sleep


@contextlib.contextmanager
def track_run(directory: Path, label: str, operation: str) -> Iterator[RunTracker]:
    """Track a run for its duration. A run started inside another tracked run joins it."""
    existing = _CURRENT.get()
    if existing is not None:
        yield existing
        return
    tracker = RunTracker(directory, label, operation)
    token = _CURRENT.set(tracker)
    try:
        yield tracker
    finally:
        _CURRENT.reset(token)


def read_status(directory: Path) -> dict[str, Any] | None:
    return _read_json(Path(directory) / STATUS_FILE)


def read_result(directory: Path) -> dict[str, Any] | None:
    return _read_json(Path(directory) / RESULT_FILE)
