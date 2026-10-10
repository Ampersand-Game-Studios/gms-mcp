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

import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import yyp_registry
from .agent_locks import GAME_RUN_LOCK, MOBILE_BUILD_LOCK, BuildSlot, DirectoryLock
from .exceptions import ValidationError
from .project_config import project_setting
from .utils import find_yyp

ACCESS_VIOLATION_MARKER = "AccessViolationException"
_COMPILE_FINISHED_MARKER = "Final Compile finished"
_ERROR_LINE = re.compile(r"Error :|error :|Project Error")
_WARNING_LINE = re.compile(r"Warning : ")
_LABEL = re.compile(r"[^A-Za-z0-9_]")
_SNAPSHOT_IGNORED = {".git", ".gms_mcp", ".gms-mcp", "output", "__pycache__", ".pytest_cache", ".gml_index_cache"}
_MAX_TEST_BYTES = 2 * 1024 * 1024

# The test API every injected test can rely on. A project may replace this file through
# ``test.prelude_file`` in .gms-mcp.json; a replacement must print the same marker lines.
DEFAULT_TEST_PRELUDE = r"""
// ---- injected by gms-mcp (snapshot only; never part of the project) ----
global.__agent_test_failures = 0;
global.__agent_test_frame = 0;
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
	agent_test_step(global.__agent_test_frame);
}, [], -1);
time_source_start(global.__agent_test_ts);
// ---- end of injected prelude ----
"""

TEST_API_HELP = (
    "A test is GML that defines `function agent_test_step(_frame) { ... }`, called once per frame from "
    "frame 1. Helpers: test_log(value), test_check(condition, label) (any failed check fails the run), "
    "test_shot(name) (screenshot), test_end() (prints the result and quits; always call it)."
)


class SnapshotError(ValidationError):
    """A snapshot build could not be prepared; the message says what to change."""


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
    elapsed_seconds: float = 0.0


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
def safe_label(label: str) -> str:
    cleaned = _LABEL.sub("_", str(label or "default")).strip("_")
    return cleaned[:60] or "default"


def runs_directory(project_root: str | Path, label: str) -> Path:
    """Where logs and screenshots of one labelled run are kept (inside the project, ignored)."""
    return Path(project_root).resolve() / ".gms_mcp" / "runs" / safe_label(label)


def _work_root() -> Path:
    configured = os.environ.get("GMS_MCP_SNAPSHOT_WORK_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path(tempfile.gettempdir()) / "gms-mcp-snapshots"


def _runner_staging_root() -> Path:
    """A directory whose path the macOS runner can parse.

    The runner treats ``-game`` anywhere in its command line as the start of the game
    argument, so a project kept in a folder such as ``my-game`` makes it load the wrong file.
    """
    candidates = [
        Path(os.environ["GMS_MCP_RUN_STAGING_DIR"]).expanduser() if os.environ.get("GMS_MCP_RUN_STAGING_DIR") else None,
        Path(tempfile.gettempdir()) / "gmsmcp_runs",
        Path("/Users/Shared/GameMakerStudio2/gmsmcp_runs"),
        Path.home() / ".gmsmcp_runs",
    ]
    for candidate in candidates:
        if candidate is not None and "-game" not in str(candidate.resolve()).lower():
            return candidate
    raise SnapshotError(
        "No usable staging directory for the macOS runner: every candidate path contains '-game', which the "
        "runner misreads as its -game argument. Set GMS_MCP_RUN_STAGING_DIR to a directory whose full path "
        "has no '-game' in it."
    )


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
def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], input=input_bytes, capture_output=True, check=False)


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
    relative = root.relative_to(repo).as_posix()
    return repo, "" if relative == "." else relative


def _project_relative(path: str, project_prefix: str) -> str:
    normalized = str(path).replace("\\", "/").strip().strip("/")
    if project_prefix and (normalized == project_prefix or normalized.startswith(project_prefix + "/")):
        normalized = normalized[len(project_prefix) :].strip("/")
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/" or normalized.startswith("/"):
        raise SnapshotError(
            f"'{path}' is not a path inside the project. Use paths relative to the folder containing the .yyp, "
            "for example scripts/my_script or objects/o_player/Step_0.gml."
        )
    return normalized


