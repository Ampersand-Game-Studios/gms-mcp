"""A running game an agent can talk to: isolated snapshot + runtime bridge.

``start`` compiles a snapshot, launches it with the bridge port in its environment and
waits for the game's endpoint to connect. ``command`` then sends bridge commands;
``stop`` ends the game and files its log and screenshots under ``.gms_mcp/runs/<label>/``.

Runtime bridge contract (protocol 2), shared by every game-side endpoint:

* Transport: TCP on 127.0.0.1. The MCP server listens; the game connects out to the port
  named in the ``GMS_MCP_BRIDGE_PORT`` environment variable. A game started without that
  variable must not open a socket at all.
* Framing: UTF-8 lines ending in ``\\n``. NUL bytes are ignored.
* Game -> server: ``HELLO:<json>`` once after connecting, ``LOG:<ms>|<text>``,
  ``RSP:<id>|<result>``.
* Server -> game: ``CMD:<id>|<name> <arguments>``.
* A result is plain text, or one line of JSON when it starts with ``{`` or ``[``.
  A failure is ``ERR:<code> <message>``.
* Standard commands every endpoint provides: ``ping`` (-> ``pong``), ``help``, ``state``,
  ``screenshot [name]``, ``log_tail [count]``, ``console <command line>``.
  ``input ...`` is reserved for input injection by a test harness.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import snapshot_build
from .agent_locks import DirectoryLock
from .mac_runtime import prepare_mac_runtime, project_identity, project_run_lock
from .bridge_server import BridgeServer
from .project_config import project_setting
from .run_session import RunSessionManager

BRIDGE_PORT_ENVIRONMENT_VARIABLE = "GMS_MCP_BRIDGE_PORT"
STANDARD_COMMANDS = ("ping", "help", "state", "screenshot", "log_tail", "console")


class LiveSessionError(snapshot_build.SnapshotError):
    """A live session request cannot be served; the message says what to do next."""


@dataclass
class LiveSession:
    project_root: Path
    label: str
    process: subprocess.Popen
    bridge: BridgeServer
    lock: DirectoryLock
    label_lock: DirectoryLock
    save_dir: Path
    staging: Path
    debug_log: Path
    run_dir: Path
    work_dir: Path
    started_wall: float = field(default_factory=time.time)
    screenshot_prefix: str = "__agent_shot_"
    run_id: str | None = None
    cleaned: bool = False
    cleanup_guard: threading.Lock = field(default_factory=threading.Lock)

    @property
    def alive(self) -> bool:
        return self.process.poll() is None


_SESSIONS: dict[str, LiveSession] = {}
_SESSIONS_GUARD = threading.Lock()


def _key(project_root: str | Path) -> str:
    return str(Path(project_root).resolve())


def get_session(project_root: str | Path) -> LiveSession | None:
    with _SESSIONS_GUARD:
        return _SESSIONS.get(_key(project_root))


def _require_session(project_root: str | Path) -> LiveSession:
    session = get_session(project_root)
    if session is None:
        raise LiveSessionError("No live game is running for this project. Start one with gm_game_start.")
    return session


def parse_bridge_result(text: str | None) -> dict[str, Any]:
    """Interpret one bridge response line."""
    raw = "" if text is None else str(text)
    if raw.startswith("ERR:"):
        code, _, message = raw[4:].partition(" ")
        return {"ok": False, "error_code": code or "error", "error": message or raw[4:], "result": raw}
    if raw[:1] in "{[":
        try:
            return {"ok": True, "result": raw, "data": json.loads(raw)}
        except ValueError:
            pass
    return {"ok": True, "result": raw}


def _start(
    project_root: str | Path,
    *,
    label: str = "live",
    isolate_paths: Iterable[str] | None = None,
    yyp_entries: Iterable[str] | None = None,
    base_only: bool = False,
    ref: str = "HEAD",
    runtime: str = "VM",
    runtime_version: str | None = None,
    attempts: int | None = None,
    connect_timeout_seconds: float = 60.0,
    test_code: str | None = None,
    lock_timeout_seconds: float = 3600.0,
    lock: DirectoryLock,
    label_lock: DirectoryLock,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    existing = get_session(root)
    if existing is not None:
        if existing.alive:
            raise LiveSessionError(
                f"A live game ('{existing.label}') is already running for this project. Use it, or stop it "
                "with gm_game_stop before starting another."
            )
        stop(root)

    public, build, work, tools = snapshot_build.snapshot_compile(
        root,
        label=label,
        isolate_paths=isolate_paths,
        yyp_entries=yyp_entries,
        ref=ref,
        base_only=base_only,
        runtime=runtime,
        runtime_version=runtime_version,
        attempts=attempts,
        test_code=test_code,
        keep_work_dir=True,
    )
    if not build.ok or build.game_archive is None:
        shutil.rmtree(work, ignore_errors=True)
        public["connected"] = False
        return public

    run_dir = snapshot_build.runs_directory(root, label)
    screenshot_prefix = str(project_setting(root, "test.screenshot_prefix", "__agent_shot_"))
    bridge = BridgeServer(port=0)
    process: subprocess.Popen | None = None
    staging: Path | None = None
    try:
        runner = snapshot_build.require_mac_runner(tools)
        if not bridge.start():
            raise LiveSessionError("Could not open a local TCP port for the runtime bridge.")
        owned_runtime = prepare_mac_runtime(runner, root, label)
        staging = owned_runtime.staging
        staging, game_file = snapshot_build.stage_game_archive(build.game_archive, staging)
        snapshot_build.clear_stale_screenshots(screenshot_prefix, owned_runtime.save_dir)
        shots = run_dir / "shots"
        if shots.exists():
            shutil.rmtree(shots)
        process, debug_log = snapshot_build.launch_mac_runner(
            owned_runtime.runner, staging, game_file, run_dir, {BRIDGE_PORT_ENVIRONMENT_VARIABLE: str(bridge.port)}
        )
        lock.bind_process(process.pid)
        label_lock.bind_process(process.pid)
        deadline = time.monotonic() + connect_timeout_seconds
        while time.monotonic() < deadline and not bridge.is_connected and process.poll() is None:
            time.sleep(0.2)
        # Give the endpoint a moment to send its handshake.
        handshake_deadline = time.monotonic() + 2.0
        while bridge.is_connected and bridge.hello is None and time.monotonic() < handshake_deadline:
            time.sleep(0.05)
    except BaseException:
        snapshot_build.stop_process(process)
        bridge.stop()
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        lock.release()
        shutil.rmtree(work, ignore_errors=True)
        raise

    session = LiveSession(
        project_root=root,
        label=public["label"],
        process=process,
        bridge=bridge,
        lock=lock,
        label_lock=label_lock,
        save_dir=owned_runtime.save_dir,
        staging=staging,
        debug_log=debug_log,
        run_dir=run_dir,
        work_dir=work,
        screenshot_prefix=screenshot_prefix,
    )
    try:
        from .runner import GameMakerRunner

        identity = GameMakerRunner(root)._snapshot_macos_processes().get(process.pid)
        if identity is None and process.poll() is None:
            raise LiveSessionError("Cannot persist the owned runner identity; stopping this launch safely.")
        persisted = RunSessionManager(root).create_session(
            pid=process.pid,
            exe_path=str(game_file),
            platform_target="macOS",
            runtime_type=runtime,
            log_file=str(debug_log),
            bridge_port=bridge.port,
            isolated_runtime=True,
            runtime_label=session.label,
            runtime_work_dir=str(work),
            runtime_save_dir=str(owned_runtime.save_dir),
            macos_runner_commands={str(process.pid): identity.command} if identity else {},
            macos_runner_starts={str(process.pid): identity.started} if identity else {},
        )
        session.run_id = persisted.run_id
    except BaseException:
        snapshot_build.stop_process(process)
        _cleanup(session)
        raise
    with _SESSIONS_GUARD:
        _SESSIONS[_key(root)] = session
    threading.Thread(target=_watch_exit, args=(session,), daemon=True, name=f"gms-game-{process.pid}").start()

    public["pid"] = process.pid
    public["run_id"] = session.run_id
    public["save_directory"] = str(owned_runtime.save_dir)
    public["bundle_id"] = owned_runtime.bundle_id
    public["connected"] = bridge.is_connected
    public["bridge_port"] = bridge.port
    public["endpoint"] = bridge.hello
    public["running"] = session.alive
    if not session.alive:
        public["ok"] = False
        public["status"] = "GAME_EXITED"
        public["message"] = (
            "The game exited during start-up. The log tail shows why (a runtime error in a Create event is "
            "the usual cause)."
        )
        public["log_tail"] = snapshot_build.tail_lines(session.debug_log, 40)
        stop(root)
    elif not bridge.is_connected:
        public["status"] = "RUNNING_NOT_CONNECTED"
        public["message"] = (
            "The game is running but its bridge endpoint did not connect within "
            f"{int(connect_timeout_seconds)}s. gm_game_log still works. The project needs a bridge endpoint "
            f"that reads the {BRIDGE_PORT_ENVIRONMENT_VARIABLE} environment variable and is enabled in this "
            "build (see documentation/BRIDGE.md, 'Runtime bridge protocol 2')."
        )
    else:
        public["status"] = "RUNNING"
        public["message"] = (
            "Game running and connected. Use gm_game_command (ping, help, state, console <line>, "
            "log_tail [n]), gm_game_screenshot and gm_game_log; call gm_game_stop when finished to "
            "release this project session."
        )
    return public


def status(project_root: str | Path) -> dict[str, Any]:
    session = get_session(project_root)
    if session is None:
        persisted = RunSessionManager(Path(project_root)).get_current_session()
        if persisted is not None and persisted.isolated_runtime:
            from .runner import GameMakerRunner

            runner = GameMakerRunner(Path(project_root))
            processes = runner._snapshot_macos_processes()
            owned, _ = runner._tracked_macos_helper_pids(persisted, processes)
            if not owned:
                stop_persisted(project_root, persisted)
            return {
                "ok": True,
                "running": bool(owned),
                "connected": False,
                "pid": persisted.pid,
                "label": persisted.runtime_label,
                "save_directory": persisted.runtime_save_dir,
                "message": "Bridge control belongs to the server that launched this session.",
            }
        return {
            "ok": True,
            "running": False,
            "connected": False,
            "message": "No live game. Start one with gm_game_start.",
        }
    if not session.alive:
        _cleanup(session)
    return {
        "ok": True,
        "running": session.alive,
        "connected": session.bridge.is_connected,
        "label": session.label,
        "bridge_port": session.bridge.port,
        "endpoint": session.bridge.hello,
        "uptime_seconds": round(time.time() - session.started_wall, 1),
        "exit_code": session.process.poll(),
        "pid": session.process.pid,
        "save_directory": str(session.save_dir),
    }


def command(project_root: str | Path, text: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    session = _require_session(project_root)
    if not session.alive:
        raise LiveSessionError(
            "The live game has exited. Read why with gm_game_log, then gm_game_stop and gm_game_start again."
        )
    if not session.bridge.is_connected:
        raise LiveSessionError(
            "The game is running but its bridge endpoint is not connected, so it cannot receive commands. "
            "gm_game_log shows the game log; see gm_game_start's message for what the project needs."
        )
    if "\n" in text or "\r" in text:
        raise LiveSessionError("A bridge command is a single line; remove the line breaks.")
    result = session.bridge.send_command(text, timeout=timeout_seconds)
    if not result.success:
        return {
            "ok": False,
            "command": text,
            "error": result.error or "The game did not answer.",
            "hint": "A timeout usually means the game is paused in a debugger, frozen, or the command is "
            "unknown to an old endpoint. Try `ping`, then `help` to list supported commands.",
        }
    parsed = parse_bridge_result(result.result)
    parsed["command"] = text
    return parsed


def screenshot(project_root: str | Path, name: str = "shot", timeout_seconds: float = 10.0) -> dict[str, Any]:
    session = _require_session(project_root)
    safe = snapshot_build.safe_label(name)
    answer = command(project_root, f"screenshot {safe}", timeout_seconds)
    if not answer.get("ok"):
        return answer
    raw_data = answer.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    source = Path(str(data.get("file", ""))) if data.get("file") else None
    if source is not None and (
        source.is_symlink() or source.resolve().parent != session.save_dir.resolve() or source.suffix.lower() != ".png"
    ):
        return {"ok": False, "error": "The screenshot path is outside this session's save directory."}
    shots_dir = session.run_dir / "shots"
    if shots_dir.is_symlink():
        raise LiveSessionError("The screenshot destination must not be a symlink.")
    shots_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    # screen_save writes at the end of the frame; wait for a complete file.
    while source is not None and time.monotonic() < deadline:
        if source.is_file() and source.stat().st_size > 0:
            break
        time.sleep(0.1)
    if source is None or not source.is_file():
        return {
            "ok": False,
            "command": answer["command"],
            "error": "The game accepted the screenshot command but no image file appeared.",
            "hint": 'The endpoint must answer with JSON {"file": "<absolute path>"} after calling screen_save.',
        }
    target = shots_dir / f"{safe}.png"
    if source.is_symlink() or source.resolve().parent != session.save_dir.resolve() or target.is_symlink():
        raise LiveSessionError("Screenshot paths changed or contain a symlink; preserving the files.")
    shutil.move(str(source), str(target))
    return {
        "ok": True,
        "screenshot": snapshot_build._relative(session.project_root, target),
        "message": "Open the image file to look at it.",
    }


def game_log(project_root: str | Path, lines: int = 100, pattern: str | None = None) -> dict[str, Any]:
    session = _require_session(project_root)
    import re

    content = (
        session.debug_log.read_text(encoding="utf-8", errors="replace").splitlines()
        if session.debug_log.is_file()
        else []
    )
    if pattern:
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            raise LiveSessionError(f"pattern is not a valid regular expression: {exc}") from exc
        content = [line for line in content if matcher.search(line)]
    return {
        "ok": True,
        "running": session.alive,
        "total_lines": len(content),
        "lines": content[-max(1, min(int(lines), 2000)) :],
    }


def stop(project_root: str | Path) -> dict[str, Any]:
    with _SESSIONS_GUARD:
        session = _SESSIONS.pop(_key(project_root), None)
    if session is None:
        persisted = RunSessionManager(Path(project_root)).get_current_session()
        if persisted is not None and persisted.isolated_runtime:
            return stop_persisted(project_root, persisted)
        return {"ok": True, "stopped": False, "message": "No live game was running."}
    exit_code = session.process.poll()
    snapshot_build.stop_process(session.process)
    shots = _cleanup(session)
    run_log = session.run_dir / "run.log"
    return {
        "ok": True,
        "stopped": True,
        "label": session.label,
        "exited_before_stop": exit_code is not None,
        "exit_code": exit_code,
        "run_log": snapshot_build._relative(session.project_root, run_log),
        "screenshots": sorted(
            str(snapshot_build._relative(session.project_root, shot))
            for shot in (session.run_dir / "shots").glob("*.png")
        ),
        "new_screenshots": len(shots),
    }


def stop_persisted(project_root: str | Path, persisted: Any) -> dict[str, Any]:
    """Stop only the persisted command/start identity, never Igor's shared Stop action."""
    from .runner import GameMakerRunner

    manager = RunSessionManager(Path(project_root))
    current_session = manager.get_current_session()
    if current_session is None or current_session.to_dict() != persisted.to_dict():
        return {"ok": True, "stopped": False, "message": "Original session has already been replaced or cleaned."}
    _persisted_paths(project_root, persisted)
    runner = GameMakerRunner(Path(project_root))
    processes = runner._snapshot_macos_processes()
    owned, _ = runner._tracked_macos_helper_pids(persisted, processes)
    for pid in owned:
        runner._terminate_pid(pid, "isolated runner", processes[pid])
    current = runner._snapshot_macos_processes()
    remaining, _ = runner._tracked_macos_helper_pids(persisted, current)
    if remaining:
        return {"ok": False, "stopped": False, "message": "Owned game is still exiting; retry stop."}
    manager = RunSessionManager(Path(project_root))
    current_session = manager.get_current_session()
    if current_session is None or current_session.run_id != persisted.run_id:
        return {"ok": True, "stopped": bool(owned), "message": "Original session has already been replaced or cleaned."}
    # Acquire in the same label->project order as start. An original live server
    # finishes its watcher first. A dead server's leases are reclaimed normally.
    label = persisted.runtime_label or "run"
    with snapshot_build.label_pipeline(project_root, label, timeout_seconds=5), contextlib.ExitStack() as cleanup_stack:
        lease = project_run_lock(project_root)
        lease.acquire(timeout_seconds=5)
        cleanup_stack.callback(lease.release)
        _archive_persisted(project_root, persisted)
    return {"ok": True, "stopped": bool(owned), "pid": persisted.pid, "message": "Owned game stopped."}


