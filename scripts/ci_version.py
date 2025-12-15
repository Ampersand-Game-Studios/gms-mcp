#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


try:
    from packaging.version import InvalidVersion, Version
except ModuleNotFoundError as e:  # pragma: no cover
    raise SystemExit("Missing dependency: packaging (pip install packaging)") from e


PROJECT_NAME = "gms-mcp"


@dataclass(frozen=True)
class Computed:
    version: str
    should_publish: bool
    reason: str


def _github_output_set(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")


def _fetch_pypi_versions(project: str) -> list[str]:
    url = f"https://pypi.org/pypi/{project}/json"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return list((payload.get("releases") or {}).keys())


def _parse_versions(version_strings: list[str]) -> list[Version]:
    parsed: list[Version] = []
    for s in version_strings:
        try:
            parsed.append(Version(s))
        except InvalidVersion:
            continue
    return parsed


def _latest_final_base(existing: list[Version]) -> Version:
    finals = [v for v in existing if not v.is_prerelease and not v.is_devrelease]
    if not finals:
        return Version("0.0.0")
    latest = max(finals)
    return Version(latest.base_version)


def _bump_patch(base: Version) -> Version:
    release = list(base.release)
    while len(release) < 3:
        release.append(0)
    major, minor, patch = release[0], release[1], release[2]
    return Version(f"{major}.{minor}.{patch + 1}")


def _run_ordinal() -> int:
    run_number = int(os.environ.get("GITHUB_RUN_NUMBER") or "0")
    run_attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT") or "1")
    return run_number * 100 + (run_attempt - 1)


def _compute_candidate(*, ref_type: str, ref_name: str, version_override: str | None) -> Computed:
    existing_strings = _fetch_pypi_versions(PROJECT_NAME)
    existing_versions = set(_parse_versions(existing_strings))

    if version_override:
        v = Version(version_override)
        if not v.is_postrelease:
            raise SystemExit("VERSION_OVERRIDE must be a .postN version (packaging-only republish).")
        base_exists = any(
            (ev.base_version == v.base_version) and (not ev.is_prerelease) and (not ev.is_devrelease)
            for ev in existing_versions
        )
        if not base_exists:
            raise SystemExit(
                f"No existing final/post release found on PyPI for base {v.base_version}; refusing to publish a post-release."
            )
        if v in existing_versions:
            raise SystemExit(f"Version already exists on PyPI: {v}")
        return Computed(version=str(v), should_publish=True, reason="workflow_dispatch override")

    if ref_type == "tag":
        if not ref_name.startswith("v"):
            raise SystemExit("Tag must be of form vX.Y.Z")
        v = Version(ref_name[1:])
        if v in existing_versions:
            raise SystemExit(f"Tag version already exists on PyPI: {v}")
        if v.is_prerelease or v.is_devrelease or v.is_postrelease:
            raise SystemExit("Tag releases must be final versions (no dev/rc/post suffix).")
        return Computed(version=str(v), should_publish=True, reason="tag release")

    base = _latest_final_base(list(existing_versions))
    next_base = _bump_patch(base)
    ordinal = _run_ordinal()

    if ref_name == "main":
        candidate = Version(str(next_base))
    elif ref_name == "dev":
        candidate = Version(f"{next_base}.dev{ordinal}")
    elif ref_name == "prerelease":
        candidate = Version(f"{next_base}rc{ordinal}")
    else:
        candidate = Version(f"{next_base}.dev{ordinal}")

    if candidate in existing_versions:
        return Computed(version=str(candidate), should_publish=False, reason="version already on PyPI")

    return Computed(version=str(candidate), should_publish=True, reason=f"branch={ref_name}")


def main() -> int:
    ref_type = os.environ.get("GITHUB_REF_TYPE") or ""
    ref_name = os.environ.get("GITHUB_REF_NAME") or ""
    version_override = (os.environ.get("VERSION_OVERRIDE") or "").strip() or None

    computed = _compute_candidate(ref_type=ref_type, ref_name=ref_name, version_override=version_override)

    _github_output_set("version", computed.version)
    _github_output_set("should_publish", "true" if computed.should_publish else "false")
    _github_output_set("reason", computed.reason)

    print(f"version={computed.version}")
    print(f"should_publish={'true' if computed.should_publish else 'false'}")
    print(f"reason={computed.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
