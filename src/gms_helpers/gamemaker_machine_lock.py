"""Host-wide serialization for cooperating GameMaker runtime operations."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


_THREAD_LOCK = threading.Lock()
_POLL_SECONDS = 0.05
_DELEGATION_TOKEN_ENV = "GMS_MCP_MACHINE_LOCK_DELEGATION_TOKEN"


def _lock_timeout_seconds() -> float:
    raw = os.environ.get("GMS_MCP_MACHINE_LOCK_TIMEOUT_SECONDS", "1800").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 1800.0


def _lock_path() -> Path:
    configured = os.environ.get("GMS_MCP_MACHINE_LOCK_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("GMS_MCP_MACHINE_LOCK_PATH must be absolute so every project uses the same lock")
        return path.resolve(strict=False)
    return Path(tempfile.gettempdir()).resolve() / "gms-mcp" / "locks" / "gamemaker-runtime.lock"


class GameMakerMachineLock:
    """Serialize Igor start/compile/stop sections across threads and processes."""

    def __init__(self, operation: str, project_root: str | Path, *, timeout_seconds: float | None = None):
        self.operation = operation
        self.project_root = Path(project_root).resolve()
        self.timeout_seconds = _lock_timeout_seconds() if timeout_seconds is None else max(0.0, timeout_seconds)
        self.path = _lock_path()
        self._file: BinaryIO | None = None
        self._thread_acquired = False
        self._os_acquired = False
        self._delegation_token = secrets.token_urlsafe(32)

    def acquire(self) -> None:
        started = time.monotonic()
        if not _THREAD_LOCK.acquire(timeout=self.timeout_seconds):
            raise TimeoutError(self._timeout_message())
        self._thread_acquired = True

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = self.path.open("a+b")
            self._file = lock_file
            os.set_inheritable(lock_file.fileno(), False)
            if lock_file.seek(0, os.SEEK_END) == 0:
                lock_file.write(b"\0")
                lock_file.flush()

            deadline = started + self.timeout_seconds
            while not self._try_os_lock(lock_file):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(self._timeout_message())
                time.sleep(min(_POLL_SECONDS, remaining))
            self._os_acquired = True
            self._write_owner_metadata(lock_file)
        except Exception:
            self.release()
            raise

    def _try_os_lock(self, lock_file: BinaryIO) -> bool:
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False

        import fcntl

        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    def _write_owner_metadata(self, lock_file: BinaryIO, *, delegate_operation: str | None = None) -> None:
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "operation": self.operation,
                "project_root": str(self.project_root),
                "acquired_at_unix": time.time(),
                "delegate_operation": delegate_operation,
                "delegation_token_sha256": (
                    hashlib.sha256(self._delegation_token.encode("utf-8")).hexdigest()
                    if delegate_operation is not None
                    else None
                ),
            },
            sort_keys=True,
        ).encode("utf-8")
        lock_file.seek(1)
        lock_file.truncate()
        lock_file.write(payload)
        lock_file.flush()

    def delegation_environment(self, delegate_operation: str) -> dict[str, str]:
        """Issue one child process a project- and parent-bound lease delegation."""
        if not self._os_acquired or self._file is None:
            raise RuntimeError("GameMaker machine lock must be acquired before delegating it")
        self._write_owner_metadata(self._file, delegate_operation=delegate_operation)
        return {_DELEGATION_TOKEN_ENV: self._delegation_token}

    def _timeout_message(self) -> str:
        return (
            f"Timed out waiting for the host-wide GameMaker runtime lock for {self.operation!r} on {self.project_root}"
        )

    def release(self) -> None:
        lock_file = self._file
        self._file = None
        if lock_file is not None:
            try:
                if self._os_acquired:
                    lock_file.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()
        self._os_acquired = False

        if self._thread_acquired:
            self._thread_acquired = False
            _THREAD_LOCK.release()

    def __enter__(self) -> GameMakerMachineLock:
        self.acquire()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.release()


@contextmanager
def gamemaker_machine_operation(operation: str, project_root: str | Path) -> Iterator[None]:
    """Hold the shared runtime lock for one bounded GameMaker critical section."""
    if _consume_valid_delegation(operation, Path(project_root).resolve()):
        yield
        return
    with GameMakerMachineLock(operation, project_root):
        yield


def _consume_valid_delegation(operation: str, project_root: Path) -> bool:
    """Consume a one-call child token only when it matches the live parent lock."""
    token = os.environ.pop(_DELEGATION_TOKEN_ENV, "").strip()
    if not token:
        return False
    try:
        raw = _lock_path().read_bytes()
        metadata = json.loads(raw[1:].decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(metadata, dict):
        return False

    expected_hash = str(metadata.get("delegation_token_sha256") or "")
    actual_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    owner_pid = metadata.get("pid")
    metadata_project = os.path.normcase(str(metadata.get("project_root") or ""))
    expected_project = os.path.normcase(str(project_root))
    return (
        secrets.compare_digest(actual_hash, expected_hash)
        and metadata.get("delegate_operation") == operation
        and metadata_project == expected_project
        and isinstance(owner_pid, int)
        and owner_pid == os.getppid()
    )
