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

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import snapshot_build
from .agent_locks import GAME_RUN_LOCK, DirectoryLock
from .bridge_server import BridgeServer
from .project_config import project_setting

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
    staging: Path
    debug_log: Path
    run_dir: Path
    work_dir: Path
    started_wall: float = field(default_factory=time.time)
    screenshot_prefix: str = "__agent_shot_"

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


def start(
    project_root: str | Path,
    *,
    label: str = "live",
    isolate_paths: Iterable[str] | None = None,
    yyp_entries: Iterable[str] | None = None,
    base_only: bool = False,
    ref: str = "HEAD",
    runtime_version: str | None = None,
    attempts: int | None = None,
    connect_timeout_seconds: float = 60.0,
    test_code: str | None = None,
    lock_timeout_seconds: float = 3600.0,
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
    lock = DirectoryLock(GAME_RUN_LOCK, stale_seconds=4 * 3600.0, purpose=f"live game {label}")
    bridge = BridgeServer(port=0)
    process: subprocess.Popen | None = None
    staging: Path | None = None
    try:
        runner = snapshot_build.require_mac_runner(tools)
        lock.acquire(timeout_seconds=lock_timeout_seconds)
        if not bridge.start():
            raise LiveSessionError("Could not open a local TCP port for the runtime bridge.")
        staging, game_file = snapshot_build.stage_game_archive(build.game_archive, label)
        snapshot_build.clear_stale_screenshots(screenshot_prefix)
        shots = run_dir / "shots"
        if shots.exists():
            shutil.rmtree(shots)
        process, debug_log = snapshot_build.launch_mac_runner(
            runner, staging, game_file, run_dir, {BRIDGE_PORT_ENVIRONMENT_VARIABLE: str(bridge.port)}
        )
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
        staging=staging,
        debug_log=debug_log,
        run_dir=run_dir,
        work_dir=work,
        screenshot_prefix=screenshot_prefix,
    )
    with _SESSIONS_GUARD:
        _SESSIONS[_key(root)] = session

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
        public["log_tail"] = snapshot_build.tail_lines(debug_log, 40)
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
            "log_tail [n]), gm_game_screenshot and gm_game_log; call gm_game_stop when finished so "
            "other people can run their games."
        )
    return public


def status(project_root: str | Path) -> dict[str, Any]:
    session = get_session(project_root)
    if session is None:
        return {
            "ok": True,
            "running": False,
            "connected": False,
            "message": "No live game. Start one with gm_game_start.",
        }
    try:
        os.utime(session.lock.path, None)  # heartbeat: the run lock is still in use
    except OSError:
        pass
    return {
        "ok": True,
        "running": session.alive,
        "connected": session.bridge.is_connected,
        "label": session.label,
        "bridge_port": session.bridge.port,
        "endpoint": session.bridge.hello,
        "uptime_seconds": round(time.time() - session.started_wall, 1),
        "exit_code": session.process.poll(),
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
    shots_dir = session.run_dir / "shots"
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
        return {"ok": True, "stopped": False, "message": "No live game was running."}
    exit_code = session.process.poll()
    snapshot_build.stop_process(session.process)
    session.bridge.stop()
    run_log = session.run_dir / "run.log"
    try:
        session.run_dir.mkdir(parents=True, exist_ok=True)
        if session.debug_log.is_file():
            shutil.copy2(session.debug_log, run_log)
        shots = snapshot_build.collect_screenshots(
            session.run_dir / "shots", session.screenshot_prefix, session.started_wall
        )
    finally:
        shutil.rmtree(session.staging, ignore_errors=True)
        shutil.rmtree(session.work_dir, ignore_errors=True)
        session.lock.release()
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


def stop_all() -> None:
    """Never leave a game (or the machine-wide run lock) behind when the server exits."""
    for key in list(_SESSIONS):
        try:
            stop(key)
        except Exception:  # noqa: BLE001 - best effort during interpreter shutdown
            pass


import atexit  # noqa: E402

atexit.register(stop_all)
