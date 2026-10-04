#!/usr/bin/env python3
"""Build twice with locked tooling; publish only identical privacy-checked artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def normalize_sdist(path: Path, epoch: int) -> None:
    """Canonicalize gzip/tar metadata not controlled by SOURCE_DATE_EPOCH."""
    replacement = path.with_suffix(".normalized")
    try:
        with tarfile.open(path, "r:gz") as source, replacement.open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=epoch) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                    for member in sorted(source.getmembers(), key=lambda item: item.name):
                        member.mtime = epoch
                        member.uid = member.gid = 0
                        member.uname = member.gname = ""
                        member.pax_headers = {}
                        payload = source.extractfile(member) if member.isfile() else None
                        try:
                            target.addfile(member, payload)
                        finally:
                            if payload is not None:
                                payload.close()
        replacement.replace(path)
    finally:
        replacement.unlink(missing_ok=True)


def artifact_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def build_reproducibly(output: Path) -> dict[str, str]:
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Release output must be an empty directory; existing artifacts are never overwritten.")
    epoch = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True).strip())
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch), "PYTHONHASHSEED": "0"}
    with tempfile.TemporaryDirectory(prefix="gms-release-reproducibility-") as temporary:
        first = Path(temporary) / "first"
        second = Path(temporary) / "second"
        for directory in (first, second):
            subprocess.run(
                [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(directory)],
                cwd=ROOT,
                env=env,
                check=True,
            )
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/verify_package_artifacts.py"), str(directory)],
                cwd=ROOT,
                env=env,
                check=True,
            )
            for archive in directory.glob("*.tar.gz"):
                normalize_sdist(archive, epoch)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/verify_package_artifacts.py"), str(directory)],
                cwd=ROOT,
                env=env,
                check=True,
            )
        hashes = artifact_hashes(first)
        if len(hashes) != 2 or hashes != artifact_hashes(second):
            raise RuntimeError("Release builds are not byte-identical; no artifacts were exported.")
        output.mkdir(parents=True, exist_ok=True)
        for path in first.iterdir():
            shutil.copy2(path, output / path.name)
        return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    hashes = build_reproducibly(args.output_dir.resolve())
    for name, digest in hashes.items():
        print(f"[OK] Reproducible privacy-checked artifact {name}: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
