"""Tests for the built-package privacy boundary."""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_package_artifacts import ArtifactPrivacyError, verify_artifacts, verify_sdist, verify_wheel


METADATA = b"Metadata-Version: 2.4\nName: gms-mcp\nVersion: 1.0\nAuthor: Ampersand Game Studios\n\n"


def _write_wheel(
    path: Path,
    extra_name: str | None = None,
    *,
    comment: bytes = b"",
    public_content: bytes = b"",
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = comment
        archive.writestr("gms_helpers/__init__.py", public_content)
        archive.writestr("gms_mcp-1.0.dist-info/METADATA", METADATA)
        archive.writestr("gms_mcp-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        archive.writestr("gms_mcp-1.0.dist-info/RECORD", "")
        if extra_name:
            archive.writestr(extra_name, "private")


def _write_sdist(
    path: Path,
    extra_name: str | None = None,
    *,
    private_owner: bool = False,
    public_content: bytes = b"",
) -> None:
    files = {
        "gms_mcp-1.0/PKG-INFO": METADATA,
        "gms_mcp-1.0/README.md": b"public\n",
        "gms_mcp-1.0/src/gms_mcp/__init__.py": public_content,
        "gms_mcp-1.0/src/gms_mcp.egg-info/PKG-INFO": METADATA,
        "gms_mcp-1.0/src/gms_mcp.egg-info/SOURCES.txt": (
            b"PKG-INFO\nREADME.md\nsrc/gms_mcp/__init__.py\nsrc/gms_mcp.egg-info/PKG-INFO\n"
            b"src/gms_mcp.egg-info/SOURCES.txt\n"
        ),
    }
    if extra_name:
        files[f"gms_mcp-1.0/{extra_name}"] = b"private"
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            if private_owner:
                info.uid = 501
                info.gid = 20
                info.uname = "local-user"
                info.gname = "local-group"
            archive.addfile(info, io.BytesIO(content))


def test_wheel_allowlist_accepts_public_runtime_files(tmp_path: Path) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    _write_wheel(wheel)
    verify_wheel(wheel)


@pytest.mark.parametrize(
    "private_path",
    [
        "gms_mcp-1.0.dist-info/scm_file_list.json",
        "gms_helpers/templates/private-project/object.create.gml",
        "docs/internal-review.md",
    ],
)
def test_wheel_allowlist_rejects_non_public_files(tmp_path: Path, private_path: str) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    _write_wheel(wheel, private_path)
    with pytest.raises(ArtifactPrivacyError):
        verify_wheel(wheel)


@pytest.mark.parametrize(
    "private_path",
    [
        "gms_mcp/.agents/session.json",
        "gms_mcp/.env.production",
        "gms_mcp/credentials.json",
        "gms_mcp/id_ed25519",
        "gms_mcp/release-signing.pem",
        "gms_mcp/reports/local.json",
    ],
)
def test_wheel_rejects_explicit_private_artifact_conventions(tmp_path: Path, private_path: str) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    _write_wheel(wheel, private_path)
    with pytest.raises(ArtifactPrivacyError):
        verify_wheel(wheel)


def test_wheel_rejects_archive_comment(tmp_path: Path) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    _write_wheel(wheel, comment=b"machine path /Users/private")
    with pytest.raises(ArtifactPrivacyError):
        verify_wheel(wheel)


def test_wheel_rejects_member_extra_metadata(tmp_path: Path) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    _write_wheel(wheel)
    rewritten = tmp_path / "rewritten.whl"
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(rewritten, "w") as target:
        for entry in source.infolist():
            copied = zipfile.ZipInfo(entry.filename)
            copied.extra = b"\x01\x00\x00\x00"
            target.writestr(copied, source.read(entry))
    with pytest.raises(ArtifactPrivacyError):
        verify_wheel(rewritten)


@pytest.mark.parametrize(
    "private_content",
    [
        b"-----BEGIN OPENSSH PRIVATE KEY-----",
        b"cache = /Users/private-user/project",
        b"cache = /home/private-user/project",
        b"endpoint = https://buildbox.studio.internal/api",
        b"endpoint = http://192.168.42.7/api",
        b"endpoint = http://[fd00::1234]/api",
        b"Authorization: Basic YWRtaW46c3VwZXJzZWNyZXQ=",
        b"token='abcdefghijklmnopqrstuvwxyz123456'",
        b'"client_secret": "abcdefghijklmnopqrstuvwxyz123456"',
        b"GITHUB_TOKEN=abcdefghijklmnopqrstuvwxyz123456",
        b"ghp_" + (b"a" * 24),
        b"sk-proj-" + (b"a" * 24),
    ],
)
def test_wheel_rejects_private_content_in_allowed_files(tmp_path: Path, private_content: bytes) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    _write_wheel(wheel, public_content=private_content)
    with pytest.raises(ArtifactPrivacyError):
        verify_wheel(wheel)


def test_sdist_allowlist_accepts_public_source_files(tmp_path: Path) -> None:
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_sdist(sdist)
    verify_sdist(sdist)


def test_sdist_allowlist_rejects_local_owner_metadata(tmp_path: Path) -> None:
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_sdist(sdist, private_owner=True)
    with pytest.raises(ArtifactPrivacyError):
        verify_sdist(sdist)


def test_metadata_rejects_maintainer_identity(tmp_path: Path) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    private_metadata = METADATA.replace(b"\n\n", b"\nMaintainer: Private Person\n\n")
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("gms_helpers/__init__.py", b"")
        archive.writestr("gms_mcp-1.0.dist-info/METADATA", private_metadata)
        archive.writestr("gms_mcp-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        archive.writestr("gms_mcp-1.0.dist-info/RECORD", "")
    with pytest.raises(ArtifactPrivacyError):
        verify_wheel(wheel)


def test_sdist_rejects_nonstandard_pax_metadata(tmp_path: Path) -> None:
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_sdist(sdist)
    rewritten = tmp_path / "rewritten.tar.gz"
    with tarfile.open(sdist, "r:gz") as source, tarfile.open(rewritten, "w:gz") as target:
        for entry in source.getmembers():
            extracted = source.extractfile(entry) if entry.isfile() else None
            entry.pax_headers = {"private.note": "local-only"}
            target.addfile(entry, extracted)
    with pytest.raises(ArtifactPrivacyError):
        verify_sdist(rewritten)


def test_sdist_rejects_private_content_in_allowed_source(tmp_path: Path) -> None:
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_sdist(sdist, public_content=b'password="abcdefghijklmnopqrstuvwxyz123456"')
    with pytest.raises(ArtifactPrivacyError):
        verify_sdist(sdist)


@pytest.mark.parametrize(
    "private_path",
    [
        "src/gms_mcp.egg-info/scm_version.json",
        "ops/service/archive.py",
        "cli/tests/python/test_private_fixture.py",
    ],
)
def test_sdist_allowlist_rejects_non_public_files(tmp_path: Path, private_path: str) -> None:
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_sdist(sdist, private_path)
    with pytest.raises(ArtifactPrivacyError):
        verify_sdist(sdist)


def test_artifact_set_rejects_extra_dist_files(tmp_path: Path) -> None:
    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    extra = tmp_path / "unexpected.txt"
    _write_wheel(wheel)
    _write_sdist(sdist)
    extra.write_text("must not be uploaded", encoding="utf-8")
    with pytest.raises(ArtifactPrivacyError):
        verify_artifacts([wheel, sdist, extra])


def test_cli_directory_contract_allows_uv_build_gitignore_only(tmp_path: Path) -> None:
    from scripts.verify_package_artifacts import main

    wheel = tmp_path / "gms_mcp-1.0-py3-none-any.whl"
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)
    (tmp_path / ".gitignore").write_bytes(b"*")
    assert main([str(tmp_path)]) == 0
