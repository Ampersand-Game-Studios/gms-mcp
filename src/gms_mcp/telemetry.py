from __future__ import annotations

import contextvars
import datetime as _dt
import gzip
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .ci_detection import is_ci_environment
from .update_notifier import get_current_version

SCHEMA_VERSION = 1
CONFIG_SCHEMA_VERSION = 1
PACKAGE_HOME_DIR = ".gms-mcp"
TELEMETRY_SUBDIR = "telemetry"
SPOOL_SUBDIR = "spool"
DEFAULT_ENDPOINT = "https://gms-mcp-telemetry.ampersandgamestudios.com/v1/events"
MAX_BATCH_EVENTS = 50
MAX_BATCH_BYTES = 128 * 1024
MAX_SPOOL_EVENTS = 1000
MAX_SPOOL_BYTES = 1024 * 1024
UPLOAD_TIMEOUT_SECONDS = 5
LOCK_STALE_SECONDS = 15 * 60
QUEUE_LOCK_TIMEOUT_SECONDS = 0.25
_LOCK_POLL_SECONDS = 0.01
BACKGROUND_FLUSH_COOLDOWN_SECONDS = 60
PROMPT_TEXT = (
    "Help improve gms-mcp by sending limited usage telemetry to "
    "gms-mcp-telemetry.ampersandgamestudios.com? We send tool names, success/failure, durations, "
    "version, OS family, and interaction mode. We do not send file paths, command arguments, "
    "stdout/stderr or project names. Events include a random per-process session ID; "
    "a persistent install ID is separately opt-in. The receiving service sees network metadata. Telemetry is off by default and can "
    "be changed any time with 'gms telemetry enable|disable'. [y/N] "
)
_OVERRIDE_VALUES = {"inherit", "on", "off"}
_STATE_VALUES = {"enabled", "disabled"}
_TEST_ENV_KEYS = ("PYTEST_CURRENT_TEST", "GMS_TEST_SUITE")
SUPPRESS_CLI_TELEMETRY_ENV_VAR = "GMS_MCP_TELEMETRY_SUPPRESS_CLI"
_TOOL_EXECUTION_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "gms_mcp_telemetry_tool_execution_context",
    default=None,
)
_SESSION_ID = uuid.uuid4().hex
_LAST_BACKGROUND_FLUSH_AT = 0.0
_STATE_LOCK = threading.Lock()
_UPLOAD_LOCK = threading.Lock()
_PENDING_FILENAME = re.compile(r"\.gms-mcp-telemetry-pending-[a-f0-9]{32}-[A-Za-z0-9_-]+\.json")

