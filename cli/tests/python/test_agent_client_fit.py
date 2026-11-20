"""Behaviour that agent clients which load tools on demand and run sessions in parallel depend on."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gms_helpers.exceptions import ValidationError
from gms_helpers.gamemaker_machine_lock import GameMakerMachineLock, machine_lock_holder
from gms_helpers.path_safety import assert_project_tree_contained, find_project_tree_violation
from gms_mcp import doctor_checks
from gms_mcp.install_support.client_configs import _collect_codex_check_state
from gms_mcp.server import progress
from gms_mcp.server.results import (
    MAX_INLINE_IMAGE_BYTES,
    attach_result_image,
    mcp_tool_result,
    unwrap_call_tool_result,
)
from gms_mcp.server.tools import live_game
from gms_mcp.server.tools.capabilities import TOOLSET_TOOLS, server_instructions, tool_guide

needs_symlinks = pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs elevation on Windows")


def _project(root: Path) -> Path:
    project = root / "project"
    (project / "sprites" / "spr_a").mkdir(parents=True)
    (project / "game.yyp").write_text('{"resources": []}', encoding="utf-8")
    (project / "sprites" / "spr_a" / "spr_a.yy").write_text("{}", encoding="utf-8")
    return project.resolve()


# --- project containment ---------------------------------------------------------------------


def test_contained_project_has_no_violation(tmp_path: Path):
    project = _project(tmp_path)
    assert find_project_tree_violation(project) is None
    assert assert_project_tree_contained(project) == project


@needs_symlinks
def test_violation_names_the_escaping_link_relative_to_the_project(tmp_path: Path):
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "sprites" / "inside").symlink_to(project / "game.yyp")
    (project / "tooling" / "bin").mkdir(parents=True)
    (project / "tooling" / "bin" / "python").symlink_to(outside / "python")

    found = find_project_tree_violation(project)

    assert found is not None
    assert (found.kind, found.relative_path) == ("escaping_link", "tooling/bin/python")
    with pytest.raises(ValidationError, match="escapes the approved project root"):
        assert_project_tree_contained(project)


@needs_symlinks
def test_symlinked_directory_that_leaves_the_project_is_a_violation(tmp_path: Path):
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "datafiles").symlink_to(outside, target_is_directory=True)

    found = find_project_tree_violation(project)

    assert found is not None
    assert (found.kind, found.relative_path) == ("escaping_link", "datafiles")


def test_a_file_that_goes_while_the_project_is_checked_is_not_a_violation(tmp_path: Path, monkeypatch):
    project = _project(tmp_path)
    temporary = project / "sprites" / "spr_a" / ".status.json.tmp"
    temporary.write_text("{}", encoding="utf-8")
    real_scandir = os.scandir

    class Listing:
        def __init__(self, path):
            self._scan = real_scandir(path)

        def __enter__(self):
            entries = list(self._scan.__enter__())
            # Its writer moves it into place after the directory was listed and before it is looked at.
            temporary.unlink(missing_ok=True)
            return iter(entries)

        def __exit__(self, *exc):
            return self._scan.__exit__(*exc)

    monkeypatch.setattr(os, "scandir", Listing)

    assert find_project_tree_violation(project) is None
    assert assert_project_tree_contained(project) == project


def test_a_file_windows_will_not_show_while_it_is_replaced_is_asked_about_again(tmp_path: Path, monkeypatch):
    from gms_helpers import path_safety

    target = tmp_path / "status.json"
    target.write_text("{}", encoding="utf-8")
    real_stat = os.stat
    refusals = [PermissionError(13, "delete pending"), PermissionError(13, "sharing violation")]

    def stat_like_windows(path, *args, **kwargs):
        if refusals and os.fspath(path) == os.fspath(target):
            raise refusals.pop()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(path_safety.os, "stat", stat_like_windows)

    # Refused twice while the file is swapped, then answered: the call is not turned away.
    assert path_safety._windows_link_count(os.fspath(target)) == 1
    assert refusals == []

    # Gone once the swap is over: the caller passes it by, as it does any vanished entry.
    target.unlink()
    with pytest.raises(FileNotFoundError):
        path_safety._windows_link_count(os.fspath(target))

    # Out of reach for good is still a failed check, not a pass.
    def never_shown(path, *args, **kwargs):
        raise PermissionError(13, "access denied")

    monkeypatch.setattr(path_safety.os, "stat", never_shown)
    with pytest.raises(PermissionError):
        path_safety._windows_link_count(os.fspath(target), patience_seconds=0.05)


def test_hard_linked_file_is_a_violation(tmp_path: Path):
    project = _project(tmp_path)
    (tmp_path / "shared.gml").write_text("// shared", encoding="utf-8")
    try:
        os.link(tmp_path / "shared.gml", project / "sprites" / "shared.gml")
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    found = find_project_tree_violation(project)

    assert found is not None
    assert (found.kind, found.relative_path) == ("multiply_linked", "sprites/shared.gml")
    with pytest.raises(ValidationError, match="multiply-linked"):
        assert_project_tree_contained(project)


@needs_symlinks
def test_doctor_reports_the_entry_that_stops_the_server_starting(tmp_path: Path):
    project = _project(tmp_path)
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / ".venv" / "bin" / "python").symlink_to(tmp_path / "python")

    check, directory = doctor_checks._build_project_detection_check(project_root=str(project), required=False)

    assert directory == project
    assert check.status == "error"
    assert "`.venv/bin/python` links outside the project folder" in check.message
    assert check.metadata["boundary_violation"] == {"kind": "escaping_link", "relative_path": ".venv/bin/python"}
    assert any("GM_PROJECT_ROOT" in line for line in check.details)


def test_doctor_project_check_stays_ok_for_a_contained_project(tmp_path: Path):
    project = _project(tmp_path)

    check, directory = doctor_checks._build_project_detection_check(project_root=str(project), required=False)

    assert directory == project
    assert check.status == "ok"
    assert check.message == "GameMaker project detected: game.yyp"


# --- Codex workspace config --------------------------------------------------------------------

_CODEX_ENTRY = '[mcp_servers.gms]\ncommand = "gms-mcp"\nargs = []\n\n[mcp_servers.gms.env]\nPYTHONUNBUFFERED = "1"\nGM_PROJECT_ROOT = "."\n'


def test_codex_check_reads_the_project_config_codex_loads(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / ".codex").mkdir(parents=True)
    (workspace / ".codex" / "config.toml").write_text(_CODEX_ENTRY, encoding="utf-8")

    with patch.dict(os.environ, {"CODEX_HOME": str(tmp_path / "codex-home")}):
        state = _collect_codex_check_state(workspace_root=workspace, server_name="gms")

    assert state["active"]["scope"] == "workspace"
    assert state["workspace"]["path"].endswith(os.path.join(".codex", "config.toml"))
    assert state["ready"] is True
    assert state["problems"] == []


def test_codex_check_flags_a_workspace_file_codex_never_reads(tmp_path: Path):
    workspace = tmp_path / "workspace"
    codex_home = tmp_path / "codex-home"
    (workspace / ".codex").mkdir(parents=True)
    codex_home.mkdir()
    (workspace / ".codex" / "mcp.toml").write_text(_CODEX_ENTRY, encoding="utf-8")
    (codex_home / "config.toml").write_text('[mcp_servers.gms]\ncommand = "gms-mcp"\nargs = []\n', encoding="utf-8")

    with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
        state = _collect_codex_check_state(workspace_root=workspace, server_name="gms")

    assert state["active"]["scope"] == "global"
    assert state["ready"] is False
    assert any("Codex does not read that file" in problem for problem in state["problems"])


# --- images in tool results --------------------------------------------------------------------


def test_attached_image_is_returned_once_beside_the_structured_result():
    attach_result_image(b"\x89PNG fake")

    first = mcp_tool_result({"ok": True}, project_root=None)
    second = mcp_tool_result({"ok": True}, project_root=None)

    assert [block.type for block in first.content] == ["text", "image"]
    assert base64.b64decode(first.content[1].data) == b"\x89PNG fake"
    assert first.content[1].mime_type == "image/png"
    assert first.structured_content == {"result": {"ok": True}}
    assert [block.type for block in second.content] == ["text"]


def test_screenshot_is_attached_when_small_and_left_on_disk_when_large(tmp_path: Path):
    shots = tmp_path / ".gms_mcp" / "runs" / "live" / "shots"
    shots.mkdir(parents=True)
    (shots / "small.png").write_bytes(b"small image")
    (shots / "large.png").write_bytes(b"0" * (MAX_INLINE_IMAGE_BYTES + 1))

    small = {"ok": True, "screenshot": ".gms_mcp/runs/live/shots/small.png"}
    live_game._attach_screenshot(tmp_path, small)
    small_result = mcp_tool_result(small, project_root=None)
    large = {"ok": True, "screenshot": ".gms_mcp/runs/live/shots/large.png"}
    live_game._attach_screenshot(tmp_path, large)
    large_result = mcp_tool_result(large, project_root=None)
    failed = {"ok": False, "error": "no session"}
    live_game._attach_screenshot(tmp_path, failed)

    assert small["image_attached"] is True
    assert base64.b64decode(small_result.content[1].data) == b"small image"
    assert large["image_attached"] is False
    assert "too large to attach" in large["message"]
    assert [block.type for block in large_result.content] == ["text"]
    assert failed == {"ok": False, "error": "no session"}


# --- server instructions -----------------------------------------------------------------------


def test_instructions_name_the_toolsets_a_search_cannot_find():
    optional = tuple(sorted(TOOLSET_TOOLS))

    core = server_instructions(enabled=("core",), optional=optional, read_only=False)
    some = server_instructions(enabled=("core", "assets", "rooms"), optional=optional, read_only=False)
    everything = server_instructions(enabled=("core", *optional), optional=optional, read_only=False)

    assert "gm_project_info first" in core
    assert "Not enabled in this session: assets: gm_create_*" in core
    assert "GMS_MCP_TOOLSETS" in core
    assert "rooms:" not in some and "events: gm_event_*" in some
    assert "Not enabled" not in everything
    # Some clients repeat these beside every tool a search returns, so they stay short.
    assert "Most used: gm_list_assets" in everything and "gm_snapshot_compile" in everything
    assert len(everything) <= 520 and max(len(core), len(some)) <= 1300


def test_read_only_instructions_do_not_offer_tools_that_are_not_registered():
    text = server_instructions(enabled=("core",), optional=tuple(sorted(TOOLSET_TOOLS)), read_only=True)
    guide = tool_guide(enabled=("core",), read_only=True)

    assert "read-only" in text
    assert "GMS_MCP_TOOLSETS" not in text
    assert set(guide) == {"read", "check"}
    assert "gm_compile" not in json.dumps(guide) and "gm_workflow_rename" not in json.dumps(guide)


def test_guide_names_only_tools_this_session_has():
    core = tool_guide(enabled=("core",), read_only=False)
    full = tool_guide(enabled=("core", "assets", "bridge"), read_only=False)

    assert core["check"].startswith("gm_snapshot_compile") and "gm_run_status" in core["run"]
    assert full["run"].startswith("gm_game_start")
    assert "gm_game_screenshot" not in core["run"] and "gm_create_" not in core["change"]
    assert "gm_game_screenshot" in full["run"] and "gm_create_script takes the code" in full["change"]


def test_server_sends_instructions_matching_its_registered_toolsets(tmp_path: Path):
    from gms_mcp.gamemaker_mcp_server import build_server
    from gms_mcp.server.results import unwrap_call_tool_result

    project = _project(tmp_path)
    with patch.dict(os.environ, {"GM_PROJECT_ROOT": str(project), "GMS_MCP_TOOLSETS": "core,rooms"}, clear=False):
        server = build_server()
        names = {tool.name for tool in asyncio.run(server.list_tools())}
        info = unwrap_call_tool_result(asyncio.run(server.call_tool("gm_project_info", {})))

    assert "gm_room_ops_list" in names and "gm_create_script" not in names
    assert "assets: gm_create_*" in server.instructions.split("Not enabled in this session:")[1]
    assert "rooms:" not in server.instructions
    assert info["toolsets"]["enabled"] == ["core", "rooms"]
    assert "gm_read_asset" in info["guide"]["read"]


# --- progress while a build waits its turn -----------------------------------------------------


class _Progress:
    def __init__(self, *, hang: bool = False) -> None:
        self.reports: list[tuple[float, float | None, str | None]] = []
        self.hang = hang

    async def report_progress(self, progress_value: float, total: float | None = None, message: str | None = None):
        if self.hang:
            await asyncio.sleep(3600)
        self.reports.append((progress_value, total, message))


def test_machine_lock_holder_describes_the_current_holder_only_while_held(tmp_path: Path):
    with patch.dict(os.environ, {"GMS_MCP_MACHINE_LOCK_PATH": str(tmp_path / "locks" / "runtime.lock")}):
        assert machine_lock_holder() is None
        with GameMakerMachineLock("compile", tmp_path, timeout_seconds=5):
            holder = machine_lock_holder()
            assert holder is not None
            assert holder["operation"] == "compile"
            assert holder["project_root"] == str(tmp_path.resolve())
            assert isinstance(holder["held_seconds"], float)
        assert machine_lock_holder() is None


def test_progress_message_says_which_project_holds_the_build_turn(tmp_path: Path):
    mine = tmp_path / "mine"
    held = {"operation": "compile", "project_root": str(tmp_path / "other"), "held_seconds": 42.4}
    with patch("gms_helpers.gamemaker_machine_lock.machine_lock_holder", return_value=held):
        waiting = progress.long_call_message("gm_compile", 30, mine)
    with patch(
        "gms_helpers.gamemaker_machine_lock.machine_lock_holder", return_value={**held, "project_root": str(mine)}
    ):
        building = progress.long_call_message("gm_compile", 30, mine)
    with patch("gms_helpers.gamemaker_machine_lock.machine_lock_holder", return_value=None):
        idle = progress.long_call_message("gm_compile", 30, mine)

    assert waiting == (
        "gm_compile has been running for 30s. Waiting for another project's compile, "
        "which has held the machine's build turn for 42s."
    )
    assert building.endswith("held by compile on this project for 42s.")
    assert idle == "gm_compile has been running for 30s."
    assert str(tmp_path) not in waiting + building + idle


def test_long_calls_report_progress_and_short_calls_report_nothing(tmp_path: Path):
    async def run(duration: float) -> list:
        ctx = _Progress()
        async with progress.long_call_progress(ctx, "gm_compile", tmp_path):
            await asyncio.sleep(duration)
        return ctx.reports

    with (
        patch.object(progress, "FIRST_REPORT_SECONDS", 0.05),
        patch.object(progress, "REPORT_INTERVAL_SECONDS", 0.05),
        patch("gms_helpers.gamemaker_machine_lock.machine_lock_holder", return_value=None),
    ):
        long_reports = asyncio.run(run(0.4))
        short_reports = asyncio.run(run(0.0))

    assert len(long_reports) >= 2
    assert all(total is None and "gm_compile has been running" in message for _, total, message in long_reports)
    assert short_reports == []


def test_a_client_that_stops_reading_progress_cannot_stall_the_call(tmp_path: Path):
    async def run() -> float:
        started = time.monotonic()
        async with progress.long_call_progress(_Progress(hang=True), "gm_compile", tmp_path):
            await asyncio.sleep(0.2)
        return time.monotonic() - started

    with (
        patch.object(progress, "FIRST_REPORT_SECONDS", 0.01),
        patch.object(progress, "SEND_TIMEOUT_SECONDS", 0.05),
        patch("gms_helpers.gamemaker_machine_lock.machine_lock_holder", return_value=None),
    ):
        elapsed = asyncio.run(run())

    assert elapsed < 2.0


def test_calls_without_a_request_context_run_unchanged(tmp_path: Path):
    async def run() -> str:
        async with progress.long_call_progress(None, "gm_compile", tmp_path):
            return "done"

    assert asyncio.run(run()) == "done"


# --- leaving when the client has gone ---------------------------------------------------------

_WATCHER_SCRIPT = """
import sys, threading, time
from gms_mcp import gamemaker_mcp_server as server

