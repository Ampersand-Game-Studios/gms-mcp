"""Cooperative locks for several agents (or people) sharing one machine and one checkout.

GameMaker work has three contended things that file-level transactions cannot protect:

* **the repository** - staging and committing while someone else stages;
* **build capacity** - each Igor build takes several cores and gigabytes of memory;
* **project runtimes** - each canonical project owns its save directory while running;
  macOS sessions use separate signed bundles, so different games can run concurrently;
* **mobile builds** - one Xcode/Gradle output directory and usually one attached device.

A lock is a directory created with ``mkdir`` (atomic on every supported filesystem). The
protocol is deliberately trivial so shell scripts can take part:

    mkdir "$LOCK_DIR/repo.lock"   # take; retry while it fails
    rmdir "$LOCK_DIR/repo.lock"   # release

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
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

_LOCK_DIR_ENV = "GMS_MCP_LOCK_DIR"
_POLL_SECONDS = 1.0

REPOSITORY_LOCK = "repo.lock"
LEGACY_GAME_RUN_LOCK = "gamerun.lock"
MOBILE_BUILD_LOCK = "ios_build.lock"
BUILD_SLOT_PREFIX = "build_slot_"


class LockTimeoutError(TimeoutError):
    """Raised with a message that says who holds the lock and what to do about it."""


def lock_directory() -> Path:
    configured = os.environ.get(_LOCK_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".gms-mcp" / "locks"


def _windows_process_alive(pid: int) -> bool:
    """Liveness check through the Win32 API.

    ``os.kill(pid, 0)`` must never be used on Windows: signal 0 is CTRL_C_EVENT there, so the
    call interrupts the console process group (including this process) instead of probing.
    """
    import ctypes

    kernel32 = getattr(ctypes, "windll").kernel32
    process_query_limited_information = 0x1000
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # Access denied means the process exists but belongs to someone else.
        return kernel32.GetLastError() == 5
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_identity(pid: int) -> str | None:
    """Birth identity prevents a recycled PID inheriting a game lease on macOS."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _owner_process_alive(owner: dict, key: str) -> bool:
    pid = owner.get(key)
    if not isinstance(pid, int) or not _process_alive(pid):
        return False
    expected = owner.get(f"{key}_started")
    actual = _process_identity(pid) if expected else None
    return not (expected and actual and expected != actual)


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
        self._token = secrets.token_hex(16)
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
            # A local owner is judged by its process alone: alive keeps the lock however long the
            # work takes, dead frees it at once. Age only decides for owners we cannot inspect.
            if _owner_process_alive(owner, "pid"):
                return False
            return not _owner_process_alive(owner, "supervisor_pid")
        return age > self.stale_seconds

    def _reclaim_stale(self) -> None:
        """Remove a stale lock and its owner record, one contender at a time.

        Without the mutex two contenders could both judge the old lock stale, and the slower one
        would then remove the lock the faster one had just taken (reading the dead owner's record).
        """
        mutex = self.path.with_name(self.path.name + ".reclaim")
        try:
            mutex.mkdir()
        except FileExistsError:
            # Another contender is reclaiming. A crashed reclaimer must not block for ever.
            try:
                if time.time() - mutex.stat().st_mtime > 10.0:
                    mutex.rmdir()
            except OSError:
                pass
            return
        try:
            if self._is_stale():  # re-check now that nobody else can be reclaiming
                try:
                    self.owner_path.unlink()
                except OSError:
                    pass
                try:
                    self.path.rmdir()
                except OSError:
                    pass
        finally:
            try:
                mutex.rmdir()
            except OSError:
                pass

    # -- acquire / release ----------------------------------------------
    def try_acquire(self) -> bool:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._is_stale():
            self._reclaim_stale()
        try:
            self.path.mkdir()
        except FileExistsError:
            return False
        self.held = True
        try:
            self.owner_path.write_text(
                json.dumps(
                    {
                        "token": self._token,
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

    def bind_process(self, pid: int) -> None:
        """Keep the lease while the game lives, even if its MCP parent disappears."""
        owner = self.owner()
        if not self.held or not owner or owner.get("token") != self._token:
            raise RuntimeError("Cannot transfer an unowned game lease")
        owner["supervisor_pid"] = os.getpid()
        owner["supervisor_pid_started"] = _process_identity(os.getpid())
        owner["pid"] = int(pid)
        owner["pid_started"] = _process_identity(int(pid))
        self.owner_path.write_text(json.dumps(owner, sort_keys=True), encoding="utf-8")

    def release(self) -> None:
        if not self.held:
            return
        mutex = self.path.with_name(self.path.name + ".reclaim")
        while True:
            try:
                mutex.mkdir()
                break
            except FileExistsError:
                try:
                    if time.time() - mutex.stat().st_mtime > 10.0:
                        mutex.rmdir()
                except OSError:
                    pass
                time.sleep(0.01)
        try:
            # Reclaimers use this same mutex. A delayed old cleanup can never remove
            # a replacement lease after its original process has exited.
            self.held = False
            owner = self.owner()
            if not owner or owner.get("token") != self._token:
                return
            self.owner_path.unlink(missing_ok=True)
            try:
                self.path.rmdir()
            except FileNotFoundError:
                pass
        finally:
            try:
                mutex.rmdir()
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
        LEGACY_GAME_RUN_LOCK,
        MOBILE_BUILD_LOCK,
        *(f"{BUILD_SLOT_PREFIX}{i}" for i in range(1, slots + 1)),
    ]
    names.extend(sorted(path.name for path in base.glob("*.lock") if path.name not in names))
    return {
        "lock_directory": str(base),
        "locks": [DirectoryLock(name, directory=base).describe() for name in names],
    }
