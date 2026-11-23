"""Isolated builds and scripted test runs that never touch the working project.

Every build here works on a *snapshot*: a throwaway copy of the project. That gives three
things a build inside the live project cannot:

* a build is not broken by someone else's half-written file ("isolated" snapshots are the
  base git revision plus only the paths you name);
* a test script can be injected into the game without ever existing in the repository;
* Igor's caches and output never appear inside the project.

The pipeline is ``snapshot -> (inject test) -> compile with Igor -> run -> collect``:

* Igor's project loader in runtime 2026.0.0.23 aborts at random with
  ``System.AccessViolationException``. That is retried automatically; any other failure is
  a real build failure and is reported with the compiler's error lines.
* The only reliable completion signal from a running game is a line in its log, so a test
  ends by printing ``[TEST_RESULT] PASS|FAIL`` and the runner waits for that line.
* Logs and screenshots are kept inside the project under ``.gms_mcp/runs/<label>/`` (an
  ignored directory) so their paths are project-relative and easy to open.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import signal
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable

from . import run_status, yyp_registry
from .dense import name_ranges, natural_key, repeat_counts
from .bounded_regex import search_many
from .agent_locks import MOBILE_BUILD_LOCK, BuildSlot, DirectoryLock, _process_alive
from .mac_runtime import prepare_mac_runtime, project_run_lock
from .exceptions import ValidationError
from .project_config import project_setting
from gms_mcp.project_detection import safe_git_command
from .path_safety import private_directory, project_file_path, project_relative_path, validate_git_ref
from .utils import _read_text_preserving_newlines, find_yyp

ACCESS_VIOLATION_MARKER = "AccessViolationException"
_COMPILE_FINISHED_MARKER = "Final Compile finished"
_ERROR_LINE = re.compile(r"Error :|error :|Project Error")
_WARNING_LINE = re.compile(r"Warning : ")
# The compiler prints one of these for every macro of an extension that does not target the platform
# being built: dozens in a project with store or platform extensions, and nothing to act on.
_OTHER_TARGET_WARNING = "not available for this target"
TEST_FRAME_MARKER = run_status.TEST_FRAME_MARKER
_LABEL = re.compile(r"[^A-Za-z0-9_]")
_SNAPSHOT_IGNORED = {".git", ".gms_mcp", ".gms-mcp", "output", "__pycache__", ".pytest_cache", ".gml_index_cache"}
_MAX_TEST_BYTES = 2 * 1024 * 1024
_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"

# The test API every injected test can rely on. A project may replace this file through
# ``test.prelude_file`` in .gms-mcp.json; a replacement must print the same marker lines.
DEFAULT_TEST_PRELUDE = r"""
// ---- injected by gms-mcp (snapshot only; never part of the project) ----
global.__agent_test_failures = 0;
global.__agent_test_frame = 0;
global.__agent_test_beat = current_time;
global.__agent_test_done = false;
function test_log(_msg) { show_debug_message("[TEST] " + string(_msg)); }
function test_check(_ok, _msg) {
	if (_ok) { show_debug_message("[TEST] PASS " + string(_msg)); }
	else { global.__agent_test_failures++; show_debug_message("[TEST] FAIL " + string(_msg)); }
}
function test_shot(_name) {
	var _file = "__agent_shot_" + string(_name) + ".png";
	screen_save(_file);
	show_debug_message("[TEST] shot " + _file);
}
function test_end() {
	if (global.__agent_test_done) exit;
	global.__agent_test_done = true;
	show_debug_message("[TEST_RESULT] " + ((global.__agent_test_failures == 0) ? "PASS" : "FAIL")
		+ " failures=" + string(global.__agent_test_failures));
	game_end();
}
global.__agent_test_ts = time_source_create(time_source_global, 1, time_source_units_frames, function() {
	if (global.__agent_test_done) exit;
	global.__agent_test_frame++;
	if (global.__agent_test_frame == 1) {
		show_debug_message("[TEST_SAVE_DIR] " + string(game_save_id));
	}
	if (current_time - global.__agent_test_beat >= 1000) {
		// About once a second: lets whoever follows the run see the frame the test has reached.
		global.__agent_test_beat = current_time;
		show_debug_message("[TEST_FRAME] " + string(global.__agent_test_frame));
	}
	agent_test_step(global.__agent_test_frame);
}, [], -1);
time_source_start(global.__agent_test_ts);
// ---- end of injected prelude ----
"""

TEST_API_HELP = (
    "A test is GML that defines `function agent_test_step(_frame) { ... }`, called once per frame from "
    "frame 1 by a global time source, after Begin Step and before Step (not after movement or End Step). "
    "Compare completed movement on the next callback, retaining the preceding frame's target state. "
    "Simulated input needs a real frame to reach Step; transforms may need their system update. "
    "Helpers: test_log(value), test_check(condition, label) (any failed check fails the run), "
    "test_shot(name) (screenshot), test_end() (prints the result and quits; always call it)."
)


class SnapshotError(ValidationError):
    """A snapshot build could not be prepared; the message says what to change."""

    retain_work_dir = False


@dataclass
class Toolchain:
    igor: Path
    runtime_path: Path
    license_file: Path
    prefabs_path: Path | None
    runtime_version: str


@dataclass
class BuildResult:
    ok: bool
    status: str
    attempts: int = 0
    access_violation_retries: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    packaging_errors: list[str] = field(default_factory=list)
    message: str = ""
    build_log: Path | None = None
    game_archive: Path | None = None
    waited_for_slot_seconds: float = 0.0
    build_seconds: float = 0.0
    other_target_warnings: int = 0


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
def safe_label(label: str) -> str:
    cleaned = _LABEL.sub("_", str(label or "default")).strip("_")
    return cleaned[:60] or "default"


def pipeline_lock(project_root: str | Path, label: str) -> DirectoryLock:
    root = Path(project_root).resolve()
    key = f"{root}|{safe_label(label)}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return DirectoryLock(f"runlabel_{digest}.lock", purpose=f"pipeline {root.name}:{safe_label(label)}")


@contextlib.contextmanager
def label_pipeline(project_root: str | Path, label: str, timeout_seconds: float = 7200.0, *, is_run: bool = True):
    """Serialize writers to one project's labelled artifact directory.

    ``is_run=False`` takes the label for housekeeping inside another run (clearing up an earlier
    session). The run in progress then does not record a stage, which would claim its own
    directory before it holds its own label.
    """
    lock = pipeline_lock(project_root, label)
    lock.acquire(timeout_seconds=timeout_seconds, sleep=run_status.sleep_unless_stopped)
    if is_run:
        run_status.report_stage("starting")
    try:
        yield
    finally:
        lock.release()


def runs_directory(project_root: str | Path, label: str) -> Path:
    """Where logs and screenshots of one labelled run are kept (inside the project, ignored)."""
    root = Path(project_root).resolve()
    result = root / ".gms_mcp" / "runs" / safe_label(label)
    if result.resolve() != result:
        raise SnapshotError("Run artifact directories must not contain symlinks.")
    return result


def _work_root() -> Path:
    configured = os.environ.get("GMS_MCP_SNAPSHOT_WORK_DIR", "").strip()
    return private_directory(Path(configured) if configured else Path.home() / ".gms-mcp" / "snapshots")


# ----------------------------------------------------------------------
# Toolchain discovery
# ----------------------------------------------------------------------
def discover_toolchain(project_root: str | Path, runtime_version: str | None = None) -> Toolchain:
    from .runner import GameMakerRunner

    root = Path(project_root).resolve()
    wanted = runtime_version or project_setting(root, "build.runtime_version")
    runner = GameMakerRunner(root, runtime_version=wanted)
    igor = runner.find_gamemaker_runtime()
    if igor is None or runner.runtime_path is None:
        raise SnapshotError(
            "No GameMaker runtime with Igor was found"
            + (f" for version {wanted}" if wanted else "")
            + ". Install the runtime from the GameMaker IDE (File > Preferences > Runtime Feeds), or call "
            "gm_runtime_list to see what is installed and pass runtime_version."
        )
    license_file = runner.find_license_file()
    if license_file is None:
        raise SnapshotError(
            "No GameMaker licence file was found. Open the GameMaker IDE and sign in once on this machine; "
            "Igor needs the licence the IDE stores."
        )
    return Toolchain(
        igor=Path(igor),
        runtime_path=Path(runner.runtime_path),
        license_file=Path(license_file),
        prefabs_path=runner.get_prefabs_path(),
        runtime_version=Path(runner.runtime_path).name.removeprefix("runtime-"),
    )


# ----------------------------------------------------------------------
# Snapshots
# ----------------------------------------------------------------------
def _git(
    repo: Path, *args: str, input_bytes: bytes | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(safe_git_command(repo, *args), input=input_bytes, capture_output=True, check=False, env=env)


def git_context(project_root: str | Path) -> tuple[Path, str]:
    """Return (repository root, project path relative to it) or explain what is missing."""
    root = Path(project_root).resolve()
    result = _git(root, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise SnapshotError(
            "This project is not inside a git repository, so there is no base revision to isolate from. "
            "Omit isolate_paths to build the working tree as it is, or commit the project to git first."
        )
    repo = Path(result.stdout.decode("utf-8").strip()).resolve()
    # Compare directory identity, not spelling: on a case-insensitive volume git may report
    # the top level with different letter case than the path the project was opened with.
    for ancestor in (root, *root.parents):
        with contextlib.suppress(OSError):
            if os.path.samefile(ancestor, repo):
                relative = root.relative_to(ancestor).as_posix()
                return repo, "" if relative == "." else relative
    raise SnapshotError(f"git reported repository root {repo}, which does not contain the project at {root}.")


def _project_relative(path: str, project_prefix: str) -> str:
    normalized = str(path)
    project_relative_path(normalized, project_root=Path.cwd(), kind="isolate path")
    if project_prefix and normalized.startswith(project_prefix + "/"):
        normalized = normalized[len(project_prefix) + 1 :]
    if normalized in {"", "."}:
        raise SnapshotError("Isolate paths must name a child of the project")
    return normalized


def _snapshot_ignored(root: Path, directory: str | os.PathLike[str], names: Iterable[str]) -> set[str]:
    """Names a snapshot never copies: tool/VCS folders at the project root and bytecode caches."""
    if Path(directory) == root:
        return {name for name in names if name in _SNAPSHOT_IGNORED}
    return {name for name in names if name == "__pycache__"}


def _check_copy_source(source: Path, root: Path) -> None:
    project_relative_path(source.relative_to(root).as_posix(), project_root=root, kind="snapshot input")
    for directory, dirs, files in os.walk(source, followlinks=False):
        skipped = _snapshot_ignored(root, directory, dirs + files)
        dirs[:] = [name for name in dirs if name not in skipped]
        files = [name for name in files if name not in skipped]
        for name in dirs + files:
            child = Path(directory) / name
            project_relative_path(child.relative_to(root).as_posix(), project_root=root, kind="snapshot input")
            if child.is_symlink() and child.is_dir():
                raise SnapshotError(f"Directory symlinks are not supported in snapshots: {child}")
            if name in files and not child.is_file():
                raise SnapshotError(f"Snapshot input is not a regular file: {child}")
    if source.is_symlink() and source.is_dir():
        raise SnapshotError(f"Directory symlinks are not supported in snapshots: {source}")


def _read_git_tree(repo: Path, sha: str, staging: Path, prefix: str) -> None:
    tree = _git(repo, "ls-tree", "-r", "-z", sha, "--", *([prefix + "/"] if prefix else []))
    if tree.returncode:
        raise SnapshotError("git could not list the snapshot tree")
    entries = []
    for record in tree.stdout.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, _oid = metadata.decode("ascii").split()
        path = os.fsdecode(raw_path)
        target = project_relative_path(path, project_root=staging, kind="Git tree path")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise SnapshotError(f"Snapshot revision contains an unsupported symlink or submodule: {path}")
        entries.append((mode, raw_path, target, path))
    # A checkout from a private index applies the repository's smudge filters (Git LFS included)
    # and end-of-line conversion, so the snapshot matches what checking out this revision gives.
    index_dir = Path(tempfile.mkdtemp(prefix="gms-mcp-index-", dir=staging.parent))
    environment = {**os.environ, "GIT_INDEX_FILE": str(index_dir / "index")}
    try:
        if _git(repo, "read-tree", sha, env=environment).returncode:
            raise SnapshotError("git could not read the snapshot tree into an index")
        checkout = _git(
            repo,
            "checkout-index",
            f"--prefix={staging}{os.sep}",
            "--stdin",
            "-z",
            input_bytes=b"".join(raw_path + b"\0" for _, raw_path, _, _ in entries),
            env=environment,
        )
    finally:
        shutil.rmtree(index_dir, ignore_errors=True)
    if checkout.returncode:
        detail = checkout.stderr.decode("utf-8", "replace").strip()
        raise SnapshotError(f"git could not check out the snapshot revision{': ' + detail if detail else ''}")
    for mode, _raw_path, target, path in entries:
        if not target.is_file() or target.is_symlink():
            raise SnapshotError(f"git did not write {path} into the snapshot")
        with target.open("rb") as handle:
            if handle.read(len(_LFS_POINTER_PREFIX)) == _LFS_POINTER_PREFIX:
                raise SnapshotError(
                    f"{path} is a Git LFS pointer in revision {sha[:12]}, and git did not replace it with the "
                    "file. Install Git LFS (git lfs install) so the snapshot gets real file contents, or build "
                    "the working tree by omitting isolate_paths and base_only."
                )
        target.chmod(0o700 if mode == "100755" else 0o600)


def _copy_tree(source: Path, destination: Path) -> None:
    _check_copy_source(source, source)
    shutil.copytree(
        source,
        destination,
        ignore=lambda directory, names: _snapshot_ignored(source, directory, names),
        symlinks=False,
        dirs_exist_ok=True,
    )


@contextlib.contextmanager
def _project_mutation_lock(root: Path):
    """Hold the project-mutation lock so a copy never mixes files from before and after a write."""
    from .transactions import _ProjectMutationLock, transaction_is_active

    if transaction_is_active(root):
        yield  # This thread's transaction already owns the lock.
        return
    lock = _ProjectMutationLock(root, "snapshot")
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def create_snapshot(
    project_root: str | Path,
    destination: str | Path,
    *,
    isolate_paths: Iterable[str] | None = None,
    yyp_entries: Iterable[str] | None = None,
    ref: str = "HEAD",
    base_only: bool = False,
) -> dict[str, Any]:
    """Copy the project to ``destination``.

    Without ``isolate_paths`` the copy is the working tree as it is now. With it, the copy
    is git revision ``ref`` plus only the named project-relative paths from the working tree
    (a named path that no longer exists is deleted from the copy), and its ``.yyp`` is the
    base revision plus only the registrations those paths need.
    """
    validate_git_ref(ref)
    root = Path(project_root).resolve()
    dest = Path(destination)
    isolate_paths = list(isolate_paths) if isolate_paths is not None else None
    for raw in isolate_paths or []:
        project_relative_path(raw, project_root=root, kind="isolate source")
        if str(raw) in {"", "."}:
            raise SnapshotError("Isolate paths must name a child of the project")
    if dest.resolve() == root or dest.resolve().is_relative_to(root) or root.is_relative_to(dest.resolve()):
        raise SnapshotError("Snapshot destination must not overlap the source project")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    yyp_name = find_yyp(root).name

    paths = [p for p in (isolate_paths or []) if str(p).strip()]
    if base_only and (paths or [e for e in (yyp_entries or []) if str(e).strip()]):
        raise SnapshotError(
            "base_only builds the revision with nothing added, so it cannot be combined with "
            "isolate_paths or yyp_entries. Drop base_only to add working-tree paths, or drop the paths."
        )
    if not paths and not base_only:
        if yyp_entries:
            raise SnapshotError(
                "yyp_entries only applies to an isolated snapshot. Pass isolate_paths as well, or drop "
                "yyp_entries to build the working tree as it is."
            )
        with _project_mutation_lock(root):
            _copy_tree(root, dest)
        return {"mode": "working-tree", "isolated_paths": [], "yyp_entries": [], "ref": None}

    repo, prefix = git_context(root)
    resolved = _git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    sha = resolved.stdout.decode("ascii", "replace").strip()
    if resolved.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        raise SnapshotError(f"git could not resolve revision '{ref}' to a commit")
    staging = Path(tempfile.mkdtemp(prefix="gms-mcp-tree-", dir=dest.parent))
    try:
        _read_git_tree(repo, sha, staging, prefix)
        base_project = staging / prefix if prefix else staging
        if not (base_project / yyp_name).is_file():
            raise SnapshotError(
                f"Revision '{ref}' does not contain {prefix + '/' if prefix else ''}{yyp_name}. "
                "Choose a revision that has this project."
            )
        relative_paths = [_project_relative(path, prefix) for path in paths]
        with _project_mutation_lock(root):
            for relative in relative_paths:
                source = project_relative_path(relative, project_root=root, kind="isolate source")
                target = project_relative_path(relative, project_root=base_project, kind="isolate target")
                _check_copy_source(root / relative, root)
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                elif target.exists() or target.is_symlink():
                    target.unlink()
                if source.is_dir():
                    shutil.copytree(
                        source,
                        target,
                        ignore=lambda directory, names: _snapshot_ignored(root, directory, names),
                        symlinks=False,
                    )
                elif source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            base_text = _read_text_preserving_newlines(base_project / yyp_name)
            working_text = _read_text_preserving_newlines(root / yyp_name)
            entries = [str(entry) for entry in (yyp_entries or []) if str(entry).strip()]
            if not entries and relative_paths:
                entries = yyp_registry.derive_yyp_entries(root, base_text, working_text, relative_paths)
            if yyp_name not in relative_paths and entries:
                composed = yyp_registry.compose_yyp(base_text, working_text, entries)
                introduced = sorted(
                    set(yyp_registry.validate_yyp_text(composed)) - set(yyp_registry.validate_yyp_text(base_text))
                )
                if introduced:
                    raise SnapshotError("The isolated project file would be inconsistent: " + "; ".join(introduced))
                (base_project / yyp_name).write_text(composed, encoding="utf-8", newline="")
        shutil.move(str(base_project), str(dest))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"mode": "isolated", "isolated_paths": relative_paths, "yyp_entries": entries, "ref": ref}


# ----------------------------------------------------------------------
# Test injection
# ----------------------------------------------------------------------
def inject_test_script(
    snapshot_root: str | Path,
    test_code: str,
    *,
    script_name: str = "__agent_test",
    prelude: str = DEFAULT_TEST_PRELUDE,
) -> str:
    """Add the test as a script asset of the snapshot. Refuses to run on a live project."""
    snapshot = Path(snapshot_root).resolve()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", script_name):
        raise SnapshotError("test.script_name must be a single GameMaker script identifier.")
    if (snapshot / ".git").exists() or not (snapshot / ".gms-mcp-snapshot").is_file():
        raise SnapshotError(
            "Refusing to inject a test outside a snapshot: test scripts must never be written into the "
            "real project. This is an internal safeguard; report it if you see it."
        )
    if "agent_test_step" not in test_code:
        raise SnapshotError("The test does not define agent_test_step(_frame). " + TEST_API_HELP)
    yyp_path = find_yyp(snapshot)
    script_dir = snapshot / "scripts" / script_name
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / f"{script_name}.gml").write_text(prelude + "\n" + test_code + "\n", encoding="utf-8")
    (script_dir / f"{script_name}.yy").write_text(
        "{\n"
        '  "$GMScript":"v1",\n'
        f'  "%Name":"{script_name}",\n'
        '  "isCompatibility":false,\n'
        '  "isDnD":false,\n'
        f'  "name":"{script_name}",\n'
        '  "parent":{\n'
        f'    "name":"{yyp_path.stem}",\n'
        f'    "path":"{yyp_path.name}",\n'
        "  },\n"
        '  "resourceType":"GMScript",\n'
        '  "resourceVersion":"2.0",\n'
        "}",
        encoding="utf-8",
    )
    relative = f"scripts/{script_name}/{script_name}.yy"
    _yyp, data = yyp_registry.load_yyp(snapshot)
    resources = data.setdefault("resources", [])
    resources[:] = [e for e in resources if (yyp_registry._resource_ref(e) or {}).get("name") != script_name]
    from .gm_order import RESOURCE_ORDERINGS, insert_ordered

    insert_ordered(resources, {"id": {"name": script_name, "path": relative}}, RESOURCE_ORDERINGS)
    yyp_registry._save_yyp(yyp_path, data)
    return relative


def _test_text_setting(project_root: Path, key: str, default: str) -> str:
    """A ``test.*`` marker or name from .gms-mcp.json; it must be a non-empty string."""
    value = project_setting(project_root, key, default)
    if not isinstance(value, str) or not value:
        raise SnapshotError(f"{key} in .gms-mcp.json must be a non-empty string, not {value!r}.")
    return value


def _test_runtime_error_patterns(project_root: Path) -> list[str]:
    """``test.runtime_error_patterns``: a list of non-empty strings matched literally in the run log."""
    value = project_setting(project_root, "test.runtime_error_patterns", [])
    if not isinstance(value, list) or not all(isinstance(pattern, str) and pattern for pattern in value):
        raise SnapshotError(
            "test.runtime_error_patterns in .gms-mcp.json must be a list of non-empty strings, "
            f'for example ["FATAL ERROR"]; got {value!r}.'
        )
    return value


def load_test_source(project_root: Path, test_file: str | None, test_code: str | None) -> str:
    if bool(test_file) == bool(test_code):
        raise SnapshotError("Pass exactly one of test_code (the GML text) or test_file (a path to a .gml file).")
    if test_code:
        return test_code.removeprefix("\ufeff")
    path = project_file_path(test_file, project_root=project_root, kind="test file")
    if not path.is_file():
        raise SnapshotError(
            f"Test file not found: {test_file}. Pass a project-relative path or the GML text as test_code."
        )
    if path.stat().st_size > _MAX_TEST_BYTES:
        raise SnapshotError("The test file is larger than 2 MB; that is not a test script.")
    # utf-8-sig drops an editor's byte-order mark, which would otherwise land mid-script after the prelude.
    return path.read_text(encoding="utf-8-sig")


# ----------------------------------------------------------------------
# Compile
# ----------------------------------------------------------------------
def _igor_accepts_mac_compile(toolchain: Toolchain) -> bool:
    """Igor before runtime 2026 aborts on ``Mac Compile`` with TargetParameterCountException."""
    major = str(toolchain.runtime_version).split(".", 1)[0]
    return major.isdigit() and int(major) >= 2026


def igor_command(
    toolchain: Toolchain,
    project_file: Path,
    *,
    cache_dir: Path,
    temp_dir: Path,
    output_file: Path,
    platform: str,
    runtime: str = "VM",
    jobs: int = 4,
    action: str = "PackageZip",
) -> list[str]:
    command = [
        str(toolchain.igor),
        f"/lf={toolchain.license_file}",
        f"/uf={toolchain.license_file.parent}",
        f"/rp={toolchain.runtime_path}",
        f"/project={project_file}",
        f"/cache={cache_dir}",
        f"/temp={temp_dir}",
        f"/of={output_file}",
    ]
    if toolchain.prefabs_path:
        command.append(f"--pf={toolchain.prefabs_path}")
    command.append(f"-r={'YYC' if str(runtime).upper() == 'YYC' else 'VM'}")
    command.append(f"-j={max(1, int(jobs))}")
    if platform == "HTML5":
        command.append(f"/tf={output_file.parent.with_name('html5')}")
    command.extend(["--", platform, action])
    return command


def summarize_build_log(text: str) -> tuple[list[str], list[str]]:
    errors, warnings, _packaging = classify_build_log(text)
    return errors, warnings


def classify_build_log(text: str) -> tuple[list[str], list[str], list[str]]:
    """Split a build log into (compiler errors, warnings, packaging errors).

    Everything up to the line that says the compile finished belongs to the compiler.
    Error lines after it come from packaging (signing, installers); for a desktop snapshot
    they do not matter as long as the game data was written.
    """
    lines = text.splitlines()
    finished_at = max((i for i, line in enumerate(lines) if _COMPILE_FINISHED_MARKER in line), default=len(lines))
    errors: list[str] = []
    warnings: list[str] = []
    packaging: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _ERROR_LINE.search(stripped):
            bucket = errors if index <= finished_at else packaging
            if stripped not in bucket:
                bucket.append(stripped)
        elif _WARNING_LINE.search(stripped) and _OTHER_TARGET_WARNING not in stripped:
            if stripped not in warnings:
                warnings.append(stripped)
    return errors, warnings, packaging


def count_other_target_warnings(text: str) -> int:
    """How many warnings the build log holds that `classify_build_log` leaves out of its warnings."""
    return sum(1 for line in text.splitlines() if _OTHER_TARGET_WARNING in line and _WARNING_LINE.search(line))


def last_test_frame(text: str) -> int | None:
    """The frame a running test last reported in the game's log, or None when it has reported none."""
    at = text.rfind(TEST_FRAME_MARKER)
    if at < 0:
        return None
    digits = text[at + len(TEST_FRAME_MARKER) :].split("\n", 1)[0].strip()
    return int(digits) if digits.isdigit() else None


