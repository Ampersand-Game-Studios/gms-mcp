"""Setuptools build hooks for repository-owned runtime assets."""

from pathlib import Path
from shutil import copy2, rmtree
import tarfile
from tempfile import NamedTemporaryFile

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.egg_info import egg_info as _egg_info
from setuptools.command.sdist import sdist as _sdist


SCM_METADATA_FILES = {"scm_file_list.json", "scm_version.json"}


class EggInfoWithoutRepositoryInventory(_egg_info):
    """Remove SCM metadata that reveals the repository file list and commit."""

    def run(self) -> None:
        super().run()
        egg_info = Path(self.egg_info)
        for filename in SCM_METADATA_FILES:
            (egg_info / filename).unlink(missing_ok=True)

        sources = egg_info / "SOURCES.txt"
        if sources.is_file():
            public_lines = [
                line
                for line in sources.read_text(encoding="utf-8").splitlines()
                if Path(line).name not in SCM_METADATA_FILES
            ]
            sources.write_text("\n".join(public_lines) + "\n", encoding="utf-8")


class SdistWithoutLocalOwnership(_sdist):
    """Normalize tar ownership so package headers do not expose the build host."""

    def make_distribution(self) -> None:
        super().make_distribution()
        for archive_name in self.archive_files:
            archive_path = Path(archive_name)
            if not archive_path.name.endswith(".tar.gz"):
                continue
            with NamedTemporaryFile(dir=archive_path.parent, suffix=".tar.gz", delete=False) as temporary:
                temporary_path = Path(temporary.name)
            try:
                with tarfile.open(archive_path, "r:gz") as source, tarfile.open(temporary_path, "w:gz") as target:
                    for member in source.getmembers():
                        member.uid = 0
                        member.gid = 0
                        member.uname = "root"
                        member.gname = "root"
                        file_handle = source.extractfile(member) if member.isfile() else None
                        target.addfile(member, file_handle)
                temporary_path.replace(archive_path)
            finally:
                temporary_path.unlink(missing_ok=True)


class BuildPyWithBundleAssets(_build_py):
    """Copy the canonical plugin bundle into the importable wheel package."""

    def run(self) -> None:
        repository_root = Path(__file__).resolve().parent
        build_lib = Path(self.build_lib)
        if build_lib.exists():
            rmtree(build_lib)
        super().run()
        bundle_root = build_lib / "gms_helpers" / "bundle"

        public_suffixes = {"skills": {".md"}, "hooks": {".json", ".sh"}}
        for directory_name, allowed_suffixes in public_suffixes.items():
            source = repository_root / directory_name
            if not source.is_dir():
                raise RuntimeError(f"Required bundle source is missing: {source}")
            for source_file in source.rglob("*"):
                if not source_file.is_file() or source_file.suffix not in allowed_suffixes:
                    continue
                if source_file.is_symlink():
                    raise RuntimeError(f"Bundle source must not be a symlink: {source_file}")
                destination = bundle_root / directory_name / source_file.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                copy2(source_file, destination)


setup(
    cmdclass={
        "build_py": BuildPyWithBundleAssets,
        "egg_info": EggInfoWithoutRepositoryInventory,
        "sdist": SdistWithoutLocalOwnership,
    }
)
