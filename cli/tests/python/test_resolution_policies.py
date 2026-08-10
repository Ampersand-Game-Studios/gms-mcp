"""GMS resolution policy contracts through public MCP Resolve APIs."""

from __future__ import annotations

import tempfile
import unittest
import os
import json
import asyncio
from pathlib import Path
from typing import Annotated
from unittest.mock import patch

from mcp import Client
from mcp.server.elicitation import ElicitationResult
from mcp.server.mcpserver import MCPServer, Resolve
from mcp.types import ElicitResult, InputRequiredResult
from pydantic import BaseModel

from gms_mcp.server.project import ProjectAccessPolicy
from gms_mcp.server.mcp_v2 import PROJECT_INDEX_URI
from gms_mcp.server.results import unwrap_call_tool_result
from gms_mcp.server.resolution import ResolutionEvidence, ResolutionPolicy, ResolutionRuntime, SafeDeleteDecision


def _policy(root: Path) -> ProjectAccessPolicy:
    resolved = root.resolve()
    return ProjectAccessPolicy(project_root=resolved, lexical_root=Path(os.path.abspath(root)))


def _resolution_server(runtime: ResolutionRuntime) -> MCPServer:
    resolver = runtime.safe_delete_resolver()

    def commit_delete(asset_type, asset_name, force=False, dry_run=True, project_root=".", decision=None):
        del asset_type, asset_name, force, dry_run, project_root
        return decision.data.action if hasattr(decision, "data") else decision.action

    commit_delete.__annotations__ = {
        "asset_type": str,
        "asset_name": str,
        "force": bool,
        "dry_run": bool,
        "project_root": str,
        "decision": Annotated[ElicitationResult[SafeDeleteDecision], Resolve(resolver)],
        "return": str,
    }
    server = MCPServer("gms-resolution-policy")
    server.tool(name="commit_delete")(commit_delete)
    return server


async def _delete(_context, _params) -> ElicitResult:
    return ElicitResult(action="accept", content={"action": "delete"})