def _copy_tree(source: Path, destination: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        if Path(directory) == source:
            return {name for name in names if name in _SNAPSHOT_IGNORED}
        return {name for name in names if name == "__pycache__"}

    shutil.copytree(source, destination, ignore=ignore, symlinks=False, dirs_exist_ok=True)


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
    root = Path(project_root).resolve()
    dest = Path(destination)
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
        _copy_tree(root, dest)
        return {"mode": "working-tree", "isolated_paths": [], "yyp_entries": [], "ref": None}

    repo, prefix = git_context(root)
    archive = _git(repo, "archive", "--format=tar", ref, *([prefix] if prefix else []))
    if archive.returncode != 0:
        raise SnapshotError(
            f"git could not read revision '{ref}': {archive.stderr.decode('utf-8', 'replace').strip()}. "
            "Pass a commit, branch or tag that exists (default HEAD)."
        )
    staging = Path(tempfile.mkdtemp(prefix="gms-mcp-archive-", dir=dest.parent))
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            try:
                tar.extractall(staging, filter="data")
            except TypeError:  # Python < 3.12 without the filter argument
                tar.extractall(staging)
        base_project = staging / prefix if prefix else staging
        if not (base_project / yyp_name).is_file():
            raise SnapshotError(
                f"Revision '{ref}' does not contain {prefix + '/' if prefix else ''}{yyp_name}. "
                "Choose a revision that has this project."
            )
        relative_paths = [_project_relative(path, prefix) for path in paths]
        for relative in relative_paths:
            source = root / relative
            target = base_project / relative
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            if source.is_dir():
                shutil.copytree(source, target, symlinks=False)
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        base_text = (base_project / yyp_name).read_text(encoding="utf-8")
        entries = [str(entry) for entry in (yyp_entries or []) if str(entry).strip()]
        if not entries and relative_paths:
            entries = yyp_registry.derive_yyp_entries(root, base_text, relative_paths)
        if yyp_name not in relative_paths and entries:
            composed = yyp_registry.compose_yyp(base_text, (root / yyp_name).read_text(encoding="utf-8"), entries)
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


def load_test_source(project_root: Path, test_file: str | None, test_code: str | None) -> str:
    if bool(test_file) == bool(test_code):
        raise SnapshotError("Pass exactly one of test_code (the GML text) or test_file (a path to a .gml file).")
    if test_code:
        return test_code
    path = Path(str(test_file)).expanduser()
    if not path.is_absolute():
        path = project_root / path
    if not path.is_file():
        raise SnapshotError(f"Test file not found: {test_file}. Pass an absolute path or the GML text as test_code.")
    if path.stat().st_size > _MAX_TEST_BYTES:
        raise SnapshotError("The test file is larger than 2 MB; that is not a test script.")
    return path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Compile
# ----------------------------------------------------------------------
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
        elif _WARNING_LINE.search(stripped) and "not available for this target" not in stripped:
            if stripped not in warnings:
                warnings.append(stripped)
    return errors, warnings, packaging


def _default_run_igor(command: list[str], log_path: Path, timeout_seconds: float) -> int:
    with log_path.open("wb") as log:
        try:
            completed = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout_seconds, check=False
            )
            return completed.returncode
        except subprocess.TimeoutExpired:
            log.write(f"\n[gms-mcp] Igor was stopped after {int(timeout_seconds)}s without finishing.\n".encode())
            return -9


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
        # Igor offers PackageZip only for desktop and HTML5 targets; mobile and Linux use Package.
        action="PackageZip" if platform in {"Mac", "Windows", "HTML5"} else "Package",
    )
    runner = run_igor or _default_run_igor
    result = BuildResult(ok=False, status="BUILD_FAILED", build_log=build_log or log_path)
    mobile = str(platform).lower() in {"android", "ios"}
    attempt_limit = max(1, int(attempts))
    text = ""
    for attempt in range(1, attempt_limit + 1):
        result.attempts = attempt
        slot = BuildSlot(max_parallel_builds, purpose=f"igor build {project_file.name}")
        slot.acquire(timeout_seconds=slot_timeout_seconds)
        result.waited_for_slot_seconds += slot.waited_seconds
        # Mobile packaging shares Xcode/Gradle output folders and attached devices, so only one
        # mobile build runs at a time, on top of the general capacity slot.
        mobile_lock = DirectoryLock(MOBILE_BUILD_LOCK, purpose=f"mobile build {project_file.name}") if mobile else None
        try:
            if mobile_lock is not None:
                mobile_lock.acquire(timeout_seconds=slot_timeout_seconds)
            runner(command, log_path, igor_timeout_seconds)
        finally:
            if mobile_lock is not None and mobile_lock.held:
                mobile_lock.release()
            slot.release()
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        result.errors, result.warnings, result.packaging_errors = classify_build_log(text)
        # The crash can hit the project loader or a later packaging step; either way the
        # output is unusable. Real compiler errors are final: retrying cannot fix them.
        if ACCESS_VIOLATION_MARKER not in text or result.errors or attempt == attempt_limit:
            break
        result.access_violation_retries += 1
    if build_log is not None and log_path.is_file() and Path(build_log) != log_path:
        Path(build_log).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(log_path, build_log)
    result.elapsed_seconds = round(time.monotonic() - started, 1)
    # Igor's final packaging step can fail on a shared staging folder after the game data
    # was written; the compiled game archive is what a run needs.
    archive = next((p for p in (out_dir / "game.zip", out_dir / "build.zip") if p.is_file()), None)
    crashed = ACCESS_VIOLATION_MARKER in text
    desktop = platform in {"Mac", "Windows", "Linux"}
    if archive is not None and not zipfile.is_zipfile(archive):
        archive = None
    if not desktop and result.packaging_errors:
        # For a mobile or web target the package is the product, so its errors are fatal.
        result.errors = [*result.errors, *result.packaging_errors]
    compiled = _COMPILE_FINISHED_MARKER in text and not result.errors and not crashed
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
def tail_lines(path: Path, count: int) -> list[str]:
    """Last lines of a log without .NET stack frames, which bury the line that matters."""
    if not path.is_file():
        return []
    lines = [
        line[:400]
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not line.lstrip().startswith("at System.") and not line.lstrip().startswith("at Microsoft.")
    ]
    return lines[-max(0, count) :]


