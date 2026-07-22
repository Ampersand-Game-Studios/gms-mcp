from __future__ import annotations

import contextvars
import datetime as _dt
import gzip
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .update_notifier import get_current_version

SCHEMA_VERSION = 1
CONFIG_SCHEMA_VERSION = 1
PACKAGE_HOME_DIR = ".gms-mcp"
TELEMETRY_SUBDIR = "telemetry"
SPOOL_SUBDIR = "spool"
DEFAULT_ENDPOINT = "https://gms-mcp-telemetry.ampersandgamestudios.com/v1/events"
MAX_BATCH_EVENTS = 50
MAX_BATCH_BYTES = 128 * 1024
UPLOAD_TIMEOUT_SECONDS = 5
LOCK_STALE_SECONDS = 15 * 60
BACKGROUND_FLUSH_COOLDOWN_SECONDS = 60
PROMPT_TEXT = (
    "Help improve gms-mcp by sending anonymous usage telemetry to "
    "gms-mcp-telemetry.ampersandgamestudios.com? We send tool names, success/failure, durations, "
    "version, OS family, and interaction mode. We do not send file paths, command arguments, "
    "stdout/stderr, project names, or personal identifiers. Telemetry is off by default and can "
    "be changed any time with 'gms telemetry enable|disable'. [y/N] "
)
_OVERRIDE_VALUES = {"inherit", "on", "off"}
_STATE_VALUES = {"enabled", "disabled"}
_CI_ENV_KEYS = ("CI", "GITHUB_ACTIONS")
_TEST_ENV_KEYS = ("PYTEST_CURRENT_TEST", "GMS_TEST_SUITE")
SUPPRESS_CLI_TELEMETRY_ENV_VAR = "GMS_MCP_TELEMETRY_SUPPRESS_CLI"
_TOOL_EXECUTION_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "gms_mcp_telemetry_tool_execution_context",
    default=None,
)
_SESSION_ID = uuid.uuid4().hex
_LAST_BACKGROUND_FLUSH_AT = 0.0


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
    root = Path.home() / PACKAGE_HOME_DIR / TELEMETRY_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def telemetry_config_path() -> Path:
    return Path.home() / PACKAGE_HOME_DIR / "telemetry.json"


def telemetry_spool_dir() -> Path:
    path = telemetry_root() / SPOOL_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    return any(bool(os.environ.get(key)) for key in _CI_ENV_KEYS)


def _test_env_enabled() -> bool:
    return any(bool(os.environ.get(key)) for key in _TEST_ENV_KEYS)


def cli_telemetry_suppressed() -> bool:
    value = os.environ.get(SUPPRESS_CLI_TELEMETRY_ENV_VAR, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _safe_json_load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


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
    return save_config(
        consent="enabled",
        include_install_hash=include_install_hash,
        install_hash=install_hash,
    )


def disable_telemetry() -> TelemetryConfig:
    return save_config(consent="disabled", include_install_hash=False, install_hash=None)


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
        choice = input(PROMPT_TEXT).strip().lower()
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
        if not force and not active_state.enabled:
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
        if active_state.include_install_hash and active_state.install_hash:
            payload["install_hash"] = active_state.install_hash

        record = {key: value for key, value in payload.items() if value is not None}
        path = telemetry_spool_dir() / f"{int(time.time() * 1000)}-{os.getpid()}-{uuid.uuid4().hex}.ndjson"
        path.write_text(json.dumps(record, separators=(",", ":")) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def emit_consent_changed(action: str) -> None:
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
    maybe_start_background_flush(force=True)


def count_spool_events() -> int:
    return sum(1 for path in telemetry_spool_dir().glob("*.ndjson") if path.is_file())


def clear_spool() -> int:
    removed = 0
    for path in telemetry_spool_dir().glob("*.ndjson"):
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            continue
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
    paths: list[Path] = []
    events: list[dict[str, Any]] = []
    total_bytes = 0

    for path in sorted(telemetry_spool_dir().glob("*.ndjson")):
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not raw:
            continue
        encoded_len = len(raw.encode("utf-8"))
        if paths and (len(paths) >= limit_events or total_bytes + encoded_len > MAX_BATCH_BYTES):
            break
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        paths.append(path)
        events.append(event)
        total_bytes += encoded_len

    return paths, events


def _post_batch(endpoint: str, events: list[dict[str, Any]]) -> None:
    body = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "sent_at": _utc_now_iso(),
            "events": events,
        },
        separators=(",", ":"),
    ).encode("utf-8")
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
    with urllib.request.urlopen(request, timeout=UPLOAD_TIMEOUT_SECONDS) as response:
        if response.status < 200 or response.status >= 300:
            raise urllib.error.HTTPError(endpoint, response.status, "upload failed", response.headers, None)


def flush_spool(*, force: bool = False) -> FlushResult:
    state = resolve_state()
    if (state.ci or state.test_env) and not force:
        return FlushResult(False, 0, 0, count_spool_events(), "Telemetry is disabled in CI/test environments.")
    if not force and not state.enabled:
        return FlushResult(False, 0, 0, count_spool_events(), "Telemetry is disabled.")

    lock_path = _acquire_lock()
    if lock_path is None:
        return FlushResult(False, 0, 0, count_spool_events(), "Telemetry flush is already running.")

    sent_events = 0
    sent_batches = 0
    try:
        while True:
            paths, events = _load_spool_records()
            if not events:
                break
            _post_batch(state.endpoint, events)
            for path in paths:
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
            sent_events += len(events)
            sent_batches += 1
        remaining = count_spool_events()
        return FlushResult(True, sent_events, sent_batches, remaining, "Telemetry flushed.")
    except Exception:
        return FlushResult(False, sent_events, sent_batches, count_spool_events(), "Telemetry flush failed.")
    finally:
        _release_lock(lock_path)


def maybe_start_background_flush(*, force: bool = False) -> bool:
    global _LAST_BACKGROUND_FLUSH_AT

    state = resolve_state()
    if state.ci or state.test_env:
        return False
    if not force and not state.enabled:
        return False
    if count_spool_events() == 0:
        return False
    now = time.monotonic()
    if not force and (now - _LAST_BACKGROUND_FLUSH_AT) < BACKGROUND_FLUSH_COOLDOWN_SECONDS:
        return False

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        subprocess.Popen(
            [sys.executable, "-m", "gms_mcp.telemetry_runtime", "flush-spool"],
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
