"""Public CLI/helper safety contract, including exhaustive route classification."""

import argparse
import asyncio
import ast
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gms_helpers.asset_creation_flow import run_post_creation_maintenance, run_pre_creation_maintenance
from gms_helpers.auto_maintenance import MaintenanceResult
from gms_helpers.exceptions import ValidationError
from gms_helpers.gms import _cli_command_name, _execute_project_command, create_parser
from gms_helpers.maintenance.trash import move_to_trash
from gms_helpers.maintenance.clean_unused_assets import clean_old_yy_files, clean_unused_folders
from gms_helpers.maintenance.orphan_cleanup import delete_orphan_files
from gms_helpers.operation_policy import (
    PROJECT_MUTATIONS,
    canonical_operation_name,
    is_project_mutation,
    is_real_destructive_operation,
    operation_succeeded,
    operation_scope,
    validate_project_operation,
)
from gms_helpers.path_safety import project_relative_path
from gms_helpers.sprite_frames import add_frame, duplicate_frame, get_frame_count, remove_frame
from gms_helpers.utils import atomic_write_text
from gms_mcp.server.dry_run_policy import destructive_policy_preflight


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "Test.yyp").write_text("{}")
    return root


@pytest.mark.parametrize("name", sorted(PROJECT_MUTATIONS))
def test_every_mutation_obeys_policy_and_real_previews(name, monkeypatch):
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    monkeypatch.delenv("GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST", raising=False)
    active = {"fix": True, "delete": True, "apply": True}
    assert is_project_mutation(name, active)
    blocked = destructive_policy_preflight("gm_" + name.replace("-", "_"), active)
    assert (blocked is not None) == is_real_destructive_operation(name, active)
    assert not is_project_mutation(name, {**active, "dry_run": True})
    assert destructive_policy_preflight(name, {**active, "dry_run": True}) is None


@pytest.mark.parametrize(
    "name,flag",
    [
        ("maintenance-auto", "fix"),
        ("maintenance-lint", "fix"),
        ("maintenance-sync-events", "fix"),
        ("maintenance-normalize-names", "fix"),
        ("maintenance-clean-old-files", "delete"),
        ("maintenance-clean-orphans", "delete"),
        ("safe-delete", "apply"),
    ],
)
def test_flag_based_preview_is_not_a_write(name, flag, monkeypatch):
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    assert not is_project_mutation(name, {flag: False})
    assert destructive_policy_preflight(name, {flag: False}) is None


def test_allowlist_has_identical_cli_and_mcp_names(monkeypatch):
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST", "gm_event_remove")
    assert destructive_policy_preflight("event.remove", {}) is None
    assert destructive_policy_preflight("gm_event_fix", {}) is not None


def _parser_leaves(parser, route=()):
    children = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not children:
        yield route, parser
    for child in children:
        for name, nested in child.choices.items():
            yield from _parser_leaves(nested, (*route, name))


def test_all_cli_resource_mutators_have_policy_classification():
    read_routes = {
        "event-list",
        "event-validate",
        "texture-group-list",
        "texture-group-read",
        "texture-group-members",
        "sprite-frames-count",
        "room-ops-list",
        "room-layer-list",
        "room-instance-list",
        "maintenance-validate-json",
        "maintenance-list-orphans",
        "maintenance-validate-paths",
        "maintenance-health",
    }
    checked = 0
    for route, _ in _parser_leaves(create_parser()):
        if route[0] not in {"asset", "event", "workflow", "texture-groups", "sprite-frames", "room", "maintenance"}:
            continue
        name = canonical_operation_name("-".join(route))
        assert name in PROJECT_MUTATIONS or name in read_routes, route
        checked += 1
    assert checked == 61


def test_real_parser_namespaces_match_every_exposed_route():
    parser = create_parser()
    checked = set()
    for route, leaf in _parser_leaves(parser):
        argv = list(route)
        for action in leaf._actions:
            if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
                continue
            if action.option_strings and not action.required:
                continue
            value = (
                str(next(iter(action.choices))) if action.choices else ("1" if action.type in {int, float} else "test")
            )
            if action.option_strings:
                argv.append(action.option_strings[0])
            argv.extend([value] * (action.nargs if isinstance(action.nargs, int) else 1))
        args = parser.parse_args(argv)
        expected = canonical_operation_name("-".join(route))
        actual = canonical_operation_name(_cli_command_name(args))
        assert actual == expected, (route, vars(args), actual)
        assert operation_scope(actual) != "unknown", route
        args.fix = args.delete = args.apply = True
        assert is_project_mutation(actual, args) == (expected in PROJECT_MUTATIONS)
        checked.add(route)
    assert len(checked) == len(list(_parser_leaves(parser)))