# Closed event schema. Mirrors services/telemetry/src/event-schema.json, which the
# ingest worker enforces; test_telemetry_schema_parity keeps the two identical.
EVENT_FIELD_RULES: dict[str, dict[str, Any]] = {
    "schema_version": {"type": "integer", "required": True},
    "event_id": {"type": "string", "required": True, "maxLength": 64},
    "session_id": {"type": "string", "required": True, "maxLength": 64},
    "timestamp": {"type": "string", "required": True, "maxLength": 32},
    "surface": {"type": "string", "required": True, "maxLength": 16},
    "event_type": {"type": "string", "required": True, "maxLength": 32},
    "action": {"type": "string", "required": True, "maxLength": 64},
    "tool_name": {"type": "string", "required": True, "maxLength": 64},
    "tool_family": {"type": "string", "required": True, "maxLength": 32},
    "result": {"type": "string", "required": True, "maxLength": 16},
    "error_family": {"type": "string", "required": False, "maxLength": 32},
    "duration_ms": {"type": "integer", "required": False},
    "duration_bucket": {"type": "string", "required": False, "maxLength": 16},
    "execution_mode": {"type": "string", "required": False, "maxLength": 32},
    "gms_mcp_version": {"type": "string", "required": True, "maxLength": 32},
    "os_family": {"type": "string", "required": True, "maxLength": 16},
    "python_version": {"type": "string", "required": True, "maxLength": 16},
    "interactive": {"type": "boolean", "required": True},
    "ci": {"type": "boolean", "required": True},
    "test_env": {"type": "boolean", "required": True},
    "install_hash": {"type": "string", "required": False, "maxLength": 128},
}
EVENT_TOKEN_PATTERN = r"^[A-Za-z0-9_.+:-]+$"
EVENT_SURFACES = {
    "cli.command": "cli",
    "telemetry.consent_changed": "cli",
    "mcp.tool": "mcp",
    "mcp.server_start": "mcp",
    "init.run": "init",
    "init.codex_check": "init",
}
EVENT_RESULTS = ("ok", "error", "cancelled")
EVENT_ERROR_FAMILIES = (
    "timeout",
    "cancelled",
    "missing_dependency",
    "permission",
    "not_found",
    "network",
    "validation",
    "system_exit",
    "runtime",
    "unexpected",
    "project_access",
)
EVENT_DURATION_BUCKETS = ("lt_100", "100_499", "500_999", "1000_4999", "5000_29999", "ge_30000")
EVENT_MAX_DURATION_MS = 7 * 24 * 60 * 60 * 1000
EVENT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
EVENT_MAX_CLOCK_SKEW_MS = 5 * 60 * 1000
EVENT_VERSION_PATTERN = (
    r"^\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?(?:\+[a-z0-9]+(?:[._-][a-z0-9]+)*)?$"
)
EVENT_PYTHON_VERSION_PATTERN = r"^\d+\.\d+$"
EVENT_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$"
_TOKEN_RE = re.compile(EVENT_TOKEN_PATTERN, re.ASCII)
_VERSION_RE = re.compile(EVENT_VERSION_PATTERN, re.ASCII | re.IGNORECASE)
_PYTHON_VERSION_RE = re.compile(EVENT_PYTHON_VERSION_PATTERN, re.ASCII)
_TIMESTAMP_RE = re.compile(EVENT_TIMESTAMP_PATTERN, re.ASCII)
_HEX32_RE = re.compile(r"[a-f0-9]{32}")
_HEX64_RE = re.compile(r"[a-f0-9]{64}")
# Client errors the service will never accept on retry; the batch is discarded.
_RETRYABLE_HTTP_STATUSES = {408, 429}


@dataclass(frozen=True)
class TelemetryConfig:
    consent: str | None = None
    include_install_hash: bool = False
    install_hash: str | None = None


@dataclass(frozen=True)
class TelemetryState:
    enabled: bool
    decision_made: bool
    source: str
    endpoint: str
    interactive: bool
    ci: bool
    test_env: bool
    include_install_hash: bool
    install_hash: str | None


@dataclass(frozen=True)
class FlushResult:
    ok: bool
    sent_events: int
    sent_batches: int
    remaining_events: int
    message: str


def telemetry_root() -> Path:
    package_dir = Path.home() / PACKAGE_HOME_DIR
    root = package_dir / TELEMETRY_SUBDIR
    for directory in (package_dir, root):
        if directory.is_symlink():
            raise ValueError("Telemetry directories must not be symlinks.")
        newly_created = not directory.exists()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if newly_created:
            _fsync_directory(directory.parent)
    return root


def telemetry_config_path() -> Path:
    return Path.home() / PACKAGE_HOME_DIR / "telemetry.json"


def telemetry_spool_dir() -> Path:
    path = telemetry_root() / SPOOL_SUBDIR
    if path.is_symlink():
        raise ValueError("Telemetry spool must not be a symlink.")
    newly_created = not path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if newly_created:
        _fsync_directory(path.parent)
    return path


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return  # Python cannot open directory handles for FlushFileBuffers on Windows.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _recover_pending_files(root: Path) -> None:
    """Under the state lock, reclaim only this writer's interrupted atomic files."""
    for directory in (root.parent, root / SPOOL_SUBDIR):
        if directory.is_symlink():
            raise ValueError("Telemetry directories must not be symlinks.")
        if not directory.is_dir():
            continue
        removed = False
        for path in directory.iterdir():
            if _PENDING_FILENAME.fullmatch(path.name) and (path.is_symlink() or path.is_file()):
                path.unlink(missing_ok=True)
                removed = True
        if removed:
            _fsync_directory(directory)


