#!/usr/bin/env python3
"""Install an approved GameMaker runtime on a disposable GitHub runner."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


APPROVED_RUNTIME_FEEDS = {
    "2024.14.4.268": "https://gms.yoyogames.com/Zeus-Runtime.rss",
    "2026.0.0.23": "https://gms.yoyogames.com/Zeus-Runtime-LTS2026.rss",
}


@dataclass(frozen=True)
class HostConfig:
    slug: str
    bootstrap_url: str
    bootstrap_sha256: str
    bootstrap_igor: str
    modules: str
    runtime_igor: str
    post_install_scripts: tuple[str, ...] = ()


HOST_CONFIGS = {
    ("Darwin", "arm64"): HostConfig(
        slug="macos",
        bootstrap_url="https://gms.yoyogames.com/igor_osx-arm64.zip",
        bootstrap_sha256="850260ede5f591000533d760a2c0379bd753e5a6ebb0db30e1003c7957ca1599",
        bootstrap_igor="osx/arm64/Igor",
        modules="mac,base-module-osx-arm64",
        runtime_igor="bin/igor/osx/arm64/Igor",
        post_install_scripts=("bin/mac-post-install.sh", "bin/mac-optimise-runtime.sh"),
    ),
    ("Windows", "x64"): HostConfig(
        slug="windows",
        bootstrap_url="https://gms.yoyogames.com/igor_win-x64.zip",
        bootstrap_sha256="2036f66ac7c3a5d195434a4be528d6d9b62bffd89a65bd664c174168749bc561",
        bootstrap_igor="windows/x64/Igor.exe",
        modules="windows,base-module-windows-x64",
        runtime_igor="bin/igor/windows/x64/Igor.exe",
    ),
    ("Linux", "x64"): HostConfig(
        slug="linux",
        bootstrap_url="https://gms.yoyogames.com/igor_linux-x64.zip",
        bootstrap_sha256="ffebba4bfc90de0a6fe23f9767179bdd4336d10358555a7e3e649d6aeb91ddc0",
        bootstrap_igor="linux/x64/Igor",
        modules="linux,base-module-linux-x64",
        runtime_igor="bin/igor/linux/x64/Igor",
    ),
}


class SetupError(RuntimeError):
    """A privacy-safe GameMaker CI setup failure."""


def _normalize_arch(machine: str) -> str:
    normalized = machine.strip().lower()
    if normalized in {"amd64", "x86_64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    return normalized


def detect_host_config() -> HostConfig:
    key = (platform.system(), _normalize_arch(platform.machine()))
    config = HOST_CONFIGS.get(key)
    if config is None:
        raise SetupError(f"unsupported disposable runner platform: {key[0]} {key[1]}")
    return config


def _github_paths() -> tuple[Path, Path]:
    runner_temp = os.environ.get("RUNNER_TEMP")
    github_env = os.environ.get("GITHUB_ENV")
    if not runner_temp or not github_env:
        raise SetupError("setup must run inside GitHub Actions")
    return Path(runner_temp), Path(github_env)


def _download_verified(url: str, expected_sha256: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "gms-mcp-ci"})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
    except OSError as exc:
        raise SetupError("official GameMaker bootstrap download failed") from exc
    if digest.hexdigest() != expected_sha256:
        raise SetupError("GameMaker bootstrap checksum mismatch; refusing to execute it")


def _extract_verified_zip(archive: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                member_path = (destination / member.filename).resolve()
                if not member_path.is_relative_to(destination_root):
                    raise SetupError("GameMaker bootstrap archive contains an unsafe path")
            bundle.extractall(destination)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SetupError("verified GameMaker bootstrap could not be extracted") from exc


def _run_private(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    failure: str,
) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(failure) from exc
    if result.returncode != 0:
        raise SetupError(failure)


def _finalize_linux_runtime(runtime_dir: Path) -> None:
    executable_paths = (
        "bin/igor/linux/x64/Igor",
        "bin/assetcompiler/linux/x64/GMAssetCompiler",
        "bin/webserver/linux/x64/GMWebServer",
    )
    for relative_path in executable_paths:
        executable = runtime_dir / relative_path
        if executable.is_file():
            executable.chmod(0o700)

    igor_dir = runtime_dir / "bin/igor/linux/x64"
    required_links = {
        "FiltersAndEffects": "../../../FiltersAndEffects",
        "ParticleImages": "../../../assetcompiler/ParticleImages",
        "Shaders": "../../../assetcompiler/Shaders",
        "BuiltinFonts": "../../../assetcompiler/BuiltinFonts",
    }
    for link_name, relative_target in required_links.items():
        link = igor_dir / link_name
        if link.is_symlink():
            if os.readlink(link) == relative_target:
                continue
            link.unlink()
        elif link.exists():
            continue
        link.symlink_to(relative_target, target_is_directory=True)


def _append_github_env(github_env: Path, values: dict[str, str]) -> None:
    for value in values.values():
        if "\n" in value or "\r" in value:
            raise SetupError("refusing to write an unsafe GitHub environment value")
    with github_env.open("a", encoding="utf-8", newline="\n") as env_file:
        for name, value in values.items():
            env_file.write(f"{name}={value}\n")


def cleanup_ephemeral_license() -> None:
    runner_temp, github_env = _github_paths()
    shutil.rmtree(runner_temp / "gms-mcp-gamemaker-user", ignore_errors=True)
    _append_github_env(github_env, {"GMS_MCP_LICENSE_FILE": ""})


def install_runtime(runtime_version: str) -> str:
    runtime_feed = APPROVED_RUNTIME_FEEDS.get(runtime_version)
    if runtime_feed is None:
        raise SetupError(f"refusing to install unapproved GameMaker runtime {runtime_version}")

    access_key = os.environ.get("GAMEMAKER_ACCESS_KEY")
    if not access_key:
        raise SetupError("GAMEMAKER_ACCESS_KEY secret is unavailable")

    host = detect_host_config()
    runner_temp, github_env = _github_paths()
    runtime_root = runner_temp / "gms-mcp-runtimes"
    runtime_dir = runtime_root / f"runtime-{runtime_version}"
    user_dir = runner_temp / "gms-mcp-gamemaker-user"
    license_file = user_dir / "licence.plist"

    shutil.rmtree(runtime_root, ignore_errors=True)
    shutil.rmtree(user_dir, ignore_errors=True)
    runtime_root.mkdir(parents=True)
    user_dir.mkdir(mode=0o700, parents=True)

    try:
        with tempfile.TemporaryDirectory(prefix="gms-mcp-igor-", dir=runner_temp) as temp_dir:
            bootstrap_root = Path(temp_dir) / "bootstrap"
            bootstrap_zip = Path(temp_dir) / "igor.zip"
            bootstrap_root.mkdir()
            _download_verified(host.bootstrap_url, host.bootstrap_sha256, bootstrap_zip)
            _extract_verified_zip(bootstrap_zip, bootstrap_root)
            bootstrap_igor = bootstrap_root / host.bootstrap_igor
            if not bootstrap_igor.is_file():
                raise SetupError("verified GameMaker bootstrap did not contain Igor")
            if platform.system() != "Windows":
                bootstrap_igor.chmod(0o700)

            # GameMaker requires the access key as a process argument. Neither the
            # command nor vendor output is written to the public Actions log.
            _run_private(
                [
                    str(bootstrap_igor),
                    "runtime",
                    "FetchLicense",
                    f"-ak={access_key}",
                    f"-of={license_file}",
                ],
                cwd=bootstrap_igor.parent,
                timeout=120,
                failure="GameMaker failed to create an ephemeral licence",
            )
            os.environ.pop("GAMEMAKER_ACCESS_KEY", None)
            access_key = ""

            if not license_file.is_file() or license_file.stat().st_size == 0:
                raise SetupError("GameMaker did not create a usable ephemeral licence")
            if platform.system() != "Windows":
                license_file.chmod(0o600)

            _run_private(
                [
                    str(bootstrap_igor),
                    f"/rp={runtime_root}",
                    f"/ru={runtime_feed}",
                    f"/uf={user_dir}",
                    f"/m={host.modules}",
                    "--",
                    "Runtime",
                    "Install",
                    runtime_version,
                ],
                cwd=bootstrap_igor.parent,
                timeout=900,
                failure=f"GameMaker failed to install approved runtime {runtime_version}",
            )

        for relative_script in host.post_install_scripts:
            post_install = runtime_dir / relative_script
            if post_install.is_file():
                post_install.chmod(0o700)
                _run_private(
                    ["sh", str(post_install)],
                    cwd=runtime_dir,
                    timeout=300,
                    failure=f"GameMaker {host.slug} post-install failed",
                )

        if host.slug == "linux":
            # The 2024 vendor script exits while probing uninstalled ARM
            # directories before it reaches x64. Apply its required operations
            # only to the x64 module this runner actually installed.
            _finalize_linux_runtime(runtime_dir)

        runtime_igor = runtime_dir / host.runtime_igor
        if not (runtime_dir / "receipt.json").is_file():
            raise SetupError("installed GameMaker runtime has no receipt")
        if not (runtime_dir / "manifest").is_dir():
            raise SetupError("installed GameMaker runtime has no manifest")
        if not runtime_igor.is_file():
            raise SetupError("installed GameMaker runtime has no Igor executable")
        if platform.system() != "Windows":
            runtime_igor.chmod(0o700)

        _append_github_env(
            github_env,
            {
                "GMS_MCP_RUNTIME_ROOT": str(runtime_root),
                "GMS_MCP_LICENSE_FILE": str(license_file),
            },
        )
    except Exception:
        shutil.rmtree(user_dir, ignore_errors=True)
        raise

    return host.slug


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_version", nargs="?", help="Exact approved GameMaker runtime version")
    parser.add_argument("--cleanup", action="store_true", help="Delete the ephemeral GameMaker licence")
    args = parser.parse_args()
    if args.cleanup == bool(args.runtime_version):
        parser.error("provide either a runtime version or --cleanup")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.cleanup:
            cleanup_ephemeral_license()
            print("Deleted the ephemeral GameMaker licence.")
        else:
            host_slug = install_runtime(str(args.runtime_version))
            print(f"Installed approved GameMaker runtime {args.runtime_version} on disposable {host_slug} runner.")
    except SetupError as exc:
        print(f"GameMaker CI setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