def _archive_persisted(project_root: str | Path, persisted: Any) -> None:
    """Archive a dead predecessor while the caller holds the project lease."""
    manager = RunSessionManager(Path(project_root))
    current = manager.get_current_session()
    if current is None or current.to_dict() != persisted.to_dict():
        return
    save_dir, staging, log, work = _persisted_paths(project_root, persisted)
    run_dir = snapshot_build.runs_directory(project_root, persisted.runtime_label or "run")
    run_dir.mkdir(parents=True, exist_ok=True)
    if log is not None and log.is_file():
        destination = run_dir / "run.log"
        if destination.is_symlink():
            raise LiveSessionError("Refusing to overwrite a run-log symlink.")
        snapshot_build.copy_artifact(log, destination)
    snapshot_build.collect_screenshots(
        run_dir / "shots",
        str(project_setting(project_root, "test.screenshot_prefix", "__agent_shot_")),
        0,
        save_dir,
    )
    shutil.rmtree(staging, ignore_errors=True)
    if work is not None:
        shutil.rmtree(work, ignore_errors=True)
    manager.clear_session()


def _persisted_paths(project_root: str | Path, persisted: Any) -> tuple[Path, Path, Path | None, Path | None]:
    """Check every cleanup path before any signals, reads or removals."""
    expected_save = (
        Path.home() / "Library" / "Application Support" / f"com.gmsmcp.game.p{project_identity(project_root)}"
    ).resolve()
    save_dir = Path(persisted.runtime_save_dir or "")
    staging = Path(persisted.exe_path).parent
    log = Path(persisted.log_file) if persisted.log_file else None
    work = Path(persisted.runtime_work_dir) if persisted.runtime_work_dir else None
    if (
        not persisted.runtime_save_dir
        or save_dir.resolve() != expected_save
        or staging != staging.resolve()
        or staging.parent != expected_save
        or not staging.name.startswith("session_")
        or (log is not None and (log != staging / "debug.txt" or log.resolve() != log))
        or (
            work is not None
            and (work != work.resolve() or work.resolve().parent != snapshot_build._work_root().resolve())
        )
    ):
        raise LiveSessionError("Persisted runtime paths do not match this project; preserving its files and processes.")
    return save_dir, staging, log, work