if sys.argv[1] == "changing":
    change = server._mutation_in_flight()
    change.__enter__()
    threading.Timer(2.5, lambda: change.__exit__(None, None, None)).start()
server._watch_for_departed_client()
print("ready", flush=True)
time.sleep(60)
"""


@pytest.mark.skipif(os.name == "nt", reason="the watcher uses poll(), which Windows does not have")
@pytest.mark.parametrize(("mode", "at_least", "at_most"), [("idle", 0.0, 6.0), ("changing", 2.0, 9.0)])
def test_server_leaves_when_nobody_can_read_it_but_finishes_a_change_first(mode, at_least, at_most):
    import subprocess
    import sys

    source_root = Path(__file__).resolve().parents[3] / "src"
    process = subprocess.Popen(
        [sys.executable, "-c", _WATCHER_SCRIPT, mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONPATH": str(source_root)},
    )
    try:
        assert process.stdout.readline().strip() == b"ready"
        started = time.monotonic()
        process.stdout.close()
        process.wait(timeout=30)
        elapsed = time.monotonic() - started
    finally:
        if process.poll() is None:
            process.kill()
        process.stdin.close()

    assert process.returncode == 0
    assert at_least <= elapsed <= at_most


# --- sessions with no game in them --------------------------------------------------------------


def test_upward_search_never_chooses_the_home_folder_or_above(tmp_path: Path):
    from gms_mcp import project_detection

    home = tmp_path / "home"
    scratch = home / ".tool" / "scratch" / "thread"
    scratch.mkdir(parents=True)
    (home / "stray.yyp").write_text("{}", encoding="utf-8")
    (tmp_path / "gamemaker").mkdir()
    (tmp_path / "gamemaker" / "above.yyp").write_text("{}", encoding="utf-8")

    with patch.object(Path, "home", return_value=home):
        assert project_detection._search_upwards_for_yyp(scratch) is None
        assert project_detection._search_upwards_for_gamemaker_yyp(scratch) is None
        with pytest.raises(FileNotFoundError):
            project_detection.resolve_project_directory(scratch)

        project = home / "Projects" / "game"
        (project / "scripts").mkdir(parents=True)
        (project / "game.yyp").write_text("{}", encoding="utf-8")
        assert project_detection._search_upwards_for_yyp(project / "scripts") == project.resolve()


def test_a_session_without_a_project_gets_a_server_that_says_so():
    from gms_mcp.gamemaker_mcp_server import _NO_PROJECT_REASON, build_unavailable_server

    server = build_unavailable_server(_NO_PROJECT_REASON)
    tools = asyncio.run(server.list_tools())
    assert [tool.name for tool in tools] == ["gm_project_info"]
    result = unwrap_call_tool_result(asyncio.run(server.call_tool("gm_project_info", {})))
    assert (result["ok"], result["available"]) == (False, False)
    assert "No GameMaker project" in result["error"] and "GM_PROJECT_ROOT" in result["error"]
