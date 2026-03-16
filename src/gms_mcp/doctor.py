from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .update_notifier import (
    check_for_updates,
    get_current_version,
    get_install_location,
    mark_update_notified,
)


def build_doctor_report() -> dict[str, Any]:
    version = get_current_version()
    update_info = check_for_updates()

    if update_info["status"] == "warn":
        summary = "update available"
    elif update_info["status"] == "unknown":
        summary = "update check unavailable"
    else:
        summary = "up to date"

    package_check = {
        "name": "package",
        "status": "ok",
        "message": f"gms-mcp {version} installed",
        "details": {
            "version": version,
            "python": sys.executable,
            "install_location": get_install_location(),
        },
    }
    update_details = {
        "current_version": update_info["current_version"],
        "latest_version": update_info["latest_version"],
        "source": update_info["source"],
        "checked_at": update_info["checked_at"],
        "used_cache": update_info["used_cache"],
        "notification_due": update_info["notification_due"],
        "upgrade_command": update_info["upgrade_command"],
    }
    if update_info.get("url"):
        update_details["url"] = update_info["url"]

    updates_check = {
        "name": "updates",
        "status": update_info["status"],
        "message": update_info["message"],
        "details": update_details,
    }
    return {
        "ok": True,
        "summary": summary,
        "checks": [package_check, updates_check],
    }


def _doctor_usage() -> str:
    return "usage: gms-mcp [server|doctor|init] ..."


def _find_check(report: dict[str, Any], name: str) -> dict[str, Any]:
    for check in report.get("checks", []):
        if check.get("name") == name:
            return check
    raise KeyError(name)


def _print_human(report: dict[str, Any]) -> None:
    package_check = _find_check(report, "package")
    update_check = _find_check(report, "updates")
    package_details = package_check["details"]
    print(f"summary: {report['summary']}")
    print(f"package: {package_check['status']} - {package_check['message']}")
    print(f"python: {package_details['python']}")
    print(f"install-location: {package_details['install_location']}")
    print(f"updates: {update_check['status']} - {update_check['message']}")


def _print_notify(report: dict[str, Any]) -> None:
    update_check = _find_check(report, "updates")
    details = update_check["details"]
    if update_check["status"] != "warn" or not details.get("notification_due"):
        return

    source = details.get("source")
    via = f" via {source}" if source else ""
    print(
        f"[gms-mcp] Update available{via}: "
        f"{details['current_version']} -> {details['latest_version']}. "
        f"Run: {details['upgrade_command']}"
    )
    mark_update_notified(
        {
            "status": update_check["status"],
            "latest_version": details["latest_version"],
            "source": details.get("source"),
            "url": details.get("url"),
            "checked_at": details.get("checked_at"),
            "current_version": details["current_version"],
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gms-mcp doctor", add_help=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Print structured JSON output.")
    mode.add_argument(
        "--notify",
        action="store_true",
        help="Silent unless an update reminder is due; intended for client startup hooks.",
    )
    args = parser.parse_args(argv)

    report = build_doctor_report()
    if args.notify:
        _print_notify(report)
        return 0
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False))
        return 0
    _print_human(report)
    return 0
