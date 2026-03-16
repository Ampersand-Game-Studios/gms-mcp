from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import time
import urllib.request
from calendar import timegm
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PACKAGE_NAME = "gms-mcp"
PACKAGE_HOME_DIR = ".gms-mcp"
DOCTOR_CACHE_SUBDIR = "doctor"
UPDATE_STATUS_FILE = "update_status.json"
CACHE_TTL_SECONDS = 24 * 60 * 60
NOTIFY_TTL_SECONDS = 24 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 3
PYPI_RELEASE_URL = "https://pypi.org/project/gms-mcp/"
GITHUB_RELEASE_URL = "https://github.com/Ampersand-Game-Studios/gms-mcp/releases/latest"
PYPI_JSON_URL = "https://pypi.org/pypi/gms-mcp/json"
GITHUB_JSON_URL = "https://api.github.com/repos/Ampersand-Game-Studios/gms-mcp/releases/latest"
_VERSION_TOKEN_RE = re.compile(r"\d+|[A-Za-z]+")


def _default_python_command() -> str:
    return "python" if sys.platform.startswith("win") else "python3"


def _utc_now() -> float:
    return time.time()


def _cache_dir() -> Path:
    cache_dir = Path.home() / PACKAGE_HOME_DIR / DOCTOR_CACHE_SUBDIR
    cache_dir.mkdir(parents=True, exist_ok=True)
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
        return str(Path(distribution(PACKAGE_NAME).locate_file("")).resolve())
    except Exception:
        return str(Path(__file__).resolve().parents[1])


def get_upgrade_command() -> str:
    """Return the most likely upgrade command for this install."""
    executable = (shutil.which("gms-mcp") or "").lower()
    if "pipx" in executable:
        return "pipx upgrade gms-mcp"
    return f"{_default_python_command()} -m pip install -U gms-mcp"


def get_latest_version_pypi() -> str | None:
    """Check PyPI for the latest version of gms-mcp."""
    try:
        req = urllib.request.Request(PYPI_JSON_URL, headers={"User-Agent": "gms-mcp-update-checker"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except Exception as exc:
        logger.debug("Failed to check PyPI for updates: %s", exc)
        return None


def get_latest_version_github() -> str | None:
    """Check GitHub for the latest release version of gms-mcp."""
    try:
        req = urllib.request.Request(GITHUB_JSON_URL, headers={"User-Agent": "gms-mcp-update-checker"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode())
            tag_name = data["tag_name"]
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


def _load_cached_state() -> dict[str, Any] | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        logger.debug("Failed to read update cache: %s", exc)
    return None


def _save_cached_state(payload: dict[str, Any]) -> None:
    path = _cache_path()
    try:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed to write update cache: %s", exc)


def _build_info_from_cache(cached: dict[str, Any], *, current: str, used_cache: bool) -> dict[str, Any]:
    status = cached.get("status") if isinstance(cached.get("status"), str) else "unknown"
    latest = cached.get("latest_version") if isinstance(cached.get("latest_version"), str) else current
    source = cached.get("source") if isinstance(cached.get("source"), str) else None
    url = cached.get("url") if isinstance(cached.get("url"), str) else None
    checked_at = cached.get("checked_at") if isinstance(cached.get("checked_at"), str) else None
    last_notified_at = cached.get("last_notified_at") if isinstance(cached.get("last_notified_at"), str) else None
    return _build_update_info(
        current=current,
        latest=latest,
        source=source,
        url=url,
        status=status,
        checked_at=checked_at,
        used_cache=used_cache,
        last_notified_at=last_notified_at,
    )


def _is_cache_fresh(cached: dict[str, Any]) -> bool:
    checked_at_ts = _iso_to_ts(cached.get("checked_at"))
    if checked_at_ts is None:
        return False
    return (_utc_now() - checked_at_ts) < CACHE_TTL_SECONDS


def _fetch_update_status(current: str) -> dict[str, Any] | None:
    checked_at = _ts_to_iso(_utc_now())
    pypi_latest = get_latest_version_pypi()
    if _is_newer(pypi_latest, current):
        return {
            "status": "warn",
            "latest_version": pypi_latest,
            "source": "PyPI",
            "url": PYPI_RELEASE_URL,
            "checked_at": checked_at,
        }

    github_latest = get_latest_version_github()
    if _is_newer(github_latest, current):
        return {
            "status": "warn",
            "latest_version": github_latest,
            "source": "GitHub",
            "url": GITHUB_RELEASE_URL,
            "checked_at": checked_at,
        }

    if pypi_latest or github_latest:
        latest = pypi_latest or github_latest or current
        return {
            "status": "ok",
            "latest_version": latest,
            "source": None,
            "url": None,
            "checked_at": checked_at,
        }

    return None


def check_for_updates(*, force_refresh: bool = False) -> dict[str, Any]:
    """
    Check if a newer version of gms-mcp is available.

    Results are cached for 24 hours under ~/.gms-mcp/doctor/update_status.json.
    """
    current = get_current_version()
    cached = _load_cached_state()

    if cached and not force_refresh and _is_cache_fresh(cached):
        return _build_info_from_cache(cached, current=current, used_cache=True)

    fetched = _fetch_update_status(current)
    if fetched is not None:
        payload = {
            "status": fetched["status"],
            "latest_version": fetched["latest_version"],
            "source": fetched["source"],
            "url": fetched["url"],
            "checked_at": fetched["checked_at"],
            "last_notified_at": cached.get("last_notified_at") if isinstance(cached, dict) else None,
        }
        _save_cached_state(payload)
        return _build_info_from_cache(payload, current=current, used_cache=False)

    if cached:
        return _build_info_from_cache(cached, current=current, used_cache=True)

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


def mark_update_notified(info: dict[str, Any]) -> None:
    """Persist the notification timestamp after a reminder is emitted."""
    timestamp = _ts_to_iso(_utc_now())
    cached = _load_cached_state() or {}
    cached.update(
        {
            "status": info.get("status") or cached.get("status") or "unknown",
            "latest_version": info.get("latest_version") or cached.get("latest_version") or info.get("current_version"),
            "source": info.get("source"),
            "url": info.get("url"),
            "checked_at": info.get("checked_at") or cached.get("checked_at"),
            "last_notified_at": timestamp,
        }
    )
    _save_cached_state(cached)