def _cleanup(session: LiveSession) -> list[Path]:
    """Archive owned evidence and release leases once, including natural window closure."""
    with session.cleanup_guard:
        if session.cleaned:
            return []
        session.bridge.stop()
        shots: list[Path] = []
        try:
            session.run_dir.mkdir(parents=True, exist_ok=True)
            if session.debug_log.is_symlink() or (session.run_dir / "run.log").is_symlink():
                raise LiveSessionError("Refusing to archive a run-log symlink.")
            if session.debug_log.is_file():
                snapshot_build.copy_artifact(session.debug_log, session.run_dir / "run.log")
                # Keep log access available after staging is removed.
                session.debug_log = session.run_dir / "run.log"
            shots = snapshot_build.collect_screenshots(
                session.run_dir / "shots", session.screenshot_prefix, session.started_wall, session.save_dir
            )
        finally:
            try:
                shutil.rmtree(session.staging, ignore_errors=True)
                shutil.rmtree(session.work_dir, ignore_errors=True)
                manager = RunSessionManager(session.project_root)
                persisted = manager.get_current_session()
                if persisted is not None and persisted.run_id == session.run_id:
                    manager.clear_session()
            finally:
                session.lock.release()
                session.label_lock.release()
                session.cleaned = True
        return shots


def _watch_exit(session: LiveSession) -> None:
    while session.process.poll() is None:
        time.sleep(0.2)
    _cleanup(session)