def _lock_file(handle: Any, *, deadline: float | None) -> None:
    """Take an exclusive byte-range/flock lock, polling until ``deadline`` when given."""
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        if deadline is None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            return
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Telemetry lock is busy.") from None
                time.sleep(_LOCK_POLL_SECONDS)
    import fcntl

    if deadline is None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError("Telemetry lock is busy.") from None
            time.sleep(_LOCK_POLL_SECONDS)


def _unlock_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _file_lock(name: str, thread_lock: threading.Lock, *, timeout: float | None = None) -> Iterator[Path]:
    deadline = None if timeout is None else time.monotonic() + timeout
    if not thread_lock.acquire(timeout=-1 if timeout is None else timeout):
        raise TimeoutError("Telemetry lock is busy.")
    try:
        path = telemetry_root() / name
        if path.is_symlink():
            raise ValueError("Telemetry lock must not be a symlink.")
        with path.open("a+b") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            _lock_file(handle, deadline=deadline)
            try:
                yield path
            finally:
                _unlock_file(handle)
    finally:
        thread_lock.release()


@contextmanager
def _state_guard(*, timeout: float | None = None) -> Iterator[None]:
    """Serialize consent changes, queue writes and spool reads across processes.

    Never held across network I/O, so short ``timeout`` waits stay short.
    """
    with _file_lock("state.lock", _STATE_LOCK, timeout=timeout) as path:
        _recover_pending_files(path.parent)
        yield


@contextmanager
def _upload_guard() -> Iterator[None]:
    """Held for the duration of one upload; consent withdrawal waits for it.

    Lock order is always upload -> state, and the state lock is never held while
    waiting for this one.
    """
    with _file_lock("upload.lock", _UPLOAD_LOCK):
        yield


def telemetry_lock_path() -> Path:
    return telemetry_root() / "flush.lock"


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_override(value: str | None) -> str:
    normalized = (value or "inherit").strip().lower()
    if normalized not in _OVERRIDE_VALUES:
        return "inherit"
    return normalized


def extract_cli_override(argv: Iterable[str]) -> str:
    items = list(argv)
    for index, token in enumerate(items):
        if token.startswith("--telemetry="):
            return _normalize_override(token.partition("=")[2])
        if token == "--telemetry" and index + 1 < len(items):
            return _normalize_override(items[index + 1])
    return "inherit"


def _interactive_stdin() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


def _ci_enabled() -> bool:
    return is_ci_environment()


def _test_env_enabled() -> bool:
    return any(bool(os.environ.get(key)) for key in _TEST_ENV_KEYS)


