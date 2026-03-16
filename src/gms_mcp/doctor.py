from __future__ import annotations

import argparse
import json
from typing import Any

from .doctor_checks import build_doctor_report
from .update_notifier import mark_update_notified
from .update_status import get_update_status


def _doctor_usage() -> str:
    return "usage: gms-mcp [server|doctor|init] ..."


def _print_human(report: dict[str, Any]) -> None:
    print(f"summary: {report['summary']}")
    print(f"overall-status: {report['overall_status']}")
    for check in report.get("checks", []):
        print(f"{check['name']}: {check['status']} - {check['message']}")
        metadata = check.get("metadata")
        if check["name"] == "package" and isinstance(metadata, dict):
            print(f"python: {metadata.get('python')}")
            print(f"install-location: {metadata.get('install_location')}")
        elif check["name"] == "project" and isinstance(metadata, dict) and metadata.get("project_directory"):
            print(f"project-directory: {metadata.get('project_directory')}")
        elif check["name"] == "updates" and isinstance(metadata, dict) and metadata.get("update_available"):
            print(f"upgrade-command: {metadata.get('upgrade_command')}")
        for detail in check.get("details", []):
            print(f"detail: {detail}")


def _print_notify() -> None:
    update_status = get_update_status()
    if not update_status.update_available or not update_status.notification_due:
        return

    source = update_status.source
    via = f" via {source}" if source else ""
    print(
        f"[gms-mcp] Update available{via}: "
        f"{update_status.current_version} -> {update_status.latest_version}. "
        f"Run: {update_status.upgrade_command}"
    )
    mark_update_notified(update_status.to_notification_record())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gms-mcp doctor", add_help=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Print structured JSON output.")
    mode.add_argument(
        "--notify",
        action="store_true",
        help="Silent unless an update reminder is due; intended for client startup hooks.",
    )
    parser.add_argument("--project", action="store_true", help="Run project-aware environment checks.")
    parser.add_argument("--full", action="store_true", help="Run the full diagnostics set, including bridge/runtime checks.")
    parser.add_argument(
        "--client",
        choices=("codex", "claude"),
        help="Validate client setup for the active workspace.",
    )
    parser.add_argument(
        "--project-root",
        help="Explicit GameMaker project directory to inspect.",
    )
    parser.add_argument(
        "--server-name",
        default="gms",
        help="MCP server name to validate in client config checks.",
    )
    args = parser.parse_args(argv)

    if args.notify:
        _print_notify()
        return 0

    report = build_doctor_report(
        project=args.project,
        full=args.full,
        client=args.client,
        project_root=args.project_root,
        server_name=args.server_name,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False))
        return report["exit_code"]
    _print_human(report)
    return report["exit_code"]
