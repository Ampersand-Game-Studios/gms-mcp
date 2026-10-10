"""Cooperative locks for several agents (or people) sharing one machine and one checkout.

GameMaker work has three contended things that file-level transactions cannot protect:

* **the repository** - staging and committing while someone else stages;
* **build capacity** - each Igor build takes several cores and gigabytes of memory;
* **the game runner** - every run of the macOS/Windows runner shares one save directory,
  one window and one audio device, so two concurrent test runs corrupt each other;
* **mobile builds** - one Xcode/Gradle output directory and usually one attached device.

A lock is a directory created with ``mkdir`` (atomic on every supported filesystem). The
protocol is deliberately trivial so shell scripts can take part:

    mkdir "$LOCK_DIR/gamerun.lock"   # take; retry while it fails
    rmdir "$LOCK_DIR/gamerun.lock"   # release

A lock whose holder died is reclaimed when its owner record names a dead process on this
host, or when it is older than its stale timeout. The lock directory itself stays empty so
``rmdir`` always works; the owner record is a sibling ``<name>.owner`` file.

``GMS_MCP_LOCK_DIR`` selects the directory (default ``~/.gms-mcp/locks``). Point it at an
existing team lock directory to cooperate with scripts already using this protocol.
"""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Callable

_LOCK_DIR_ENV = "GMS_MCP_LOCK_DIR"
_POLL_SECONDS = 1.0

REPOSITORY_LOCK = "repo.lock"
GAME_RUN_LOCK = "gamerun.lock"
MOBILE_BUILD_LOCK = "ios_build.lock"
BUILD_SLOT_PREFIX = "build_slot_"


class LockTimeoutError(TimeoutError):
    """Raised with a message that says who holds the lock and what to do about it."""


def lock_directory() -> Path:
    configured = os.environ.get(_LOCK_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".gms-mcp" / "locks"


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class DirectoryLock:
    """One named ``mkdir`` lock."""

    def __init__(
        self,
        name: str,
        *,
        directory: Path | None = None,
        stale_seconds: float = 900.0,
        purpose: str = "",
    ):
        self.name = name
        self.directory = Path(directory) if directory is not None else lock_directory()
        self.path = self.directory / name
        self.owner_path = self.directory / f"{name}.owner"
        self.stale_seconds = stale_seconds
        self.purpose = purpose
        self.held = False
        self.waited_seconds = 0.0

    # -- inspection -----------------------------------------------------
    def owner(self) -> dict | None:
        try:
            data = json.loads(self.owner_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def age_seconds(self) -> float | None:
        try:
            return max(0.0, time.time() - self.path.stat().st_mtime)
        except OSError:
            return None

    def describe(self) -> dict:
        age = self.age_seconds()
        return {
            "name": self.name,
            "held": age is not None,
            "age_seconds": None if age is None else round(age, 1),
            "owner": self.owner() if age is not None else None,
        }

    def _is_stale(self) -> bool:
        age = self.age_seconds()
        if age is None:
            return False
        owner = self.owner()
        if owner and owner.get("host") == socket.gethostname() and isinstance(owner.get("pid"), int):
            if not _process_alive(owner["pid"]):
                return True
        return age > self.stale_seconds

    # -- acquire / release ----------------------------------------------
    def try_acquire(self) -> bool:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._is_stale():
            try:
                self.path.rmdir()
            except OSError:
                pass
        try:
            self.path.mkdir()
        except FileExistsError:
            return False
        self.held = True
        try:
            self.owner_path.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "host": socket.gethostname(),
                        "purpose": self.purpose,
                        "acquired_at_unix": time.time(),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        return True

    def acquire(
        self, timeout_seconds: float = 600.0, *, sleep: Callable[[float], None] = time.sleep
    ) -> "DirectoryLock":
        started = time.monotonic()
        while not self.try_acquire():
            self.waited_seconds = time.monotonic() - started
            if self.waited_seconds >= timeout_seconds:
                raise LockTimeoutError(self._timeout_message(timeout_seconds))
            sleep(_POLL_SECONDS)
        self.waited_seconds = time.monotonic() - started
        return self

    def _timeout_message(self, timeout_seconds: float) -> str:
        owner = self.owner() or {}
        holder = (
            f"process {owner.get('pid')} on {owner.get('host')} ({owner.get('purpose') or 'no purpose recorded'})"
            if owner
            else "an unidentified holder (taken by a script)"
        )
        return (
            f"Timed out after {int(timeout_seconds)}s waiting for the '{self.name}' lock in {self.directory}; "
            f"it is held by {holder}. Wait for that work to finish and retry. If the holder has crashed, "
            f"the lock is reclaimed automatically after {int(self.stale_seconds)}s, or remove the directory "
            f"'{self.path.name}' there yourself once you have confirmed nothing is using it."
        )

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        try:
            self.owner_path.unlink()
        except OSError:
            pass
        try:
            self.path.rmdir()
        except OSError:
            pass

    def __enter__(self) -> "DirectoryLock":
        return self.acquire() if not self.held else self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class BuildSlot:
    """A counting semaphore made of ``build_slot_<n>`` directory locks."""

    def __init__(
        self, slots: int = 4, *, directory: Path | None = None, purpose: str = "", stale_seconds: float = 1200.0
    ):
        self.slots = max(1, int(slots))
        self.directory = directory
        self.purpose = purpose
        self.stale_seconds = stale_seconds
        self._lock: DirectoryLock | None = None
        self.waited_seconds = 0.0

    def acquire(self, timeout_seconds: float = 3600.0, *, sleep: Callable[[float], None] = time.sleep) -> "BuildSlot":
        started = time.monotonic()
        while True:
            for index in range(1, self.slots + 1):
                candidate = DirectoryLock(
                    f"{BUILD_SLOT_PREFIX}{index}",
                    directory=self.directory,
                    stale_seconds=self.stale_seconds,
                    purpose=self.purpose,
                )
                if candidate.try_acquire():
                    self._lock = candidate
                    self.waited_seconds = time.monotonic() - started
                    return self
            self.waited_seconds = time.monotonic() - started
            if self.waited_seconds >= timeout_seconds:
                raise LockTimeoutError(
                    f"Timed out after {int(timeout_seconds)}s waiting for one of {self.slots} build slots in "
                    f"{self.directory or lock_directory()}. Other builds are still running; retry later "
                    "or raise build.max_parallel_builds in .gms-mcp.json if the machine has capacity."
                )
            sleep(3.0)

    def release(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    def __enter__(self) -> "BuildSlot":
        return self.acquire() if self._lock is None else self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def lock_status(slots: int = 4, *, directory: Path | None = None) -> dict:
    """Describe every shared lock so an agent can see why it is waiting."""
    base = Path(directory) if directory is not None else lock_directory()
    names = [
        REPOSITORY_LOCK,
        GAME_RUN_LOCK,
        MOBILE_BUILD_LOCK,
        *(f"{BUILD_SLOT_PREFIX}{i}" for i in range(1, slots + 1)),
    ]
    return {
        "lock_directory": str(base),
        "locks": [DirectoryLock(name, directory=base).describe() for name in names],
    }