def cli_telemetry_suppressed() -> bool:
    value = os.environ.get(SUPPRESS_CLI_TELEMETRY_ENV_VAR, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _safe_json_load(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_BATCH_BYTES:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def load_config() -> TelemetryConfig:
    path = telemetry_config_path()
    if not path.exists():
        return TelemetryConfig()

    payload = _safe_json_load(path)
    consent = payload.get("consent")
    if consent not in _STATE_VALUES:
        consent = None

    include_install_hash = bool(payload.get("include_install_hash"))
    install_hash = payload.get("install_hash")
    if not isinstance(install_hash, str) or not install_hash:
        install_hash = None

    if not include_install_hash:
        install_hash = None

    return TelemetryConfig(
        consent=consent,
        include_install_hash=include_install_hash,
        install_hash=install_hash,
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    telemetry_root()
    if path.is_symlink():
        raise ValueError("Telemetry files must not be symlinks.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".gms-mcp-telemetry-pending-{uuid.uuid4().hex}-",
            suffix=".json",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
        _fsync_directory(path.parent)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _generate_install_hash() -> str:
    seed = uuid.uuid4().hex.encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def save_config(*, consent: str | None, include_install_hash: bool, install_hash: str | None) -> TelemetryConfig:
    payload = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "consent": consent,
        "include_install_hash": bool(include_install_hash),
        "install_hash": install_hash if include_install_hash else None,
        "updated_at": _utc_now_iso(),
    }
    _write_json_atomic(telemetry_config_path(), payload)
    return TelemetryConfig(
        consent=consent,
        include_install_hash=bool(include_install_hash),
        install_hash=install_hash if include_install_hash else None,
    )


def enable_telemetry(*, include_install_hash: bool = False) -> TelemetryConfig:
    install_hash = _generate_install_hash() if include_install_hash else None
    with _upload_guard(), _state_guard():
        config = save_config(consent="enabled", include_install_hash=include_install_hash, install_hash=install_hash)
        spool = telemetry_root() / SPOOL_SUBDIR
        if not include_install_hash and spool.exists():
            prune_spool()
            for path in spool.glob("*.ndjson"):
                record = _safe_json_load(path)
                if "install_hash" in record:
                    record.pop("install_hash")
                    _write_json_atomic(path, record)
        return config


def disable_telemetry() -> TelemetryConfig:
    with _upload_guard(), _state_guard():
        config = save_config(consent="disabled", include_install_hash=False, install_hash=None)
        clear_spool()
        return config


def resolve_state(cli_override: str | None = None) -> TelemetryState:
    interactive = _interactive_stdin()
    ci = _ci_enabled()
    test_env = _test_env_enabled()
    config = load_config()
    env_override = _normalize_override(os.environ.get("GMS_MCP_TELEMETRY"))
    cli_value = _normalize_override(cli_override)

    source = "default"
    enabled = False

    if ci or test_env:
        source = "system"
        enabled = False
    elif cli_value != "inherit":
        source = "cli"
        enabled = cli_value == "on"
    elif env_override != "inherit":
        source = "env"
        enabled = env_override == "on"
    elif config.consent == "enabled":
        source = "config"
        enabled = True
    elif config.consent == "disabled":
        source = "config"
        enabled = False

    endpoint = os.environ.get("GMS_MCP_TELEMETRY_ENDPOINT", "").strip() or DEFAULT_ENDPOINT
    return TelemetryState(
        enabled=enabled,
        decision_made=config.consent in _STATE_VALUES,
        source=source,
        endpoint=endpoint,
        interactive=interactive,
        ci=ci,
        test_env=test_env,
        include_install_hash=bool(config.include_install_hash and config.install_hash),
        install_hash=config.install_hash if config.include_install_hash else None,
    )


def should_prompt_for_consent(*, cli_override: str | None = None, allow_prompt: bool) -> bool:
    state = resolve_state(cli_override)
    if not allow_prompt:
        return False
    if state.ci or state.test_env or not state.interactive:
        return False
    if state.decision_made:
        return False
    if state.source in {"cli", "env"}:
        return False
    return True


def prompt_for_consent() -> bool:
    while True:
        try:
            choice = input(PROMPT_TEXT).strip().lower()
        except EOFError:
            # No answer is possible (stdin closed); leave the decision unmade.
            print()
            return False
        if choice in {"", "n", "no"}:
            disable_telemetry()
            return False
        if choice in {"y", "yes"}:
            enable_telemetry(include_install_hash=False)
            return True
        print("Please enter Y or N.")


def _duration_bucket(duration_ms: int | None) -> str | None:
    if duration_ms is None:
        return None
    if duration_ms < 100:
        return "lt_100"
    if duration_ms < 500:
        return "100_499"
    if duration_ms < 1000:
        return "500_999"
    if duration_ms < 5000:
        return "1000_4999"
    if duration_ms < 30000:
        return "5000_29999"
    return "ge_30000"


def classify_error_family(error: Any = None, *, timed_out: bool = False) -> str | None:
    if timed_out:
        return "timeout"
    if error is None:
        return None

    if isinstance(error, BaseException):
        name = type(error).__name__.lower()
        message = str(error).lower()
    else:
        name = ""
        message = str(error).lower()

    if "keyboardinterrupt" in name:
        return "cancelled"
    if "module" in name and "notfound" in name:
        return "missing_dependency"
    if "permission" in name or "permission" in message:
        return "permission"
    if "filenotfound" in name or "not found" in message or "no such file" in message:
        return "not_found"
    if "timeout" in name or "timeout" in message or "timed out" in message:
        return "timeout"
    if "url" in name or "http" in message or "connection" in message or "network" in message:
        return "network"
    if "valueerror" in name or "argparse" in message or "invalid" in message:
        return "validation"
    if "gmserror" in name:
        return "validation"
    if "systemexit" in name:
        return "system_exit"
    if name:
        return "runtime"
    return "unexpected"


def _os_family() -> str:
    system = platform.system().lower()
    if system.startswith("darwin"):
        return "macos"
    if system.startswith("windows"):
        return "windows"
    if system.startswith("linux"):
        return "linux"
    return system or "unknown"


def _python_minor_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def queue_event(
    *,
    state: TelemetryState | None,
    surface: str,
    event_type: str,
    action: str,
    tool_name: str,
    tool_family: str,
    result: str,
    error_family: str | None = None,
    duration_ms: int | None = None,
    execution_mode: str | None = None,
    force: bool = False,
) -> bool:
    try:
        active_state = state or resolve_state()
        if not active_state.enabled or active_state.ci or active_state.test_env:
            return False

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "session_id": _SESSION_ID,
            "timestamp": _utc_now_iso(),
            "surface": surface,
            "event_type": event_type,
            "action": action,
            "tool_name": tool_name,
            "tool_family": tool_family,
            "result": result,
            "error_family": error_family,
            "duration_ms": duration_ms,
            "duration_bucket": _duration_bucket(duration_ms),
            "execution_mode": execution_mode,
            "gms_mcp_version": get_current_version(),
            "os_family": _os_family(),
            "python_version": _python_minor_version(),
            "interactive": active_state.interactive,
            "ci": active_state.ci,
            "test_env": active_state.test_env,
        }
        record = {key: value for key, value in payload.items() if value is not None}
        # Called from the MCP event loop after tool calls: never wait long for the lock.
        with _state_guard(timeout=QUEUE_LOCK_TIMEOUT_SECONDS):
            config = load_config()
            if config.consent == "disabled":
                return False
            if config.include_install_hash and config.install_hash:
                record["install_hash"] = config.install_hash
            if not _valid_spool_event(record):
                return False
            path = telemetry_spool_dir() / f"{int(time.time() * 1000)}-{os.getpid()}-{uuid.uuid4().hex}.ndjson"
            _write_json_atomic(path, record)
            prune_spool()
            return path.exists()
    except Exception:
        return False


def emit_consent_changed(action: str, *, cli_override: str | None = None) -> None:
    if action != "enable":
        return
    # A per-run "off" (CLI flag or GMS_MCP_TELEMETRY) still wins over the saved consent.
    if not resolve_state(cli_override).enabled:
        return
    config = load_config()
    state = TelemetryState(
        enabled=action == "enable",
        decision_made=True,
        source="config",
        endpoint=os.environ.get("GMS_MCP_TELEMETRY_ENDPOINT", "").strip() or DEFAULT_ENDPOINT,
        interactive=_interactive_stdin(),
        ci=_ci_enabled(),
        test_env=_test_env_enabled(),
        include_install_hash=bool(config.include_install_hash and config.install_hash),
        install_hash=config.install_hash if config.include_install_hash else None,
    )
    queue_event(
        state=state,
        surface="cli",
        event_type="telemetry.consent_changed",
        action=action,
        tool_name="telemetry",
        tool_family="telemetry",
        result="ok",
        execution_mode="inline",
        force=True,
    )
    maybe_start_background_flush(force=True, cli_override=cli_override)


def count_spool_events() -> int:
    prune_spool()
    return sum(1 for path in telemetry_spool_dir().glob("*.ndjson") if path.is_file())


def _valid_spool_event(event: Any, *, now: float | None = None) -> bool:
    """Apply the ingest service's closed schema so the service never rejects a stored event."""
    if not isinstance(event, dict) or set(event) - set(EVENT_FIELD_RULES):
        return False
    for key, rule in EVENT_FIELD_RULES.items():
        value = event.get(key)
        if value is None:
            if rule["required"] or key in event:
                return False
            continue
        if rule["type"] == "string":
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > rule["maxLength"]
                or (key != "timestamp" and not _TOKEN_RE.fullmatch(value))
            ):
                return False
        elif rule["type"] == "integer":
            if type(value) is not int or value < 0:
                return False
        elif type(value) is not bool:
            return False
    if event["schema_version"] != SCHEMA_VERSION or event["ci"] or event["test_env"]:
        return False
    if not _HEX32_RE.fullmatch(event["event_id"]) or not _HEX32_RE.fullmatch(event["session_id"]):
        return False
    if "install_hash" in event and not _HEX64_RE.fullmatch(event["install_hash"]):
        return False
    if event["result"] not in EVENT_RESULTS or EVENT_SURFACES.get(event["event_type"]) != event["surface"]:
        return False
    if "error_family" in event and event["error_family"] not in EVENT_ERROR_FAMILIES:
        return False
    if "duration_bucket" in event and event["duration_bucket"] not in EVENT_DURATION_BUCKETS:
        return False
    if event.get("duration_ms", 0) > EVENT_MAX_DURATION_MS:
        return False
    if not _VERSION_RE.fullmatch(event["gms_mcp_version"]) or not _PYTHON_VERSION_RE.fullmatch(event["python_version"]):
        return False
    return _valid_event_timestamp(event["timestamp"], now=now)


def _valid_event_timestamp(value: str, *, now: float | None = None) -> bool:
    if not _TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    timestamp_ms = parsed.timestamp() * 1000
    now_ms = (time.time() if now is None else now) * 1000
    return now_ms - EVENT_MAX_AGE_MS <= timestamp_ms <= now_ms + EVENT_MAX_CLOCK_SKEW_MS


def prune_spool() -> int:
    """Bound retention and disk usage; delete invalid records without following links."""
    records = []
    removed = 0
    now = time.time()
    for path in telemetry_spool_dir().glob("*.ndjson"):
        try:
            info = path.lstat()
            invalid = path.is_symlink() or not path.is_file() or info.st_size > MAX_BATCH_BYTES
            if not invalid:
                invalid = not _valid_spool_event(_safe_json_load(path), now=now)
            if invalid:
                path.unlink()
                removed += 1
            else:
                records.append((info.st_mtime, path, info.st_size))
        except (OSError, ValueError):
            continue
    total = sum(item[2] for item in records)
    count = len(records)
    for _, path, size in sorted(records):
        if count <= MAX_SPOOL_EVENTS and total <= MAX_SPOOL_BYTES:
            break
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
        count -= 1
        total -= size
    if removed:
        _fsync_directory(telemetry_spool_dir())
    return removed


def clear_spool() -> int:
    removed = 0
    for path in telemetry_spool_dir().glob("*.ndjson"):
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            continue
    if removed:
        _fsync_directory(telemetry_spool_dir())
    return removed


def _acquire_lock() -> Path | None:
    lock_path = telemetry_lock_path()
    if lock_path.exists():
        try:
            age = time.time() - lock_path.stat().st_mtime
        except FileNotFoundError:
            age = 0
        if age > LOCK_STALE_SECONDS:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
        else:
            return None

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")
    return lock_path


def _release_lock(lock_path: Path | None) -> None:
    if lock_path is None:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _load_spool_records(limit_events: int = MAX_BATCH_EVENTS) -> tuple[list[Path], list[dict[str, Any]]]:
    prune_spool()
    paths: list[Path] = []
    events: list[dict[str, Any]] = []
    total_bytes = 128  # Envelope, timestamp, punctuation; larger than their encoded size.

    for path in sorted(telemetry_spool_dir().glob("*.ndjson")):
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not _valid_spool_event(event):
            continue
        encoded_len = len(json.dumps(event, separators=(",", ":")).encode("utf-8")) + 1
        if len(paths) >= limit_events or total_bytes + encoded_len > MAX_BATCH_BYTES:
            break
        paths.append(path)
        events.append(event)
        total_bytes += encoded_len

    return paths, events


class _NoUploadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise urllib.error.HTTPError(req.full_url, code, "Telemetry redirects are prohibited.", headers, fp)


def _post_batch(endpoint: str, events: list[dict[str, Any]]) -> None:
    destination = urllib.parse.urlsplit(endpoint)
    if destination.scheme != "https" or not destination.hostname or destination.username or destination.password:
        raise ValueError("Telemetry endpoints require HTTPS without embedded credentials.")
    body = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "sent_at": _utc_now_iso(),
            "events": events,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    if len(events) > MAX_BATCH_EVENTS or len(body) > MAX_BATCH_BYTES:
        raise ValueError("Telemetry batch exceeds limits.")
    compressed = gzip.compress(body)
    request = urllib.request.Request(
        endpoint,
        data=compressed,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "User-Agent": f"gms-mcp/{get_current_version()}",
        },
    )
    with urllib.request.build_opener(_NoUploadRedirect()).open(request, timeout=UPLOAD_TIMEOUT_SECONDS) as response:
        if response.status < 200 or response.status >= 300:
            raise urllib.error.HTTPError(endpoint, response.status, "upload failed", response.headers, None)