def parse_run_log(
    text: str,
    *,
    result_marker: str = "[TEST_RESULT]",
    line_marker: str = "[TEST]",
    started_marker: str = "[TEST_SAVE_DIR]",
    runtime_error_patterns: Iterable[str] = (),
    timed_out: bool = False,
) -> dict[str, Any]:
    """Turn a runner log into a verdict. The log is the only source of truth for a run."""
    lines = text.splitlines()
    test_lines = [line.strip() for line in lines if line_marker in line or result_marker in line]
    result_line = next((line.strip() for line in lines if result_marker in line), None)
    patterns = [pattern for pattern in runtime_error_patterns if pattern]
    error_blocks: list[str] = []
    for index, line in enumerate(lines):
        if any(pattern in line for pattern in patterns) and not any(line in block for block in error_blocks):
            block = "\n".join(lines[max(0, index - 2) : index + 15])
            if len(error_blocks) < 5:
                error_blocks.append(block)
    failed_checks = [line for line in test_lines if f"{line_marker} FAIL" in line]
    started = started_marker in text
    note = ""
    if result_line and "PASS" in result_line.split(result_marker, 1)[1]:
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
    return {
        "status": status,
        "passed": status == "TEST_PASSED",
        "result_line": result_line,
        "test_lines": test_lines[:400],
        "failed_checks": failed_checks[:100],
        "runtime_errors": error_blocks,
        "started": started,
        "note": note,
    }


def _mac_runner(toolchain: Toolchain) -> Path:
    return toolchain.runtime_path / "mac" / "YoYo Runner.app" / "Contents" / "MacOS" / "Mac_Runner"


def _mac_save_directory() -> Path:
    return Path.home() / "Library" / "Application Support" / "com.yoyogames.macyoyorunner"


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


def stage_game_archive(game_archive: Path, label: str) -> tuple[Path, Path]:
    """Unpack a compiled game where the runner can load it. Returns (staging dir, game file)."""
    staging = _runner_staging_root() / safe_label(label)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(game_archive) as archive:
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
    with (run_dir / "runner_stderr.log").open("wb") as stderr_log:
        process = subprocess.Popen(
            [str(runner), "-game", str(game_file), "-debugoutput", str(debug_log), "-output", str(debug_log)],
            cwd=str(staging),
            stdout=stderr_log,
            stderr=subprocess.STDOUT,
            env={**os.environ, **(environment or {})},
        )
    return process, debug_log


