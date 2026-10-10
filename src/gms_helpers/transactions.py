"""Transactional safety helpers for GameMaker project mutations."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Dict, Iterable, Iterator, List, TextIO, TypeVar

from .exceptions import GMSError, ValidationError
from .gamemaker_machine_lock import GameMakerMachineLock
from .utils import load_json_loose


_IGNORED_DIR_NAMES = {
    ".git",
    ".gms_mcp",
    ".gms-mcp",
    ".gml_index_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "output",
}
_IGNORED_FILE_NAMES = {
    ".coverage",
    ".gml_index_cache.json",
    "mcp_tool_smoke_report.json",
}

_TRANSACTION_JOURNAL_ENV = "GMS_MCP_TRANSACTION_JOURNAL"
_TRANSACTION_ROOT_ENV = "GMS_MCP_TRANSACTION_ROOT"
_TRANSACTION_BACKUP_ENV = "GMS_MCP_TRANSACTION_BACKUP_ROOT"
_PROJECT_LOCKS: Dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()
_JOURNAL_WRITE_GUARD = threading.Lock()
_AUDIT_HOOK_GUARD = threading.Lock()
_AUDIT_HOOK_INSTALLED = False
_ThreadResult = TypeVar("_ThreadResult")
_WINDOWS_DEVICE_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


async def _run_thread_shielded(callable_to_run: Callable[[], _ThreadResult]) -> _ThreadResult:
    """Finish transaction I/O before propagating task cancellation."""
    thread_task = asyncio.create_task(asyncio.to_thread(callable_to_run))
    try:
        return await asyncio.shield(thread_task)
    except asyncio.CancelledError as cancellation:
        try:
            await thread_task
        finally:
            raise cancellation


@dataclass
class _TransactionJournalContext:
    project_root: Path
    journal_path: Path
    backup_root: Path
    seen_paths: set[str] = field(default_factory=set)


_ACTIVE_TRANSACTION: contextvars.ContextVar[_TransactionJournalContext | None] = contextvars.ContextVar(
    "gms_mcp_active_transaction",
    default=None,
)


class _ProjectMutationLock:
    """One project-wide lock shared by threads and cooperating processes."""

    def __init__(self, project_root: Path, tool_name: str):
        self.project_root = project_root
        self.tool_name = tool_name
        self._thread_lock: threading.Lock | None = None
        self._lock_file: TextIO | None = None
        self._acquired = False
        self._shared_lock: Any = None

    def acquire(self) -> None:
        key = os.path.normcase(str(self.project_root.resolve()))
        with _PROJECT_LOCKS_GUARD:
            thread_lock = _PROJECT_LOCKS.setdefault(key, threading.Lock())
        thread_lock.acquire()
        self._thread_lock = thread_lock

        try:
            if os.environ.get("GMS_MCP_LOCK_DIR", "").strip():
                # A team lock directory is configured: scripts that edit the project file
                # take its repo.lock, so project mutations must take it too.
                from .agent_locks import REPOSITORY_LOCK, DirectoryLock

                shared_lock = DirectoryLock(REPOSITORY_LOCK, purpose=f"project mutation {self.tool_name}")
                shared_lock.acquire(timeout_seconds=600.0)
                self._shared_lock = shared_lock
            lock_dir = self.project_root / ".gms_mcp" / "locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_path = lock_dir / "project-mutation.lock"
            lock_file = lock_path.open("a+", encoding="utf-8")
            self._lock_file = lock_file
            self._acquire_os_lock(lock_file)
            self._acquired = True
            lock_file.seek(0)
            lock_file.truncate()
            json.dump(
                {
                    "pid": os.getpid(),
                    "tool": self.tool_name,
                    "acquired_at_unix": time.time(),
                },
                lock_file,
                sort_keys=True,
            )
            lock_file.flush()
        except Exception:
            self.release()
            raise

    @staticmethod
    def _acquire_os_lock(lock_file: TextIO) -> None:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write("\0")
                lock_file.flush()
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    time.sleep(0.05)

        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        lock_file = self._lock_file
        self._lock_file = None
        if lock_file is not None:
            try:
                if self._acquired:
                    if os.name == "nt":
                        import msvcrt

                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

        self._acquired = False
        shared_lock = self._shared_lock
        self._shared_lock = None
        if shared_lock is not None:
            shared_lock.release()
        thread_lock = self._thread_lock
        self._thread_lock = None
        if thread_lock is not None:
            thread_lock.release()


def _lexical_absolute_path(raw_path: Any, dir_fd: Any = None) -> Path | None:
    if not isinstance(raw_path, (str, bytes, os.PathLike)):
        return None
    try:
        path = Path(os.fsdecode(raw_path))
        if not path.is_absolute():
            base = Path.cwd()
            if isinstance(dir_fd, int) and dir_fd >= 0:
                for fd_root in (Path("/proc/self/fd"), Path("/dev/fd")):
                    fd_path = fd_root / str(dir_fd)
                    try:
                        base = fd_path.resolve(strict=True)
                        break
                    except OSError:
                        continue
            path = base / path
        return Path(os.path.abspath(path))
    except (OSError, TypeError, ValueError):
        return None


def _audit_absolute_path(raw_path: Any, dir_fd: Any = None) -> Path | None:
    path = _lexical_absolute_path(raw_path, dir_fd)
    if path is None:
        return None
    try:
        # Resolve parent directories to enforce the project boundary without
        # following the final path when it is itself a symlink being changed.
        return path.parent.resolve(strict=False) / path.name
    except (OSError, TypeError, ValueError):
        return None


def _journal_relative_path(
    context: _TransactionJournalContext,
    raw_path: Any,
    dir_fd: Any = None,
) -> str | None:
    try:
        raw_name = os.fsdecode(raw_path).replace("/", "\\").rsplit("\\", 1)[-1].rstrip(" .")
        if os.name == "nt" and raw_name.split(".", 1)[0].casefold() in _WINDOWS_DEVICE_NAMES:
            return None
        lexical = _lexical_absolute_path(raw_path, dir_fd)
        if lexical is None:
            return None
        resolved = _audit_absolute_path(raw_path, dir_fd)
        if resolved is None:
            return None
        try:
            lexical.relative_to(context.project_root)
            lexical_is_project_path = True
        except ValueError:
            lexical_is_project_path = False
        try:
            resolved.relative_to(context.project_root)
        except ValueError:
            if lexical_is_project_path:
                raise ValidationError("Project mutation blocked: a project path resolves outside the approved root")
            # Transaction infrastructure writes journals/backups outside the
            # project. Those paths are intentionally outside this boundary.
            return None
        try:
            lexical.resolve(strict=False).relative_to(context.project_root)
        except (OSError, ValueError):
            raise ValidationError("Project mutation blocked: a project path resolves outside the approved root")
        relative = resolved.relative_to(context.project_root).as_posix()
    except (OSError, TypeError, ValueError):
        return None
    if not relative or relative == "." or _is_ignored_path(Path(relative)):
        return None
    return relative


def _append_journal_path(
    context: _TransactionJournalContext,
    raw_path: Any,
    event: str,
    dir_fd: Any = None,
) -> None:
    relative = _journal_relative_path(context, raw_path, dir_fd)
    if relative is None:
        return
    with _JOURNAL_WRITE_GUARD:
        if relative in context.seen_paths:
            return
        if relative in _load_journal_paths(context.journal_path):
            context.seen_paths.add(relative)
            return
        if not _capture_original_path(context, relative):
            raise RuntimeError(f"Cannot safely snapshot transaction path before mutation: {relative}")
        context.seen_paths.add(relative)
        with context.journal_path.open("a", encoding="utf-8") as journal:
            backup = _safe_backup_path(context.backup_root, relative)
            if backup is None:
                raise ValidationError(f"Unsafe transaction backup: {relative}")
            journal.write(
                json.dumps(
                    {"event": event, "path": relative, "original": list(_path_fingerprint(backup))}, sort_keys=True
                )
                + "\n"
            )
            journal.flush()
            os.fsync(journal.fileno())


def _append_journal_tree(
    context: _TransactionJournalContext,
    root_raw: Any,
    event: str,
    dir_fd: Any = None,
) -> None:
    root = _audit_absolute_path(root_raw, dir_fd)
    _append_journal_path(context, root_raw, event, dir_fd)
    if root is None:
        return
    try:
        root.relative_to(context.project_root)
    except ValueError:
        return
    if not root.is_dir() or root.is_symlink():
        return
    try:
        descendants = list(root.rglob("*"))
    except OSError:
        return
    for child in descendants:
        _append_journal_path(context, child, f"{event}:descendant")


def _append_rename_tree(
    context: _TransactionJournalContext,
    source_raw: Any,
    destination_raw: Any,
    source_dir_fd: Any = None,
    destination_dir_fd: Any = None,
) -> None:
    """Journal both sides of a rename, including descendants moved implicitly."""
    _append_journal_path(context, source_raw, "os.rename", source_dir_fd)
    _append_journal_path(context, destination_raw, "os.rename", destination_dir_fd)
    source = _audit_absolute_path(source_raw, source_dir_fd)
    destination = _audit_absolute_path(destination_raw, destination_dir_fd)
    if source is None or destination is None:
        return
    try:
        source.relative_to(context.project_root)
        destination.relative_to(context.project_root)
    except ValueError:
        return
    if not source.is_dir() or source.is_symlink():
        return

    try:
        descendants = list(source.rglob("*"))
    except OSError:
        return
    for child in descendants:
        try:
            suffix = child.relative_to(source)
        except ValueError:
            continue
        _append_journal_path(context, child, "os.rename:descendant")
        _append_journal_path(context, destination / suffix, "os.rename:descendant")


def _open_event_is_write(args: tuple[Any, ...]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str) and any(character in mode for character in "wax+"):
        return True
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    return isinstance(flags, int) and bool(flags & write_flags)


def _assert_link_source_contained(
    context: _TransactionJournalContext,
    event: str,
    args: tuple[Any, ...],
) -> None:
    source_raw = next(iter(args), None)
    destination_raw = next(iter(args[1:]), None)
    if source_raw is None or destination_raw is None:
        return
    third_arg = next(iter(args[2:]), None)
    fourth_arg = next(iter(args[3:]), None)
    destination_dir_fd = fourth_arg if event == "os.link" else third_arg
    destination = _audit_absolute_path(destination_raw, destination_dir_fd)
    if destination is None or not destination.is_relative_to(context.project_root):
        return

    source = Path(os.fsdecode(source_raw))
    if event == "os.symlink" and not source.is_absolute():
        source = destination.parent / source
    else:
        source_dir_fd = third_arg if event == "os.link" else None
        source = _lexical_absolute_path(source, source_dir_fd) or source
    try:
        source.resolve(strict=False).relative_to(context.project_root)
    except (OSError, ValueError):
        raise ValidationError("Project mutation blocked: filesystem links cannot target outside the approved root")


def _transaction_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    context = _ACTIVE_TRANSACTION.get()
    if context is None:
        return

    if event == "open" and args and _open_event_is_write(args):
        _append_journal_path(context, args[0], event)
    elif event in {"os.remove", "os.rmdir"} and args:
        _append_journal_path(context, args[0], event, args[1] if len(args) > 1 else None)
    elif event in {"os.mkdir", "os.chmod"} and args:
        _append_journal_path(context, args[0], event, args[2] if len(args) > 2 else None)
    elif event == "os.truncate" and args:
        _append_journal_path(context, args[0], event)
    elif event == "os.rename" and len(args) >= 2:
        _append_rename_tree(
            context,
            args[0],
            args[1],
            args[2] if len(args) > 2 else None,
            args[3] if len(args) > 3 else None,
        )
    elif event == "shutil.rmtree" and args:
        _append_journal_tree(context, args[0], event, args[1] if len(args) > 1 else None)
    elif event in {"shutil.copyfile", "shutil.copytree"} and len(args) >= 2:
        _append_journal_path(context, args[1], event)
    elif event in {"os.link", "os.symlink"} and len(args) >= 2:
        _assert_link_source_contained(context, event, args)
        _append_journal_path(context, args[1], event)


def _ensure_transaction_audit_hook() -> None:
    global _AUDIT_HOOK_INSTALLED
    with _AUDIT_HOOK_GUARD:
        if _AUDIT_HOOK_INSTALLED:
            return
        sys.addaudithook(_transaction_audit_hook)
        _AUDIT_HOOK_INSTALLED = True


def transaction_subprocess_environment() -> Dict[str, str]:
    """Return child-process journal settings for the active transaction."""
    context = _ACTIVE_TRANSACTION.get()
    if context is None:
        return {}
    return {
        _TRANSACTION_ROOT_ENV: str(context.project_root),
        _TRANSACTION_JOURNAL_ENV: str(context.journal_path),
        _TRANSACTION_BACKUP_ENV: str(context.backup_root),
    }


def transaction_is_active(project_root: str | Path | None = None) -> bool:
    """Trust only a context established while owning the project/participant lock."""
    context = _ACTIVE_TRANSACTION.get()
    return context is not None and (project_root is None or context.project_root == Path(project_root).resolve())


def journaled_gms_cli_command(cli_arguments: List[str]) -> List[str]:
    """Build the Python CLI command that activates the inherited write journal."""
    return [
        sys.executable,
        "-u",
        "-c",
        "from gms_helpers.transactions import run_journaled_cli; run_journaled_cli()",
        *cli_arguments,
    ]


@contextmanager
def inherited_transaction_context() -> Iterator[None]:
    """Activate the parent transaction journal described by the child environment."""
    root_raw = os.environ.get(_TRANSACTION_ROOT_ENV, "").strip()
    journal_raw = os.environ.get(_TRANSACTION_JOURNAL_ENV, "").strip()
    backup_raw = os.environ.get(_TRANSACTION_BACKUP_ENV, "").strip()
    configured = [bool(root_raw), bool(journal_raw), bool(backup_raw)]
    if not any(configured):
        yield
        return
    if not all(configured):
        raise RuntimeError("Inherited transaction environment is incomplete")

    root = Path(root_raw).resolve()
    journal = Path(journal_raw)
    backup = Path(backup_raw)
    recovery_dir = journal.parent
    if (
        recovery_dir.parent != root / ".gms_mcp" / "transactions"
        or not recovery_dir.name.startswith("tx-")
        or journal.name != "writes.jsonl"
        or backup != recovery_dir / "project"
    ):
        raise ValidationError("Inherited transaction journal is outside its approved recovery directory")
    for path in (journal, backup, recovery_dir / "state.json"):
        _assert_plain_infrastructure(root, path)
    # This independent OS lock survives a parent crash because the child owns
    # its descriptor. A new parent must wait until every child finishes writes.
    with _transaction_participant_lock(root, recovery_dir):
        state = json.loads((recovery_dir / "state.json").read_text(encoding="utf-8"))
        if state.get("status") != "active" or state.get("project_root") != str(root):
            raise ValidationError("Inherited transaction is no longer active")
        _load_journal_records(journal)
        _ensure_transaction_audit_hook()
        context = _TransactionJournalContext(root, journal, backup)
        token = _ACTIVE_TRANSACTION.set(context)
        try:
            yield
        finally:
            _ACTIVE_TRANSACTION.reset(token)


def run_journaled_cli() -> None:
    """Run the GMS CLI while journaling project writes for its parent transaction."""
    with inherited_transaction_context():
        if not transaction_is_active():
            raise RuntimeError("Journaled CLI requires an active transaction environment")
        from . import gms as gms_module

        try:
            success = gms_module.main()
            raise SystemExit(0 if success else 1)
        except GMSError as exc:
            raise SystemExit(exc.exit_code) from exc


from .project_validation import (
    ProjectValidationResult,
    errors_introduced_by_mutation,
    validate_project_after_mutation,
)

_STRICT_VALIDATION_ENV = "GMS_MCP_STRICT_PROJECT_VALIDATION"
_VALIDATION_BASELINE_FILE = "validation-baseline.json"


class TransactionValidationError(ValidationError):
    """Raised when a project mutation was rolled back after validation failed."""


def _is_ignored_path(path: Path) -> bool:
    # Verification bookkeeping is part of the mutation, unlike locks/caches.
    if path.parent == Path(".gms_mcp") and any(
        filename in path.name for filename in ("verification_state.json", "runtime.json")
    ):
        return False
    # Only project-root infrastructure is excluded. An asset named "output"
    # (scripts/output/output.yy) must not silently escape rollback coverage.
    return bool(path.parts) and (
        path.parts[0] in _IGNORED_DIR_NAMES or (len(path.parts) == 1 and path.name in _IGNORED_FILE_NAMES)
    )


def _iter_project_paths(project_root: Path) -> Iterable[Path]:
    for path in project_root.rglob("*"):
        if _is_ignored_path(path.relative_to(project_root)):
            continue
        yield path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_state(project_root: Path) -> Dict[str, str]:
    """Build a metadata manifest without copying or reading every project file."""
    state: Dict[str, str] = {}
    for path in _iter_project_paths(project_root):
        rel = path.relative_to(project_root).as_posix()
        try:
            stat_result = path.lstat()
            if path.is_symlink():
                fingerprint = ("symlink", os.readlink(path), stat_result.st_mode, stat_result.st_ctime_ns)
            elif path.is_dir():
                # Directory timestamps change when children change.  Type and
                # mode still detect creation, deletion, replacement, and chmod.
                fingerprint = ("directory", stat_result.st_mode)
            elif path.is_file():
                fingerprint = (
                    "file",
                    stat_result.st_mode,
                    stat_result.st_size,
                    stat_result.st_mtime_ns,
                    stat_result.st_ctime_ns,
                )
            else:
                fingerprint = ("other", stat_result.st_mode, stat_result.st_ctime_ns)
            state[rel] = json.dumps(fingerprint, separators=(",", ":"), ensure_ascii=True)
        except OSError:
            continue
    return state


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _fsync_directory(path: Path) -> None:
    """Make journal creation/renames durable as well as their file contents."""
    if os.name == "nt":
        return  # Windows does not expose POSIX directory fsync.
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    """Flush existing bytes without truncation, using Windows-required write access."""
    # CPython's Windows fsync uses _commit/FlushFileBuffers. A read-only
    # descriptor cannot flush there; POSIX still permits read-only descriptors.
    with path.open("r+b" if sys.platform == "win32" else "rb") as stream:
        os.fsync(stream.fileno())


def _assert_plain_infrastructure(project_root: Path, path: Path) -> None:
    """Never follow links for locks, journals, state or backup directories."""
    relative = path.relative_to(project_root)
    candidate = project_root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink() or candidate.resolve(strict=False) != candidate:
            raise ValidationError(f"Unsafe transaction infrastructure: {candidate}")
        if candidate.exists() and candidate.is_file() and candidate.stat().st_nlink != 1:
            raise ValidationError(f"Unsafe linked transaction infrastructure: {candidate}")


@contextmanager
def _transaction_participant_lock(project_root: Path, recovery_dir: Path) -> Iterator[None]:
    lock_path = recovery_dir / "participants.lock"
    _assert_plain_infrastructure(project_root, lock_path)
    lock = _ProjectMutationLock(project_root, "transaction-participant")
    lock._lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        lock._acquire_os_lock(lock._lock_file)
        lock._acquired = True
        yield
    finally:
        lock.release()


def _path_fingerprint(path: Path) -> tuple[Any, ...]:
    """Fingerprint one path without following symlinks."""
    try:
        if not _path_exists(path):
            return ("absent",)
        stat_result = path.lstat()
        metadata = (stat_result.st_mode, stat_result.st_size, stat_result.st_mtime_ns)
        if path.is_symlink():
            return ("symlink", os.readlink(path), *metadata)
        if path.is_dir():
            return ("directory", stat_result.st_mode)
        if path.is_file():
            return ("file", _hash_file(path), *metadata)
        return ("other", *metadata)
    except FileNotFoundError:
        return ("absent",)
    except OSError as exc:
        return ("unavailable", type(exc).__name__, str(exc))


def _load_journal_records(journal_path: Path | None) -> list[dict[str, Any]]:
    if journal_path is None or not journal_path.exists():
        return []
    if journal_path.is_symlink() or not journal_path.is_file() or journal_path.stat().st_nlink != 1:
        raise ValidationError("Unsafe transaction journal")
    records = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError("Transaction journal is incomplete or corrupt") from exc
        if not isinstance(record, dict) or not _valid_relative_path(record.get("path")):
            raise ValidationError("Unsafe transaction journal path")
        if not isinstance(record.get("event"), str):
            raise ValidationError("Transaction journal event is missing")
        fingerprint_key = "fingerprint" if record["event"] == "owned" else "original"
        fingerprint = record.get(fingerprint_key)
        if (
            not isinstance(fingerprint, list)
            or not fingerprint
            or fingerprint[0] not in {"absent", "file", "directory", "symlink", "other"}
        ):
            raise ValidationError("Transaction journal fingerprint is missing or corrupt")
        records.append(record)
    return records


def _load_journal_paths(journal_path: Path | None) -> set[str]:
    return {record["path"] for record in _load_journal_records(journal_path)}


def _load_journal_owned_states(journal_path: Path | None) -> Dict[str, tuple[Any, ...]]:
    owned: Dict[str, tuple[Any, ...]] = {}
    for record in _load_journal_records(journal_path):
        if record["event"] == "owned":
            owned[record["path"]] = tuple(record["fingerprint"])
    return owned


def mark_transaction_path_owned(path: str | Path, *, expected_fingerprint: tuple[Any, ...] | None = None) -> None:
    """Record the exact post-mutation state produced by transaction code."""
    context = _ACTIVE_TRANSACTION.get()
    if context is None:
        return
    relative = _journal_relative_path(context, path)
    if relative is None:
        return
    target = _safe_relative_path(context.project_root, relative)
    if target is None:
        return
    fingerprint = expected_fingerprint if expected_fingerprint is not None else _path_fingerprint(target)
    with _JOURNAL_WRITE_GUARD:
        with context.journal_path.open("a", encoding="utf-8") as journal:
            journal.write(
                json.dumps(
                    {"event": "owned", "path": relative, "fingerprint": list(fingerprint)},
                    sort_keys=True,
                )
                + "\n"
            )
            journal.flush()
            os.fsync(journal.fileno())


def mark_transaction_tree_owned(path: str | Path, *, expected_states: Dict[str, tuple[Any, ...]] | None = None) -> None:
    """Record every already-journaled path at or below a mutated tree."""
    context = _ACTIVE_TRANSACTION.get()
    if context is None:
        return
    relative_root = _journal_relative_path(context, path)
    if relative_root is None:
        return
    for relative in sorted(_load_journal_paths(context.journal_path)):
        if relative == relative_root or relative.startswith(f"{relative_root}/"):
            suffix = relative[len(relative_root) :].lstrip("/") or "."
            expected = expected_states.get(suffix, ("absent",)) if expected_states is not None else None
            mark_transaction_path_owned(context.project_root / relative, expected_fingerprint=expected)


def _tree_output_fingerprints(path: Path, *, follow_links: bool = False) -> Dict[str, tuple[Any, ...]]:
    """Predict a tree operation's output before any destination can be edited."""
    states = {}

    def visit(source: Path, suffix: str, ancestors: set[tuple[int, int]]) -> None:
        physical = source.resolve() if follow_links else source
        fingerprint = _path_fingerprint(physical)
        states[suffix] = fingerprint
        if fingerprint[0] != "directory":
            return
        stat_result = physical.stat()
        identity = (stat_result.st_dev, stat_result.st_ino)
        if identity in ancestors:
            raise ValidationError("Cannot transactionally copy a cyclic filesystem tree")
        for child in source.iterdir():
            child_suffix = child.name if suffix == "." else f"{suffix}/{child.name}"
            visit(child, child_suffix, ancestors | {identity})

    visit(path, ".", set())
    return states