def _delete_spool_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
    if paths:
        _fsync_directory(paths[0].parent)


def flush_spool(*, force: bool = False) -> FlushResult:
    state = resolve_state()
    if state.ci or state.test_env:
        return FlushResult(False, 0, 0, count_spool_events(), "Telemetry is disabled in CI/test environments.")
    if not state.enabled:
        return FlushResult(False, 0, 0, count_spool_events(), "Telemetry is disabled.")

    lock_path = _acquire_lock()
    if lock_path is None:
        return FlushResult(False, 0, 0, count_spool_events(), "Telemetry flush is already running.")

    sent_events = 0
    sent_batches = 0
    rejected_events = 0
    try:
        while True:
            # The upload lock (not the state lock) spans the network call, so queue
            # writes never wait on the network while consent withdrawal still does.
            with _upload_guard():
                with _state_guard():
                    config = load_config()
                    if config.consent == "disabled":
                        return FlushResult(
                            False, sent_events, sent_batches, count_spool_events(), "Telemetry consent withdrawn."
                        )
                    paths, events = _load_spool_records()
                if not events:
                    break
                for event in events:
                    if not config.include_install_hash or event.get("install_hash") != config.install_hash:
                        event.pop("install_hash", None)
                try:
                    _post_batch(state.endpoint, events)
                except urllib.error.HTTPError as exc:
                    if not 400 <= exc.code < 500 or exc.code in _RETRYABLE_HTTP_STATUSES:
                        raise
                    # The service rejected this batch permanently; keeping it would
                    # block every later event until the spool ages out.
                    with _state_guard():
                        _delete_spool_paths(paths)
                    rejected_events += len(events)
                    continue
                with _state_guard():
                    _delete_spool_paths(paths)
            sent_events += len(events)
            sent_batches += 1
        remaining = count_spool_events()
        message = "Telemetry flushed."
        if rejected_events:
            message = f"Telemetry flushed; discarded {rejected_events} event(s) rejected by the service."
        return FlushResult(True, sent_events, sent_batches, remaining, message)
    except Exception:
        return FlushResult(False, sent_events, sent_batches, count_spool_events(), "Telemetry flush failed.")
    finally:
        _release_lock(lock_path)


