"""Setuptools build hooks for repository-owned runtime assets."""

from pathlib import Path
from shutil import copytree, rmtree

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class BuildPyWithBundleAssets(_build_py):
    """Copy the canonical plugin bundle into the importable wheel package."""

    def run(self) -> None:
        repository_root = Path(__file__).resolve().parent
        build_lib = Path(self.build_lib)
        if build_lib.exists():
            rmtree(build_lib)
        super().run()
        bundle_root = build_lib / "gms_helpers" / "bundle"

        for directory_name in ("skills", "hooks"):
            source = repository_root / directory_name
            if not source.is_dir():
                raise RuntimeError(f"Required bundle source is missing: {source}")
            copytree(source, bundle_root / directory_name, dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildPyWithBundleAssets})
