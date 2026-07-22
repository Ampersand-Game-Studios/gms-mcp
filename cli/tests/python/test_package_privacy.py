"""Tests for the built-package privacy boundary."""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_package_artifacts import ArtifactPrivacyError, verify_artifacts, verify_sdist, verify_wheel


METADATA = b"Metadata-Version: 2.4\nName: gms-mcp\nVersion: 1.0\nAuthor: Ampersand Game Studios\n\n"


def _write_wheel(path: Path, extra_name: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("gms_helpers/__init__.py", "")
        archive.writestr("gms_mcp-1.0.dist-info/METADATA", METADATA)
        archive.writestr("gms_mcp-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        archive.writestr("gms_mcp-1.0.dist-info/RECORD", "")
        if extra_name:
            archive.writestr(extra_name, "private")


def _write_sdist(path: Path, extra_name: str | None = None, *, private_owner: bool = False) -> None:
    files = {
        "gms_mcp-1.0/PKG-INFO": METADATA,
        "gms_mcp-1.0/README.md": b"public\n",
        "gms_mcp-1.0/src/gms_mcp/__init__.py": b"",
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


def test_sdist_allowlist_accepts_public_source_files(tmp_path: Path) -> None:
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_sdist(sdist)
    verify_sdist(sdist)


def test_sdist_allowlist_rejects_local_owner_metadata(tmp_path: Path) -> None:
    sdist = tmp_path / "gms_mcp-1.0.tar.gz"
    _write_sdist(sdist, private_owner=True)
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