def maybe_start_background_flush(*, force: bool = False, cli_override: str | None = None) -> bool:
    global _LAST_BACKGROUND_FLUSH_AT

    state = resolve_state(cli_override)
    if state.ci or state.test_env:
        return False
    if not state.enabled:
        return False
    if count_spool_events() == 0:
        return False
    now = time.monotonic()
    if not force and (now - _LAST_BACKGROUND_FLUSH_AT) < BACKGROUND_FLUSH_COOLDOWN_SECONDS:
        return False

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["PYTHONSAFEPATH"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    if state.source in {"cli", "env"}:
        # Carry this run's explicit override into the detached flush process.
        env["GMS_MCP_TELEMETRY"] = "on"
    try:
        subprocess.Popen(
            [sys.executable, "-P", "-m", "gms_mcp.telemetry_runtime", "flush-spool"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=env,
        )
        _LAST_BACKGROUND_FLUSH_AT = now
        return True
    except Exception:
        return False


def reset_tool_execution_context() -> None:
    _TOOL_EXECUTION_CONTEXT.set(None)


def note_tool_execution(
    *, tool_name: str, execution_mode: str | None, ok: bool, timed_out: bool = False, error: Any = None
) -> None:
    _TOOL_EXECUTION_CONTEXT.set(
        {
            "tool_name": tool_name,
            "execution_mode": execution_mode,
            "result": "ok"
            if ok
            else ("cancelled" if classify_error_family(error, timed_out=timed_out) == "cancelled" else "error"),
            "error_family": classify_error_family(error, timed_out=timed_out),
        }
    )


def get_tool_execution_context() -> dict[str, Any] | None:
    return _TOOL_EXECUTION_CONTEXT.get()
