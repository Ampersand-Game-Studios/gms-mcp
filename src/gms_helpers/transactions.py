"""Transactional safety helpers for GameMaker project mutations."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .exceptions import ValidationError
from .utils import load_json_loose


_IGNORED_DIR_NAMES = {
    ".git",
    ".gms_mcp",
    ".gms-mcp",
    ".gml_index_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
_IGNORED_FILE_NAMES = {
    ".coverage",
    ".gml_index_cache.json",
    "mcp_tool_smoke_report.json",
}


@dataclass
class ProjectValidationResult:
    success: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    yyp: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TransactionValidationError(ValidationError):
    """Raised when a project mutation was rolled back after validation failed."""


def _is_ignored_path(path: Path) -> bool:
    return any(part in _IGNORED_DIR_NAMES for part in path.parts) or path.name in _IGNORED_FILE_NAMES


def _iter_project_files(project_root: Path) -> Iterable[Path]:
    for path in project_root.rglob("*"):
        if _is_ignored_path(path.relative_to(project_root)):
            continue
        if path.is_file():
            yield path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_state(project_root: Path) -> Dict[str, str]:
    state: Dict[str, str] = {}
    for path in _iter_project_files(project_root):
        rel = path.relative_to(project_root).as_posix()
        try:
            state[rel] = _hash_file(path)
        except OSError:
            continue
    return state


def _summarize_changes(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    created = sorted(after_keys - before_keys)
    deleted = sorted(before_keys - after_keys)
    modified = sorted(path for path in before_keys & after_keys if before[path] != after[path])
    return {
        "created_count": len(created),
        "modified_count": len(modified),
        "deleted_count": len(deleted),
        "changed_count": len(created) + len(modified) + len(deleted),
        "created": created[:50],
        "modified": modified[:50],
        "deleted": deleted[:50],
        "truncated": len(created) > 50 or len(modified) > 50 or len(deleted) > 50,
    }


def _safe_relative_path(project_root: Path, relative_path: str) -> Path | None:
    try:
        if not relative_path or Path(relative_path).is_absolute():
            return None
        candidate = (project_root / relative_path).resolve()
        candidate.relative_to(project_root.resolve())
        return candidate
    except (OSError, ValueError):
        return None


def validate_project_after_mutation(project_root: str | Path) -> ProjectValidationResult:
    """Validate JSON structure, resource paths, and parent-folder links after a mutation."""
    root = Path(project_root).resolve()
    result = ProjectValidationResult(success=True)

    yyp_files = sorted(root.glob("*.yyp"))
    if not yyp_files:
        result.errors.append(f"No .yyp file found in {root}")
        result.success = False
        return result
    if len(yyp_files) > 1:
        result.warnings.append(f"Multiple .yyp files found; validating {yyp_files[0].name}")

    yyp_path = yyp_files[0]
    result.yyp = yyp_path.name
    yyp_data = load_json_loose(yyp_path)
    if not isinstance(yyp_data, dict):
        result.errors.append(f"Invalid project JSON: {yyp_path.name}")
        result.success = False
        return result

    for json_path in sorted([*root.rglob("*.yyp"), *root.rglob("*.yy")]):
        rel = json_path.relative_to(root)
        if _is_ignored_path(rel):
            continue
        if load_json_loose(json_path) is None:
            result.errors.append(f"Invalid JSON: {rel.as_posix()}")

    folders = yyp_data.get("Folders", []) or []
    defined_folders = {folder.get("folderPath") for folder in folders if isinstance(folder, dict)}
    resources = yyp_data.get("resources", []) or []

    for resource in resources:
        if not isinstance(resource, dict):
            result.errors.append("Malformed .yyp resource entry")
            continue
        resource_id = resource.get("id", {})
        if not isinstance(resource_id, dict):
            result.errors.append("Malformed .yyp resource id")
            continue

        name = resource_id.get("name")
        path_value = resource_id.get("path")
        if not isinstance(name, str) or not isinstance(path_value, str):
            result.errors.append(f"Malformed .yyp resource entry: {resource_id!r}")
            continue

        asset_path = _safe_relative_path(root, path_value)
        if asset_path is None:
            result.errors.append(f"Resource '{name}' has unsafe path '{path_value}'")
            continue
        if not asset_path.exists():
            result.errors.append(f"Resource '{name}' points to missing file '{path_value}'")
            continue

        asset_data = load_json_loose(asset_path)
        if not isinstance(asset_data, dict):
            continue
        parent = asset_data.get("parent", {})
        parent_path = parent.get("path") if isinstance(parent, dict) else None
        if not parent_path:
            result.warnings.append(f"Resource '{name}' has no parent path")
            continue
        if isinstance(parent_path, str) and parent_path.lower().endswith(".yyp"):
            continue
        if parent_path not in defined_folders:
            result.errors.append(f"Resource '{name}' references missing parent folder '{parent_path}'")

    result.success = not result.errors
    return result


def _copy_ignore(_directory: str, names: List[str]) -> set[str]:
    return {name for name in names if name in _IGNORED_DIR_NAMES or name in _IGNORED_FILE_NAMES}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def should_compile_verify_after_mutation() -> bool:
    mode = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY", "").strip().lower()
    return mode in {"1", "true", "yes", "on", "compile", "ide"} or _env_truthy(
        "GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION"
    )


def compile_verify_project(
    project_root: str | Path,
    *,
    platform: str | None = None,
    runtime: str | None = None,
    timeout_seconds: int | None = None,
) -> Dict[str, Any]:
    if timeout_seconds is None:
        timeout_raw = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY_TIMEOUT_SECONDS", "1800").strip()
        try:
            timeout_seconds = max(1, int(timeout_raw))
        except ValueError:
            timeout_seconds = 1800

    selected_runtime = (runtime or os.environ.get("GMS_MCP_POST_MUTATION_RUNTIME", "VM")).strip() or "VM"
    selected_platform = (platform or os.environ.get("GMS_MCP_POST_MUTATION_PLATFORM", "")).strip()
    root = Path(project_root).resolve()
    if not selected_platform:
        from .runner import detect_default_target_platform

        selected_platform = detect_default_target_platform()

    cmd = [
        sys.executable,
        "-u",
        "-m",
        "gms_helpers.gms",
        "--project-root",
        str(root),
        "run",
        "compile",
        "--platform",
        selected_platform,
        "--runtime",
        selected_runtime,
    ]
    started = time.monotonic()
    completed = subprocess.run(
        cmd,
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    elapsed = time.monotonic() - started
    ok = completed.returncode == 0
    return {
        "ok": ok,
        "mode": "compile",
        "platform": selected_platform,
        "runtime": selected_runtime,
        "exit_code": completed.returncode,
        "elapsed_seconds": elapsed,
        "stdout_tail": "\n".join((completed.stdout or "").splitlines()[-80:]),
        "stderr_tail": "\n".join((completed.stderr or "").splitlines()[-80:]),
    }


def _compile_verification(project_root: Path) -> Dict[str, Any]:
    return compile_verify_project(project_root)


class GameMakerProjectTransaction:
    """Snapshot a GameMaker project, then rollback if mutation or validation fails."""

    def __init__(self, project_root: str | Path, tool_name: str):
        self.project_root = Path(project_root).resolve()
        self.tool_name = tool_name
        self._tmp_dir: Path | None = None
        self._backup_root: Path | None = None
        self._before_state: Dict[str, str] = {}
        self._after_state: Dict[str, str] = {}
        self.validation: ProjectValidationResult | None = None
        self.compile_verification: Dict[str, Any] | None = None
        self.rolled_back = False
        self.committed = False

    def begin(self) -> None:
        if not self.project_root.exists() or not self.project_root.is_dir():
            raise ValidationError(f"Cannot start transaction; project root not found: {self.project_root}")
        self._before_state = _snapshot_state(self.project_root)
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="gms-mcp-tx-"))
        self._backup_root = self._tmp_dir / "project"
        shutil.copytree(self.project_root, self._backup_root, ignore=_copy_ignore)

    def rollback(self) -> None:
        if self.rolled_back or self._backup_root is None:
            return
        for child in self.project_root.iterdir():
            if child.name in {".git", ".gms_mcp", ".gms-mcp"}:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in self._backup_root.iterdir():
            target = self.project_root / child.name
            if child.is_dir():
                shutil.copytree(child, target, symlinks=True)
            else:
                shutil.copy2(child, target)
        self.rolled_back = True

    def commit(self, *, verify_compile: bool = False) -> Dict[str, Any]:
        self.validation = validate_project_after_mutation(self.project_root)
        if not self.validation.success:
            self.rollback()
            raise TransactionValidationError(
                "Project validation failed after mutation; changes were rolled back.",
                details={"validation": self.validation.to_dict(), "transaction": self.to_dict()},
            )

        if verify_compile:
            self.compile_verification = compile_verify_project(self.project_root)
            if not self.compile_verification.get("ok"):
                self.rollback()
                raise TransactionValidationError(
                    "Compile verification failed after mutation; changes were rolled back.",
                    details={
                        "validation": self.validation.to_dict(),
                        "compile_verification": self.compile_verification,
                        "transaction": self.to_dict(),
                    },
                )

        self._after_state = _snapshot_state(self.project_root)
        self.committed = True
        return self.to_dict()

    def cleanup(self) -> None:
        if self._tmp_dir and self._tmp_dir.exists():
            shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def to_dict(self) -> Dict[str, Any]:
        after_state = self._after_state or _snapshot_state(self.project_root)
        return {
            "enabled": True,
            "tool": self.tool_name,
            "project_root": str(self.project_root),
            "committed": self.committed,
            "rolled_back": self.rolled_back,
            "changes": _summarize_changes(self._before_state, after_state),
            "validation": self.validation.to_dict() if self.validation else None,
            "compile_verification": self.compile_verification,
        }
