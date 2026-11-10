from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from calendar import timegm
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

PACKAGE_NAME = "gms-mcp"
PACKAGE_HOME_DIR = ".gms-mcp"
DOCTOR_CACHE_SUBDIR = "doctor"
UPDATE_STATUS_FILE = "update_status.json"
CACHE_TTL_SECONDS = 24 * 60 * 60
NOTIFY_TTL_SECONDS = 24 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 3
FAILURE_BACKOFF_SECONDS = 60 * 60
UPDATE_CHECK_DISABLE_ENV = "GMS_MCP_DISABLE_UPDATE_CHECK"
_TRUE_VALUES = {"1", "true", "yes", "on"}
PYPI_RELEASE_URL = "https://pypi.org/project/gms-mcp/"
GITHUB_RELEASE_URL = "https://github.com/Ampersand-Game-Studios/gms-mcp/releases/latest"
PYPI_JSON_URL = "https://pypi.org/pypi/gms-mcp/json"
GITHUB_JSON_URL = "https://api.github.com/repos/Ampersand-Game-Studios/gms-mcp/releases/latest"
_VERSION_TOKEN_RE = re.compile(r"\d+|[A-Za-z]+")


class _CachedUpdateState(TypedDict):
    status: str
    latest_version: str
    source: str | None
    url: str | None
    checked_at: str
    last_notified_at: str | None
    last_failure_at: str | None


# Per-process state for callers that must not write the cache file (persist=False),
# keyed by cache path so separate homes never share results.
_MEMORY_STATE: dict[Path, _CachedUpdateState] = {}


def _default_python_command() -> str:
    return "python" if sys.platform.startswith("win") else "python3"


def _utc_now() -> float:
    return time.time()


def _cache_dir() -> Path:
    cache_dir = Path.home() / PACKAGE_HOME_DIR / DOCTOR_CACHE_SUBDIR
    return cache_dir


def _cache_path() -> Path:
    return _cache_dir() / UPDATE_STATUS_FILE