def start(project_root: str | Path, **options: Any) -> dict[str, Any]:
    """Own this project's runtime and artifact label before compiling or launching."""
    snapshot_build.require_vm_runtime(options.get("runtime", "VM"))
    existing = get_session(project_root)
    if existing is not None and existing.alive:
        raise LiveSessionError(f"A live game ('{existing.label}') is already running for this project.")
    persisted = RunSessionManager(Path(project_root)).get_current_session()
    if persisted is not None and persisted.isolated_runtime and existing is None:
        current = status(project_root)
        if current.get("running"):
            raise LiveSessionError("An owned game is already running for this project. Use gm_game_stop first.")
        stop_persisted(project_root, persisted)
    label_lock = snapshot_build.pipeline_lock(project_root, options.get("label", "live"))
    lock = project_run_lock(project_root)
    timeout = float(options.get("lock_timeout_seconds", 3600.0))
    label_lock.acquire(timeout_seconds=timeout)
    try:
        lock.acquire(timeout_seconds=timeout)
        try:
            # A concurrent launcher may have published a session while we waited.
            # Reconcile it under our lease before replacing its logs or metadata.
            predecessor = RunSessionManager(Path(project_root)).get_current_session()
            if predecessor is not None and predecessor.isolated_runtime:
                from .runner import GameMakerRunner

                runner = GameMakerRunner(Path(project_root))
                owned, _ = runner._tracked_macos_helper_pids(predecessor, runner._snapshot_macos_processes())
                if owned:
                    raise LiveSessionError("An owned game is already running for this project. Use gm_game_stop first.")
                _archive_persisted(project_root, predecessor)
            public = _start(project_root, lock=lock, label_lock=label_lock, **options)
            if not public.get("running"):
                lock.release()
                label_lock.release()
            return public
        except BaseException:
            lock.release()
            raise
    except BaseException:
        label_lock.release()
        raise


def stop_all() -> None:
    """Explicitly stop all games owned by this server; server exit preserves manual games."""
    for key in list(_SESSIONS):
        try:
            stop(key)
        except Exception:  # noqa: BLE001 - finish stopping independent sessions
            pass