def test_all_registered_mcp_resource_mutators_have_policy_classification():
    tools = Path(__file__).resolve().parents[3] / "src/gms_mcp/server/tools"
    readers = {
        "gm_event_list",
        "gm_event_validate",
        "gm_room_ops_list",
        "gm_room_layer_list",
        "gm_room_instance_list",
        "gm_sprite_frame_count",
        "gm_texture_group_list",
        "gm_texture_group_read",
        "gm_texture_group_members",
        "gm_texture_group_scan",
        "gm_bridge_status",
        "gm_run_logs",
        "gm_run_command",
        "gm_runtime_list",
        "gm_runtime_verify",
        "gm_maintenance_validate_json",
        "gm_maintenance_list_orphans",
        "gm_maintenance_validate_paths",
    }
    checked = set()
    for module in (
        "asset_creation",
        "workflow",
        "events",
        "rooms",
        "texture_groups",
        "maintenance",
        "bridge",
        "runtime",
    ):
        tree = ast.parse((tools / f"{module}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("gm_"):
                assert canonical_operation_name(node.name) in PROJECT_MUTATIONS or node.name in readers, node.name
                checked.add(node.name)
    assert len(checked) == 70


def test_every_exposed_cli_and_mcp_route_has_an_explicit_state_scope():
    tools = Path(__file__).resolve().parents[3] / "src/gms_mcp/server/tools"
    for module in tools.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("gm_"):
                assert operation_scope(node.name) != "unknown", node.name
    for route, _ in _parser_leaves(create_parser()):
        assert operation_scope("-".join(route)) != "unknown", route


@pytest.mark.parametrize("value", ["../outside.txt", "/tmp/outside.txt", "C:\\outside.txt", "foo/../../outside.txt"])
def test_destination_rejects_escape_before_writes(project, value):
    with pytest.raises(ValidationError):
        project_relative_path(value, project_root=project)
    with pytest.raises(ValidationError):
        validate_project_operation(project, {"sprite_path": value})


@pytest.mark.parametrize("field", ["asset_path", "sprite_path", "parent_path", "path", "folder_path"])
def test_all_project_destination_fields_reject_symlink_escape(project, tmp_path, field):
    (project / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValidationError):
        validate_project_operation(project, {field: "escape/outside.txt"})


@pytest.mark.parametrize(
    "handler,args", [(add_frame, ()), (remove_frame, (0,)), (duplicate_frame, (0,)), (get_frame_count, ())]
)
@pytest.mark.parametrize("escape", ["../outside.yy", "absolute", "symlink"])
def test_every_sprite_frame_helper_enforces_boundaries(project, tmp_path, handler, args, escape):
    outside = tmp_path / "outside.yy"
    outside.write_text("sentinel")
    if escape == "absolute":
        escape = str(outside)
    elif escape == "symlink":
        (project / "linked.yy").symlink_to(outside)
        escape = "linked.yy"
    with pytest.raises(ValidationError):
        handler(project, escape, *args)
    assert outside.read_text() == "sentinel"


def test_trash_validates_whole_batch_before_moving_any_file(project):
    original = project / "keep.txt"
    original.write_text("keep")
    with pytest.raises(ValidationError):
        move_to_trash(str(project), ["keep.txt", "../outside.txt"])
    assert original.read_text() == "keep"
    assert not (project / ".maintenance_trash").exists()


def test_trash_preserves_prior_recovery_files(project):
    original = project / "keep.txt"
    original.write_text("first")
    result = move_to_trash(str(project), ["keep.txt"], "batch")
    assert result["moved_count"] == 1
    original.write_text("second")
    with pytest.raises(ValidationError):
        move_to_trash(str(project), ["keep.txt"], "batch")
    assert original.read_text() == "second"
    assert (project / ".maintenance_trash/batch/keep.txt").read_text() == "first"


def test_creation_maintenance_is_always_read_only(project):
    args = SimpleNamespace(project_root=str(project), no_auto_fix=False)
    with patch("gms_helpers.asset_creation_flow.run_auto_maintenance", return_value=MaintenanceResult()) as maintenance:
        assert run_pre_creation_maintenance(args, "create")
        assert run_post_creation_maintenance(args, "create")
    assert len(maintenance.call_args_list) == 2
    assert all(call.kwargs["fix_issues"] is False for call in maintenance.call_args_list)


@pytest.mark.parametrize(
    "result",
    [
        {"ok": False},
        {"success": False},
        {"success": True, "ok": False},
        SimpleNamespace(success=False),
        SimpleNamespace(has_errors=True),
        False,
    ],
)
def test_failure_status_is_not_truthy_success(result):
    assert not operation_succeeded(result)


def test_cli_failure_rolls_back_and_real_success_commits(project, monkeypatch):
    monkeypatch.delenv("GMS_MCP_REQUIRE_DRY_RUN", raising=False)
    target = project / "tracked.txt"
    target.write_text("before")

    def mutate(_):
        atomic_write_text(target, "after")
        return {"ok": False}

    args = SimpleNamespace(project_root=str(project), category="event", event_action="remove", func=mutate)
    assert not operation_succeeded(_execute_project_command(args))
    assert target.read_text() == "before"
    args.func = lambda _: (atomic_write_text(target, "success"), {"ok": True})[1]
    assert operation_succeeded(_execute_project_command(args))
    assert target.read_text() == "success"


def test_cli_policy_blocks_no_preview_operation_before_handler(project, monkeypatch):
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    handler = Mock()
    args = SimpleNamespace(project_root=str(project), category="event", event_action="remove", func=handler)
    assert not operation_succeeded(_execute_project_command(args))
    handler.assert_not_called()


@pytest.mark.parametrize("command", [["doc", "cache", "clear"], ["run", "stop"]])
def test_cli_state_destructive_policy_blocks_before_handler(command, monkeypatch):
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    monkeypatch.delenv("GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST", raising=False)
    args = create_parser().parse_args(command)
    args.func = Mock()
    assert not operation_succeeded(_execute_project_command(args))
    args.func.assert_not_called()


def test_cli_reports_incomplete_rollback_after_exception(project, monkeypatch):
    from gms_helpers.transactions import TransactionValidationError

    monkeypatch.delenv("GMS_MCP_REQUIRE_DRY_RUN", raising=False)
    args = create_parser().parse_args(["event", "remove", "o_keep", "create"])
    args.project_root = str(project)
    args.func = Mock(side_effect=RuntimeError("handler failed"))
    transaction = Mock(committed=False)
    transaction.rollback.return_value = False
    transaction.to_dict.return_value = {"status": "rollback_incomplete"}
    with (
        patch("gms_helpers.transactions.transaction_is_active", return_value=False),
        patch("gms_helpers.transactions.GameMakerProjectTransaction", return_value=transaction),
        pytest.raises(TransactionValidationError, match="safe rollback could not restore"),
    ):
        _execute_project_command(args)


@pytest.mark.parametrize("name", ["telemetry-disable", "telemetry-clear"])
def test_privacy_opt_out_stays_available_under_destructive_policy(name, monkeypatch):
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    assert operation_scope(name) == "local-config"
    assert destructive_policy_preflight(name, {}) is None


def test_cli_filter_type_is_not_part_of_operation_identity():
    args = create_parser().parse_args(["maintenance", "normalize-names", "--asset-type", "room", "--fix"])
    assert _cli_command_name(args) == "maintenance.normalize-names"
    assert is_project_mutation(_cli_command_name(args), args)


@pytest.mark.parametrize("action", ["search", "list"])
def test_doc_category_filter_cannot_replace_dispatch_identity(action):
    command = ["doc", action, *(["draw"] if action == "search" else []), "--category", "Drawing"]
    args = create_parser().parse_args(command)
    assert _cli_command_name(args) == f"doc.{action}"
    assert operation_scope(_cli_command_name(args)) == "cache"
    helper = "search" if action == "search" else "list_functions"
    with patch(f"gms_helpers.gml_docs.{helper}", return_value={"ok": False, "error": "offline"}) as query:
        _execute_project_command(args)
    assert query.call_args.kwargs["category"] == "Drawing"


@pytest.mark.parametrize("asset_type", ["../outside", "/tmp", "C:\\temp", "objects/../scripts", ".", "folders"])
def test_direct_cleaning_rejects_arbitrary_asset_directories(project, tmp_path, asset_type):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    with pytest.raises(ValidationError):
        clean_unused_folders(project, asset_type, do_delete=True)
    assert (outside / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize(
    "cleaner",
    [
        lambda root: clean_unused_folders(root, "objects", do_delete=True),
        lambda root: clean_old_yy_files(root, do_delete=True),
        lambda root: delete_orphan_files(str(root), fix_issues=True),
    ],
)
def test_every_direct_cleaner_rejects_symlink_escape(project, tmp_path, cleaner):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.old.yy"
    sentinel.write_text("keep")
    (project / "objects").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        cleaner(project)
    assert sentinel.read_text() == "keep"


def test_direct_cleaning_positive_and_dry_run_paths(project):
    (project / "Test.yyp").write_text(json.dumps({"resources": []}))
    unused = project / "objects/o_unused"
    unused.mkdir(parents=True)
    backup = unused / "o_unused.old.yy"
    backup.write_text("{}")
    before = _tree_state(project)
    assert clean_unused_folders(project, "objects") == (1, 0)
    assert clean_old_yy_files(project) == (1, 0)
    assert _tree_state(project) == before
    assert clean_old_yy_files(project, do_delete=True) == (1, 1)
    assert clean_unused_folders(project, "objects", do_delete=True) == (1, 1)
    assert not unused.exists()


def _tree_state(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None for path in root.rglob("*")
    }


def test_hardlinked_project_payload_rejected_before_mutation(project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    os.link(outside, project / "linked.txt")
    with pytest.raises(ValidationError):
        validate_project_operation(project, {})
    assert outside.read_text() == "keep"


@pytest.mark.parametrize("result", [{"status": "failed"}, {"status": "error"}, {"errors": ["failed"]}])
def test_raw_failure_reports_are_not_success(result):
    assert not operation_succeeded(result)


@pytest.mark.parametrize("result", [{"status": "failed"}, {"errors": ["failure"]}, SimpleNamespace(has_errors=True)])
def test_worker_and_cli_share_failure_result_semantics(result):
    from gms_mcp.server.direct_worker import _capture_output

    ok, _stdout, _stderr, returned, _error, exit_code = _capture_output(lambda: result)
    assert returned is result
    assert not ok
    assert exit_code == 1


@pytest.mark.parametrize(
    "result", [{"status": "failed"}, {"success": False}, {"errors": ["failure"]}, {"ok": True, "error": "failed"}]
)
def test_normalized_worker_result_cannot_contradict_failure(result):
    from gms_helpers.results import normalize_result
    from gms_mcp.server.direct import _normalize_direct_result

    assert not normalize_result(result, operation="test").success
    assert _normalize_direct_result(result, operation="test")["ok"] is False


PREVIEW_COMMANDS = [
    ["maintenance", "auto"],
    ["maintenance", "lint"],
    ["maintenance", "sync-events"],
    ["maintenance", "normalize-names"],
    ["maintenance", "clean-old-files"],
    ["maintenance", "clean-orphans"],
    ["maintenance", "prune-missing", "--dry-run"],
    ["maintenance", "dedupe-resources", "--dry-run"],
    ["room", "ops", "delete", "r_keep", "--dry-run"],
    ["workflow", "safe-delete", "--asset-type", "script", "--asset-name", "scr_keep"],
    ["texture-groups", "create", "Preview", "--dry-run"],
    ["texture-groups", "update", "Default", "--set", "autocrop=true", "--dry-run"],
    ["texture-groups", "rename", "Default", "Preview", "--dry-run"],
    ["texture-groups", "delete", "Preview", "--dry-run"],
    ["texture-groups", "assign", "Default", "--dry-run"],
]


@pytest.fixture
def preview_project(project):
    from gms_helpers.assets import ObjectAsset, RoomAsset, ScriptAsset, SpriteAsset

    resources = []
    for asset, name in [
        (RoomAsset(), "r_keep"),
        (ScriptAsset(), "scr_keep"),
        (ObjectAsset(), "o_keep"),
        (SpriteAsset(), "spr_keep"),
    ]:
        relative = asset.create_files(project, name, "")
        resources.append({"id": {"name": name, "path": relative}})
    folders = json.loads((project / "Test.yyp").read_text()).get("Folders", [])
    (project / "Test.yyp").write_text(
        json.dumps(
            {
                "name": "Test",
                "resources": resources,
                "Folders": folders,
                "TextureGroups": [{"name": "Default"}, {"name": "Preview"}],
                "resourceType": "GMProject",
                "resourceVersion": "2.0",
            }
        )
    )
    (project / "objects/o_unused").mkdir(parents=True)
    (project / "objects/o_unused/o_unused.old.yy").write_text("{}")
    return project


@pytest.mark.parametrize("command", PREVIEW_COMMANDS, ids=lambda command: " ".join(command))
def test_every_actual_cli_preview_leaves_project_state_unchanged(preview_project, command, monkeypatch):
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    monkeypatch.chdir(preview_project)
    args = create_parser().parse_args(command)
    args.project_root = str(preview_project)
    assert not is_project_mutation(_cli_command_name(args), args)
    before = _tree_state(preview_project)
    _execute_project_command(args)
    assert _tree_state(preview_project) == before
    assert not (preview_project / ".gms_mcp").exists()


@pytest.mark.parametrize("prefer_cli", [False, True])
def test_every_actual_mcp_preview_leaves_project_state_unchanged(
    preview_project, no_write_audit, monkeypatch, prefer_cli
):
    from mcp import Client
    from gms_mcp.gamemaker_mcp_server import build_server
    from gms_mcp.server.results import unwrap_call_tool_result

    monkeypatch.setenv("GM_PROJECT_ROOT", str(preview_project))
    monkeypatch.setenv("GMS_MCP_TOOLSETS", "all")
    monkeypatch.setenv("GMS_MCP_POST_MUTATION_VERIFY", "off")
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    monkeypatch.setenv("GMS_MCP_TELEMETRY", "on")
    monkeypatch.setenv("GMS_MCP_ENABLE_DIRECT", "1")
    monkeypatch.delenv("GMS_MCP_READ_ONLY", raising=False)
    state, violations = no_write_audit
    calls = [
        ("gm_maintenance_auto", {"fix": False}),
        ("gm_maintenance_lint", {"fix": False}),
        ("gm_maintenance_sync_events", {"fix": False}),
        ("gm_maintenance_normalize_names", {"fix": False}),
        ("gm_maintenance_clean_old_files", {"delete": False}),
        ("gm_maintenance_clean_orphans", {"delete": False}),
        ("gm_maintenance_prune_missing", {"dry_run": True}),
        ("gm_maintenance_dedupe_resources", {"dry_run": True}),
        ("gm_room_ops_delete", {"room_name": "r_keep", "dry_run": True}),
        ("gm_safe_delete", {"asset_type": "script", "asset_name": "scr_keep", "dry_run": True}),
        ("gm_texture_group_create", {"name": "NewPreview", "dry_run": True}),
        ("gm_texture_group_update", {"name": "Default", "patch": {"autocrop": True}, "dry_run": True}),
        ("gm_texture_group_rename", {"old_name": "Default", "new_name": "NewPreview", "dry_run": True}),
        ("gm_texture_group_delete", {"name": "Preview", "dry_run": True}),
        ("gm_texture_group_assign", {"group_name": "Default", "dry_run": True}),
    ]

    async def exercise():
        async with Client(build_server(), mode="2026-07-28") as client:
            specs = {spec.name: spec for spec in (await client.list_tools()).tools}
            before = _tree_state(preview_project)
            for name, values in calls:
                if "prefer_cli" in specs[name].input_schema.get("properties", {}):
                    values["prefer_cli"] = prefer_cli
                result = unwrap_call_tool_result(
                    await client.call_tool(name, {**values, "project_root": str(preview_project)})
                )
                assert not result.get("blocked_by_policy"), (name, result)
                assert "WRITE_FREE_VIOLATION" not in json.dumps(result), (name, result)
                assert result.get("exit_code", 0) == 0, (name, result)
                assert _tree_state(preview_project) == before, name

    state["active"] = True
    try:
        asyncio.run(exercise())
    finally:
        state["active"] = False
    assert not violations, "\n".join(str(item) for item in violations)


def test_mcp_additive_creation_allowed_and_never_cleans_unregistered_files(preview_project, monkeypatch):
    from mcp import Client
    from gms_mcp.gamemaker_mcp_server import build_server
    from gms_mcp.server.results import unwrap_call_tool_result

    monkeypatch.setenv("GM_PROJECT_ROOT", str(preview_project))
    monkeypatch.setenv("GMS_MCP_TOOLSETS", "all")
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    monkeypatch.setenv("GMS_MCP_POST_MUTATION_VERIFY", "off")
    monkeypatch.setenv("GMS_MCP_TELEMETRY", "off")
    sentinel = preview_project / "objects/o_unused/manual.txt"
    sentinel.write_text("must remain")

    async def exercise():
        async with Client(build_server(), mode="2026-07-28") as client:
            for name, values in [
                ("gm_create_script", {"name": "scr_new"}),
                ("gm_texture_group_create", {"name": "NewGroup"}),
            ]:
                result = unwrap_call_tool_result(
                    await client.call_tool(name, {**values, "project_root": str(preview_project)})
                )
                assert result.get("ok") is True, (name, result)
                assert sentinel.read_text() == "must remain"

    asyncio.run(exercise())
    assert (preview_project / "scripts/scr_new/scr_new.yy").exists()


def test_cli_reuses_inherited_transaction_instead_of_deadlocking(project, monkeypatch):
    monkeypatch.delenv("GMS_MCP_REQUIRE_DRY_RUN", raising=False)
    args = create_parser().parse_args(["event", "remove", "o_keep", "create"])
    args.project_root = str(project)
    args.func = Mock(return_value={"ok": True})
    with (
        patch("gms_helpers.transactions.transaction_is_active", return_value=True),
        patch("gms_helpers.transactions.GameMakerProjectTransaction") as transaction,
    ):
        assert operation_succeeded(_execute_project_command(args))
    transaction.assert_not_called()
    args.func.assert_called_once_with(args)


@pytest.fixture
def no_write_audit(tmp_path, monkeypatch):
    """Trap writes in the server and every child, including home/temp/cache paths."""
    audit_source = """import os, stat, sys
def reject(event, args):
    if event == "open" and args[0] == os.devnull:
        return
    if event == "open" and isinstance(args[0], int) and (stat.S_ISFIFO(os.fstat(args[0]).st_mode) or stat.S_ISSOCK(os.fstat(args[0]).st_mode)):
        return
    writing = event == "open" and len(args) > 2 and (args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    if writing or event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.symlink", "os.link", "shutil.copyfile", "shutil.rmtree"}:
        sys.stderr.write("WRITE_FREE_VIOLATION:" + event + "\\n")
        raise RuntimeError("WRITE_FREE_VIOLATION:" + event + ":" + str(args))
sys.addaudithook(reject)
"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "sitecustomize.py").write_text(audit_source)
    monkeypatch.setenv("PYTHONPATH", str(audit_dir) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    state = {"active": False}
    violations = []

    def parent_audit(event, args):
        if not state["active"]:
            return
        if event == "open" and args[0] == os.devnull:
            return
        if event == "open" and isinstance(args[0], int):
            mode = os.fstat(args[0]).st_mode
            if stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode):
                return
        writing = (
            event == "open"
            and len(args) > 2
            and (args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        )
        if writing or event in {
            "os.mkdir",
            "os.remove",
            "os.rmdir",
            "os.rename",
            "os.chmod",
            "os.symlink",
            "os.link",
            "shutil.copyfile",
            "shutil.rmtree",
        }:
            import traceback

            violations.append((event, str(args), "".join(traceback.format_stack(limit=7))))
            raise RuntimeError("WRITE_FREE_VIOLATION:" + event + ":" + str(args))

    sys.addaudithook(parent_audit)
    yield state, violations
    state["active"] = False


@pytest.mark.parametrize("toolsets", ["core", "all"])
@pytest.mark.parametrize("prefer_cli", [False, True])
def test_safe_profile_exercises_every_reader_without_any_filesystem_write(
    preview_project, no_write_audit, monkeypatch, prefer_cli, toolsets
):
    from mcp import Client
    from mcp.client.extension import advertise
    from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
    from gms_mcp.gamemaker_mcp_server import build_server
    from gms_mcp.server.results import unwrap_call_tool_result
    from gms_mcp.update_notifier import _CachedUpdateState

    monkeypatch.setenv("GM_PROJECT_ROOT", str(preview_project))
    if toolsets == "core":
        monkeypatch.setenv("GMS_MCP_READ_ONLY", "1")
    else:
        monkeypatch.delenv("GMS_MCP_READ_ONLY", raising=False)
    monkeypatch.setenv("GMS_MCP_TOOLSETS", toolsets)
    monkeypatch.setenv("GMS_MCP_TELEMETRY", "on")
    monkeypatch.setenv("GMS_MCP_ENABLE_DIRECT", "1")
    state, violations = no_write_audit
    fetched: _CachedUpdateState = {
        "status": "ok",
        "latest_version": "0.0.1",
        "source": None,
        "url": None,
        "checked_at": "2026-01-01T00:00:00Z",
        "last_notified_at": None,
    }

    async def exercise():
        extensions = [advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})] if toolsets == "all" else []
        async with Client(build_server(), mode="2026-07-28", extensions=extensions) as client:
            specs = [spec for spec in (await client.list_tools()).tools if operation_scope(spec.name) == "read"]
            for spec in specs:
                assert operation_scope(spec.name) == "read", spec.name
                values = {
                    "gm_read_asset": {"asset_identifier": "scr_keep"},
                    "gm_search_references": {"pattern": "scr_keep"},
                    "gm_find_definition": {"symbol_name": "scr_keep"},
                    "gm_find_references": {"symbol_name": "scr_keep"},
                    "gm_diagnostics": {"depth": "deep"},
                    "gm_event_list": {"object": "o_keep"},
                    "gm_event_validate": {"object": "o_keep"},
                    "gm_room_layer_list": {"room_name": "r_keep"},
                    "gm_room_instance_list": {"room_name": "r_keep"},
                    "gm_sprite_frame_count": {"sprite_path": "sprites/spr_keep/spr_keep.yy"},
                    "gm_texture_group_read": {"name": "Default"},
                    "gm_texture_group_members": {"group_name": "Default"},
                }.get(spec.name, {})
                if "prefer_cli" in spec.input_schema.get("properties", {}):
                    values["prefer_cli"] = prefer_cli
                result = unwrap_call_tool_result(await client.call_tool(spec.name, values))
                assert "WRITE_FREE_VIOLATION" not in json.dumps(result), (spec.name, result)
                assert result.get("exit_code", 0) == 0, (spec.name, result)
            if toolsets == "core":
                assert len(specs) == 17
            else:
                assert len(specs) == 43
                await client.read_resource("ui://gms-mcp/project-dashboard.html")
            assert "gm_resourcetool_validate" not in {spec.name for spec in specs}

    with patch("gms_mcp.update_notifier._fetch_update_status", return_value=fetched):
        state["active"] = True
        try:
            asyncio.run(exercise())
        finally:
            state["active"] = False
    assert not violations, "\n".join(str(item) for item in violations)


def test_mcp_central_policy_denies_sync_and_async_destructive_tools(preview_project, monkeypatch):
    from mcp import Client
    from gms_mcp.gamemaker_mcp_server import build_server
    from gms_mcp.server.results import unwrap_call_tool_result

    monkeypatch.setenv("GM_PROJECT_ROOT", str(preview_project))
    monkeypatch.setenv("GMS_MCP_TOOLSETS", "all")
    monkeypatch.setenv("GMS_MCP_REQUIRE_DRY_RUN", "1")
    monkeypatch.delenv("GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST", raising=False)
    monkeypatch.setenv("GMS_MCP_TELEMETRY", "off")

    async def exercise():
        async with Client(build_server(), mode="2026-07-28") as client:
            before = _tree_state(preview_project)
            for name, values in [
                ("gm_texture_group_update", {"name": "Default", "patch": {"autocrop": True}}),
                ("gm_event_remove", {"object": "o_keep", "event": "create"}),
                ("gm_bridge_uninstall", {}),
                ("gm_runtime_unpin", {}),
                ("gm_doc_cache_clear", {}),
                ("gm_run_stop", {}),
                ("gm_run_command", {"command": "set_var global.money 1"}),
            ]:
                result = unwrap_call_tool_result(
                    await client.call_tool(name, {**values, "project_root": str(preview_project)})
                )
                assert result.get("blocked_by_policy") is True, (name, result)
                assert _tree_state(preview_project) == before

    asyncio.run(exercise())