_COMPILED_UNIT = re.compile(
    r"gml_(?P<kind>GlobalScript|Object)_(?P<name>[A-Za-z0-9_]+)\((?P<line>\d+)\)\s*:\s*(?P<message>.*)"
)
_OBJECT_EVENT_UNIT = re.compile(
    r"^(?P<object>.+)_(?P<event>PreCreate|Create|Destroy|CleanUp|Alarm|Step|Collision|Keyboard|KeyPress|KeyRelease|"
    r"Mouse|Gesture|Other|Draw)_(?P<number>[A-Za-z0-9_]+)$"
)


def locate_compile_errors(
    project_root: Path, errors: list[str], *, compiled_root: Path | None = None
) -> list[dict[str, Any]]:
    """Turn the compiler's internal unit names into project files and lines an editor can open.

    Igor reports "gml_GlobalScript_scr_x(3) : message": the unit is a script or an object event,
    and its line number counts from zero. Each located error carries the source text of that
    line so a reader can see at once that it is the right one.

    ``compiled_root`` is the copy that was actually compiled. The line is read from there: the
    working tree may hold another revision of the file, or have been edited since, and would
    show valid code beside the error. A file the working tree does not have (another revision's,
    or the injected test) is still located and marked ``only_in_build``.
    """
    located: list[dict[str, Any]] = []
    project = Path(project_root)
    root = Path(compiled_root) if compiled_root is not None else project
    for error in errors:
        match = _COMPILED_UNIT.search(error)
        if match is None:
            continue
        name = match.group("name")
        if match.group("kind") == "GlobalScript":
            relative = f"scripts/{name}/{name}.gml"
        else:
            event = _OBJECT_EVENT_UNIT.match(name)
            if event is None:
                continue
            relative = f"objects/{event.group('object')}/{event.group('event')}_{event.group('number')}.gml"
        path = root / relative
        if path.is_symlink() or not path.is_file():
            continue
        line = int(match.group("line")) + 1
        entry: dict[str, Any] = {"file": relative, "line": line, "message": match.group("message").strip()}
        if compiled_root is not None and not (project / relative).is_file():
            entry["only_in_build"] = True
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            lines = []
        if 0 < line <= len(lines):
            entry["source"] = lines[line - 1].strip()[:200]
        located.append(entry)
    return located


