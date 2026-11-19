"""What an agent gets back from the read tools: bounded, named and explicit about what to do next."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp import Client

from gms_helpers import introspection
from gms_helpers.commands.diagnostics_commands import handle_diagnostics
from gms_helpers.event_model import event_display_name
from gms_helpers.gml_index import GMLIndex
from gms_mcp.gamemaker_mcp_server import build_server
from gms_mcp.server import project as project_module
from gms_mcp.server.results import mcp_tool_result, unwrap_call_tool_result


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _resource(kind: str, name: str) -> dict:
    return {"id": {"name": name, "path": f"{kind}/{name}/{name}.yy"}}


def _make_project(root: Path, *, scripts: int = 2) -> Path:
    """A small project inside a workspace folder: one object with events, a room, a sprite, scripts."""
    project = root / "workspace" / "gamemaker"
    script_names = [f"scr_helper_{index}" for index in range(scripts)]
    _write_json(
        project / "game.yyp",
        {
            "name": "game",
            "resources": [
                _resource("objects", "o_player"),
                _resource("rooms", "r_start"),
                _resource("sprites", "spr_player"),
                *(_resource("scripts", name) for name in script_names),
            ],
            "Folders": [
                {"name": "Objects", "folderPath": "folders/Objects.yy"},
                {"name": "Enemies", "folderPath": "folders/Objects/Enemies.yy"},
            ],
            "IncludedFiles": [{"name": "data.json", "filePath": "datafiles"}],
        },
    )
    _write_json(
        project / "objects" / "o_player" / "o_player.yy",
        {
            "name": "o_player",
            "resourceType": "GMObject",
            "parent": {"name": "Objects", "path": "folders/Objects.yy"},
            "spriteId": {"name": "spr_player", "path": "sprites/spr_player/spr_player.yy"},
            "parentObjectId": None,
            "eventList": [
                {"eventType": 0, "eventNum": 0, "collisionObjectId": None},
                {"eventType": 3, "eventNum": 1, "collisionObjectId": None},
                {"eventType": 8, "eventNum": 64, "collisionObjectId": None},
            ],
        },
    )
    (project / "objects" / "o_player" / "Create_0.gml").write_text("hp = 3;\nscr_helper_0();\n", encoding="utf-8")
    (project / "objects" / "o_player" / "Step_1.gml").write_text("x += 1;\n", encoding="utf-8")
    (project / "objects" / "o_player" / "Draw_64.gml").write_text("draw_self();\n", encoding="utf-8")
    _write_json(
        project / "rooms" / "r_start" / "r_start.yy",
        {
            "name": "r_start",
            "resourceType": "GMRoom",
            "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
            "roomSettings": {"Width": 640, "Height": 360},
            "layers": [
                {
                    "name": "Instances",
                    "resourceType": "GMRInstanceLayer",
                    "instances": [
                        {"name": "inst_1", "objectId": {"name": "o_player", "path": "objects/o_player/o_player.yy"}}
                    ],
                }
            ],
            "padding": "x" * 20_000,
        },
    )
    _write_json(
        project / "sprites" / "spr_player" / "spr_player.yy",
        {"name": "spr_player", "resourceType": "GMSprite", "parent": {"name": "Sprites", "path": "folders/Sprites.yy"}},
    )
    for name in script_names:
        _write_json(
            project / "scripts" / name / f"{name}.yy",
            {"name": name, "resourceType": "GMScript", "parent": {"name": "Scripts", "path": "folders/Scripts.yy"}},
        )
        (project / "scripts" / name / f"{name}.gml").write_text(
            f"function {name}() {{\n    return 1;\n}}\n", encoding="utf-8"
        )
    (project / "datafiles").mkdir()
    (project / "datafiles" / "data.json").write_text("{}", encoding="utf-8")
    return project.resolve()


@contextmanager
def _server(project: Path, *, cwd: Path | None = None, root_setting: str | None = None, toolsets: str = "core"):
    setting = str(project) if root_setting is None else root_setting
    start = (cwd or project).resolve()
    with (
        patch.dict(os.environ, {"GM_PROJECT_ROOT": setting, "GMS_MCP_TOOLSETS": toolsets}, clear=False),
        patch.object(project_module, "_SERVER_START_DIRECTORY", start),
        patch("gms_mcp.server.tools.project_health._SERVER_START_DIRECTORY", start),
    ):
        yield build_server()


def _call(server, tool: str, **arguments):
    return unwrap_call_tool_result(asyncio.run(server.call_tool(tool, arguments)))


# --- which project, which checkout -----------------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "expected_notice"),
    [
        ("${CLAUDE_PROJECT_DIR}/gamemaker", "variable the client did not expand"),
        ("/gamemaker", "names a folder that does not exist"),
        ("/nowhere/at/all", "using the project found from the folder the server was started in"),
    ],
)
def test_unusable_project_root_falls_back_to_the_workspace_and_says_so(tmp_path: Path, setting, expected_notice):
    project = _make_project(tmp_path)
    with _server(project, cwd=project.parent, root_setting=setting) as server:
        info = _call(server, "gm_project_info")

    assert info["project"] == "game"
    assert info["workspace"]["project_folder"] == "gamemaker"
    assert len(info["notices"]) == 1 and expected_notice in info["notices"][0]


def test_valid_project_root_has_no_notice(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project, cwd=project.parent, root_setting="gamemaker") as server:
        info = _call(server, "gm_project_info")

    assert info["notices"] == []


def test_project_info_identifies_the_checkout_without_a_host_path(tmp_path: Path):
    project = _make_project(tmp_path)
    workspace = project.parent
    git = ["git", "-C", str(workspace), "-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q", "-b", "feature/trial"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)

    with _server(project, cwd=workspace, toolsets="core,rooms") as server:
        result = asyncio.run(server.call_tool("gm_project_info", {}))
    info = unwrap_call_tool_result(result)

    assert info["workspace"]["folder"] == "workspace"
    assert info["workspace"]["project_folder"] == "gamemaker"
    assert info["workspace"]["git_branch"] == "feature/trial"
    assert info["workspace"]["git_linked_worktree"] is False
    assert len(info["workspace"]["git_commit"]) >= 7
    assert info["assets"]["by_type"]["object"] == 1
    assert info["toolsets"]["enabled"] == ["core", "rooms"]
    assert "assets" in info["toolsets"]["disabled"]
    assert str(tmp_path) not in result.content[0].text


# --- listing ----------------------------------------------------------------------------------


def test_unfiltered_listing_of_a_large_project_returns_counts_and_how_to_narrow(tmp_path: Path):
    project = _make_project(tmp_path, scripts=250)
    with _server(project) as server:
        summary = _call(server, "gm_list_assets")
        page = _call(server, "gm_list_assets", limit=100, offset=200)

    assert summary["count"] == 254 and summary["by_type"]["script"] == 250
    assert summary["assets"] == {} and summary["truncated"] is True
    assert "asset_type" in summary["message"]
    assert page["returned"] == 54 and page["truncated"] is False and page["next_offset"] is None


def test_filtered_listing_pages_and_does_not_repeat_the_type_on_every_entry(tmp_path: Path):
    project = _make_project(tmp_path, scripts=5)
    with _server(project) as server:
        first = _call(server, "gm_list_assets", asset_type="script", limit=2)
        folders = _call(server, "gm_list_assets", asset_type="folder", name_contains="enem")

    assert first["count"] == 5 and first["returned"] == 2 and first["next_offset"] == 2
    assert first["assets"]["script"][0] == {
        "name": "scr_helper_0",
        "path": "scripts/scr_helper_0/scr_helper_0.yy",
    }
    assert folders["assets"]["folder"] == [{"name": "Enemies", "path": "folders/Objects/Enemies.yy"}]


# --- reading one asset ------------------------------------------------------------------------


def test_object_is_described_by_named_events_and_their_code_files(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project) as server:
        described = _call(server, "gm_read_asset", asset_identifier="o_player")
        code = _call(server, "gm_read_asset", asset_identifier="objects/o_player/Create_0.gml")

    assert described["asset_type"] == "object"
    assert described["folder"] == "folders/Objects.yy"
    assert described["sprite"] == "spr_player"
    assert described["events"] == [
        {"event": "Create", "file": "objects/o_player/Create_0.gml", "lines": 2},
        {"event": "Begin Step", "file": "objects/o_player/Step_1.gml", "lines": 1},
        {"event": "Draw GUI", "file": "objects/o_player/Draw_64.gml", "lines": 1},
    ]
    assert described["asset_data"]["name"] == "o_player"
    assert code == {
        "ok": True,
        "path": "objects/o_player/Create_0.gml",
        "lines": 2,
        "code": "hp = 3;\nscr_helper_0();\n",
        "truncated": False,
    }


def test_large_yy_is_left_out_unless_asked_for(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project) as server:
        automatic = _call(server, "gm_read_asset", asset_identifier="r_start")
        full = _call(server, "gm_read_asset", asset_identifier="r_start", yy="full")

    assert automatic["layers"] == ["Instances"] and automatic["instances"] == 1 and automatic["size"] == [640, 360]
    assert "asset_data" not in automatic and 'yy="full"' in automatic["asset_data_omitted"]
    assert full["asset_data"]["name"] == "r_start"


def test_missing_asset_suggests_close_names_and_never_reads_outside_the_project(tmp_path: Path):
    project = _make_project(tmp_path)
    (tmp_path / "secret.gml").write_text("secret", encoding="utf-8")
    with _server(project) as server:
        typo = _call(server, "gm_read_asset", asset_identifier="o_playr")
        escape = _call(server, "gm_read_asset", asset_identifier="../../secret.gml")

    assert typo["ok"] is False and typo["did_you_mean"][0] == "o_player"
    assert escape["ok"] is False and "code" not in escape


def test_event_names_match_the_ide():
    def name(event_type: int, event_num: int) -> str:
        return event_display_name({"eventType": event_type, "eventNum": event_num})

    assert [name(0, 0), name(3, 0), name(3, 2), name(8, 0), name(8, 75), name(7, 4), name(2, 3), name(7, 10)] == [
        "Create",
        "Step",
        "End Step",
        "Draw",
        "Draw GUI End",
        "Room Start",
        "Alarm 3",
        "User Event 0",
    ]
    collision = {
        "eventType": 4,
        "eventNum": 0,
        "collisionObjectId": {"name": "o_wall", "path": "objects/o_wall/o_wall.yy"},
    }
    assert event_display_name(collision) == "Collision with o_wall"


# --- the asset graph --------------------------------------------------------------------------


def test_asset_graph_answers_who_uses_an_asset_and_summarises_by_default(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project) as server:
        player = _call(server, "gm_get_asset_graph", asset="o_player")
        summary = _call(server, "gm_get_asset_graph")
        missing = _call(server, "gm_get_asset_graph", asset="o_playr")
        full = _call(server, "gm_get_asset_graph", full=True)

    assert {"asset": "spr_player", "type": "sprite", "relation": "sprite"} in player["uses"]
    assert {"asset": "r_start", "type": "room", "relation": "contains"} in player["used_by"]
    assert "nodes" not in summary and summary["node_count"] == len(full["nodes"])
    assert summary["most_used"][0]["used_by"] >= 1
    assert missing["ok"] is False and missing["did_you_mean"][0] == "o_player"


def test_asset_graph_does_not_reload_the_project_file_for_assets_without_a_yy(tmp_path: Path):
    project = _make_project(tmp_path)
    with patch.object(introspection, "_safe_load_yyp", wraps=introspection._safe_load_yyp) as load_yyp:
        graph = introspection.build_asset_graph(project)

    assert any(node["type"] == "includedfile" for node in graph["nodes"])
    # One read to list the assets; the included file must not trigger a name search per asset.
    assert load_yyp.call_count == 1


# --- result envelope --------------------------------------------------------------------------


def test_command_results_drop_fields_that_only_say_nothing_unusual_happened():
    ran = {
        "ok": True,
        "direct_used": False,
        "stdout": "Rooms: 2\n",
        "stderr": "",
        "exit_code": 0,
        "error": None,
        "direct_error": None,
        "elapsed_seconds": 0.8228265,
        "timed_out": False,
        "execution_mode": "subprocess:python-module",
        "result": None,
        "transaction": None,
        "validation": None,
    }
    failed = {**ran, "ok": False, "exit_code": 4, "error": "Process exited with code 4", "timed_out": True}

    clean = unwrap_call_tool_result(mcp_tool_result(ran, project_root=None))
    kept = unwrap_call_tool_result(mcp_tool_result(failed, project_root=None))

    assert clean == {"ok": True, "stdout": "Rooms: 2\n", "elapsed_seconds": 0.82}
    assert kept["exit_code"] == 4 and kept["error"] == "Process exited with code 4" and kept["timed_out"] is True
    assert "\n" not in mcp_tool_result({"ok": True, "items": [1, 2]}, project_root=None).content[0].text


def test_unknown_argument_is_refused_with_the_valid_names(tmp_path: Path):
    project = _make_project(tmp_path)

    async def call():
        with _server(project) as server:
            async with Client(server, mode="2026-07-28") as client:
                wrong = await client.call_tool("gm_list_symbols", {"symbol_type": "function"})
                right = await client.call_tool("gm_list_assets", {"asset_type": "object"})
                return wrong, right

    wrong, right = asyncio.run(call())
    payload = wrong.structured_content["result"]

    assert wrong.is_error and payload["error"] == "Unknown argument: symbol_type"
    assert "kind" in payload["valid_arguments"] and "ctx" not in payload["valid_arguments"]
    assert not right.is_error and right.structured_content["result"]["count"] == 1


def test_tool_descriptions_start_with_text_not_a_blank_line(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project, toolsets="all") as server:
        tools = asyncio.run(server.list_tools())

    assert len(tools) > 100
    untidy = [tool.name for tool in tools if not tool.description or tool.description != tool.description.strip()]
    assert untidy == []


def test_lock_status_lists_only_held_locks_without_owner_secrets(tmp_path: Path):
    project = _make_project(tmp_path)
    held = {
        "name": "build_slot_1",
        "held": True,
        "age_seconds": 12.5,
        "owner": {"purpose": "igor build", "token": "abc123", "host": "mac"},
    }
    free = {"name": "repo.lock", "held": False, "age_seconds": None, "owner": None}
    with (
        _server(project) as server,
        patch("gms_helpers.agent_locks.lock_status", return_value={"lock_directory": "/x", "locks": [free, held]}),
        patch("gms_helpers.gamemaker_machine_lock.machine_lock_holder", return_value=None),
    ):
        compact = _call(server, "gm_lock_status")
        everything = _call(server, "gm_lock_status", include_free=True)

    assert compact["locks"] == [{"name": "build_slot_1", "held": True, "age_seconds": 12.5, "purpose": "igor build"}]
    assert compact["build_turn"] == {"held": False}
    assert compact["summary"].startswith("1 lock(s) held")
    assert [lock["name"] for lock in everything["locks"]] == ["repo.lock", "build_slot_1"]
    assert "abc123" not in json.dumps(everything)


def test_diagnostics_prints_what_it_found(tmp_path: Path, capsys, monkeypatch):
    project = _make_project(tmp_path)
    monkeypatch.chdir(project)
    (project / "objects" / "o_player" / "o_player.yy").write_text("{ not json", encoding="utf-8")

    class Args:
        project_root = str(project)
        depth = "quick"
        include_info = False

    result = handle_diagnostics(Args())
    printed = capsys.readouterr().out

    assert result["summary"]["error"] >= 1
    assert "[DIAGNOSTICS]" in printed and "objects/o_player/o_player.yy" in printed
    assert 'depth="deep"' in printed


# --- the symbol index -------------------------------------------------------------------------


@pytest.fixture
def index_cache(tmp_path: Path):
    cache = tmp_path / "index-cache"
    with patch.dict(os.environ, {"GMS_MCP_GML_INDEX_CACHE_DIR": str(cache)}, clear=False):
        os.environ.pop("GMS_MCP_READ_ONLY", None)
        yield cache


def test_lookups_read_a_saved_index_without_writing_to_it(tmp_path: Path, index_cache: Path):
    project = _make_project(tmp_path)
    assert GMLIndex(project).build(persist=False)["status"] == "built"
    assert not index_cache.exists()

    saved = GMLIndex(project)
    assert saved.build()["status"] == "built"
    before = saved.cache_path.stat().st_mtime_ns

    lookup = GMLIndex(project)
    report = lookup.build(persist=False)
    references = lookup.find_references("scr_helper_0")

    assert report["status"] == "cached"
    assert [
        (str(ref.location.file_path), ref.context) for ref in references if "objects" in str(ref.location.file_path)
    ] == [("objects/o_player/Create_0.gml", "scr_helper_0();")]
    assert lookup.find_definition("scr_helper_1")[0].location.line == 1
    assert saved.cache_path.stat().st_mtime_ns == before


def test_lookup_sees_edits_made_after_the_index_was_saved_and_leaves_the_file_alone(tmp_path: Path, index_cache: Path):
    project = _make_project(tmp_path)
    saved = GMLIndex(project)
    saved.build()
    cache_bytes = saved.cache_path.read_bytes()
    edited = project / "scripts" / "scr_helper_0" / "scr_helper_0.gml"
    edited.write_text("function scr_renamed() {\n    return 2;\n}\n", encoding="utf-8")

    lookup = GMLIndex(project)
    report = lookup.build(persist=False)

    assert report["status"] == "incremental" and report["changed_files"] == 1
    assert lookup.find_definition("scr_helper_0") == []
    assert len(lookup.find_definition("scr_renamed")) == 1
    assert saved.cache_path.read_bytes() == cache_bytes

    assert GMLIndex(project).build()["status"] == "incremental"
    assert GMLIndex(project).build(persist=False)["status"] == "cached"


def test_saved_index_replaces_the_json_cache_and_survives_a_locked_database(tmp_path: Path, index_cache: Path):
    project = _make_project(tmp_path)
    index = GMLIndex(project)
    index_cache.mkdir()
    legacy = index.cache_path.with_suffix(".json")
    legacy.write_text("{}", encoding="utf-8")

    index.build()
    assert not legacy.exists() and index.cache_path.suffix == ".sqlite3"

    blocker = sqlite3.connect(index.cache_path)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        (project / "scripts" / "scr_helper_1" / "scr_helper_1.gml").write_text("function scr_other() {}\n")
        with patch.object(sqlite3, "connect", wraps=lambda *a, **k: _real_connect(*a, timeout=0.05, **k)):
            contended = GMLIndex(project)
            report = contended.build()
        assert report["status"] == "built"
        assert len(contended.find_definition("scr_other")) == 1
    finally:
        blocker.rollback()
        blocker.close()


_real_connect = sqlite3.connect


# --- changes ----------------------------------------------------------------------------------


def test_committed_change_reports_what_changed_and_not_the_bookkeeping():
    ran = {
        "ok": True,
        "direct_used": True,
        "stdout": "[OK] Script created\n",
        "stderr": "",
        "exit_code": 0,
        "error": None,
        "direct_error": None,
        "elapsed_seconds": 0.2,
        "timed_out": False,
        "execution_mode": "direct:isolated",
        "result": {
            "success": True,
            "message": "Create script completed",
            "warnings": [],
            "error": None,
            "data": {},
            "ok": True,
        },
        "transaction": {
            "enabled": True,
            "tool": "gm_create_script",
            "project_root": ".",
            "committed": True,
            "recovery_path": None,
            "rolled_back": False,
            "rollback_complete": None,
            "rollback_conflicts": [],
            "ownership_checkpoint_captured": True,
            "owned_path_count": 7,
            "changes": {
                "created_count": 1,
                "modified_count": 1,
                "deleted_count": 0,
                "changed_count": 2,
                "created": ["scripts/a/a.gml"],
                "modified": ["game.yyp"],
                "deleted": [],
                "truncated": False,
            },
            "validation": {
                "success": True,
                "errors": [],
                "warnings": [],
                "yyp": "game.yyp",
                "preexisting_error_count": 20,
                "preexisting_errors": ["old problem"] * 10,
                "preexisting_errors_truncated": True,
            },
            "compile_verification": None,
            "gamemaker_ide": None,
            "warnings": [],
            "verification_policy": {"mode": "off", "action": "skip", "risk": "high", "reason": "off"},
        },
        "validation": None,
    }

    clean = unwrap_call_tool_result(mcp_tool_result(ran, project_root=None, total_seconds=6.84))
    quick = unwrap_call_tool_result(mcp_tool_result(ran, project_root=None, total_seconds=0.4))

    assert clean["result"] == {"message": "Create script completed", "ok": True}
    assert clean["transaction"] == {
        "committed": True,
        "changes": {"created": ["scripts/a/a.gml"], "modified": ["game.yyp"]},
        "preexisting_issues": (
            "20 validation issue(s) were already in the project before this change; gm_project_check lists them under asset_reference_issues."
        ),
    }
    assert clean["total_seconds"] == 6.8 and "total_seconds" not in quick
    assert "old problem" not in json.dumps(clean)


def test_change_that_did_nothing_or_went_wrong_is_not_summarised_away():
    base = {"ok": True, "stdout": "", "execution_mode": "direct:isolated"}
    nothing = {**base, "transaction": {"committed": True, "changes": {"created": [], "modified": [], "deleted": []}}}
    rolled_back = {
        **base,
        "ok": False,
        "transaction": {
            "committed": False,
            "rolled_back": True,
            "rollback_complete": True,
            "changes": {"created": [], "modified": [], "deleted": []},
            "validation": {"success": False, "errors": ["broken reference"]},
        },
    }
    verified = {
        **base,
        "transaction": {
            "committed": True,
            "changes": {"created": ["a"], "modified": [], "deleted": []},
            "validation": {"success": True, "errors": [], "warnings": ["check this"]},
            "compile_verification": {"ok": True, "seconds": 41},
            "verification_policy": {"mode": "smart", "action": "compile", "risk": "high", "reason": "risky"},
        },
    }

    assert unwrap_call_tool_result(mcp_tool_result(nothing, project_root=None))["transaction"] == {
        "committed": True,
        "changes": {},
        "changed": False,
    }
    kept = unwrap_call_tool_result(mcp_tool_result(rolled_back, project_root=None))["transaction"]
    assert kept["rolled_back"] is True and kept["validation"]["errors"] == ["broken reference"]
    checked = unwrap_call_tool_result(mcp_tool_result(verified, project_root=None))["transaction"]
    assert checked["compile_verification"] == {"ok": True, "seconds": 41}
    assert checked["validation"] == {"warnings": ["check this"]}
    assert checked["verification_policy"]["action"] == "compile"


def test_script_can_be_created_with_its_code(tmp_path: Path):
    from gms_helpers.asset_types.code import ScriptAsset

    folder = tmp_path / "scripts" / "trial_probe"
    folder.mkdir(parents=True)
    ScriptAsset().create_stub_files(folder, "trial_probe", code='function trial_probe() {\n\treturn "trial";\n}')
    stub_folder = tmp_path / "scripts" / "other"
    stub_folder.mkdir(parents=True)
    ScriptAsset().create_stub_files(stub_folder, "other")

    assert (folder / "trial_probe.gml").read_text() == 'function trial_probe() {\n\treturn "trial";\n}\n'
    assert "function other()" in (stub_folder / "other.gml").read_text()


def test_adding_an_event_that_exists_never_reports_unwritten_code_as_done(tmp_path: Path, capsys):
    from gms_helpers.event_helper import add_event
    from gms_helpers.exceptions import ValidationError

    project = _make_project(tmp_path)
    create = project / "objects" / "o_player" / "Create_0.gml"
    step = project / "objects" / "o_player" / "Step_1.gml"
    written = create.read_text()

    assert add_event("o_player", "create", "", project) is True
    assert "nothing was changed" in capsys.readouterr().out
    assert add_event("o_player", "create", written, project) is True
    with pytest.raises(
        ValidationError, match="was not written. Pass overwrite to replace it, or edit objects/o_player/Create_0.gml"
    ):
        add_event("o_player", "create", "other_code();\n", project)
    assert create.read_text() == written

    step.write_text("// Step_1.gml event\n", encoding="utf-8")
    assert add_event("o_player", "begin_step", "x += 2;\n", project) is True
    assert step.read_text() == "x += 2;\n"
    assert "generated placeholder" in capsys.readouterr().out


def test_generated_create_event_can_be_filled_in_after_creating_an_object(tmp_path: Path):
    from gms_helpers.event_helper import add_event

    project = _make_project(tmp_path)
    create = project / "objects" / "o_player" / "Create_0.gml"
    create.write_text("/// Create Event for o_player\n// Initialize variables here\n", encoding="utf-8")

    assert add_event("o_player", "create", "show_debug_message(1);\n", project) is True
    assert create.read_text() == "show_debug_message(1);\n"


def test_compile_errors_are_located_in_project_files(tmp_path: Path):
    from gms_helpers.snapshot_build import locate_compile_errors

    project = _make_project(tmp_path)
    (project / "scripts" / "scr_helper_0" / "scr_helper_0.gml").write_text(
        "/// doc\nfunction scr_helper_0() {\n\tvar value = (1 + ;\n}\n", encoding="utf-8"
    )
    errors = [
        "Error : gml_GlobalScript_scr_helper_0(2) : got ';' expected ')'",
        "Error : gml_Object_o_player_Step_1(0) : unknown variable",
        "Error : gml_GlobalScript_not_in_project(4) : something",
        "Project Error: licence",
    ]

    located = locate_compile_errors(project, errors)

    assert located == [
        {
            "file": "scripts/scr_helper_0/scr_helper_0.gml",
            "line": 3,
            "message": "got ';' expected ')'",
            "source": "var value = (1 + ;",
        },
        {"file": "objects/o_player/Step_1.gml", "line": 1, "message": "unknown variable", "source": "x += 1;"},
    ]


def test_unknown_asset_type_is_an_error_not_an_empty_list(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project) as server:
        wrong = _call(server, "gm_list_assets", asset_type="objects")
        folders = _call(server, "gm_list_assets", asset_type="folder")

    assert wrong["ok"] is False and "assets" not in wrong
    assert "asset_type" in json.dumps(wrong)
    assert folders["ok"] is True and folders["count"] == 2


def test_doctor_warns_when_the_client_would_pass_an_unexpanded_root(tmp_path: Path):
    from gms_mcp import doctor_checks

    project = _make_project(tmp_path)
    with (
        patch.dict(os.environ, {"GM_PROJECT_ROOT": "${CLAUDE_PROJECT_DIR}/gamemaker"}, clear=False),
        patch.object(project_module, "_SERVER_START_DIRECTORY", project.parent),
    ):
        check, directory = doctor_checks._build_project_detection_check(project_root=None, required=False)

    assert directory == project and check.status == "warning"
    assert "did not expand" in check.details[0] and "${CLAUDE_PROJECT_DIR:-.}" in check.details[1]


def test_asset_reference_count_matches_the_full_scan_when_the_name_is_absent_or_present():
    from gms_helpers import reference_scanner

    source = 'var a = o_player;\n// o_enemy in a comment\nvar b = asset_get_index("spr_player");\n'

    assert reference_scanner.count_gml_identifier(source, "o_player") == 1
    assert reference_scanner.count_gml_identifier(source, "spr_player") == 1
    assert reference_scanner.count_gml_identifier(source, "o_enemy") == 0
    assert reference_scanner.count_gml_identifier(source, "o_missing") == 0


# --- answering in one call --------------------------------------------------------------------


def test_asset_graph_lists_what_an_assets_code_uses(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project) as server:
        player = _call(server, "gm_get_asset_graph", asset="o_player")
        helper = _call(server, "gm_get_asset_graph", asset="scr_helper_0")

    assert {"asset": "scr_helper_0", "type": "script", "relation": "code_reference"} in player["uses"]
    assert {"asset": "spr_player", "type": "sprite", "relation": "sprite"} in player["uses"]
    assert {"asset": "o_player", "type": "object", "relation": "code_reference"} in helper["used_by"]


def test_room_is_described_with_its_instances_and_creation_order(tmp_path: Path):
    project = _make_project(tmp_path)
    room_file = project / "rooms" / "r_start" / "r_start.yy"
    room = json.loads(room_file.read_text())
    room["instanceCreationOrder"] = [{"name": "inst_1", "path": "rooms/r_start/r_start.yy"}]
    room_file.write_text(json.dumps(room), encoding="utf-8")
    with _server(project) as server:
        described = _call(server, "gm_read_asset", asset_identifier="r_start")

    assert described["instances_by_layer"] == {"Instances": [{"instance": "inst_1", "object": "o_player"}]}
    assert described["creation_order"] == ["inst_1"]


def test_object_can_be_read_with_all_its_code_and_listed_with_its_folder(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project) as server:
        read = _call(server, "gm_read_asset", asset_identifier="o_player", yy="none", include_code=True)
        listed = _call(server, "gm_list_assets", asset_type="object", include_folder=True)

    assert [event["code"] for event in read["events"]] == ["hp = 3;\nscr_helper_0();\n", "x += 1;\n", "draw_self();\n"]
    assert listed["assets"]["object"] == [
        {"name": "o_player", "path": "objects/o_player/o_player.yy", "folder": "folders/Objects.yy"}
    ]


def test_delete_preview_of_a_placed_object_is_a_result_that_names_the_instances(tmp_path: Path):
    project = _make_project(tmp_path)
    with _server(project) as server:
        preview = _call(server, "gm_safe_delete", asset_type="object", asset_name="o_player", dry_run=True)

    data = preview["data"]
    assert preview["ok"] is True and data["would_be_blocked"] is True and data["deleted"] is False
    room = next(item for item in data["dependencies"] if item["asset_name"] == "r_start")
    assert room["instances"] == ["inst_1"] and "gm_room_instance_remove" in room["remove_with"]
    assert "force=true" in data["next"]
    assert "preflight" not in data


def test_reference_listing_marks_the_definition_and_reports_whether_the_index_was_saved(
    tmp_path: Path, index_cache, capsys
):
    from gms_helpers.commands.symbol_commands import handle_find_references

    project = _make_project(tmp_path)

    class Args:
        project_root = str(project)
        symbol_name = "scr_helper_0"
        max_results = 50

    handle_find_references(Args())
    first = capsys.readouterr().out
    handle_find_references(Args())
    second = capsys.readouterr().out

    assert "index saved" in first and "index saved" not in second
    assert "scripts/scr_helper_0/scr_helper_0.gml:1 - function scr_helper_0() {  [definition]" in second
    assert "objects/o_player/Create_0.gml:2 - scr_helper_0();\n" in second


def test_project_info_names_the_starting_room(tmp_path: Path):
    project = _make_project(tmp_path)
    yyp = project / "game.yyp"
    data = json.loads(yyp.read_text())
    data["RoomOrderNodes"] = [{"roomId": {"name": "r_start", "path": "rooms/r_start/r_start.yy"}}]
    yyp.write_text(json.dumps(data), encoding="utf-8")
    with _server(project) as server:
        info = _call(server, "gm_project_info")

    assert info["rooms"] == {"first": "r_start", "order": ["r_start"]}
    assert "updates" not in info or info["updates"].get("update_available")


def test_gesture_events_are_named():
    assert event_display_name({"eventType": 13, "eventNum": 65}) == "Global Double Tap"
    assert event_display_name({"eventType": 13, "eventNum": 0}) == "Tap"
