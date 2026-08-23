#!/usr/bin/env python3
"""Fail when built package archives contain files outside the public contract."""

from __future__ import annotations

import argparse
import email
import re
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


PUBLIC_AUTHOR = "Ampersand Game Studios"
SDIST_ROOT_FILES = {
    "LICENSE",
    "MANIFEST.in",
    "PKG-INFO",
    "README.md",
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
}
EGG_INFO_FILES = {
    "PKG-INFO",
    "SOURCES.txt",
    "dependency_links.txt",
    "entry_points.txt",
    "requires.txt",
    "top_level.txt",
}
DIST_INFO_FILES = {
    "METADATA",
    "RECORD",
    "WHEEL",
    "entry_points.txt",
    "top_level.txt",
}
FORBIDDEN_METADATA_FILES = {
    "direct_url.json",
    "scm_file_list.json",
    "scm_version.json",
}
FORBIDDEN_PATH_COMPONENTS = {
    ".agents",
    ".env",
    ".git",
    ".github",
    ".idea",
    ".pytest_cache",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "reports",
}
FORBIDDEN_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "google-services.json",
    "googleservice-info.plist",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "known_hosts",
    "secrets.json",
}
FORBIDDEN_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".mobileprovision"}
PRIVATE_CONTENT_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("macOS user path", re.compile(rb"/Users/(?!Shared/)[A-Za-z0-9._-]+/")),
    ("Linux user path", re.compile(rb"/home/[A-Za-z0-9._-]+/")),
    ("Windows user path", re.compile(rb"[A-Za-z]:\\Users\\[^\\\r\n]+\\")),
    ("macOS private temporary path", re.compile(rb"/(?:private/)?var/folders/[A-Za-z0-9_./-]+")),
    (
        "private network address",
        re.compile(
            rb"(?<![0-9])(?:10(?:\.[0-9]{1,3}){3}|192\.168(?:\.[0-9]{1,3}){2}|172\.(?:1[6-9]|2[0-9]|3[01])(?:\.[0-9]{1,3}){2})(?![0-9])"
        ),
    ),
    ("private IPv6 address", re.compile(rb"(?i)\[(?:fc|fd)[0-9a-f:]+\]")),
    (
        "private hostname",
        re.compile(rb"(?i)\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:corp|internal|lan|local)\b"),
    ),
    ("cloud metadata address", re.compile(rb"(?<![0-9])169\.254\.169\.254(?![0-9])")),
    ("GitHub token", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("AWS access key", re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    ("Slack token", re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("OpenAI token", re.compile(rb"sk-(?:proj|svcacct)-[A-Za-z0-9_-]{20,}")),
    ("Basic authorization", re.compile(rb"(?i)\bbasic\s+[A-Za-z0-9+/=]{16,}")),
    (
        "assigned secret",
        re.compile(
            rb"(?i)['\"]?\b[A-Za-z0-9_.-]*(?:access[_-]?key|api[_-]?key|client[_-]?secret|connection[_-]?string|"
            rb"password|passwd|private[_-]?key|secret|session[_-]?id|token)['\"]?"
            rb"\s*[=:]\s*(?:(['\"])[A-Za-z0-9+/_.-]{24,}\1|[A-Za-z0-9+/_-]{24,}(?![A-Za-z0-9+/_-]))"
        ),
    ),
)


class ArtifactPrivacyError(RuntimeError):
    """Raised when an archive violates the public package boundary."""


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ArtifactPrivacyError(f"unsafe archive path: {name}")
    return path


def _is_sensitive_member_path(path: PurePosixPath) -> bool:
    """Reject exact private-artifact conventions without matching normal source names."""
    lowered_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        bool(lowered_parts & FORBIDDEN_PATH_COMPONENTS)
        or name in FORBIDDEN_FILENAMES
        or name.startswith(".env.")
        or path.suffix.lower() in FORBIDDEN_SUFFIXES
    )


def _is_sdist_file_allowed(path: PurePosixPath) -> bool:
    if len(path.parts) == 1:
        return path.name in SDIST_ROOT_FILES

    parts = path.parts
    if parts[:2] == ("src", "gms_helpers") or parts[:2] == ("src", "gms_mcp"):
        if parts[:2] == ("src", "gms_mcp") and len(parts) >= 3 and parts[2] == "gms_mcp.egg-info":
            return False
        return path.suffix == ".py"
    if parts[:2] == ("src", "gms_mcp.egg-info"):
        return len(parts) == 3 and parts[2] in EGG_INFO_FILES
    if parts[:2] == ("skills", "gms-mcp"):
        return path.suffix == ".md"
    if parts[0] == "hooks":
        return len(parts) == 2 and path.suffix in {".json", ".sh"}
    return False


def _is_wheel_file_allowed(path: PurePosixPath) -> bool:
    parts = path.parts
    if not parts:
        return False

    if parts[0] == "gms_helpers":
        if len(parts) >= 3 and parts[1:3] == ("bundle", "skills"):
            return len(parts) >= 5 and parts[3] == "gms-mcp" and path.suffix == ".md"
        if len(parts) >= 3 and parts[1:3] == ("bundle", "hooks"):
            return len(parts) == 4 and path.suffix in {".json", ".sh"}
        return path.suffix == ".py"
    if parts[0] == "gms_mcp":
        return path.suffix == ".py"
    if parts[0].endswith(".dist-info"):
        if len(parts) == 2:
            return parts[1] in DIST_INFO_FILES
        return len(parts) == 3 and parts[1] == "licenses" and parts[2] == "LICENSE"
    return False


def _validate_metadata(raw: bytes, source: str) -> None:
    metadata = email.message_from_bytes(raw)
    authors = metadata.get_all("Author", [])
    if authors != [PUBLIC_AUTHOR]:
        raise ArtifactPrivacyError(f"{source}: unexpected Author metadata: {authors!r}")
    if metadata.get_all("Author-email"):
        raise ArtifactPrivacyError(f"{source}: Author-email must not be published")
    for field in ("Maintainer", "Maintainer-email"):
        if metadata.get_all(field):
            raise ArtifactPrivacyError(f"{source}: {field} must not be published")
    for field in ("Author", "Author-email", "Maintainer", "Maintainer-email", "Home-page"):
        for value in metadata.get_all(field, []):
            if value.startswith(("/", "~")) or "file://" in value.lower():
                raise ArtifactPrivacyError(f"{source}: {field} must not contain a local path")


def _validate_public_content(raw: bytes, source: str) -> None:
    """Reject concrete credential/private-host signatures inside allowed files."""
    for label, pattern in PRIVATE_CONTENT_PATTERNS:
        if pattern.search(raw):
            raise ArtifactPrivacyError(f"{source}: detected {label}")


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.comment:
            raise ArtifactPrivacyError(f"{path.name}: archive comment must be empty")
        failures: list[str] = []
        metadata_names: list[str] = []
        for entry in archive.infolist():
            name = entry.filename
            member = _safe_member_path(name)
            mode = entry.external_attr >> 16
            if (
                entry.is_dir()
                or stat.S_ISLNK(mode)
                or bool(entry.extra)
                or member.name in FORBIDDEN_METADATA_FILES
                or _is_sensitive_member_path(member)
                or not _is_wheel_file_allowed(member)
            ):
                failures.append(name)
            if member.name == "METADATA" and member.parent.name.endswith(".dist-info"):
                metadata_names.append(name)
            if not entry.is_dir():
                _validate_public_content(archive.read(entry), f"{path.name}:{name}")
        if failures:
            raise ArtifactPrivacyError(f"{path.name}: non-public wheel members: {sorted(failures)!r}")
        if len(metadata_names) != 1:
            raise ArtifactPrivacyError(f"{path.name}: expected exactly one METADATA file")
        _validate_metadata(archive.read(metadata_names[0]), f"{path.name}:{metadata_names[0]}")


def verify_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        roots = {PurePosixPath(member.name).parts[0] for member in members}
        if len(roots) != 1:
            raise ArtifactPrivacyError(f"{path.name}: expected one source archive root, found {sorted(roots)!r}")
        root = next(iter(roots))
        failures: list[str] = []
        directories: list[str] = []
        public_files: list[str] = []
        metadata_members = []
        sources_members = []
        for entry in members:
            member = _safe_member_path(entry.name)
            relative = PurePosixPath(*member.parts[1:])
            if entry.uid != 0 or entry.gid != 0 or entry.uname not in {"", "root"} or entry.gname not in {"", "root"}:
                failures.append(f"{entry.name} [non-public owner metadata]")
            if any(
                key != "mtime" or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)
                for key, value in entry.pax_headers.items()
            ):
                failures.append(f"{entry.name} [non-public PAX metadata]")
            if (
                member.parts[0] != root
                or relative.name in FORBIDDEN_METADATA_FILES
                or _is_sensitive_member_path(relative)
            ):
                failures.append(entry.name)
                continue
            if entry.isdir():
                directories.append(entry.name.rstrip("/"))
                continue
            if not entry.isfile() or not _is_sdist_file_allowed(relative):
                failures.append(entry.name)
                continue
            public_files.append(entry.name)
            extracted = archive.extractfile(entry)
            if extracted is None:
                failures.append(f"{entry.name} [unreadable]")
                continue
            _validate_public_content(extracted.read(), f"{path.name}:{relative.as_posix()}")
            if relative == PurePosixPath("PKG-INFO"):
                metadata_members.append(entry)
            if relative == PurePosixPath("src/gms_mcp.egg-info/SOURCES.txt"):
                sources_members.append(entry)
        for directory in directories:
            if directory != root and not any(name.startswith(f"{directory}/") for name in public_files):
                failures.append(f"{directory}/ [unexpected empty directory]")
        if failures:
            raise ArtifactPrivacyError(f"{path.name}: non-public sdist members: {sorted(failures)!r}")
        if len(metadata_members) != 1:
            raise ArtifactPrivacyError(f"{path.name}: expected exactly one root PKG-INFO file")
        metadata_file = archive.extractfile(metadata_members[0])
        if metadata_file is None:
            raise ArtifactPrivacyError(f"{path.name}: cannot read PKG-INFO")
        _validate_metadata(metadata_file.read(), f"{path.name}:PKG-INFO")
        if len(sources_members) != 1:
            raise ArtifactPrivacyError(f"{path.name}: expected exactly one SOURCES.txt file")
        sources_file = archive.extractfile(sources_members[0])
        if sources_file is None:
            raise ArtifactPrivacyError(f"{path.name}: cannot read SOURCES.txt")
        source_failures = []
        for line in sources_file.read().decode("utf-8").splitlines():
            source = _safe_member_path(line.strip())
            if _is_sensitive_member_path(source) or not _is_sdist_file_allowed(source):
                source_failures.append(line)
        if source_failures:
            raise ArtifactPrivacyError(
                f"{path.name}: SOURCES.txt exposes non-public paths: {sorted(source_failures)!r}"
            )


def verify_artifacts(paths: list[Path]) -> None:
    if len(paths) != 2:
        raise ArtifactPrivacyError(f"expected exactly one wheel and one sdist, found {len(paths)} entries")
    wheels = 0
    sdists = 0
    for path in paths:
        if path.suffix == ".whl":
            verify_wheel(path)
            wheels += 1
        elif path.name.endswith(".tar.gz"):
            verify_sdist(path)
            sdists += 1
        else:
            raise ArtifactPrivacyError(f"unsupported package artifact: {path}")
    if wheels == 0 or sdists == 0:
        raise ArtifactPrivacyError("verification requires at least one wheel and one sdist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)

    if args.path.is_dir():
        entries = sorted(args.path.iterdir())
        paths = []
        for entry in entries:
            if entry.name == ".gitignore" and entry.is_file() and entry.read_bytes() == b"*":
                continue
            paths.append(entry)
    else:
        paths = [args.path]
    try:
        verify_artifacts(paths)
    except (ArtifactPrivacyError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"package privacy check failed: {exc}\n")
    print(f"Package privacy check passed for {len(paths)} artifact(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
