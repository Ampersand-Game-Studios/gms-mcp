#!/usr/bin/env python3
"""Fail closed unless every required real-GameMaker CI fixture passed."""

from __future__ import annotations

import argparse
import fnmatch
import json
import string
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


REQUIRED_CHECKS = {
    "high_risk_mutation_compiled",
    "batchable_mutation_deferred",
    "deferred_batch_flushed",
    "collision_reference_emitted",
    "collision_event_compiled",
    "collision_target_rename_schema",
    "collision_target_rename_compiled",
    "room_order_duplicate_delete_schema",
    "room_order_changes_compiled",
}
EXPECTED_RUNTIME_PREFIXES = {
    "gm-2024": "2024.",
    "gm-2026-lts": "2026.",
}
EXPECTED_SOURCE_IDE_PREFIXES = {
    "gm-2024": "2024.",
    "gm-2026-lts": "2026.",
}
SOURCE_PROVENANCE_FIELDS = (
    "source_yyp_name",
    "source_yyp_sha256",
    "source_ide_version",
)


def _runtime_version_matches(version: str, expected: str) -> bool:
    if not expected:
        return False
    if any(marker in expected for marker in ("*", "?", "[")):
        return fnmatch.fnmatch(version, expected)
    return version == expected


def _is_safe_yyp_name(value: str) -> bool:
    """Accept a filename only, never a host-local source path."""
    if not value or value in {".", ".."}:
        return False
    return (
        PurePosixPath(value).name == value and PureWindowsPath(value).name == value and value.lower().endswith(".yyp")
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in string.hexdigits for character in value)


def verify_reports(root: Path, expected_fixtures: list[str]) -> list[str]:
    errors: list[str] = []
    reports: dict[str, dict[str, Any]] = {}
    source_yyp_hashes: dict[str, str] = {}
    for path in sorted(root.rglob("real_gamemaker_smoke-*.json")):
        try:
            raw_payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid certification report {path}: {exc}")
            continue
        if not isinstance(raw_payload, dict):
            errors.append(f"Certification report must contain a JSON object: {path}")
            continue
        payload: dict[str, Any] = raw_payload
        raw_fixture = payload.get("fixture")
        fixture: dict[str, Any] = raw_fixture if isinstance(raw_fixture, dict) else {}
        name = str(fixture.get("name") or "")
        if not name:
            errors.append(f"Certification report has no fixture name: {path}")
            continue
        if name in reports:
            errors.append(f"Duplicate certification report for fixture {name}: {path}")
            continue
        reports[name] = payload

    for name in expected_fixtures:
        report = reports.get(name)
        if report is None:
            errors.append(f"Missing real GameMaker certification report for {name}")
            continue
        payload = report
        if payload.get("ok") is not True or payload.get("status") != "passed":
            errors.append(f"Real GameMaker fixture {name} did not pass: {payload.get('status', 'unknown')}")
            continue
        raw_runtime = payload.get("runtime")
        runtime: dict[str, Any] = raw_runtime if isinstance(raw_runtime, dict) else {}
        if runtime.get("ok") is not True or not runtime.get("version"):
            errors.append(f"Real GameMaker fixture {name} has no verified runtime")
        raw_fixture = payload.get("fixture")
        fixture = raw_fixture if isinstance(raw_fixture, dict) else {}
        expected_pattern = str(fixture.get("expected_runtime_version") or "")
        if not expected_pattern:
            errors.append(f"Real GameMaker fixture {name} has no configured runtime expectation")
        expected_prefix = EXPECTED_RUNTIME_PREFIXES.get(name)
        runtime_version = str(runtime.get("version") or "")
        if expected_pattern and not _runtime_version_matches(runtime_version, expected_pattern):
            errors.append(
                f"Real GameMaker fixture {name} used runtime {runtime_version!r}, "
                f"which does not match configured expectation {expected_pattern!r}"
            )
        if expected_prefix and not runtime_version.startswith(expected_prefix):
            errors.append(
                f"Real GameMaker fixture {name} used runtime {runtime_version!r}, expected {expected_prefix}*"
            )
        if name == "gm-2026-lts" and runtime.get("channel") != "lts":
            errors.append("Real GameMaker fixture gm-2026-lts did not use an LTS-classified runtime")
        source_ide_prefix = EXPECTED_SOURCE_IDE_PREFIXES.get(name)
        if source_ide_prefix:
            raw_fixture = payload.get("fixture")
            fixture = raw_fixture if isinstance(raw_fixture, dict) else {}
            provenance = {field: str(fixture.get(field) or "").strip() for field in SOURCE_PROVENANCE_FIELDS}
            missing_provenance = [field for field, value in provenance.items() if not value]
            if missing_provenance:
                errors.append(
                    f"Real GameMaker fixture {name} is missing source provenance: {', '.join(missing_provenance)}"
                )
            else:
                source_yyp_name = provenance["source_yyp_name"]
                source_yyp_sha256 = provenance["source_yyp_sha256"].lower()
                source_ide_version = provenance["source_ide_version"]
                if not _is_safe_yyp_name(source_yyp_name):
                    errors.append(f"Real GameMaker fixture {name} source YYP name is not a privacy-safe filename")
                if not _is_sha256(source_yyp_sha256):
                    errors.append(f"Real GameMaker fixture {name} source YYP SHA-256 is invalid")
                if not source_ide_version.startswith(source_ide_prefix):
                    errors.append(
                        f"Real GameMaker fixture {name} source IDEVersion is {source_ide_version!r}, "
                        f"expected {source_ide_prefix}*"
                    )
                source_yyp_hashes[name] = source_yyp_sha256
        raw_checks = payload.get("checks")
        checks: dict[str, Any] = raw_checks if isinstance(raw_checks, dict) else {}
        missing_checks = sorted(check for check in REQUIRED_CHECKS if checks.get(check) is not True)
        if missing_checks:
            errors.append(f"Real GameMaker fixture {name} is missing checks: {', '.join(missing_checks)}")

    required_provenance_names = [name for name in expected_fixtures if name in EXPECTED_SOURCE_IDE_PREFIXES]
    complete_provenance = all(name in source_yyp_hashes for name in required_provenance_names)
    if len(required_provenance_names) > 1 and complete_provenance:
        if len({source_yyp_hashes.get(name, "") for name in required_provenance_names}) != len(
            required_provenance_names
        ):
            errors.append("Real GameMaker fixture source YYP SHA-256 hashes must be distinct")

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing downloaded real-smoke artifacts")
    parser.add_argument("--expected", nargs="+", required=True, help="Required fixture names")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = verify_reports(args.root, args.expected)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1
    print(f"[OK] Release certified by real GameMaker fixtures: {', '.join(args.expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