@contextlib.contextmanager
def artifact_writer(path: Path):
    """Open an output file without following a checkout-supplied symlink."""
    if path.is_symlink():
        raise SnapshotError(f"Refusing to write a symlink artifact: {path.name}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        yield stream


def copy_artifact(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise SnapshotError("Refusing to archive a symlink source.")
    with source.open("rb") as incoming, artifact_writer(destination) as outgoing:
        shutil.copyfileobj(incoming, outgoing)


# Igor processes started by this process, with the run each belongs to, so that one run can be
# stopped and none is left building after the server has gone.
_ACTIVE_BUILDS: dict[subprocess.Popen, run_status.RunTracker | None] = {}
_ACTIVE_BUILDS_LOCK = threading.Lock()


def _end_process_tree(process: subprocess.Popen, *, grace_seconds: float = 3.0) -> None:
    """Stop Igor and whatever it started: its process group when it leads one, else Igor itself."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        _end_windows_process_tree(process)
    else:
        leads_its_group = False
        with contextlib.suppress(ProcessLookupError, PermissionError):
            leads_its_group = os.getpgid(process.pid) == process.pid
        # Igor shares this process's group, so the group cannot be signalled: that would end this
        # process too. Its tools are found now, while they can still be told from anything else.
        tree = [] if leads_its_group else [process.pid, *_descendant_process_ids(process.pid)]

        def send(signal_number: int) -> None:
            if leads_its_group:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(process.pid, signal_number)
                return
            for process_id in tree:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(process_id, signal_number)

        def anything_left() -> bool:
            # Igor itself is this process's child: it has to be collected before it stops counting.
            if process.poll() is None:
                return True
            if leads_its_group:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    return True
                return True
            return any(_process_alive(process_id) for process_id in tree[1:])

        def gone_within(seconds: float) -> bool:
            deadline = time.monotonic() + seconds
            while anything_left():
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)
            return True

        send(signal.SIGTERM)
        # Igor leaving is not the end of it: a tool it started may ignore the request, and would go
        # on writing into the build's output after the build slot had been given to someone else.
        if not gone_within(grace_seconds):
            send(signal.SIGKILL)
            gone_within(5.0)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)


def _descendant_process_ids(process_id: int) -> list[int]:
    """The processes started by ``process_id`` and by those, as the system lists them now."""
    try:
        listing = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            children.setdefault(int(fields[1]), []).append(int(fields[0]))
    found: list[int] = []
    pending = [process_id]
    while pending:
        for child in children.get(pending.pop(), []):
            found.append(child)
            pending.append(child)
    return found


def _end_windows_process_tree(process: subprocess.Popen) -> None:
    """End Igor and the compiler and packaging tools it started.

    Killing Igor alone leaves those tools running: they would go on writing into packaging
    output the next build shares, after this build's slot had been given away.
    """
    import ntpath

    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    taskkill = ntpath.join(system_root, "System32", "taskkill.exe")
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30)
    if process.poll() is None:
        # taskkill could not be run, or left Igor itself behind.
        with contextlib.suppress(OSError):
            process.kill()


def stop_builds(tracker: run_status.RunTracker | None = None, *, grace_seconds: float = 3.0) -> int:
    """Stop the Igor processes of one run, or of every run when no tracker is given."""
    with _ACTIVE_BUILDS_LOCK:
        processes = [process for process, owner in _ACTIVE_BUILDS.items() if tracker is None or owner is tracker]
    for process in processes:
        _end_process_tree(process, grace_seconds=grace_seconds)
    return len(processes)


def _default_run_igor(command: list[str], log_path: Path, timeout_seconds: float) -> int:
    tracker = run_status.current()
    with artifact_writer(log_path) as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "DOTNET_PROCESSOR_COUNT": os.environ.get("DOTNET_PROCESSOR_COUNT", "1")},
            # A run this process tracks is stopped by signalling Igor's own group, which also ends the
            # tools Igor starts. An untracked build is a command someone else started (gm_compile
            # runs it that way) and stops by ending that command's group: Igor has to stay in it, or
            # the stop would end the command and leave the compiler running.
            start_new_session=tracker is not None and os.name != "nt",
        )
        with _ACTIVE_BUILDS_LOCK:
            _ACTIVE_BUILDS[process] = tracker
        deadline = time.monotonic() + timeout_seconds
        try:
            while True:
                try:
                    code = process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    code = None
                if tracker is not None and tracker.stop_requested:
                    # Checked first: the stop may already have ended the process.
                    _end_process_tree(process)
                    log.write(b"\n[gms-mcp] The build was stopped on request.\n")
                    return -15
                if code is not None:
                    return code
                if time.monotonic() >= deadline:
                    _end_process_tree(process)
                    log.write(
                        f"\n[gms-mcp] Igor was stopped after {int(timeout_seconds)}s without finishing.\n".encode()
                    )
                    return -9
        finally:
            _end_process_tree(process)
            with _ACTIVE_BUILDS_LOCK:
                _ACTIVE_BUILDS.pop(process, None)


def compile_snapshot(
    snapshot_root: str | Path,
    work_dir: str | Path,
    toolchain: Toolchain,
    *,
    platform: str = "Mac",
    runtime: str = "VM",
    attempts: int = 10,
    jobs: int = 4,
    max_parallel_builds: int = 4,
    build_log: Path | None = None,
    igor_timeout_seconds: float = 1800.0,
    slot_timeout_seconds: float = 3600.0,
    run_igor: Callable[[list[str], Path, float], int] | None = None,
) -> BuildResult:
    """Compile the snapshot, retrying Igor's random project-loader crash."""
    started = time.monotonic()
    work = Path(work_dir)
    cache_dir, temp_dir, out_dir = work / "cache", work / "temp", work / "out"
    for directory in (cache_dir, temp_dir, out_dir):
        directory.mkdir(parents=True, exist_ok=True)
    # Igor writes to a log inside this invocation's own work directory. The labelled run log
    # (build_log) is shared by every process that uses the same label, so it is only published
    # once this invocation has finished and its result has been read from its own log.
    log_path = work / "build.log"
    project_file = find_yyp(Path(snapshot_root))
    command = igor_command(
        toolchain,
        project_file,
        cache_dir=cache_dir,
        temp_dir=temp_dir,
        output_file=out_dir / "build.zip",
        platform=platform,
        runtime=runtime,
        jobs=jobs,
        action=(
            "folder"
            if platform == "HTML5"
            else "Compile"
            if platform == "Mac" and str(runtime).upper() == "VM" and _igor_accepts_mac_compile(toolchain)
            else "PackageZip"
            if platform in {"Mac", "Windows"}
            else "Package"
        ),
    )
    from .runner_support.igor import RunnerIgorMixin

    html5_output = work / "html5"
    html5_baseline = RunnerIgorMixin._verified_html5_artifacts(html5_output) if platform == "HTML5" else {}
    runner = run_igor or _default_run_igor
    result = BuildResult(ok=False, status="BUILD_FAILED", build_log=build_log or log_path)
    mobile = str(platform).lower() in {"android", "ios"}
    attempt_limit = max(1, int(attempts))
    text = ""
    retry_note: dict[str, str] = {}
    for attempt in range(1, attempt_limit + 1):
        result.attempts = attempt
        # Mobile packaging shares Xcode/Gradle output folders and attached devices, so only one
        # mobile build runs at a time. Its lock is taken before a capacity slot: a mobile build
        # waiting its turn must not sit on a slot that a desktop build could be using.
        mobile_lock = DirectoryLock(MOBILE_BUILD_LOCK, purpose=f"mobile build {project_file.name}") if mobile else None
        # The run's label and attempt let a caller find its own build in gm_lock_status.
        run_label = Path(build_log or log_path).parent.name
        slot = BuildSlot(max_parallel_builds, purpose=f"igor build {project_file.name} [{run_label}] attempt {attempt}")
        try:
            waiting = run_status.waiting_sleep(
                "waiting for a build slot", attempt=attempt, attempts=attempt_limit, **retry_note
            )
            if mobile_lock is not None:
                mobile_lock.acquire(timeout_seconds=slot_timeout_seconds, sleep=waiting)
            slot.acquire(timeout_seconds=slot_timeout_seconds, sleep=waiting)
            result.waited_for_slot_seconds += slot.waited_seconds
            try:
                run_status.report_stage(
                    "compiling", attempt=attempt, attempts=attempt_limit, live_log=str(log_path), **retry_note
                )
                run_status.publish_live_log(log_path)
                return_code = runner(command, log_path, igor_timeout_seconds)
            finally:
                slot.release()
        finally:
            if mobile_lock is not None and mobile_lock.held:
                mobile_lock.release()
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        result.errors, result.warnings, result.packaging_errors = classify_build_log(text)
        result.other_target_warnings = count_other_target_warnings(text)
        # The crash can hit the project loader or a later packaging step; either way the
        # output is unusable. Real compiler errors are final: retrying cannot fix them.
        if ACCESS_VIOLATION_MARKER not in text or result.errors or attempt == attempt_limit:
            break
        run_status.raise_if_stopped()
        result.access_violation_retries += 1
        retry_note = {
            "previous_attempt": (
                f"Attempt {attempt} hit Igor's random crash ({ACCESS_VIOLATION_MARKER}), which is retried automatically."
            )
        }
    run_status.raise_if_stopped()
    run_status.report_stage("reading the build result")
    if build_log is not None and log_path.is_file() and Path(build_log) != log_path:
        try:
            Path(build_log).parent.mkdir(parents=True, exist_ok=True)
            copy_artifact(log_path, Path(build_log))
        except OSError as exc:
            error = SnapshotError(
                f"Could not publish the build log: {exc}. Compiler output is retained at {log_path}. "
                "Free space at the artifact destination before retrying; "
                "GMS_MCP_SNAPSHOT_WORK_DIR selects an external snapshot/cache directory."
            )
            error.retain_work_dir = True
            raise error from exc
    result.build_seconds = round(time.monotonic() - started, 1)
    # Igor's final packaging step can fail on a shared staging folder after the game data
    # was written; the compiled game archive is what a run needs.
    archive = next((p for p in (out_dir / "game.zip", out_dir / "build.zip") if p.is_file()), None)
    crashed = ACCESS_VIOLATION_MARKER in text
    desktop = platform in {"Mac", "Windows", "Linux"}
    if archive is not None and not zipfile.is_zipfile(archive):
        archive = None
    if platform == "Mac" and str(runtime).upper() == "YYC":
        # The asset-compiler marker precedes the native C++ link. A data-only
        # archive, or a failed signing/link step, cannot certify a YYC build.
        native_executable = False
        if archive is not None:
            with zipfile.ZipFile(archive) as package:
                native_executable = any(
                    ".app/Contents/MacOS/" in member.filename and member.file_size > 0 and not member.is_dir()
                    for member in package.infolist()
                )
        if return_code != 0 or not native_executable or result.packaging_errors:
            result.errors.append("The native macOS YYC application was not built and packaged successfully.")
    if not desktop and result.packaging_errors:
        # For a mobile or web target the package is the product, so its errors are fatal.
        result.errors = [*result.errors, *result.packaging_errors]
    completed = _COMPILE_FINISHED_MARKER in text
    if platform == "HTML5":
        # HTML5 emits Stats/Igor complete, not the desktop compile marker.
        # Verify fresh web artifacts instead of trusting Igor's zero exit code.
        completed = RunnerIgorMixin._verified_html5_package_exists(html5_output, html5_baseline)
        if not completed:
            result.errors.append("HTML5 export did not produce a new verified index.html and JavaScript artifact.")
    compiled = (
        completed
        and not result.errors
        and not crashed
        and not RunnerIgorMixin._igor_rejected_command(text.splitlines())
    )
    if compiled and (archive is not None or not desktop):
        result.ok = True
        result.status = "COMPILE_OK"
        result.game_archive = archive
        result.message = (
            f"Compiled on attempt {result.attempts}"
            + (
                f" after {result.access_violation_retries} Igor crash retries"
                if result.access_violation_retries
                else ""
            )
            + "."
            + (
                " The packaging step after the compile reported errors (usually macOS signing); the game data "
                "was built and can be run, but no distributable package was made."
                if result.packaging_errors
                else ""
            )
        )
        return result
    if result.errors:
        result.message = (
            f"The compiler reported {len(result.errors)} error(s). Fix them and build again; each error line "
            "names the script or object event and the line number. If the errors are in files you are not "
            "working on, someone else's edit is half done: build with isolate_paths (the base revision plus "
            "only your files) instead."
        )
    elif crashed:
        result.message = (
            f"Igor crashed with System.AccessViolationException on all {result.attempts} attempts. This is a "
            "GameMaker runtime fault, not an error in the project: run the build again, or raise "
            "build.igor_attempts in .gms-mcp.json. If it never succeeds, check gm_project_check for a "
            "mis-ordered .yyp, which makes the crash far more likely."
        )
    elif "[IGOR] Unknown command" in text:
        result.message = (
            f"Igor does not accept the package command for platform {platform} in this runtime. The build log "
            "lists the commands it does accept; report this so the platform mapping can be corrected."
        )
    elif _COMPILE_FINISHED_MARKER not in text:
        result.message = (
            "Igor stopped before the compile finished and printed no compiler error. Read the end of the build "
            "log for the cause (licence, missing runtime module, or a resource the project loader rejected)."
        )
    else:
        result.message = (
            "The compile finished but Igor produced no game archive. Read the end of the build log; "
            "the packaging step failed."
        )
    return result


# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------
def tail_lines(path: Path, count: int, *, skip: Callable[[str], bool] | None = None) -> list[str]:
    """Last lines of a log without .NET stack frames, which bury the line that matters.

    ``skip`` leaves out lines the caller reports elsewhere, so the tail holds only new ones. A
    line repeated back to back counts once and is written once with its count.
    """
    if not path.is_file():
        return []
    lines = [
        line[:400]
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not line.lstrip().startswith("at System.")
        and not line.lstrip().startswith("at Microsoft.")
        and TEST_FRAME_MARKER not in line
        and not (skip is not None and skip(line))
    ]
    return repeat_counts(lines)[-max(0, count) :]


_SEPARATOR_LINE = re.compile(r"\s*[#_=-]{10,}\s*")


def _after_marker(line: str, marker: str) -> str:
    return line.split(marker, 1)[1].strip() if marker in line else line.strip()


def _dense_test_lines(lines: list[str]) -> list[str]:
    """Test lines with consecutive screenshot lines joined into brace ranges, then repeats counted."""
    out: list[str] = []
    index = 0
    while index < len(lines):
        end = index
        while end < len(lines) and lines[end].startswith("shot ") and " " not in lines[end][5:]:
            end += 1
        if end == index:
            out.append(lines[index])
            index += 1
            continue
        names = [line[5:] for line in lines[index:end]]
        # Only a run already in order, with no name twice, can be written as ranges without losing anything.
        if len(set(names)) == len(names) and names == sorted(names, key=natural_key):
            out.extend(f"shot {name}" for name in name_ranges(names))
        else:
            out.extend(lines[index:end])
        index = end
    return repeat_counts(out)


def _runtime_error_blocks(lines: list[str], patterns: list[str], markers: tuple[str, ...]) -> tuple[list[str], int]:
    """Each runtime error once, with how many times it was logged, and the total number logged.

    A block is the matching line with two lines before it and fifteen after, without the rows of
    #### or ____ that GameMaker frames it with and without test lines (``markers``), which the result
    reports already. The same block logged again (an error raised every frame) is counted, not repeated.
    """
    blocks: dict[str, int] = {}
    consumed = -1

    def starts_error(row: str) -> bool:
        return any(pattern in row for pattern in patterns) and not _SEPARATOR_LINE.fullmatch(row)

    for index, line in enumerate(lines):
        if index <= consumed or not any(pattern in line for pattern in patterns):
            continue
        # A block ends where the next error begins, so an error logged again is counted, not merged.
        end = next(
            (later for later in range(index + 1, min(index + 15, len(lines))) if starts_error(lines[later])), index + 15
        )
        window = lines[max(0, index - 2) : end]
        consumed = end - 1
        text = "\n".join(
            row
            for row in window
            if row.strip() and not _SEPARATOR_LINE.fullmatch(row) and not any(marker in row for marker in markers)
        )
        blocks[text] = blocks.get(text, 0) + 1
    total = sum(blocks.values())
    rendered = [text if count == 1 else f"{text}\n[logged {count} times]" for text, count in blocks.items()]
    return rendered, total


def parse_run_log(
    text: str,
    *,
    result_marker: str = "[TEST_RESULT]",
    line_marker: str = "[TEST]",
    started_marker: str = "[TEST_SAVE_DIR]",
    runtime_error_patterns: Iterable[str] = (),
    timed_out: bool = False,
) -> dict[str, Any]:
    """Turn a runner log into a verdict. The log is the only source of truth for a run.

    Every test line is returned, without its marker; the result line is returned once, as
    ``result_line``, and the failed checks once more by their text alone, as ``failed_checks``.
    """
    lines = text.splitlines()
    result_line = next((_after_marker(line, result_marker) for line in lines if result_marker in line), None)
    test_lines = [
        _after_marker(line, line_marker) for line in lines if line_marker in line and result_marker not in line
    ]
    patterns = [pattern for pattern in runtime_error_patterns if pattern]
    error_blocks, error_count = _runtime_error_blocks(
        lines, patterns, (line_marker, result_marker, started_marker, TEST_FRAME_MARKER)
    )
    failed_checks = [line[5:] for line in test_lines if line.startswith("FAIL ")]
    started = started_marker in text
    note = ""
    if result_line and "PASS" in result_line:
        status = "TEST_PASSED"
    elif result_line:
        status = "TEST_FAILED"
    elif timed_out:
        status = "TEST_TIMEOUT"
        note = (
            "The game was still running at the timeout and never printed a result line. Make sure the test "
            "calls test_end() on every path, or raise timeout_seconds."
        )
    else:
        status = "TEST_FAILED"
        note = (
            "The game exited without printing a result line."
            if started
            else "The test never started: the game crashed or failed to boot before the first frame. "
            "Read the runtime_errors and the log tail."
        )
    if error_blocks and status == "TEST_PASSED":
        status = "TEST_FAILED"
        note = "The test reported PASS but the game logged a runtime error, which always fails a run."
    verdict: dict[str, Any] = {
        "status": status,
        "passed": status == "TEST_PASSED",
        "result_line": result_line,
        "test_lines": _dense_test_lines(test_lines),
        "failed_checks": repeat_counts(failed_checks),
        "runtime_errors": error_blocks,
        "started": started,
        "note": note,
    }
    if error_count > len(error_blocks):
        verdict["runtime_errors_logged"] = error_count
    return verdict


def screenshot_listing(project_root: Path, shots_dir: Path, shots: Iterable[Path] | None = None) -> dict[str, Any]:
    """Name a run's screenshots once: a path pattern, then what each file puts in place of its ``*``.

    ``{"screenshot_files": ".gms_mcp/runs/t/shots/__agent_shot_*.png", "screenshots": ["menu",
    "f{0001..0240}"]}`` stands for .gms_mcp/runs/t/shots/__agent_shot_menu.png and the 240 numbered
    files f0001 to f0240 (see dense.name_ranges).
    """
    names = sorted(shot.name for shot in (list(shots) if shots is not None else shots_dir.glob("*.png")))
    if not names:
        return {"screenshots": []}
    prefix = suffix = ""
    if len(names) > 1:
        # Never split a number between the shared text and the names, or the ranges would read oddly.
        prefix = os.path.commonprefix(names).rstrip("0123456789")
        suffix = os.path.commonprefix([name[::-1] for name in names])[::-1].lstrip("0123456789")
        shortest = min(len(name) for name in names)
        if len(prefix) + len(suffix) > shortest:
            suffix = suffix[len(prefix) + len(suffix) - shortest :]
    return {
        "screenshot_files": f"{_relative(project_root, shots_dir)}/{prefix}*{suffix}",
        "screenshots": name_ranges(name[len(prefix) : len(name) - len(suffix)] for name in names),
    }


def _mac_runner(toolchain: Toolchain) -> Path:
    return toolchain.runtime_path / "mac" / "YoYo Runner.app" / "Contents" / "MacOS" / "Mac_Runner"


def require_mac_runner(toolchain: Toolchain) -> Path:
    if sys.platform != "darwin":
        raise SnapshotError(
            "Running a snapshot build is implemented for macOS hosts only. The compile step works on every "
            "host; on Windows or Linux use gm_run for now."
        )
    runner = _mac_runner(toolchain)
    if not runner.is_file():
        raise SnapshotError(
            f"The macOS runner is missing from runtime {toolchain.runtime_version}. Install the macOS target "
            "module for that runtime in the GameMaker IDE."
        )
    return runner


def require_vm_runtime(runtime: str) -> None:
    """Owned snapshot runs load VM data; YYC needs its own linked executable."""
    if str(runtime).upper() != "VM":
        raise SnapshotError(
            "Isolated macOS runs support runtime='VM' only. YYC requires a compiled native application; "
            "its game data cannot be launched with the VM runner."
        )


def stage_game_archive(game_archive: Path, staging: Path) -> tuple[Path, Path]:
    """Unpack a compiled game where the runner can load it. Returns (staging dir, game file)."""
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(game_archive) as archive:
        # The signed runner already lives here. Game assets cannot overwrite it,
        # and archive paths must remain literal descendants of the staging root.
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if (
                path.is_absolute()
                or PureWindowsPath(item.filename).anchor
                or ".." in path.parts
                or "\\" in item.filename
                or (path.parts and path.parts[0].casefold() == "runner.app")
            ):
                raise SnapshotError("The game archive contains an unsafe or reserved path.")
        archive.extractall(staging)
    assets = staging / "assets"
    if assets.is_dir():
        for child in assets.iterdir():
            shutil.move(str(child), str(staging / child.name))
        assets.rmdir()
    game_file = next(iter(sorted(staging.glob("*.ios"))), staging / "game.ios")
    if not game_file.is_file():
        shutil.rmtree(staging, ignore_errors=True)
        raise SnapshotError("The build archive has no game data file (game.ios); the package step failed.")
    return staging, game_file


def launch_mac_runner(
    runner: Path,
    staging: Path,
    game_file: Path,
    run_dir: Path,
    environment: dict[str, str] | None = None,
) -> tuple[subprocess.Popen, Path]:
    """Start the game. Returns (process, the game's log file)."""
    debug_log = staging / "debug.txt"
    run_dir.mkdir(parents=True, exist_ok=True)
    with artifact_writer(run_dir / "runner_stderr.log") as stderr_log:
        process = subprocess.Popen(
            [str(runner), "-game", mac_game_path(game_file), "-debugoutput", "debug.txt", "-output", "debug.txt"],
            cwd=str(staging),
            stdout=stderr_log,
            stderr=subprocess.STDOUT,
            env={**os.environ, **(environment or {})},
        )
    return process, debug_log


def mac_game_path(path: PurePath) -> str:
    """The native runner misparses the /private/var spelling of macOS temp paths."""
    value = str(path)
    return value.removeprefix("/private") if value.startswith("/private/var/") else value


def screenshot_files(screenshot_prefix: str, save_dir: Path) -> list[Path]:
    """Select only literal immediate files in this project's save directory."""
    if not screenshot_prefix or any(char in screenshot_prefix for char in "/\\*?[]\0"):
        raise SnapshotError("test.screenshot_prefix must be a nonempty filename prefix without paths or wildcards.")
    if not save_dir.is_dir():
        return []
    return sorted(
        path
        for path in save_dir.iterdir()
        if path.name.startswith(screenshot_prefix)
        and path.name.endswith(".png")
        and not path.is_symlink()
        and path.is_file()
        and path.resolve().parent == save_dir.resolve()
    )


def clear_stale_screenshots(screenshot_prefix: str, save_dir: Path) -> None:
    for stale in screenshot_files(screenshot_prefix, save_dir):
        stale.unlink(missing_ok=True)


def collect_screenshots(shots_dir: Path, screenshot_prefix: str, started_wall: float, save_dir: Path) -> list[Path]:
    """Move screenshots the game saved (screen_save writes to its save directory) next to the run log."""
    if shots_dir.is_symlink():
        raise SnapshotError("The screenshot destination must not be a symlink.")
    shots_dir.mkdir(parents=True, exist_ok=True)
    collected: list[Path] = []
    for shot in screenshot_files(screenshot_prefix, save_dir):
        if shot.stat().st_mtime >= started_wall - 1.0:
            target = shots_dir / shot.name
            if target.is_symlink():
                raise SnapshotError("Refusing to overwrite a screenshot symlink.")
            shutil.move(str(shot), str(target))
            collected.append(target)
    return collected


def stop_process(process: subprocess.Popen | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run_game_archive(
    game_archive: Path,
    toolchain: Toolchain,
    *,
    label: str,
    run_dir: Path,
    project_root: Path,
    run_lock: DirectoryLock | None = None,
    timeout_seconds: float = 120.0,
    result_marker: str = "[TEST_RESULT]",
    screenshot_prefix: str = "__agent_shot_",
    lock_timeout_seconds: float = 3600.0,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a compiled game on this Mac and wait for its result line.

    Different projects use separate signed runner bundles and save directories.
    A project lease protects saves; waiting does not count towards ``timeout_seconds``.
    """
    runner = require_mac_runner(toolchain)
    run_dir.mkdir(parents=True, exist_ok=True)
    shots_dir = run_dir / "shots"
    if shots_dir.exists():
        shutil.rmtree(shots_dir)
    run_log = run_dir / "run.log"

    error_patterns = _test_runtime_error_patterns(project_root)
    lock = run_lock or project_run_lock(project_root)
    if not lock.held:
        lock.acquire(
            timeout_seconds=lock_timeout_seconds,
            sleep=run_status.waiting_sleep("waiting for this project's game to be free"),
        )
    process: subprocess.Popen | None = None
    staging: Path | None = None
    timed_out = False
    waited = 0.0
    try:
        owned_runtime = prepare_mac_runtime(runner, project_root, label)
        staging = owned_runtime.staging
        staging, game_file = stage_game_archive(game_archive, staging)
        clear_stale_screenshots(screenshot_prefix, owned_runtime.save_dir)
        started_wall = time.time()
        run_status.report_stage("starting the game")
        process, debug_log = launch_mac_runner(owned_runtime.runner, staging, game_file, run_dir, environment)
        lock.bind_process(process.pid)
        started = time.monotonic()
        run_status.report_stage("running the test", live_log=str(debug_log), timeout_seconds=timeout_seconds)
        reported_frame: int | None = None
        while True:
            time.sleep(0.5)
            waited = time.monotonic() - started
            if run_status.stop_requested():
                break
            lock.heartbeat()  # so a long run is not mistaken for a dead one
            text = debug_log.read_text(encoding="utf-8", errors="replace") if debug_log.is_file() else ""
            frame = last_test_frame(text)
            if frame is not None and frame != reported_frame:
                reported_frame = frame
                run_status.report_detail(test_frame=frame)
            if result_marker in text:
                time.sleep(1.0)  # let screen_save and the final log lines land
                break
            if any(pattern in text for pattern in error_patterns):
                break  # Fatal-error dialogs keep the process alive but cannot produce a test result.
            if process.poll() is not None and waited > 2.0:
                break
            if waited >= timeout_seconds:
                timed_out = True
                break
        run_status.report_stage("collecting the test result")
        if debug_log.is_file():
            copy_artifact(debug_log, run_log)
        else:
            with artifact_writer(run_log):
                pass
        exit_code = process.poll()
        stop_process(process)
        return {
            "timed_out": timed_out,
            "test_frame": reported_frame,
            "waited_seconds": round(waited, 1),
            "waited_for_lock_seconds": round(lock.waited_seconds, 1),
            "run_log": run_log,
            "screenshots": collect_screenshots(shots_dir, screenshot_prefix, started_wall, owned_runtime.save_dir),
            "exit_code": exit_code,
        }
    finally:
        stop_process(process)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        lock.release()


# ----------------------------------------------------------------------
# Whole pipelines
# ----------------------------------------------------------------------
_IGOR_PLATFORMS = frozenset({"Mac", "Windows", "Linux", "Android", "iOS", "HTML5"})


def igor_platform(platform: str | None) -> str:
    """The token Igor expects after ``--``, shared with the runner's platform mapping."""
    from .runner_support.targets import _to_igor_platform, normalize_platform_target

    if not platform:
        return {"darwin": "Mac", "win32": "Windows"}.get(sys.platform, "Linux")
    token = _to_igor_platform(normalize_platform_target(str(platform)))
    if token not in _IGOR_PLATFORMS:
        raise SnapshotError(f"Unknown platform '{platform}'. Use one of: macOS, Windows, Linux, Android, iOS, HTML5.")
    return token


def _relative(project_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def snapshot_compile(
    project_root: str | Path,
    *,
    label: str = "default",
    isolate_paths: Iterable[str] | None = None,
    yyp_entries: Iterable[str] | None = None,
    ref: str = "HEAD",
    base_only: bool = False,
    platform: str | None = None,
    runtime: str = "VM",
    runtime_version: str | None = None,
    attempts: int | None = None,
    test_code: str | None = None,
    keep_work_dir: bool = False,
    run_igor: Callable[[list[str], Path, float], int] | None = None,
    toolchain: Toolchain | None = None,
) -> tuple[dict[str, Any], BuildResult, Path, Toolchain]:
    """Snapshot and compile. Returns (public result, build result, work dir, toolchain)."""
    root = Path(project_root).resolve()
    label = safe_label(label)
    run_dir = runs_directory(root, label)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Unique per invocation: tools run on threads, so two calls in one process can share a label,
    # and two projects can share a folder name.
    work = Path(tempfile.mkdtemp(prefix=f"{safe_label(root.name)}_{label}_", dir=_work_root()))
    snapshot_root = work / "project"
    try:
        run_status.report_stage("copying the project")
        snapshot_info = create_snapshot(
            root, snapshot_root, isolate_paths=isolate_paths, yyp_entries=yyp_entries, ref=ref, base_only=base_only
        )
        (snapshot_root / ".gms-mcp-snapshot").write_text("snapshot\n", encoding="utf-8")
        if test_code is not None:
            prelude = DEFAULT_TEST_PRELUDE
            prelude_file = project_setting(root, "test.prelude_file")
            if prelude_file:
                prelude_path = project_file_path(prelude_file, project_root=root, kind="test.prelude_file")
                if not prelude_path.is_file():
                    raise SnapshotError(
                        f"test.prelude_file in .gms-mcp.json points at '{prelude_file}', which does not exist."
                    )
                prelude = load_test_source(root, str(prelude_file), None)
            inject_test_script(
                snapshot_root,
                test_code,
                script_name=_test_text_setting(root, "test.script_name", "__agent_test"),
                prelude=prelude,
            )
        tools = toolchain or discover_toolchain(root, runtime_version)
        build = compile_snapshot(
            snapshot_root,
            work,
            tools,
            platform=igor_platform(platform),
            runtime=runtime,
            attempts=attempts if attempts is not None else int(project_setting(root, "build.igor_attempts", 10)),
            jobs=int(project_setting(root, "build.jobs", 4)),
            max_parallel_builds=int(project_setting(root, "build.max_parallel_builds", 4)),
            build_log=run_dir / "build.log",
            run_igor=run_igor,
        )
    except BaseException as exc:
        # A stopped run never hands its work directory to the caller, so nothing else would remove it.
        stopped = isinstance(exc, run_status.RunStopped)
        if stopped or (not keep_work_dir and not (isinstance(exc, SnapshotError) and exc.retain_work_dir)):
            shutil.rmtree(work, ignore_errors=True)
        raise
    public = {
        "ok": build.ok,
        "status": build.status,
        "message": build.message,
        "label": label,
        "snapshot": {key: value for key, value in snapshot_info.items() if value not in (None, [], "")},
        "runtime_version": tools.runtime_version,
        "platform": igor_platform(platform),
        "attempts": build.attempts,
        "igor_crash_retries": build.access_violation_retries,
        "errors": build.errors[:80],
        "warnings": build.warnings[:40],
        "packaging_errors": build.packaging_errors[:20],
        "build_log": _relative(root, build.build_log),
        # The build alone, slot wait and retries included. A followed run adds run_seconds for the whole run.
        "build_seconds": build.build_seconds,
        "waited_for_build_slot_seconds": round(build.waited_for_slot_seconds, 1),
    }
    # Leave out what says only "nothing unusual": no errors, one attempt, no wait for a build slot.
    for key, usual in (
        ("errors", []),
        ("warnings", []),
        ("packaging_errors", []),
        ("attempts", 1),
        ("igor_crash_retries", 0),
        ("waited_for_build_slot_seconds", 0.0),
    ):
        if public[key] == usual:
            del public[key]
    if build.other_target_warnings:
        # Otherwise a missing `warnings` reads as "none" beside a log that is full of the word.
        public["other_target_warnings_omitted"] = build.other_target_warnings
    if not build.ok and not build.errors:
        public["log_tail"] = tail_lines(run_dir / "build.log", 25)
    error_locations = locate_compile_errors(root, build.errors[:80], compiled_root=snapshot_root)
    if error_locations:
        # Placed ahead of the raw messages: this is the version a reader can act on.
        located = {
            "error_locations": error_locations,
            "error_locations_note": (
                "`line` is the 1-based line in the file; the compiler's own messages in `errors` count from 0."
            ),
        }
        public = {
            **{key: value for key, value in public.items() if key in ("ok", "status", "message")},
            **located,
            **{key: value for key, value in public.items() if key not in ("ok", "status", "message")},
        }
    return public, build, work, tools


def _run_test_pipeline(
    project_root: str | Path,
    *,
    test_code: str | None = None,
    test_file: str | None = None,
    label: str = "test",
    timeout_seconds: float | None = None,
    isolate_paths: Iterable[str] | None = None,
    yyp_entries: Iterable[str] | None = None,
    ref: str = "HEAD",
    base_only: bool = False,
    runtime: str = "VM",
    runtime_version: str | None = None,
    attempts: int | None = None,
    environment: dict[str, str] | None = None,
    run_igor: Callable[[list[str], Path, float], int] | None = None,
    run_game: Callable[..., dict[str, Any]] | None = None,
    toolchain: Toolchain | None = None,
    run_lock: DirectoryLock | None = None,
) -> dict[str, Any]:
    """Compile a snapshot with the test injected, run it, and report the verdict."""
    root = Path(project_root).resolve()
    source = load_test_source(root, test_file, test_code)
    timeout = float(timeout_seconds or project_setting(root, "test.timeout_seconds", 120))
    result_marker = _test_text_setting(root, "test.result_marker", "[TEST_RESULT]")
    screenshot_prefix = _test_text_setting(root, "test.screenshot_prefix", "__agent_shot_")
    line_marker = _test_text_setting(root, "test.line_marker", "[TEST]")
    started_marker = _test_text_setting(root, "test.started_marker", "[TEST_SAVE_DIR]")
    error_patterns = _test_runtime_error_patterns(root)
    public, build, work, tools = snapshot_compile(
        root,
        label=label,
        isolate_paths=isolate_paths,
        yyp_entries=yyp_entries,
        ref=ref,
        base_only=base_only,
        runtime=runtime,
        runtime_version=runtime_version,
        attempts=attempts,
        test_code=source,
        run_igor=run_igor,
        toolchain=toolchain,
    )
    try:
        if not build.ok or build.game_archive is None:
            public["status"] = "BUILD_FAILED"
            return public
        run_dir = runs_directory(root, label)
        outcome = (run_game or run_game_archive)(
            build.game_archive,
            tools,
            label=public["label"],
            run_dir=run_dir,
            project_root=root,
            run_lock=run_lock,
            timeout_seconds=timeout,
            result_marker=result_marker,
            screenshot_prefix=screenshot_prefix,
            environment=environment,
        )
        run_log: Path = outcome["run_log"]
        verdict = parse_run_log(
            run_log.read_text(encoding="utf-8", errors="replace") if run_log.is_file() else "",
            result_marker=result_marker,
            line_marker=line_marker,
            started_marker=started_marker,
            runtime_error_patterns=error_patterns,
            timed_out=bool(outcome.get("timed_out")),
        )
        note = verdict.pop("note")
        passed = verdict.pop("passed")  # `ok` and `status` already say it
        public.update(verdict)
        public["ok"] = passed
        public["message"] = note or (
            "All checks passed." if passed else "One or more checks failed; see failed_checks."
        )
        for key in ("test_lines", "failed_checks", "runtime_errors"):
            if not public[key]:
                del public[key]
        if public["started"]:
            del public["started"]  # only its absence is news: the game never reached the first frame
        if public["result_line"] is None:
            del public["result_line"]
        public["run_log"] = _relative(root, run_log)
        public.update(screenshot_listing(root, run_dir / "shots", outcome.get("screenshots", [])))
        public["waited_seconds"] = outcome.get("waited_seconds")
        if isinstance(outcome.get("test_frame"), int):
            # Reported about once a second, so the last frame before a timeout or crash is close to this.
            public["test_frame"] = outcome["test_frame"]
        if outcome.get("waited_for_lock_seconds"):
            public["waited_for_game_lock_seconds"] = outcome["waited_for_lock_seconds"]
        if not passed:
            # The lines above already carry the test's own output and the errors; the tail adds the rest.
            reported = {line for block in verdict.get("runtime_errors", []) for line in block.splitlines()}
            public["log_tail"] = tail_lines(
                run_log,
                40,
                skip=lambda line: (
                    not line.strip()
                    or _SEPARATOR_LINE.fullmatch(line) is not None
                    or any(marker in line for marker in (line_marker, result_marker, started_marker))
                    or line.strip() in reported
                ),
            )
        return public
    finally:
        shutil.rmtree(work, ignore_errors=True)


def read_run_artifact(
    project_root: str | Path, label: str, which: str = "run", lines: int = 200, pattern: str | None = None
) -> dict[str, Any]:
    """Read the run log or build log of an earlier labelled run."""
    root = Path(project_root).resolve()
    run_dir = runs_directory(root, label)
    names = {"run": "run.log", "build": "build.log", "runner": "runner_stderr.log"}
    if which not in names:
        raise SnapshotError("which must be one of: run (game log), build (Igor log), runner (runner stderr).")
    path = run_dir / names[which]
    if not path.is_file():
        available = sorted(p.name for p in (root / ".gms_mcp" / "runs").glob("*") if p.is_dir())
        raise SnapshotError(
            f"No {names[which]} for label '{safe_label(label)}'. Labels with saved runs: "
            f"{', '.join(available) or 'none yet'}. Run gm_test_run or gm_snapshot_compile first."
        )
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not pattern:
        # The once-a-second frame reports would crowd out the game's own lines; a pattern can still find them.
        content = [line for line in content if TEST_FRAME_MARKER not in line]
    if pattern:
        try:
            content = [content[index] for index, _ in search_many(pattern, content)]
        except re.error as exc:
            raise SnapshotError(f"pattern is not a valid regular expression: {exc}") from exc
        except ValueError as exc:
            raise SnapshotError(f"Regex search failed: {exc}") from exc
    selected = content[-max(1, min(int(lines), 2000)) :]
    return {
        "ok": True,
        "label": safe_label(label),
        "log": _relative(root, path),
        "total_lines": len(content),
        "lines": selected,
        **screenshot_listing(root, run_dir / "shots"),
    }


def run_test(
    project_root: str | Path,
    *,
    test_code: str | None = None,
    test_file: str | None = None,
    label: str = "test",
    timeout_seconds: float | None = None,
    isolate_paths: Iterable[str] | None = None,
    yyp_entries: Iterable[str] | None = None,
    ref: str = "HEAD",
    base_only: bool = False,
    runtime: str = "VM",
    runtime_version: str | None = None,
    attempts: int | None = None,
    environment: dict[str, str] | None = None,
    run_igor: Callable[[list[str], Path, float], int] | None = None,
    run_game: Callable[..., dict[str, Any]] | None = None,
    toolchain: Toolchain | None = None,
) -> dict[str, Any]:
    """Build and run a scripted test; same-label runs for one project are serialised end to end."""
    require_vm_runtime(runtime)
    with label_pipeline(project_root, label):
        run_lock = project_run_lock(project_root)
        run_lock.acquire(sleep=run_status.waiting_sleep("waiting for this project's game to be free"))
        try:
            return _run_test_pipeline(
                project_root,
                test_code=test_code,
                test_file=test_file,
                label=label,
                timeout_seconds=timeout_seconds,
                isolate_paths=isolate_paths,
                yyp_entries=yyp_entries,
                ref=ref,
                base_only=base_only,
                runtime=runtime,
                runtime_version=runtime_version,
                attempts=attempts,
                environment=environment,
                run_igor=run_igor,
                run_game=run_game,
                toolchain=toolchain,
                run_lock=run_lock,
            )
        finally:
            run_lock.release()