def transactional_copy2(source: str | Path, destination: str | Path, **kwargs: Any) -> str:
    """Copy one file and record the destination's exact transaction-owned state."""
    source_path = Path(source)
    destination_path = Path(destination)
    if destination_path.is_dir():
        destination_path /= source_path.name
    if kwargs.get("follow_symlinks", True):
        source_path = source_path.resolve()
    if source_path.resolve() == destination_path.resolve():
        raise shutil.SameFileError(source, destination, "Source and destination are the same file")
    expected = _path_fingerprint(source_path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination_path.name}.copy-", dir=destination_path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary, **kwargs)
        mark_transaction_path_owned(temporary, expected_fingerprint=expected)
        transactional_replace(temporary, destination_path, expected_fingerprint=expected)
        return str(destination_path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            transactional_unlink(temporary)


def transactional_copytree(source: str | Path, destination: str | Path, **kwargs: Any) -> str:
    """Copy a tree and record every resulting destination path as transaction-owned."""
    expected = _tree_output_fingerprints(Path(source), follow_links=not kwargs.get("symlinks", False))
    kwargs.setdefault("copy_function", transactional_copy2)
    try:
        copied = shutil.copytree(source, destination, **kwargs)
    finally:
        # A tree copy may fail after producing several complete files/directories.
        # The known source outputs remain safe ownership proof for those paths.
        mark_transaction_tree_owned(destination, expected_states=expected)
    return str(copied)


def transactional_unlink(path: str | Path, *, missing_ok: bool = False) -> None:
    """Unlink one path and record its resulting absence as transaction-owned."""
    target = Path(path)
    target.unlink(missing_ok=missing_ok)
    mark_transaction_path_owned(target, expected_fingerprint=("absent",))


def transactional_rmdir(path: str | Path) -> None:
    """Remove an empty directory and record its resulting absence."""
    target = Path(path)
    target.rmdir()
    mark_transaction_path_owned(target, expected_fingerprint=("absent",))


def transactional_rmtree(path: str | Path, **kwargs: Any) -> None:
    """Remove a tree and record every deleted path as transaction-owned."""
    target = Path(path)
    if kwargs.get("ignore_errors") or kwargs.get("onerror") or kwargs.get("onexc"):
        raise ValueError("Transactional deletion cannot suppress cleanup failures")
    # Use individually journaled removals: a partial deletion must retain
    # ownership evidence for each successful removal, even if the next fails.
    for child in list(target.iterdir()):
        if child.is_dir() and not child.is_symlink():
            transactional_rmtree(child, **kwargs)
        else:
            transactional_unlink(child)
    transactional_rmdir(target)


def transactional_rename(source: str | Path, destination: str | Path) -> Path:
    """Rename a path and record both source and destination trees."""
    source_path = Path(source)
    destination_path = Path(destination)
    expected = _tree_output_fingerprints(source_path)
    renamed = source_path.rename(destination_path)
    mark_transaction_tree_owned(source_path, expected_states={})
    mark_transaction_tree_owned(destination_path, expected_states=expected)
    return renamed


def transactional_replace(
    source: str | Path, destination: str | Path, *, expected_fingerprint: tuple[Any, ...] | None = None
) -> Path:
    """Atomically replace a path and record both resulting path states."""
    source_path = Path(source)
    destination_path = Path(destination)
    expected = _path_fingerprint(source_path) if expected_fingerprint is None else expected_fingerprint
    if _path_fingerprint(source_path) != expected:
        raise ValidationError("Replacement source changed before its transaction-owned output could be written")
    replaced = source_path.replace(destination_path)
    mark_transaction_path_owned(source_path, expected_fingerprint=("absent",))
    mark_transaction_path_owned(destination_path, expected_fingerprint=expected)
    return replaced


def _valid_relative_path(relative_path: Any) -> bool:
    if not isinstance(relative_path, str):
        return False
    # A Windows root without a drive (e.g. /tmp/outside) is not "absolute"
    # according to pathlib, but joining it still discards the project root.
    # Reject roots and drives in both flavours before any filesystem access.
    posix_relative = PurePosixPath(relative_path)
    windows_relative = PureWindowsPath(relative_path)
    if posix_relative.root or windows_relative.root or windows_relative.drive:
        return False
    relative = Path(relative_path)
    return bool(relative_path) and (
        relative_path == relative.as_posix()
        and relative_path != "."
        and not relative.is_absolute()
        and "\\" not in relative_path
        and "\x00" not in relative_path
        and ".." not in relative.parts
        and not _is_ignored_path(relative)
    )


def _safe_backup_path(backup_root: Path, relative_path: str) -> Path | None:
    if not _valid_relative_path(relative_path):
        return None
    candidate = backup_root / relative_path
    # Parents must remain at their original lexical locations. Following an
    # attacker-replaced internal symlink is as unsafe as leaving the root.
    if backup_root.is_symlink() or candidate.parent.resolve() != candidate.parent:
        return None
    return candidate


def _capture_original_path(context: _TransactionJournalContext, relative: str) -> bool:
    """Lazily copy one path before its first transaction write."""
    source = _safe_relative_path(context.project_root, relative)
    backup = _safe_backup_path(context.backup_root, relative)
    if source is None or backup is None:
        return False
    try:
        initial_source = _path_fingerprint(source)
        if not _path_exists(source):
            return True
        backup.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            backup.symlink_to(os.readlink(source))
        elif source.is_dir():
            backup.mkdir(exist_ok=True)
            shutil.copystat(source, backup, follow_symlinks=False)
        elif source.is_file():
            shutil.copy2(source, backup, follow_symlinks=False)
            _fsync_file(backup)
        else:
            return False
        if _path_fingerprint(source) != initial_source:
            return False  # The snapshot raced an external editor's save.
        for directory in (backup.parent, *backup.parent.parents):
            _fsync_directory(directory)
            if directory == context.backup_root:
                break
        return True
    except OSError:
        return False


def _restore_file_atomically(backup_path: Path, target_path: Path, expected: tuple[Any, ...]) -> bool:
    """Restore one file/symlink only if its live fingerprint still matches the plan."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target_path.name}.rollback-", dir=str(target_path.parent))
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        if backup_path.is_symlink():
            temporary_path.unlink()
            temporary_path.symlink_to(os.readlink(backup_path))
        else:
            shutil.copy2(backup_path, temporary_path, follow_symlinks=False)
            _fsync_file(temporary_path)
        if _path_fingerprint(target_path) != expected:
            return False
        os.replace(temporary_path, target_path)
        _fsync_directory(target_path.parent)
        return True
    finally:
        if _path_exists(temporary_path):
            temporary_path.unlink()


def _rollback_entry_matches(backup_path: Path, target_path: Path) -> bool:
    """Verify rollback content without rejecting harmless directory timestamp changes."""
    if not _path_exists(backup_path):
        return not _path_exists(target_path)
    if backup_path.is_symlink():
        return target_path.is_symlink() and os.readlink(target_path) == os.readlink(backup_path)
    if backup_path.is_dir():
        return (
            target_path.is_dir()
            and not target_path.is_symlink()
            and target_path.stat().st_mode == backup_path.stat().st_mode
        )
    if backup_path.is_file():
        return (
            target_path.is_file()
            and not target_path.is_symlink()
            and _hash_file(target_path) == _hash_file(backup_path)
        )
    return _path_fingerprint(target_path)[0] == _path_fingerprint(backup_path)[0]


def _summarize_changes(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    created = sorted(after_keys - before_keys)
    deleted = sorted(before_keys - after_keys)
    modified = sorted(path for path in before_keys & after_keys if before[path] != after[path])
    return {
        "created_count": len(created),
        "modified_count": len(modified),
        "deleted_count": len(deleted),
        "changed_count": len(created) + len(modified) + len(deleted),
        "created": created[:50],
        "modified": modified[:50],
        "deleted": deleted[:50],
        "truncated": len(created) > 50 or len(modified) > 50 or len(deleted) > 50,
    }


def _changed_project_paths(before: Dict[str, str], after: Dict[str, str]) -> set[str]:
    before_keys = set(before)
    after_keys = set(after)
    return (before_keys ^ after_keys) | {path for path in before_keys & after_keys if before[path] != after[path]}


def _safe_relative_path(project_root: Path, relative_path: str) -> Path | None:
    try:
        relative = Path(relative_path)
        if not _valid_relative_path(relative_path):
            return None
        raw_candidate = project_root / relative
        candidate = raw_candidate.parent.resolve(strict=False) / raw_candidate.name
        candidate.relative_to(project_root.resolve())
        if candidate != raw_candidate:
            return None
        return candidate
    except (OSError, ValueError):
        return None


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def should_compile_verify_after_mutation() -> bool:
    mode = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY", "").strip().lower()
    return mode in {"1", "true", "yes", "on", "compile", "ide"} or _env_truthy("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION")


def _compile_stage_succeeded(stdout: str) -> bool:
    compile_finished = "Final Compile finished" in stdout and "Saving IFF file" in stdout
    return compile_finished and ("Igor complete." in stdout or "Stats : GMA" in stdout)


_ACCESS_VIOLATION_SIGNATURE = "System.AccessViolationException"


def _command_references_project(command: str, project_root: str, *, case_insensitive: bool) -> bool:
    normalized_command = command.replace("\\", "/")
    normalized_root = project_root.replace("\\", "/").rstrip("/")
    if case_insensitive:
        normalized_command = normalized_command.casefold()
        normalized_root = normalized_root.casefold()
    if not normalized_root:
        return False

    start = 0
    while True:
        index = normalized_command.find(normalized_root, start)
        if index < 0:
            return False
        before_ok = index == 0 or normalized_command[index - 1].isspace() or normalized_command[index - 1] in "\"'=,"
        end = index + len(normalized_root)
        # A descendant separator or closing quote is a real path boundary. Whitespace
        # is not: it can be part of an unquoted sibling such as "Exact Game Backup".
        after_ok = end == len(normalized_command) or normalized_command[end] in "/\"'"
        if before_ok and after_ok:
            return True
        start = index + 1


def _compile_verification_process_pids(project_root: Path) -> set[int]:
    """Return active validation helper PIDs scoped to one exact project path."""
    windows = os.name == "nt"
    command = (
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                "Get-CimInstance Win32_Process | "
                "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
            ),
        ]
        if windows
        # ``-ww`` prevents hosted runners from truncating long command lines
        # before the project path or helper marker appears.
        else ["ps", "-ww", "-axo", "pid=,command="]
    )
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        output, _stderr = process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return set()
    except (OSError, subprocess.SubprocessError):
        return set()

    root_token = str(project_root)
    markers = ("gms_helpers.gms", "Igor", "Mac_Runner", "tail -F", "runner.exe")
    pids: set[int] = set()
    if windows:
        try:
            records = json.loads(output or "[]")
        except json.JSONDecodeError:
            return set()
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            return set()
        normalized_markers = tuple(marker.casefold() for marker in markers)
        for record in records:
            if not isinstance(record, dict):
                continue
            command_line = str(record.get("CommandLine") or "")
            normalized_command = command_line.replace("\\", "/").casefold()
            if not _command_references_project(command_line, root_token, case_insensitive=True) or not any(
                marker in normalized_command for marker in normalized_markers
            ):
                continue
            raw_pid = record.get("ProcessId")
            if not isinstance(raw_pid, (int, str)):
                continue
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                continue
            if pid != os.getpid():
                pids.add(pid)
        return pids

    for raw_line in output.splitlines():
        parts = raw_line.strip().split(None, 1)
        if (
            len(parts) != 2
            or not _command_references_project(parts[1], root_token, case_insensitive=False)
            or not any(marker in parts[1] for marker in markers)
        ):
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid != os.getpid():
            pids.add(pid)
    return pids


def _terminate_compile_verification_processes(project_root: Path, baseline_pids: set[int]) -> Dict[str, Any]:
    """Terminate only new compile helpers associated with this verification run."""
    candidates = sorted(_compile_verification_process_pids(project_root) - baseline_pids, reverse=True)
    terminated: List[int] = []
    failed: List[int] = []
    if os.name == "nt":
        for pid in candidates:
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError):
                failed.append(pid)
                continue
            if completed.returncode == 0:
                terminated.append(pid)
            else:
                failed.append(pid)
        return {"terminated_pids": terminated, "failed_pids": failed}

    for pid in candidates:
        try:
            os.kill(pid, signal.SIGTERM)
            terminated.append(pid)
        except ProcessLookupError:
            continue
        except OSError:
            failed.append(pid)

    deadline = time.monotonic() + 1.0
    remaining = set(terminated)
    while remaining and time.monotonic() < deadline:
        for pid in list(remaining):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                remaining.discard(pid)
        if remaining:
            time.sleep(0.05)

    force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    for pid in sorted(remaining, reverse=True):
        try:
            os.kill(pid, force_signal)
        except ProcessLookupError:
            pass
        except OSError:
            if pid not in failed:
                failed.append(pid)
    return {"terminated_pids": terminated, "failed_pids": failed}


def _timeout_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _compile_verify_attempt_limit() -> int:
    raw = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY_INFRA_ATTEMPTS", "3").strip()
    try:
        return min(3, max(1, int(raw)))
    except ValueError:
        return 3


def compile_verify_project(
    project_root: str | Path,
    *,
    platform: str | None = None,
    runtime: str | None = None,
    timeout_seconds: int | None = None,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    with GameMakerMachineLock("compile-verify", root) as machine_lock:
        return _compile_verify_project_locked(
            root,
            platform=platform,
            runtime=runtime,
            timeout_seconds=timeout_seconds,
            machine_lock=machine_lock,
        )


def _compile_verify_project_locked(
    root: Path,
    *,
    platform: str | None,
    runtime: str | None,
    timeout_seconds: int | None,
    machine_lock: GameMakerMachineLock,
) -> Dict[str, Any]:
    if timeout_seconds is None:
        timeout_raw = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY_TIMEOUT_SECONDS", "1800").strip()
        try:
            timeout_seconds = max(1, int(timeout_raw))
        except ValueError:
            timeout_seconds = 1800

    selected_runtime = (runtime or os.environ.get("GMS_MCP_POST_MUTATION_RUNTIME", "VM")).strip() or "VM"
    selected_platform = (platform or os.environ.get("GMS_MCP_POST_MUTATION_PLATFORM", "")).strip()
    if not selected_platform:
        from .runner import detect_default_target_platform

        selected_platform = detect_default_target_platform()

    cli_arguments = [
        "--project-root",
        str(root),
        "run",
        "compile",
        "--platform",
        selected_platform,
        "--runtime",
        selected_runtime,
    ]
    transaction_env = transaction_subprocess_environment()
    cmd = (
        journaled_gms_cli_command(cli_arguments)
        if transaction_env
        else [sys.executable, "-u", "-m", "gms_helpers.gms", *cli_arguments]
    )
    child_env = os.environ.copy()
    child_env.update(transaction_env)
    attempt_limit = _compile_verify_attempt_limit()
    attempts: List[Dict[str, Any]] = []
    retried_infrastructure_failure = False
    started = time.monotonic()
    for attempt_number in range(1, attempt_limit + 1):
        attempt_started = time.monotonic()
        baseline_compile_pids = _compile_verification_process_pids(root)
        timed_out = False
        timeout_cleanup: Dict[str, Any] = {"terminated_pids": [], "failed_pids": []}
        attempt_env = child_env.copy()
        attempt_env.update(machine_lock.delegation_environment("compile"))
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(root),
                env=attempt_env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            timeout_cleanup = _terminate_compile_verification_processes(root, baseline_compile_pids)
            completed = subprocess.CompletedProcess(
                args=cmd,
                returncode=-9,
                stdout=_timeout_output(exc.stdout),
                stderr=_timeout_output(exc.stderr),
            )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        compile_stage_ok = _compile_stage_succeeded(stdout)
        access_violation = _ACCESS_VIOLATION_SIGNATURE in stdout or _ACCESS_VIOLATION_SIGNATURE in stderr
        retryable_infrastructure_failure = (
            not timed_out and completed.returncode != 0 and access_violation and not compile_stage_ok
        )
        accepted_compile_stage_success = (
            completed.returncode != 0
            and compile_stage_ok
            and _env_bool("GMS_MCP_POST_MUTATION_ACCEPT_COMPILE_STAGE_SUCCESS", default=True)
        )
        ok = completed.returncode == 0 or accepted_compile_stage_success
        attempts.append(
            {
                "attempt": attempt_number,
                "exit_code": completed.returncode,
                "compile_stage_ok": compile_stage_ok,
                "access_violation": access_violation,
                "timed_out": timed_out,
                "timeout_cleanup": timeout_cleanup,
                "retryable_infrastructure_failure": retryable_infrastructure_failure,
                "elapsed_seconds": time.monotonic() - attempt_started,
            }
        )
        if ok or not retryable_infrastructure_failure or attempt_number >= attempt_limit:
            break
        retried_infrastructure_failure = True

    elapsed = time.monotonic() - started
    return {
        "ok": ok,
        "mode": "compile",
        "platform": selected_platform,
        "runtime": selected_runtime,
        "exit_code": completed.returncode,
        "compile_stage_ok": compile_stage_ok,
        "accepted_compile_stage_success": accepted_compile_stage_success,
        "post_compile_exit_failure": completed.returncode != 0 and compile_stage_ok,
        "timed_out": timed_out,
        "timeout_cleanup": timeout_cleanup,
        "elapsed_seconds": elapsed,
        "attempt_count": len(attempts),
        "attempt_limit": attempt_limit,
        "retried_infrastructure_failure": retried_infrastructure_failure,
        "attempts": attempts,
        "stdout_tail": "\n".join((completed.stdout or "").splitlines()[-80:]),
        "stderr_tail": "\n".join((completed.stderr or "").splitlines()[-80:]),
    }


def _compile_verification(project_root: Path) -> Dict[str, Any]:
    return compile_verify_project(project_root)


class GameMakerProjectTransaction:
    """Serialize a project mutation and journal its writes for selective rollback."""

    def __init__(self, project_root: str | Path, tool_name: str):
        self.project_root = Path(project_root).resolve()
        self.tool_name = tool_name
        self._tmp_dir: Path | None = None
        self._backup_root: Path | None = None
        self._journal_path: Path | None = None
        self._journal_context: _TransactionJournalContext | None = None
        self._context_token: contextvars.Token | None = None
        self._project_lock: _ProjectMutationLock | None = None
        self._before_state: Dict[str, str] = {}
        self._after_state: Dict[str, str] = {}
        self._owned_mutation_state: Dict[str, tuple[Any, ...]] = {}
        self._unproven_owned_paths: set[str] = set()
        self._mutation_state_captured = False
        self.validation: ProjectValidationResult | None = None
        self._baseline_errors: List[str] | None = None
        self.compile_verification: Dict[str, Any] | None = None
        self.rollback_conflicts: List[Dict[str, str]] = []
        self.rollback_complete: bool | None = None
        self._rollback_attempted = False
        self.rolled_back = False
        self.committed = False
        self.bookkeeping: Dict[str, Any] = {}

    def _persist_status(self, status: str) -> None:
        if self._tmp_dir is None:
            return
        payload = {
            "version": 2,
            "status": status,
            "project_root": str(self.project_root),
            "tool": self.tool_name,
            "before_state": self._before_state,
        }
        temporary = self._tmp_dir / "state.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._tmp_dir / "state.json")
        _fsync_directory(self._tmp_dir)

    def _recover_interrupted_locked(self) -> None:
        directory = self.project_root / ".gms_mcp" / "transactions"
        _assert_plain_infrastructure(self.project_root, directory)
        if not directory.exists():
            return
        for recovery_dir in sorted(directory.iterdir()):
            if not recovery_dir.is_dir() or recovery_dir.is_symlink():
                raise ValidationError(f"Unsafe transaction recovery entry: {recovery_dir}")
            with _transaction_participant_lock(self.project_root, recovery_dir):
                self._recover_one_locked(recovery_dir)
            # Close the lock handle before deletion (required on Windows).
            # Completed status prevents a queued child from activating writes.
            shutil.rmtree(recovery_dir)

    def _recover_one_locked(self, recovery_dir: Path) -> None:
        state_file = recovery_dir / "state.json"
        for path in (state_file, recovery_dir / "writes.jsonl", recovery_dir / "project"):
            _assert_plain_infrastructure(self.project_root, path)
        if not state_file.exists():
            # A crash during initialization precedes activation and cannot
            # have modified project data. Do not trust an unexplained journal.
            journal = recovery_dir / "writes.jsonl"
            if journal.exists() and journal.stat().st_size:
                raise ValidationError(f"Transaction recovery metadata missing: {recovery_dir}")
            return
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Transaction recovery metadata is corrupt: {recovery_dir}") from exc
        if not isinstance(state, dict) or state.get("project_root") != str(self.project_root):
            raise ValidationError(f"Transaction recovery root mismatch: {recovery_dir}")
        if state.get("version") != 2 or state.get("status") not in {"active", "committed", "rolled_back"}:
            raise ValidationError(f"Transaction recovery metadata is unsupported: {recovery_dir}")
        if state.get("status") in {"committed", "rolled_back"}:
            return
        recovery = GameMakerProjectTransaction(self.project_root, str(state.get("tool", "recovery")))
        recovery._tmp_dir = recovery_dir
        recovery._backup_root = recovery_dir / "project"
        recovery._journal_path = recovery_dir / "writes.jsonl"
        recovery._before_state = state.get("before_state", {})
        if (
            not recovery._backup_root.is_dir()
            or not recovery._journal_path.is_file()
            or not isinstance(recovery._before_state, dict)
            or any(
                not _valid_relative_path(path) or not isinstance(value, str)
                for path, value in recovery._before_state.items()
            )
        ):
            raise ValidationError(f"Transaction recovery snapshot is invalid: {recovery_dir}")
        recovery.capture_mutation_state()
        if not recovery.rollback():
            raise TransactionValidationError(
                "Interrupted mutation requires recovery; external or unproven changes were preserved.",
                details={"transaction": recovery.to_dict()},
            )

    # ------------------------------------------------------------------
    # Differential validation
    # ------------------------------------------------------------------
    @staticmethod
    def _strict_validation() -> bool:
        """Old behaviour: any validation error blocks, including ones that predate the mutation."""
        return _env_truthy(_STRICT_VALIDATION_ENV)

    @staticmethod
    def _state_digest(state: Dict[str, str]) -> str:
        return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _baseline_cache_path(self) -> Path:
        return self.project_root / ".gms_mcp" / "cache" / _VALIDATION_BASELINE_FILE

    def _load_baseline_errors(self) -> List[str]:
        """Return the findings the project already had before this mutation started.

        The result of the previous commit is reused while the project is byte-for-byte
        unchanged; any external edit invalidates it and costs one extra validation.
        """
        digest = self._state_digest(self._before_state)
        cache_path = self._baseline_cache_path()
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and cached.get("state_digest") == digest
                and isinstance(cached.get("errors"), list)
                and all(isinstance(error, str) for error in cached["errors"])
            ):
                return list(cached["errors"])
        except (OSError, ValueError):
            pass
        return list(validate_project_after_mutation(self.project_root).errors)

    def _store_baseline_errors(self, state: Dict[str, str], errors: List[str]) -> None:
        cache_path = self._baseline_cache_path()
        try:
            _assert_plain_infrastructure(self.project_root, cache_path.parent)
            _assert_plain_infrastructure(self.project_root, cache_path)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps({"state_digest": self._state_digest(state), "errors": errors}, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, cache_path)
        except (OSError, ValidationError):
            # The cache only saves time; a failure to write it must never fail a commit.
            pass

    def _validate_after_mutation(self) -> ProjectValidationResult:
        validation = validate_project_after_mutation(self.project_root)
        if validation.success or self._baseline_errors is None:
            return validation
        introduced, preexisting = errors_introduced_by_mutation(self._baseline_errors, validation.errors)
        validation.errors = introduced
        validation.preexisting_errors = preexisting
        validation.success = not introduced
        return validation

    def _begin_locked(self) -> None:
        from .path_safety import assert_project_tree_contained

        if not self.project_root.exists() or not self.project_root.is_dir():
            raise ValidationError(f"Cannot start transaction; project root not found: {self.project_root}")
        if self._project_lock is not None:
            raise ValidationError("Transaction has already started")
        assert_project_tree_contained(self.project_root)
        for path in (
            self.project_root / ".gms_mcp" / "locks" / "project-mutation.lock",
            self.project_root / ".gms_mcp" / "transactions",
        ):
            _assert_plain_infrastructure(self.project_root, path)

        project_lock = _ProjectMutationLock(self.project_root, self.tool_name)
        self._project_lock = project_lock
        try:
            project_lock.acquire()
            # An editor may have replaced a boundary while this process waited.
            assert_project_tree_contained(self.project_root)
            _assert_plain_infrastructure(self.project_root, self.project_root / ".gms_mcp" / "transactions")
            self._recover_interrupted_locked()
            self._before_state = _snapshot_state(self.project_root)
            if not self._strict_validation():
                self._baseline_errors = self._load_baseline_errors()
            recovery_root = self.project_root / ".gms_mcp" / "transactions"
            recovery_root.mkdir(parents=True, exist_ok=True)
            self._tmp_dir = Path(tempfile.mkdtemp(prefix="tx-", dir=recovery_root))
            self._backup_root = self._tmp_dir / "project"
            self._backup_root.mkdir()
            self._journal_path = self._tmp_dir / "writes.jsonl"
            self._journal_path.write_text("", encoding="utf-8")
            self._persist_status("active")
            _fsync_directory(recovery_root)
        except Exception:
            self._cleanup_locked()
            raise

    def _activate_context(self) -> None:
        if self._journal_path is None or self._backup_root is None:
            raise RuntimeError("Cannot activate a transaction before its journal is ready")
        _ensure_transaction_audit_hook()
        context = _TransactionJournalContext(self.project_root, self._journal_path, self._backup_root)
        self._journal_context = context
        self._context_token = _ACTIVE_TRANSACTION.set(context)

    def _deactivate_context(self) -> None:
        token = self._context_token
        if token is not None and _ACTIVE_TRANSACTION.get() is self._journal_context:
            _ACTIVE_TRANSACTION.reset(token)
        self._context_token = None
        self._journal_context = None

    def begin(self) -> None:
        self._begin_locked()
        self._activate_context()

    async def begin_async(self) -> None:
        begin_task = asyncio.create_task(asyncio.to_thread(self._begin_locked))
        try:
            await asyncio.shield(begin_task)
        except asyncio.CancelledError:
            try:
                await begin_task
            except Exception:
                pass
            await asyncio.to_thread(self._cleanup_locked)
            raise
        self._activate_context()

    def _add_rollback_conflict(self, relative: str, reason: str) -> None:
        self.rollback_conflicts.append({"path": relative, "reason": reason})

    def _sync_mutated_paths(self) -> None:
        """Persist project data before making a terminal journal status durable."""
        directories = set()
        for relative in _load_journal_paths(self._journal_path):
            target = _safe_relative_path(self.project_root, relative)
            if target is None:
                raise ValidationError(f"Unsafe transaction path before commit: {relative}")
            if target.is_file() and not target.is_symlink():
                _fsync_file(target)
            for parent in target.parents:
                if parent.is_dir():
                    directories.add(parent)
                if parent == self.project_root:
                    break
        for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
            _fsync_directory(directory)

    def capture_mutation_state(self) -> None:
        """Checkpoint transaction-owned path state before validation or rollback."""
        if self._mutation_state_captured:
            return
        journal_paths = _load_journal_paths(self._journal_path)
        recorded_owned = _load_journal_owned_states(self._journal_path)
        original_states = {
            record["path"]: tuple(record["original"])
            for record in _load_journal_records(self._journal_path)
            if record["event"] != "owned"
        }
        owned_state: Dict[str, tuple[Any, ...]] = {}
        unproven: set[str] = set()
        for relative in journal_paths:
            target = _safe_relative_path(self.project_root, relative)
            if target is not None:
                current = _path_fingerprint(target)
                recorded = recorded_owned.get(relative)
                backup = _safe_backup_path(self._backup_root, relative) if self._backup_root is not None else None
                if backup is None or _path_fingerprint(backup) != original_states.get(relative):
                    owned_state[relative] = current
                    unproven.add(relative)
                    continue
                if backup is not None and _rollback_entry_matches(backup, target):
                    # A crash during recovery may have already restored this path.
                    owned_state[relative] = current
                    continue
                if recorded is not None:
                    owned_state[relative] = recorded
                else:
                    owned_state[relative] = current
                    original_exists = backup is not None and _path_exists(backup)
                    safely_structural = not original_exists and current[0] in {"directory", "absent"}
                    if not safely_structural:
                        unproven.add(relative)
        self._owned_mutation_state = owned_state
        self._unproven_owned_paths = unproven
        self._mutation_state_captured = True

    async def capture_mutation_state_async(self) -> None:
        await _run_thread_shielded(self.capture_mutation_state)

    def rollback(self) -> bool:
        # Rollback's own temporary files and restores are not transaction
        # mutations.  Suspend the audit context in this execution context.
        _ACTIVE_TRANSACTION.set(None)
        if self._rollback_attempted:
            return bool(self.rollback_complete)
        self._rollback_attempted = True
        if self._backup_root is None:
            self.rollback_complete = False
            return False

        self.rollback_conflicts = []
        journal_paths = _load_journal_paths(self._journal_path)
        current_state = _snapshot_state(self.project_root)
        for relative in sorted(_changed_project_paths(self._before_state, current_state) - journal_paths):
            self._add_rollback_conflict(relative, "change was not recorded in the transaction journal")
        for relative in sorted(self._unproven_owned_paths):
            self._add_rollback_conflict(relative, "transaction ownership was not recorded after mutation")
        if not journal_paths and self.rollback_conflicts:
            self.rollback_complete = False
            self.rolled_back = False
            self._after_state = current_state
            return False

        if journal_paths and not self._mutation_state_captured:
            for relative in sorted(journal_paths):
                self._add_rollback_conflict(relative, "transaction ownership checkpoint is missing")
            self.rollback_complete = False
            self.rolled_back = False
            self._after_state = current_state
            return False

        safe_paths: Dict[str, tuple[Path, Path]] = {}
        for relative in journal_paths:
            target = _safe_relative_path(self.project_root, relative)
            backup = _safe_backup_path(self._backup_root, relative)
            if target is None or backup is None:
                self._add_rollback_conflict(relative, "unsafe journal path")
                continue
            safe_paths[relative] = (target, backup)

        expected = self._owned_mutation_state
        owned_paths: Dict[str, tuple[Path, Path]] = {}
        for relative, paths in safe_paths.items():
            if relative in self._unproven_owned_paths:
                continue
            owned_fingerprint = expected.get(relative)
            if owned_fingerprint is None:
                self._add_rollback_conflict(relative, "path was journaled after the ownership checkpoint")
                continue
            if _path_fingerprint(paths[0]) != owned_fingerprint:
                self._add_rollback_conflict(relative, "path differs from the recorded transaction output")
                continue
            owned_paths[relative] = paths

        original_directories: List[tuple[str, Path, Path]] = []
        original_files: List[tuple[str, Path, Path]] = []
        created_paths: List[tuple[str, Path]] = []
        for relative, (target, backup) in owned_paths.items():
            if _path_exists(backup):
                if backup.is_dir() and not backup.is_symlink():
                    original_directories.append((relative, target, backup))
                else:
                    original_files.append((relative, target, backup))
            else:
                created_paths.append((relative, target))

        for relative, target, _backup in sorted(original_directories, key=lambda item: len(Path(item[0]).parts)):
            current = _path_fingerprint(target)
            if current != expected[relative]:
                self._add_rollback_conflict(relative, "path changed while rollback was being prepared")
                continue
            if current[0] == "absent":
                target.mkdir(parents=True, exist_ok=True)
            elif current[0] != "directory":
                self._add_rollback_conflict(relative, "cannot replace a non-directory with the original directory")
                continue
            try:
                shutil.copystat(_backup, target, follow_symlinks=False)
            except OSError as exc:
                self._add_rollback_conflict(relative, f"directory metadata restore failed: {exc}")

        for relative, target, backup in original_files:
            current = _path_fingerprint(target)
            if current != expected[relative]:
                self._add_rollback_conflict(relative, "path changed while rollback was being prepared")
                continue
            if current[0] == "directory":
                self._add_rollback_conflict(relative, "cannot replace a directory with the original file")
                continue
            try:
                if not _restore_file_atomically(backup, target, expected[relative]):
                    self._add_rollback_conflict(relative, "path changed before its original content could be restored")
            except OSError as exc:
                self._add_rollback_conflict(relative, f"restore failed: {exc}")

        created_directories: List[tuple[str, Path]] = []
        for relative, target in sorted(created_paths, key=lambda item: len(Path(item[0]).parts), reverse=True):
            current = _path_fingerprint(target)
            if current[0] == "absent":
                continue
            if current[0] == "directory":
                created_directories.append((relative, target))
                continue
            if current != expected[relative]:
                self._add_rollback_conflict(relative, "created path changed before it could be removed")
                continue
            try:
                target.unlink()
            except OSError as exc:
                self._add_rollback_conflict(relative, f"created path could not be removed: {exc}")

        for relative, target in sorted(
            created_directories,
            key=lambda item: len(Path(item[0]).parts),
            reverse=True,
        ):
            if not target.exists():
                continue
            try:
                target.rmdir()
            except OSError:
                self._add_rollback_conflict(
                    relative,
                    "created directory is not empty; preserving possible external content",
                )

        conflicted_paths = {conflict["path"] for conflict in self.rollback_conflicts}
        for relative, (target, backup) in owned_paths.items():
            if relative in conflicted_paths:
                continue
            try:
                restored = _rollback_entry_matches(backup, target)
            except OSError:
                restored = False
            if not restored:
                self._add_rollback_conflict(relative, "post-rollback verification did not match original content")

        self.rollback_complete = not self.rollback_conflicts
        self._after_state = _snapshot_state(self.project_root)
        if self.rollback_complete:
            try:
                self._sync_mutated_paths()
                self._persist_status("rolled_back")
            except (OSError, ValidationError) as exc:
                self._add_rollback_conflict("<recovery-state>", f"rollback durability checkpoint failed: {exc}")
                self.rollback_complete = False
        self.rolled_back = self.rollback_complete
        return self.rollback_complete

    async def rollback_async(self) -> bool:
        return await _run_thread_shielded(self.rollback)

    def commit(
        self,
        *,
        verify_compile: bool = False,
        before_commit: Callable[[Dict[str, Any]], Dict[str, Any] | None] | None = None,
    ) -> Dict[str, Any]:
        if not self._mutation_state_captured:
            self.capture_mutation_state()
        self.validation = self._validate_after_mutation()
        if not self.validation.success:
            rollback_complete = self.rollback()
            raise TransactionValidationError(
                (
                    "Project validation failed after mutation; changes were rolled back. "
                    "The listed errors were introduced by this operation: fix the inputs and retry."
                    if rollback_complete
                    else "Project validation failed and safe rollback could not restore every journaled path."
                ),
                details={"validation": self.validation.to_dict(), "transaction": self.to_dict()},
            )

        if verify_compile:
            try:
                self.compile_verification = compile_verify_project(self.project_root)
            finally:
                # Compile helpers can themselves write project files. Include
                # their exact owned states even when verification fails.
                self._mutation_state_captured = False
                self.capture_mutation_state()
            if not self.compile_verification.get("ok"):
                rollback_complete = self.rollback()
                raise TransactionValidationError(
                    (
                        "Compile verification failed after mutation; changes were rolled back."
                        if rollback_complete
                        else "Compile verification failed and safe rollback could not restore every journaled path."
                    ),
                    details={
                        "validation": self.validation.to_dict(),
                        "compile_verification": self.compile_verification,
                        "transaction": self.to_dict(),
                    },
                )

        self._after_state = _snapshot_state(self.project_root)
        try:
            if before_commit is not None:
                try:
                    self.bookkeeping = before_commit(self.to_dict()) or {}
                finally:
                    # A partially written marker belongs to the same atomic
                    # mutation as the asset writes preceding it.
                    self._mutation_state_captured = False
                    self.capture_mutation_state()
                    self._after_state = _snapshot_state(self.project_root)
            self._sync_mutated_paths()
            self._persist_status("committed")
        except BaseException:
            self.rollback()
            raise
        self.committed = True
        if self._baseline_errors is not None:
            self._store_baseline_errors(
                self._after_state,
                [*self.validation.preexisting_errors, *self.validation.errors],
            )
        return self.to_dict()

    async def commit_async(
        self,
        *,
        verify_compile: bool = False,
        before_commit: Callable[[Dict[str, Any]], Dict[str, Any] | None] | None = None,
    ) -> Dict[str, Any]:
        return await _run_thread_shielded(
            lambda: self.commit(verify_compile=verify_compile, before_commit=before_commit)
        )

    def _cleanup_locked(self) -> None:
        if self._tmp_dir and self._tmp_dir.exists() and (self.committed or self.rolled_back):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        project_lock = self._project_lock
        self._project_lock = None
        if project_lock is not None:
            project_lock.release()

    def cleanup(self) -> None:
        self._deactivate_context()
        self._cleanup_locked()

    async def cleanup_async(self) -> None:
        self._deactivate_context()
        await _run_thread_shielded(self._cleanup_locked)

    def to_dict(self) -> Dict[str, Any]:
        after_state = self._after_state or _snapshot_state(self.project_root)
        return {
            **self.bookkeeping,
            "enabled": True,
            "tool": self.tool_name,
            "project_root": str(self.project_root),
            "committed": self.committed,
            "recovery_path": str(self._tmp_dir) if self._tmp_dir and not (self.committed or self.rolled_back) else None,
            "rolled_back": self.rolled_back,
            "rollback_complete": self.rollback_complete,
            "rollback_conflicts": self.rollback_conflicts,
            "ownership_checkpoint_captured": self._mutation_state_captured,
            "owned_path_count": len(self._owned_mutation_state),
            "changes": _summarize_changes(self._before_state, after_state),
            "validation": self.validation.to_dict() if self.validation else None,
            "compile_verification": self.compile_verification,
        }