def _minimal_game_project(root: Path) -> None:
    for name in ("objects", "sprites", "scripts", "rooms", "texturegroups"):
        (root / name).mkdir(parents=True, exist_ok=True)
    root.joinpath("Resolve.yyp").write_text(
        json.dumps(
            {
                "$GMProject": "",
                "%Name": "Resolve",
                "name": "Resolve",
                "resources": [],
                "folders": [],
                "resourceType": "GMProject",
                "resourceVersion": "2.0",
                "configs": {"name": "Default", "children": []},
                "TextureGroups": [
                    {"name": "Default", "%Name": "Default", "resourceType": "GMTextureGroup", "ConfigValues": {}},
                    {"name": "Temp", "%Name": "Temp", "resourceType": "GMTextureGroup", "ConfigValues": {}},
                    {
                        "name": "Child",
                        "%Name": "Child",
                        "resourceType": "GMTextureGroup",
                        "groupParent": "Temp",
                        "ConfigValues": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


class ResolutionPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_safe_delete_collision_and_texture_group_tools_resume_without_unapproved_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _minimal_game_project(root)
            with patch.dict(
                os.environ,
                {
                    "GM_PROJECT_ROOT": str(root),
                    "GMS_MCP_TOOLSETS": "all",
                    "GMS_MCP_POST_MUTATION_VERIFY": "off",
                    "GMS_MCP_REQUIRE_DRY_RUN": "0",
                },
                clear=False,
            ):
                from gms_mcp.gamemaker_mcp_server import build_server

                async with Client(build_server(), mode="2026-07-28", elicitation_callback=_delete) as client:
                    for script_name in ("scr_target", "scr_caller", "scr_caller_b"):
                        created = unwrap_call_tool_result(
                            await client.call_tool("gm_create_script", {"name": script_name, "project_root": str(root)})
                        )
                        self.assertTrue(created["ok"])
                    room_created = unwrap_call_tool_result(
                        await client.call_tool("gm_create_room", {"name": "r_resolve", "project_root": str(root)})
                    )
                    self.assertTrue(room_created["ok"])
                    root.joinpath("scripts/scr_caller/scr_caller.gml").write_text(
                        "scr_target();\nroom_goto(r_resolve);",
                        encoding="utf-8",
                    )

                    delete_args = {
                        "asset_type": "script",
                        "asset_name": "scr_target",
                        "dry_run": False,
                        "project_root": str(root),
                    }
                    async with client.listen(resource_subscriptions=[PROJECT_INDEX_URI]) as subscription:
                        next_update = asyncio.create_task(anext(subscription))
                        pending = await client.session.call_tool(
                            "gm_safe_delete", delete_args, allow_input_required=True
                        )
                        self.assertIsInstance(pending, InputRequiredResult)
                        assert isinstance(pending, InputRequiredResult)
                        key = next(iter(pending.input_requests or {}))
                        cancelled = unwrap_call_tool_result(
                            await client.session.call_tool(
                                "gm_safe_delete",
                                delete_args,
                                input_responses={key: ElicitResult(action="accept", content={"action": "cancel"})},
                                request_state=pending.request_state,
                                allow_input_required=True,
                            )
                        )
                        self.assertTrue(cancelled["cancelled"])
                        self.assertTrue(root.joinpath("scripts/scr_target").exists())
                        await asyncio.sleep(0.02)
                        self.assertFalse(next_update.done(), "cancelled Resolve published a mutation update")

                        room_args = {
                            "room_name": "r_resolve",
                            "dry_run": False,
                            "project_root": str(root),
                        }
                        room_pending = await client.session.call_tool(
                            "gm_room_ops_delete", room_args, allow_input_required=True
                        )
                        self.assertIsInstance(room_pending, InputRequiredResult)
                        assert isinstance(room_pending, InputRequiredResult)
                        key = next(iter(room_pending.input_requests or {}))
                        room_deleted = unwrap_call_tool_result(
                            await client.session.call_tool(
                                "gm_room_ops_delete",
                                room_args,
                                input_responses={key: ElicitResult(action="accept", content={"action": "force"})},
                                request_state=room_pending.request_state,
                                allow_input_required=True,
                            )
                        )
                        self.assertTrue(room_deleted["ok"])
                        self.assertFalse(root.joinpath("rooms/r_resolve").exists())
                        self.assertEqual((await asyncio.wait_for(next_update, timeout=1)).uri, PROJECT_INDEX_URI)
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(anext(subscription), timeout=0.03)

                    stale_pending = await client.session.call_tool(
                        "gm_safe_delete", delete_args, allow_input_required=True
                    )
                    self.assertIsInstance(stale_pending, InputRequiredResult)
                    assert isinstance(stale_pending, InputRequiredResult)
                    root.joinpath("scripts/scr_caller/scr_caller.gml").write_text(
                        "// reference moved\n", encoding="utf-8"
                    )
                    root.joinpath("scripts/scr_caller_b/scr_caller_b.gml").write_text(
                        "scr_target();\n", encoding="utf-8"
                    )
                    key = next(iter(stale_pending.input_requests or {}))
                    stale_response = await client.session.call_tool(
                        "gm_safe_delete",
                        delete_args,
                        input_responses={key: ElicitResult(action="accept", content={"action": "force"})},
                        request_state=stale_pending.request_state,
                        allow_input_required=True,
                    )
                    self.assertIsInstance(stale_response, InputRequiredResult)
                    assert isinstance(stale_response, InputRequiredResult)
                    self.assertIn("Evidence changed", next(iter(stale_response.input_requests.values())).params.message)
                    key = next(iter(stale_response.input_requests or {}))
                    stale_cancelled = unwrap_call_tool_result(
                        await client.session.call_tool(
                            "gm_safe_delete",
                            delete_args,
                            input_responses={key: ElicitResult(action="accept", content={"action": "cancel"})},
                            request_state=stale_response.request_state,
                            allow_input_required=True,
                        )
                    )
                    self.assertTrue(stale_cancelled["cancelled"])
                    self.assertTrue(root.joinpath("scripts/scr_target").exists())

                    collision = await client.session.call_tool(
                        "gm_create_script", {"name": "scr_target", "project_root": str(root)}, allow_input_required=True
                    )
                    self.assertIsInstance(collision, InputRequiredResult)
                    renamed = collision
                    for _ in range(3):
                        assert isinstance(renamed, InputRequiredResult)
                        key = next(iter(renamed.input_requests or {}))
                        renamed = await client.session.call_tool(
                            "gm_create_script",
                            {"name": "scr_target", "project_root": str(root)},
                            input_responses={
                                key: ElicitResult(
                                    action="accept", content={"action": "rename", "replacement_name": "scr_alternate"}
                                )
                            },
                            request_state=renamed.request_state,
                            allow_input_required=True,
                        )
                        if not isinstance(renamed, InputRequiredResult):
                            break
                    self.assertNotIsInstance(renamed, InputRequiredResult)
                    renamed = unwrap_call_tool_result(renamed)
                    self.assertTrue(renamed["ok"])
                    self.assertTrue(root.joinpath("scripts/scr_alternate").exists())

                    folder_created = unwrap_call_tool_result(
                        await client.call_tool(
                            "gm_create_folder",
                            {"name": "UI", "path": "folders/UI.yy", "project_root": str(root)},
                        )
                    )
                    self.assertTrue(folder_created["ok"])
                    folder_collision = await client.session.call_tool(
                        "gm_create_folder",
                        {"name": "UI", "path": "folders/UI.yy", "project_root": str(root)},
                        allow_input_required=True,
                    )
                    self.assertIsInstance(folder_collision, InputRequiredResult)
                    assert isinstance(folder_collision, InputRequiredResult)
                    key = next(iter(folder_collision.input_requests or {}))
                    folder_renamed = unwrap_call_tool_result(
                        await client.session.call_tool(
                            "gm_create_folder",
                            {"name": "UI", "path": "folders/UI.yy", "project_root": str(root)},
                            input_responses={
                                key: ElicitResult(
                                    action="accept", content={"action": "rename", "replacement_name": "UI2"}
                                )
                            },
                            request_state=folder_collision.request_state,
                            allow_input_required=True,
                        )
                    )
                    self.assertTrue(folder_renamed["ok"])

                    texture_args = {"name": "Temp", "dry_run": False, "project_root": str(root)}
                    texture = await client.session.call_tool(
                        "gm_texture_group_delete", texture_args, allow_input_required=True
                    )
                    self.assertIsInstance(texture, InputRequiredResult)
                    assert isinstance(texture, InputRequiredResult)
                    key = next(iter(texture.input_requests or {}))
                    reassigned = unwrap_call_tool_result(
                        await client.session.call_tool(
                            "gm_texture_group_delete",
                            texture_args,
                            input_responses={
                                key: ElicitResult(
                                    action="accept", content={"action": "reassign", "reassign_to": "Default"}
                                )
                            },
                            request_state=texture.request_state,
                            allow_input_required=True,
                        )
                    )

            self.assertTrue(reassigned["ok"])
            from gms_helpers.utils import load_json_loose

            yyp = load_json_loose(root / "Resolve.yyp")
            self.assertNotIn("Temp", [group.get("name") for group in yyp["TextureGroups"]])
            self.assertTrue({"UI", "UI2"}.issubset({folder["name"] for folder in yyp["Folders"]}))
            self.assertEqual(
                next(group for group in yyp["TextureGroups"] if group["name"] == "Child")["groupParent"], "Default"
            )

    async def test_automatic_client_path_injects_the_typed_accepted_decision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "game.yyp").write_text("{}", encoding="utf-8")
            runtime = ResolutionRuntime(
                _policy(root),
                evidence_readers={
                    ResolutionPolicy.SAFE_DELETE: lambda *_: ResolutionEvidence(
                        "script has no dependencies", facts={"asset_exists": True, "blocked": False}
                    )
                },
            )
            async with Client(_resolution_server(runtime), mode="2026-07-28", elicitation_callback=_delete) as client:
                result = await client.call_tool(
                    "commit_delete", {"asset_type": "script", "asset_name": "scr_old", "project_root": str(root)}
                )

        self.assertFalse(result.is_error, result.content)
        self.assertEqual(result.content[0].text, "delete")

    async def test_manual_resume_preserves_decline_and_cancel_as_typed_outcomes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "game.yyp").write_text("{}", encoding="utf-8")
            runtime = ResolutionRuntime(
                _policy(root),
                evidence_readers={
                    ResolutionPolicy.SAFE_DELETE: lambda *_: ResolutionEvidence(
                        "delete has dependents", facts={"asset_exists": True, "blocked": True}
                    )
                },
            )
            async with Client(_resolution_server(runtime), mode="2026-07-28", elicitation_callback=_delete) as client:
                for action in ("decline", "cancel"):
                    initial = await client.session.call_tool(
                        "commit_delete",
                        {
                            "asset_type": "script",
                            "asset_name": "scr_old",
                            "dry_run": False,
                            "project_root": str(root),
                        },
                        allow_input_required=True,
                    )
                    self.assertIsInstance(initial, InputRequiredResult)
                    assert isinstance(initial, InputRequiredResult)
                    key = next(iter(initial.input_requests or {}))
                    final = await client.session.call_tool(
                        "commit_delete",
                        {
                            "asset_type": "script",
                            "asset_name": "scr_old",
                            "dry_run": False,
                            "project_root": str(root),
                        },
                        input_responses={key: ElicitResult(action=action)},
                        request_state=initial.request_state,
                        allow_input_required=True,
                    )
                    self.assertNotIsInstance(final, InputRequiredResult)
                    self.assertEqual(final.content[0].text, action)

    async def test_changed_evidence_reasks_before_accepting_a_stale_response(self):
        reads = 0

        def changed_evidence(*_args) -> ResolutionEvidence:
            nonlocal reads
            reads += 1
            count = min(reads, 2)
            return ResolutionEvidence(
                f"current dependent count is {count}",
                affected_count=count,
                facts={"asset_exists": True, "blocked": True},
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "game.yyp").write_text("{}", encoding="utf-8")
            runtime = ResolutionRuntime(
                _policy(root), evidence_readers={ResolutionPolicy.SAFE_DELETE: changed_evidence}
            )
            arguments = {"asset_type": "script", "asset_name": "scr_old", "dry_run": False, "project_root": str(root)}
            async with Client(_resolution_server(runtime), mode="2026-07-28", elicitation_callback=_delete) as client:
                initial = await client.session.call_tool("commit_delete", arguments, allow_input_required=True)
                assert isinstance(initial, InputRequiredResult)
                key = next(iter(initial.input_requests or {}))
                changed = await client.session.call_tool(
                    "commit_delete",
                    arguments,
                    input_responses={key: ElicitResult(action="accept", content={"action": "delete"})},
                    request_state=initial.request_state,
                    allow_input_required=True,
                )
                self.assertIsInstance(changed, InputRequiredResult)
                assert isinstance(changed, InputRequiredResult)
                self.assertIn("Evidence changed", next(iter(changed.input_requests.values())).params.message)
                key = next(iter(changed.input_requests or {}))
                refreshed = await client.session.call_tool(
                    "commit_delete",
                    arguments,
                    input_responses={key: ElicitResult(action="accept", content={"action": "delete"})},
                    request_state=changed.request_state,
                    allow_input_required=True,
                )
                self.assertNotIsInstance(refreshed, InputRequiredResult)
                final = refreshed

        self.assertEqual(final.content[0].text, "delete")
        self.assertGreaterEqual(reads, 3)

    async def test_stale_project_is_rejected_before_any_resolution_request(self):
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as outside_dir:
            root, outside = Path(project_dir), Path(outside_dir)
            (root / "game.yyp").write_text("{}", encoding="utf-8")
            (outside / "other.yyp").write_text("{}", encoding="utf-8")
            runtime = ResolutionRuntime(
                _policy(root), evidence_readers={ResolutionPolicy.SAFE_DELETE: lambda *_: ResolutionEvidence("unused")}
            )
            async with Client(_resolution_server(runtime), mode="2026-07-28", elicitation_callback=_delete) as client:
                result = await client.call_tool(
                    "commit_delete", {"asset_type": "script", "asset_name": "scr_old", "project_root": str(outside)}
                )

        self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()
