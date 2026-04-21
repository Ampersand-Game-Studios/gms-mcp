#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://gms-mcp-telemetry.ampersandgamestudios.com"
DEFAULT_DRIVE_REMOTE = "ampersand-drive"
DEFAULT_DRIVE_PATH = "Ampersand Game Studios/Projects/GMS MCP/GMS MCP telemetry"
DEFAULT_ARCHIVE_PREFIX = "gms-mcp-telemetry-archive"
DEFAULT_RCLONE_BIN = "rclone"
TIMEOUT_SECONDS = 60
ARCHIVE_USER_AGENT = "curl/8.7.1"


@dataclass(frozen=True)
class ArchiveRange:
    start_date: date
    end_date: date

    @property
    def label(self) -> str:
        return f"{self.start_date:%Y%m%d}-{self.end_date:%Y%m%d}"


def previous_week_range(today: date | None = None) -> ArchiveRange:
    current = today or datetime.now(timezone.utc).date()
    this_monday = current - timedelta(days=current.weekday())
    end_date = this_monday - timedelta(days=1)
    start_date = end_date - timedelta(days=6)
    return ArchiveRange(start_date=start_date, end_date=end_date)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def optional_env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def request_json(base_url: str, token: str, path: str, params: dict[str, str]) -> dict:
    url = f"{base_url.rstrip('/')}{path}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "authorization": f"Bearer {token}",
            "accept": "application/json",
            "user-agent": ARCHIVE_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Archive request failed ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Archive request failed: {error.reason}") from error


def download_object(base_url: str, token: str, key: str, destination_root: Path) -> Path:
    destination = destination_root / key
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"{base_url.rstrip('/')}/v1/archive/object?{urlencode({'key': key})}"
    request = Request(
        url,
        headers={
            "authorization": f"Bearer {token}",
            "user-agent": ARCHIVE_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            destination.write_bytes(response.read())
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Object download failed for {key} ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Object download failed for {key}: {error.reason}") from error
    return destination


def create_bundle(source_root: Path, bundle_path: Path) -> None:
    with tarfile.open(bundle_path, "w:gz") as archive:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(source_root))


def ensure_drive_folder(rclone_bin: str, drive_remote: str, drive_path: str) -> None:
    subprocess.run(
        [rclone_bin, "mkdir", f"{drive_remote}:{drive_path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def upload_to_drive(rclone_bin: str, drive_remote: str, drive_path: str, local_path: Path) -> None:
    destination = f"{drive_remote}:{drive_path.rstrip('/')}/{local_path.name}"
    subprocess.run(
        [rclone_bin, "copyto", str(local_path), destination],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def object_keys(manifest: dict) -> list[str]:
    keys: list[str] = []
    for item in manifest.get("objects", []):
        if isinstance(item, str):
            keys.append(item)
        elif isinstance(item, dict):
            key = item.get("key")
            if isinstance(key, str) and key:
                keys.append(key)
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Archive prior telemetry artifacts to Google Drive from the Mac mini.")
    parser.add_argument("--start-date", help="Start date in YYYY-MM-DD (default: previous Monday).")
    parser.add_argument("--end-date", help="End date in YYYY-MM-DD (default: previous Sunday).")
    parser.add_argument("--archive-prefix", default=DEFAULT_ARCHIVE_PREFIX, help="Prefix for uploaded bundle names.")
    args = parser.parse_args(argv)

    archive_range = previous_week_range()
    if args.start_date:
        archive_range = ArchiveRange(
            start_date=date.fromisoformat(args.start_date),
            end_date=archive_range.end_date,
        )
    if args.end_date:
        archive_range = ArchiveRange(
            start_date=archive_range.start_date,
            end_date=date.fromisoformat(args.end_date),
        )
    if archive_range.end_date < archive_range.start_date:
        raise RuntimeError("End date must be on or after start date.")

    base_url = optional_env("TELEMETRY_ARCHIVE_BASE_URL", DEFAULT_BASE_URL)
    token = required_env("TELEMETRY_ARCHIVE_TOKEN")
    drive_remote = optional_env("TELEMETRY_DRIVE_REMOTE", DEFAULT_DRIVE_REMOTE)
    drive_path = optional_env("TELEMETRY_DRIVE_PATH", DEFAULT_DRIVE_PATH)
    rclone_bin = optional_env("RCLONE_BIN", DEFAULT_RCLONE_BIN)

    manifest = request_json(
        base_url,
        token,
        "/v1/archive/manifest",
        {
            "start_date": archive_range.start_date.isoformat(),
            "end_date": archive_range.end_date.isoformat(),
        },
    )
    keys = object_keys(manifest)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        download_root = temp_root / "download"
        download_root.mkdir(parents=True, exist_ok=True)

        for key in keys:
            download_object(base_url, token, key, download_root)

        manifest_path = temp_root / f"{args.archive_prefix}-{archive_range.label}-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        ensure_drive_folder(rclone_bin, drive_remote, drive_path)
        upload_to_drive(rclone_bin, drive_remote, drive_path, manifest_path)
        print(f"Uploaded manifest: {manifest_path.name}")

        if keys:
            bundle_path = temp_root / f"{args.archive_prefix}-{archive_range.label}.tar.gz"
            create_bundle(download_root, bundle_path)
            upload_to_drive(rclone_bin, drive_remote, drive_path, bundle_path)
            print(f"Uploaded archive bundle: {bundle_path.name}")
        else:
            print("No telemetry objects found for the requested range; uploaded manifest only.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