def clear_stale_screenshots(screenshot_prefix: str) -> None:
    save_dir = _mac_save_directory()
    if save_dir.is_dir():
        for stale in save_dir.glob(f"{screenshot_prefix}*.png"):
            stale.unlink(missing_ok=True)


def collect_screenshots(shots_dir: Path, screenshot_prefix: str, started_wall: float) -> list[Path]:
    """Move screenshots the game saved (screen_save writes to its save directory) next to the run log."""
    shots_dir.mkdir(parents=True, exist_ok=True)
    collected: list[Path] = []
    save_dir = _mac_save_directory()
    if save_dir.is_dir():
        for shot in sorted(save_dir.glob(f"{screenshot_prefix}*.png")):
            if shot.stat().st_mtime >= started_wall - 1.0:
                target = shots_dir / shot.name
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


def run_game_archive(
    game_archive: Path,
    toolchain: Toolchain,
    *,
    label: str,
    run_dir: Path,
    timeout_seconds: float = 120.0,
    result_marker: str = "[TEST_RESULT]",
    screenshot_prefix: str = "__agent_shot_",
    lock_timeout_seconds: float = 3600.0,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a compiled game on this Mac and wait for its result line.

    Only one game runs at a time on a machine (they share a save directory, a window and
    the audio device); waiting for that lock does not count towards ``timeout_seconds``.
    """
    runner = require_mac_runner(toolchain)
    run_dir.mkdir(parents=True, exist_ok=True)
    shots_dir = run_dir / "shots"
    if shots_dir.exists():
        shutil.rmtree(shots_dir)
    run_log = run_dir / "run.log"

    lock = DirectoryLock(GAME_RUN_LOCK, stale_seconds=max(1800.0, timeout_seconds + 600.0), purpose=f"test run {label}")
    lock.acquire(timeout_seconds=lock_timeout_seconds)
    process: subprocess.Popen | None = None
    staging: Path | None = None
    timed_out = False
    waited = 0.0
    try:
        staging, game_file = stage_game_archive(game_archive, label)
        clear_stale_screenshots(screenshot_prefix)
        started_wall = time.time()
        process, debug_log = launch_mac_runner(runner, staging, game_file, run_dir, environment)
        started = time.monotonic()
        while True:
            time.sleep(0.5)
            waited = time.monotonic() - started
            try:
                os.utime(lock.path, None)  # heartbeat so a long run is not mistaken for a dead one
            except OSError:
                pass
            text = debug_log.read_text(encoding="utf-8", errors="replace") if debug_log.is_file() else ""
            if result_marker in text:
                time.sleep(1.0)  # let screen_save and the final log lines land
                break
            if process.poll() is not None and waited > 2.0:
                break
            if waited >= timeout_seconds:
                timed_out = True
                break
        if debug_log.is_file():
            shutil.copy2(debug_log, run_log)
        else:
            run_log.write_text("", encoding="utf-8")
        exit_code = process.poll()
        stop_process(process)
        return {
            "timed_out": timed_out,
            "waited_seconds": round(waited, 1),
            "waited_for_lock_seconds": round(lock.waited_seconds, 1),
            "run_log": run_log,
            "screenshots": collect_screenshots(shots_dir, screenshot_prefix, started_wall),
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
_IGOR_PLATFORMS = {
    "macos": "Mac",
    "mac": "Mac",
    "windows": "Windows",
    "linux": "Linux",
    "android": "Android",
    "ios": "ios",
    "html5": "HTML5",
}


def igor_platform(platform: str | None) -> str:
    if not platform:
        return {"darwin": "Mac", "win32": "Windows"}.get(sys.platform, "Linux")
    key = str(platform).strip().lower()
    if key not in _IGOR_PLATFORMS:
        raise SnapshotError(f"Unknown platform '{platform}'. Use one of: macOS, Windows, Linux, Android, iOS, HTML5.")
    return _IGOR_PLATFORMS[key]


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
    work = _work_root() / f"{safe_label(root.name)}_{label}_{os.getpid()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    snapshot_root = work / "project"
    try:
        snapshot_info = create_snapshot(
            root, snapshot_root, isolate_paths=isolate_paths, yyp_entries=yyp_entries, ref=ref, base_only=base_only
        )
        (snapshot_root / ".gms-mcp-snapshot").write_text("snapshot\n", encoding="utf-8")
        if test_code is not None:
            prelude = DEFAULT_TEST_PRELUDE
            prelude_file = project_setting(root, "test.prelude_file")
            if prelude_file:
                prelude_path = root / str(prelude_file)
                if not prelude_path.is_file():
                    raise SnapshotError(
                        f"test.prelude_file in .gms-mcp.json points at '{prelude_file}', which does not exist."
                    )
                prelude = prelude_path.read_text(encoding="utf-8")
            inject_test_script(
                snapshot_root,
                test_code,
                script_name=str(project_setting(root, "test.script_name", "__agent_test")),
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
    except BaseException:
        if not keep_work_dir:
            shutil.rmtree(work, ignore_errors=True)
        raise
    public = {
        "ok": build.ok,
        "status": build.status,
        "message": build.message,
        "label": label,
        "snapshot": snapshot_info,
        "runtime_version": tools.runtime_version,
        "platform": igor_platform(platform),
        "attempts": build.attempts,
        "igor_crash_retries": build.access_violation_retries,
        "errors": build.errors[:80],
        "warnings": build.warnings[:40],
        "packaging_errors": build.packaging_errors[:20],
        "build_log": _relative(root, build.build_log),
        "elapsed_seconds": build.elapsed_seconds,
        "waited_for_build_slot_seconds": round(build.waited_for_slot_seconds, 1),
    }
    if not build.ok and not build.errors:
        public["log_tail"] = tail_lines(run_dir / "build.log", 25)
    return public, build, work, tools


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
    """Compile a snapshot with the test injected, run it, and report the verdict."""
    root = Path(project_root).resolve()
    source = load_test_source(root, test_file, test_code)
    timeout = float(timeout_seconds or project_setting(root, "test.timeout_seconds", 120))
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
            public["passed"] = False
            return public
        run_dir = runs_directory(root, label)
        outcome = (run_game or run_game_archive)(
            build.game_archive,
            tools,
            label=public["label"],
            run_dir=run_dir,
            timeout_seconds=timeout,
            result_marker=str(project_setting(root, "test.result_marker", "[TEST_RESULT]")),
            screenshot_prefix=str(project_setting(root, "test.screenshot_prefix", "__agent_shot_")),
            environment=environment,
        )
        run_log: Path = outcome["run_log"]
        verdict = parse_run_log(
            run_log.read_text(encoding="utf-8", errors="replace") if run_log.is_file() else "",
            result_marker=str(project_setting(root, "test.result_marker", "[TEST_RESULT]")),
            line_marker=str(project_setting(root, "test.line_marker", "[TEST]")),
            started_marker=str(project_setting(root, "test.started_marker", "[TEST_SAVE_DIR]")),
            runtime_error_patterns=project_setting(root, "test.runtime_error_patterns", []),
            timed_out=bool(outcome.get("timed_out")),
        )
        public.update(verdict)
        public["ok"] = verdict["passed"]
        public["message"] = verdict["note"] or (
            "All checks passed." if verdict["passed"] else "One or more checks failed; see failed_checks."
        )
        public["run_log"] = _relative(root, run_log)
        public["screenshots"] = [_relative(root, shot) for shot in outcome.get("screenshots", [])]
        public["waited_seconds"] = outcome.get("waited_seconds")
        public["waited_for_game_lock_seconds"] = outcome.get("waited_for_lock_seconds")
        if not verdict["passed"]:
            public["log_tail"] = tail_lines(run_log, 40)
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
    if pattern:
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            raise SnapshotError(f"pattern is not a valid regular expression: {exc}") from exc
        content = [line for line in content if matcher.search(line)]
    selected = content[-max(1, min(int(lines), 2000)) :]
    return {
        "ok": True,
        "label": safe_label(label),
        "log": _relative(root, path),
        "total_lines": len(content),
        "lines": selected,
        "screenshots": sorted(str(_relative(root, p)) for p in (run_dir / "shots").glob("*.png")),
    }