def _ts_to_iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _iso_to_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return float(timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return None


def _version_key(raw_version: str) -> tuple[tuple[int, int | str], ...]:
    precedence = {
        "dev": -3,
        "a": -2,
        "alpha": -2,
        "b": -1,
        "beta": -1,
        "rc": 0,
        "post": 1,
    }
    pieces: list[tuple[int, int | str]] = []
    for token in _VERSION_TOKEN_RE.findall(raw_version.replace("-", ".")):
        if token.isdigit():
            pieces.append((1, int(token)))
        else:
            pieces.append((0, precedence.get(token.lower(), 0)))
            pieces.append((2, token.lower()))
    return tuple(pieces)


def _is_newer(candidate: str | None, current: str) -> bool:
    if not candidate or candidate == current:
        return False
    try:
        return _version_key(candidate) > _version_key(current)
    except Exception:
        return candidate != current


def get_current_version() -> str:
    """Get the current version of the gms-mcp package."""
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        # Fallback for development installs or if not installed via pip
        return "0.0.0"


def get_install_location() -> str:
    """Best-effort package location for doctor output."""
    try:
        location = distribution(PACKAGE_NAME).locate_file("")
        return str(Path(str(location)).resolve())
    except Exception:
        return str(Path(__file__).resolve().parents[1])


def get_upgrade_command() -> str:
    """Return the most likely upgrade command for this install."""
    executable = (shutil.which("gms-mcp") or "").lower()
    if "pipx" in executable:
        return "pipx upgrade gms-mcp"
    return f"{_default_python_command()} -m pip install -U gms-mcp"


def _fetch_json(url: str) -> Any:
    """Fetch JSON from ``url``, giving up after REQUEST_TIMEOUT_SECONDS of wall-clock time.

    urllib applies its timeout to each socket operation and each resolved address, so a
    host whose IPv6 addresses silently drop traffic can block for many multiples of it.
    The request runs on a daemon thread so an abandoned attempt never delays exit.
    """
    outcome: dict[str, Any] = {}

    def fetch() -> None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gms-mcp-update-checker"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                outcome["data"] = json.loads(response.read().decode())
        except Exception as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=fetch, name="gms-mcp-update-check", daemon=True)
    worker.start()
    worker.join(REQUEST_TIMEOUT_SECONDS)
    if worker.is_alive():
        raise TimeoutError(f"no response within {REQUEST_TIMEOUT_SECONDS}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["data"]


def get_latest_version_pypi() -> str | None:
    """Check PyPI for the latest version of gms-mcp."""
    try:
        return _fetch_json(PYPI_JSON_URL)["info"]["version"]
    except Exception as exc:
        logger.debug("Failed to check PyPI for updates: %s", exc)
        return None


def get_latest_version_github() -> str | None:
    """Check GitHub for the latest release version of gms-mcp."""
    try:
        tag_name = _fetch_json(GITHUB_JSON_URL)["tag_name"]
        return tag_name[1:] if tag_name.startswith("v") else tag_name
    except Exception as exc:
        logger.debug("Failed to check GitHub for updates: %s", exc)
        return None


def _build_message(
    *,
    current: str,
    latest: str,
    source: str | None,
    update_available: bool,
    upgrade_command: str,
    url: str | None,
    status: str,
) -> str:
    if status == "unknown":
        return "Unable to check for updates right now."
    if update_available and source:
        suffix = f" or check {url}" if url else ""
        return (
            f"A newer version of gms-mcp is available via {source}: {latest} "
            f"(current: {current}). Update with '{upgrade_command}'{suffix}"
        )
    return "You are running the latest version of gms-mcp."


def _build_update_info(
    *,
    current: str,
    latest: str,
    source: str | None,
    url: str | None,
    status: str,
    checked_at: str | None,
    used_cache: bool,
    last_notified_at: str | None,
) -> dict[str, Any]:
    upgrade_command = get_upgrade_command()
    update_available = bool(source and _is_newer(latest, current))
    normalized_status = "unknown" if status == "unknown" else ("warn" if update_available else "ok")
    notification_due = False
    if update_available:
        if not last_notified_at:
            notification_due = True
        else:
            last_notified_ts = _iso_to_ts(last_notified_at)
            if last_notified_ts is None:
                notification_due = True
            else:
                notification_due = (_utc_now() - last_notified_ts) >= NOTIFY_TTL_SECONDS
    info = {
        "status": normalized_status,
        "update_available": update_available,
        "current_version": current,
        "latest_version": latest if latest else current,
        "source": source,
        "url": url,
        "checked_at": checked_at,
        "used_cache": used_cache,
        "last_notified_at": last_notified_at,
        "notification_due": notification_due,
        "upgrade_command": upgrade_command,
    }
    info["message"] = _build_message(
        current=current,
        latest=info["latest_version"],
        source=source,
        update_available=update_available,
        upgrade_command=upgrade_command,
        url=url,
        status=normalized_status,
    )
    return info


def _string_value(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _optional_string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _load_cached_state() -> _CachedUpdateState | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {
                "status": _string_value(payload.get("status"), "unknown"),
                "latest_version": _optional_string_value(payload.get("latest_version")) or "0.0.0",
                "source": _optional_string_value(payload.get("source")),
                "url": _optional_string_value(payload.get("url")),
                "checked_at": _string_value(payload.get("checked_at"), ""),
                "last_notified_at": _optional_string_value(payload.get("last_notified_at")),
                "last_failure_at": _optional_string_value(payload.get("last_failure_at")),
            }
    except Exception as exc:
        logger.debug("Failed to read update cache: %s", exc)
    return None


def _save_cached_state(payload: _CachedUpdateState) -> None:
    path = _cache_path()
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except Exception as exc:
        logger.debug("Failed to write update cache: %s", exc)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def update_check_disabled() -> bool:
    return os.environ.get(UPDATE_CHECK_DISABLE_ENV, "").strip().lower() in _TRUE_VALUES


def _in_failure_backoff(cached: _CachedUpdateState | None) -> bool:
    failed_at = _iso_to_ts(cached.get("last_failure_at")) if cached else None
    return failed_at is not None and (_utc_now() - failed_at) < FAILURE_BACKOFF_SECONDS


def _build_info_from_cache(cached: _CachedUpdateState, *, current: str, used_cache: bool) -> dict[str, Any]:
    checked_at = cached.get("checked_at") or None
    return _build_update_info(
        current=current,
        latest=cached.get("latest_version") or current,
        source=cached.get("source"),
        url=cached.get("url"),
        status=cached.get("status") or "unknown",
        checked_at=checked_at,
        used_cache=used_cache,
        last_notified_at=cached.get("last_notified_at"),
    )


def _is_cache_fresh(cached: _CachedUpdateState) -> bool:
    checked_at_ts = _iso_to_ts(cached.get("checked_at"))
    if checked_at_ts is None:
        return False
    return (_utc_now() - checked_at_ts) < CACHE_TTL_SECONDS


def _fetch_update_status(current: str) -> _CachedUpdateState | None:
    checked_at = _ts_to_iso(_utc_now())
    pypi_latest = get_latest_version_pypi()
    if _is_newer(pypi_latest, current):
        assert pypi_latest is not None
        payload: _CachedUpdateState = {
            "status": "warn",
            "latest_version": pypi_latest,
            "source": "PyPI",
            "url": PYPI_RELEASE_URL,
            "checked_at": checked_at,
            "last_notified_at": None,
            "last_failure_at": None,
        }
        return payload

    github_latest = get_latest_version_github()
    if _is_newer(github_latest, current):
        assert github_latest is not None
        payload: _CachedUpdateState = {
            "status": "warn",
            "latest_version": github_latest,
            "source": "GitHub",
            "url": GITHUB_RELEASE_URL,
            "checked_at": checked_at,
            "last_notified_at": None,
            "last_failure_at": None,
        }
        return payload

    if pypi_latest or github_latest:
        latest = pypi_latest or github_latest or current
        payload = {
            "status": "ok",
            "latest_version": latest,
            "source": None,
            "url": None,
            "checked_at": checked_at,
            "last_notified_at": None,
            "last_failure_at": None,
        }
        return payload

    return None


def _unknown_info(current: str) -> dict[str, Any]:
    return _build_update_info(
        current=current,
        latest=current,
        source=None,
        url=None,
        status="unknown",
        checked_at=None,
        used_cache=False,
        last_notified_at=None,
    )


def check_for_updates(*, force_refresh: bool = False, persist: bool = True) -> dict[str, Any]:
    """
    Check if a newer version of gms-mcp is available.

    Results are cached for 24 hours under ~/.gms-mcp/doctor/update_status.json; a failed
    check is retried after an hour. ``persist=False`` keeps results in memory only.
    Set GMS_MCP_DISABLE_UPDATE_CHECK=1 to never contact PyPI or GitHub.
    """
    current = get_current_version()
    path = _cache_path()
    cached = _MEMORY_STATE.get(path) if not persist else None
    cached = cached or _load_cached_state()

    if update_check_disabled():
        return _build_info_from_cache(cached, current=current, used_cache=True) if cached else _unknown_info(current)

    if cached and not force_refresh and (_is_cache_fresh(cached) or _in_failure_backoff(cached)):
        if cached.get("checked_at") or cached.get("status") != "unknown":
            return _build_info_from_cache(cached, current=current, used_cache=True)
        return _unknown_info(current)

    fetched = _fetch_update_status(current)
    if fetched is not None:
        payload: _CachedUpdateState = {
            "status": fetched["status"],
            "latest_version": fetched["latest_version"],
            "source": fetched["source"],
            "url": fetched["url"],
            "checked_at": fetched["checked_at"],
            "last_notified_at": cached.get("last_notified_at") if cached else None,
            "last_failure_at": None,
        }
        _store_state(path, payload, persist=persist)
        return _build_info_from_cache(payload, current=current, used_cache=False)

    failed: _CachedUpdateState = (
        {**cached}
        if cached
        else {
            "status": "unknown",
            "latest_version": current,
            "source": None,
            "url": None,
            "checked_at": "",
            "last_notified_at": None,
            "last_failure_at": None,
        }
    )
    failed["last_failure_at"] = _ts_to_iso(_utc_now())
    _store_state(path, failed, persist=persist)
    if cached:
        return _build_info_from_cache(cached, current=current, used_cache=True)
    return _unknown_info(current)


def _store_state(path: Path, payload: _CachedUpdateState, *, persist: bool) -> None:
    if persist:
        _MEMORY_STATE.pop(path, None)
        _save_cached_state(payload)
    else:
        _MEMORY_STATE[path] = payload


def mark_update_notified(info: dict[str, Any]) -> None:
    """Persist the notification timestamp after a reminder is emitted."""
    timestamp = _ts_to_iso(_utc_now())
    cached = _load_cached_state() or {
        "status": "unknown",
        "latest_version": _string_value(info.get("current_version"), "0.0.0"),
        "source": None,
        "url": None,
        "checked_at": "",
        "last_notified_at": None,
        "last_failure_at": None,
    }
    cached["status"] = _string_value(info.get("status"), cached["status"])
    cached["latest_version"] = _string_value(
        info.get("latest_version"),
        _string_value(info.get("current_version"), cached["latest_version"]),
    )
    cached["source"] = _optional_string_value(info.get("source"))
    cached["url"] = _optional_string_value(info.get("url"))
    cached["checked_at"] = _string_value(info.get("checked_at"), cached["checked_at"])
    cached["last_notified_at"] = timestamp
    _save_cached_state(cached)
