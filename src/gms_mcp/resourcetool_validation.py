"""Opt-in, isolated validation through an explicitly configured ResourceTool.

ResourceTool's command-line contract is deliberately not assumed here.  A
caller must configure the official executable and the fixed read-only
``resource list`` argv contract with one ``{project_copy_yyp}`` placeholder.
The original project is never passed to the executable.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping


RESOURCETOOL_ENABLED_ENV = "GMS_MCP_RESOURCETOOL_ENABLED"
RESOURCETOOL_EXECUTABLE_ENV = "GMS_MCP_RESOURCETOOL_EXECUTABLE"
RESOURCETOOL_ARGUMENTS_ENV = "GMS_MCP_RESOURCETOOL_ARGUMENTS_JSON"
RESOURCETOOL_SHA256_ENV = "GMS_MCP_RESOURCETOOL_SHA256"
DEFAULT_TIMEOUT_SECONDS = 90
MAX_TIMEOUT_SECONDS = 600
MAX_OUTPUT_CHARS = 4_096

_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/][^\s\"']+|/(?:[^\s\"']+))")
_SECRET_VALUE = re.compile(
    r"(?i)\b([a-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|authorization|cookie)[a-z0-9_.-]*)"
    r"\s*([=:])\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"sk-(?:proj|svcacct)-[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_BASIC_VALUE = re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{16,}")
_DESCRIPTOR_PRIVATE_CONTENT = (
    re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|xox[baprs]-[A-Za-z0-9-]{20,})"),
    re.compile(rb"sk-(?:proj|svcacct)-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(
        rb"(?i)['\"]?[A-Za-z0-9_.-]*(?:api[_-]?key|password|passwd|secret|token)['\"]?\s*[=:]\s*"
        rb"(?:(['\"])[A-Za-z0-9+/_.-]{16,}\1|[A-Za-z0-9+/_-]{16,}(?![A-Za-z0-9+/_-]))"
    ),
)
_PRIVATE_COMPONENTS = {".agents", ".git", ".idea", ".ssh", ".vscode", "credentials", "private", "secrets"}
_PRIVATE_FILENAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
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
_PRIVATE_SUFFIXES = {".key", ".mobileprovision", ".p12", ".pem", ".pfx"}
_OFFICIAL_ARGUMENTS = ["resourcetool", "eval", "resource list", "{project_copy_yyp}"]


def _safe_text(value: object, *, private_paths: tuple[Path, ...] = ()) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    for private_path in private_paths:
        text = text.replace(str(private_path), "<project>")
    text = _ABSOLUTE_PATH.sub("<path>", text)
    text = _BEARER_VALUE.sub("Bearer [REDACTED]", text)
    text = _BASIC_VALUE.sub("Basic [REDACTED]", text)
    text = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    text = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _KNOWN_TOKEN.sub("[REDACTED]", text)
    text = " ".join(text.replace("\x00", " ").split())
    if len(text) > MAX_OUTPUT_CHARS:
        return f"{text[:MAX_OUTPUT_CHARS].rstrip()}…"
    return text


def _manifest(project_root: Path) -> dict[str, str]:
    """Hash every regular project file, rejecting symlinks before copying."""
    entries: dict[str, str] = {}
    for current_root, directory_names, file_names in os.walk(project_root, followlinks=False):
        current = Path(current_root)
        for directory_name in directory_names:
            if (current / directory_name).is_symlink():
                raise ValueError("The project contains a filesystem link and cannot be isolated safely.")
        for file_name in file_names:
            path = current / file_name
            if path.is_symlink():
                raise ValueError("The project contains a filesystem link and cannot be isolated safely.")
            if not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1_048_576), b""):
                    digest.update(block)
            entries[path.relative_to(project_root).as_posix()] = digest.hexdigest()
    return entries


def _private_project_member(project_root: Path) -> str | None:
    """Return a generic reason when known private material is inside a project."""
    for path in project_root.rglob("*"):
        relative = path.relative_to(project_root)
        lowered_parts = {part.lower() for part in relative.parts}
        name = path.name.lower()
        if (
            lowered_parts & _PRIVATE_COMPONENTS
            or name in _PRIVATE_FILENAMES
            or name.startswith(".env.")
            or path.suffix.lower() in _PRIVATE_SUFFIXES
        ):
            return "known_private_path"
    return None


def _manifest_checksum(manifest: Mapping[str, str]) -> str:
    payload = json.dumps(dict(sorted(manifest.items())), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _descriptor_contains_private_content(path: Path) -> bool:
    try:
        content = path.read_bytes()
    except OSError:
        return True
    return any(pattern.search(content) for pattern in _DESCRIPTOR_PRIVATE_CONTENT)


def _bounded_timeout(value: object) -> int:
    if not isinstance(value, (int, str)):
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return min(MAX_TIMEOUT_SECONDS, max(1, timeout))


def _configured_command(environ: Mapping[str, str]) -> tuple[list[str] | None, str | None]:
    if environ.get(RESOURCETOOL_ENABLED_ENV, "").strip() != "1":
        return None, "disabled"
    executable_raw = environ.get(RESOURCETOOL_EXECUTABLE_ENV, "").strip()
    executable = Path(executable_raw).expanduser()
    if (
        not executable_raw
        or not executable.is_absolute()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
    ):
        return None, "invalid_executable"
    if executable.name.lower() not in {"gm-cli", "gm-cli.exe"}:
        return None, "invalid_executable"
    expected_sha256 = environ.get(RESOURCETOOL_SHA256_ENV, "").strip().lower()
    try:
        identity_matches = bool(re.fullmatch(r"[a-f0-9]{64}", expected_sha256)) and (
            _sha256_file(executable) == expected_sha256
        )
    except OSError:
        identity_matches = False
    if not identity_matches:
        return None, "executable_identity_mismatch"
    arguments_raw = environ.get(RESOURCETOOL_ARGUMENTS_ENV, "").strip()
    try:
        arguments = json.loads(arguments_raw)
    except json.JSONDecodeError:
        return None, "invalid_arguments"
    if not isinstance(arguments, list) or not all(isinstance(argument, str) for argument in arguments):
        return None, "invalid_arguments"
    if arguments != _OFFICIAL_ARGUMENTS:
        return None, "invalid_arguments"
    return [str(executable), *arguments], None


def _sanitized_environment(environ: Mapping[str, str], temp_root: Path) -> dict[str, str]:
    """Pass only platform bootstrap values; project/user environment is not inherited."""
    safe = {
        "HOME": str(temp_root),
        "LANG": "C",
        "LC_ALL": "C",
        "TMPDIR": str(temp_root),
        "XDG_CACHE_HOME": str(temp_root / "cache"),
        "XDG_CONFIG_HOME": str(temp_root / "config"),
    }
    if os.name == "nt":
        safe["USERPROFILE"] = str(temp_root)
    else:
        safe["PATH"] = "/usr/bin:/bin"
    for key in ("SystemRoot", "WINDIR", "COMSPEC"):
        value = environ.get(key)
        if value:
            safe[key] = value
    return safe


def _public_result(*, ok: bool, status: str, **details: Any) -> dict[str, Any]:
    return {"ok": ok, "status": status, **details}


def _copy_only_command(command_template: list[str], copied_project_file: Path) -> list[str]:
    """Materialize the single fixed official read-only command contract."""
    return [copied_project_file.as_posix() if item == "{project_copy_yyp}" else item for item in command_template]


def _sandboxed_command(command: list[str], *, source: Path, temporary_root: Path) -> list[str] | None:
    """Wrap the pinned executable so it cannot access the live project, network, or writable host paths."""
    system = platform.system()
    if system == "Darwin" and Path("/usr/bin/sandbox-exec").is_file():
        escaped_source = str(source).replace("\\", "\\\\").replace('"', '\\"')
        escaped_temp = str(temporary_root).replace("\\", "\\\\").replace('"', '\\"')
        profile_path = temporary_root / "resourcetool.sb"
        profile_path.write_text(
            "\n".join(
                (
                    "(version 1)",
                    "(allow default)",
                    "(deny network*)",
                    f'(deny file-read* (subpath "{escaped_source}"))',
                    f'(deny file-write* (require-not (subpath "{escaped_temp}")))',
                )
            ),
            encoding="utf-8",
        )
        return ["/usr/bin/sandbox-exec", "-f", str(profile_path), *command]
    if system == "Linux":
        bwrap = shutil.which("bwrap", path="/usr/bin:/bin")
        if bwrap:
            return [
                bwrap,
                "--die-with-parent",
                "--unshare-all",
                "--new-session",
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                str(source),
                "--bind",
                str(temporary_root),
                str(temporary_root),
                "--chdir",
                str(temporary_root / "project"),
                *command,
            ]
    return None


def validate_with_resourcetool(
    project_root: str | Path,
    *,
    timeout_seconds: object = DEFAULT_TIMEOUT_SECONDS,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate a fully copied project without revealing local paths or configuration."""
    environment = os.environ if environ is None else environ
    command_template, configuration_error = _configured_command(environment)
    if configuration_error is not None:
        return _public_result(
            ok=False,
            status=configuration_error,
            executed=False,
            evidence={"copy_created": False, "cleanup_completed": True},
        )
    assert command_template is not None

    source = Path(project_root)
    project_files = sorted(source.glob("*.yyp")) if source.is_dir() else []
    if not source.is_absolute() or source.is_symlink() or len(project_files) != 1:
        return _public_result(
            ok=False,
            status="invalid_project",
            executed=False,
            evidence={"copy_created": False, "cleanup_completed": True},
        )
    if _private_project_member(source) is not None or _descriptor_contains_private_content(project_files[0]):
        return _public_result(
            ok=False,
            status="private_project_data",
            executed=False,
            evidence={"copy_created": False, "cleanup_completed": True},
        )

    timeout = _bounded_timeout(timeout_seconds)
    with tempfile.TemporaryDirectory(prefix="gms-mcp-resourcetool-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        copy_root = temporary_root / "project"
        private_paths = (source, copy_root, temporary_root)
        try:
            _manifest(source)
            copy_root.mkdir()
            shutil.copy2(project_files[0], copy_root / project_files[0].name, follow_symlinks=False)
            before = _manifest(copy_root)
            copied = _manifest(copy_root)
        except (OSError, ValueError) as error:
            return _public_result(
                ok=False,
                status="copy_failed",
                executed=False,
                evidence={"copy_created": copy_root.exists(), "cleanup_completed": True},
                error=_safe_text(error, private_paths=private_paths),
            )
        if copied != before:
            return _public_result(
                ok=False,
                status="copy_mismatch",
                executed=False,
                evidence={
                    "copy_created": True,
                    "cleanup_completed": True,
                    "source_checksum": _manifest_checksum(before),
                    "copy_checksum": _manifest_checksum(copied),
                    "file_count": len(before),
                },
            )

        command = _copy_only_command(command_template, copy_root / project_files[0].name)
        sandboxed_command = _sandboxed_command(command, source=source, temporary_root=temporary_root)
        if sandboxed_command is None:
            return _public_result(
                ok=False,
                status="sandbox_unavailable",
                executed=False,
                evidence={"copy_created": True, "cleanup_completed": True},
            )
        try:
            completed = subprocess.run(
                sandboxed_command,
                cwd=copy_root,
                env=_sanitized_environment(environment, temporary_root),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            after = _manifest(copy_root)
            return _public_result(
                ok=False,
                status="timeout",
                executed=True,
                evidence={
                    "copy_created": True,
                    "cleanup_completed": True,
                    "before_checksum": _manifest_checksum(before),
                    "after_checksum": _manifest_checksum(after),
                    "rewritten_copy": after != before,
                    "file_count": len(before),
                    "timeout_seconds": timeout,
                },
                output_suppressed=True,
            )
        except OSError as error:
            after = _manifest(copy_root)
            return _public_result(
                ok=False,
                status="execution_failed",
                executed=True,
                evidence={
                    "copy_created": True,
                    "cleanup_completed": True,
                    "before_checksum": _manifest_checksum(before),
                    "after_checksum": _manifest_checksum(after),
                    "rewritten_copy": after != before,
                    "file_count": len(before),
                },
                error=_safe_text(error, private_paths=private_paths),
            )

        after = _manifest(copy_root)
        rewritten = after != before
        status = (
            "validated"
            if completed.returncode == 0 and not rewritten
            else "rewrote_copy"
            if rewritten
            else "validation_failed"
        )
        return _public_result(
            ok=status == "validated",
            status=status,
            executed=True,
            evidence={
                "copy_created": True,
                "cleanup_completed": True,
                "before_checksum": _manifest_checksum(before),
                "after_checksum": _manifest_checksum(after),
                "rewritten_copy": rewritten,
                "file_count": len(before),
                "timeout_seconds": timeout,
            },
            process={"exit_code": completed.returncode},
            output_suppressed=True,
        )
