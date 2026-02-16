#!/usr/bin/env python3
"""Deterministic MCP smoke runner for all registered gm_* tools.

This runner:
- discovers tools from FastMCP `list_tools()`
- executes each tool in an isolated copy of the BLANK GAME1 fixture
- applies per-tool preconditions for tools with required args/state
- writes a deterministic JSON report

Default fixture:
  gamemaker/BLANK GAME1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.bridge_server import get_bridge_server, stop_bridge_server
from gms_helpers.utils import load_json_loose
from gms_mcp.gamemaker_mcp_server import build_server


def _unwrap_call_tool(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], dict):
        payload = value[1]
        if "result" in payload:
            return payload["result"]
    return value


def _sanitize_tool_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", name)


def _is_ok(result: Any) -> bool:
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        if "ok" in result:
            return bool(result.get("ok"))
        if "success" in result:
            return bool(result.get("success"))
        return True
    return True


def _error_text(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("error", "message", "stderr", "stdout"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(result)


def _write_minimal_png(path: Path) -> None:
    """Write a valid 1x1 RGBA PNG."""
    path.write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A"
            "0000000D49484452000000010000000108060000001F15C489"
            "0000000D49444154789C6360606060000000050001A5F64540"
            "0000000049454E44AE426082"
        )
    )


class FakeBridgeClient:
    """Small fake game client used to validate gm_run_logs/gm_run_command."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.server = None

    def start(self) -> None:
        stop_bridge_server(str(self.project_root))
        self.server = get_bridge_server(str(self.project_root), create=True)
        if not self.server:
            raise RuntimeError("Failed to create bridge server")
        if not self.server.start():
            raise RuntimeError("Failed to start bridge server")

        port = self.server.port
        self.thread = threading.Thread(
            target=self._client_loop,
            args=(port,),
            daemon=True,
            name="fake-bridge-client",
        )
        self.thread.start()

        deadline = time.time() + 8.0
        while time.time() < deadline:
            if self.server.is_connected and self.server.get_log_count() > 0:
                return
            time.sleep(0.1)
        raise RuntimeError("Fake bridge client did not connect in time")

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        stop_bridge_server(str(self.project_root))

    def _client_loop(self, port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline and not self.stop_event.is_set():
                try:
                    sock.connect(("127.0.0.1", port))
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                return

            sock.settimeout(0.2)
            last_log = 0.0
            log_index = 0
            buffer = ""

            while not self.stop_event.is_set():
                now = time.time()
                if now - last_log >= 0.2:
                    log_index += 1
                    line = f"LOG:{int(now * 1000)}|fake-log-{log_index}\n"
                    try:
                        sock.sendall(line.encode("utf-8"))
                    except OSError:
                        break
                    last_log = now

                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    buffer += data.decode("utf-8", "replace").replace("\x00", "")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip().replace("\x00", "")
                        if not line:
                            continue
                        if line.startswith("CMD:"):
                            payload = line[4:]
                            if "|" in payload:
                                cmd_id, _ = payload.split("|", 1)
                            else:
                                cmd_id = payload
                            response = f"RSP:{cmd_id}|pong\n"
                            sock.sendall(response.encode("utf-8"))
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            try:
                sock.close()
            except OSError:
                pass


@dataclass
class ToolRunRecord:
    tool: str
    workspace: str
    ok: bool
    args: Dict[str, Any]
    elapsed_seconds: float
    result: Any = None
    error: Optional[str] = None


class MCPToolSmokeRunner:
    def __init__(
        self,
        base_project: Path,
        work_root: Path,
        output_path: Path,
        *,
        include_tools: Optional[List[str]] = None,
        exclude_tools: Optional[List[str]] = None,
        keep_workdirs: bool = False,
        fail_fast: bool = False,
    ) -> None:
        self.base_project = Path(base_project).resolve()
        self.work_root = Path(work_root).resolve()
        self.output_path = Path(output_path).resolve()
        self.include_tools = include_tools or []
        self.exclude_tools = set(exclude_tools or [])
        self.keep_workdirs = keep_workdirs
        self.fail_fast = fail_fast

        self.mcp = None
        self.tools: List[str] = []
        self.tool_schemas: Dict[str, Dict[str, Any]] = {}
        self.records: List[ToolRunRecord] = []

        self.create_tool_defaults: Dict[str, Dict[str, Any]] = {
            "gm_create_animcurve": {"name": "curve_tool_smoke", "skip_maintenance": True},
            "gm_create_folder": {"name": "SmokeFolder", "path": "folders", "skip_maintenance": True},
            "gm_create_font": {"name": "fnt_tool_smoke", "skip_maintenance": True},
            "gm_create_note": {"name": "note_tool_smoke", "skip_maintenance": True},
            "gm_create_object": {"name": "o_tool_smoke", "skip_maintenance": True},
            "gm_create_path": {"name": "pth_tool_smoke", "skip_maintenance": True},
            "gm_create_room": {"name": "r_tool_smoke", "skip_maintenance": True},
            "gm_create_script": {"name": "scr_tool_smoke", "skip_maintenance": True},
            "gm_create_sequence": {"name": "seq_tool_smoke", "skip_maintenance": True},
            "gm_create_shader": {"name": "sh_tool_smoke", "skip_maintenance": True},
            "gm_create_sound": {"name": "snd_tool_smoke", "skip_maintenance": True},
            "gm_create_sprite": {"name": "spr_tool_smoke", "frame_count": 1, "skip_maintenance": True},
            "gm_create_tileset": {"name": "ts_tool_smoke", "skip_maintenance": True},
            "gm_create_timeline": {"name": "tl_tool_smoke", "skip_maintenance": True},
        }

        self.scenarios: Dict[str, Callable[[Path], Awaitable[tuple[Dict[str, Any], Any]]]] = {
            "gm_asset_delete": self._scenario_asset_delete,
            "gm_cli": self._scenario_cli,
            "gm_doc_lookup": self._scenario_doc_lookup,
            "gm_doc_search": self._scenario_doc_search,
            "gm_event_add": self._scenario_event_add,
            "gm_event_duplicate": self._scenario_event_duplicate,
            "gm_event_fix": self._scenario_event_fix,
            "gm_event_list": self._scenario_event_list,
            "gm_event_remove": self._scenario_event_remove,
            "gm_event_validate": self._scenario_event_validate,
            "gm_find_definition": self._scenario_find_definition,
            "gm_find_references": self._scenario_find_references,
            "gm_read_asset": self._scenario_read_asset,
            "gm_room_instance_add": self._scenario_room_instance_add,
            "gm_room_instance_list": self._scenario_room_instance_list,
            "gm_room_instance_remove": self._scenario_room_instance_remove,
            "gm_room_layer_add": self._scenario_room_layer_add,
            "gm_room_layer_list": self._scenario_room_layer_list,
            "gm_room_layer_remove": self._scenario_room_layer_remove,
            "gm_room_ops_delete": self._scenario_room_ops_delete,
            "gm_room_ops_duplicate": self._scenario_room_ops_duplicate,
            "gm_room_ops_rename": self._scenario_room_ops_rename,
            "gm_run": self._scenario_run,
            "gm_run_command": self._scenario_run_command,
            "gm_run_logs": self._scenario_run_logs,
            "gm_run_status": self._scenario_run_status,
            "gm_run_stop": self._scenario_run_stop,
            "gm_runtime_pin": self._scenario_runtime_pin,
            "gm_runtime_unpin": self._scenario_runtime_unpin,
            "gm_search_references": self._scenario_search_references,
            "gm_sprite_add_frame": self._scenario_sprite_add_frame,
            "gm_sprite_duplicate_frame": self._scenario_sprite_duplicate_frame,
            "gm_sprite_frame_count": self._scenario_sprite_frame_count,
            "gm_sprite_import_strip": self._scenario_sprite_import_strip,
            "gm_sprite_remove_frame": self._scenario_sprite_remove_frame,
            "gm_texture_group_assign": self._scenario_texture_group_assign,
            "gm_texture_group_create": self._scenario_texture_group_create,
            "gm_texture_group_delete": self._scenario_texture_group_delete,
            "gm_texture_group_members": self._scenario_texture_group_members,
            "gm_texture_group_read": self._scenario_texture_group_read,
            "gm_texture_group_rename": self._scenario_texture_group_rename,
            "gm_texture_group_update": self._scenario_texture_group_update,
            "gm_workflow_delete": self._scenario_workflow_delete,
            "gm_workflow_duplicate": self._scenario_workflow_duplicate,
            "gm_workflow_rename": self._scenario_workflow_rename,
            "gm_workflow_swap_sprite": self._scenario_workflow_swap_sprite,
        }

    async def run(self) -> int:
        if not self.base_project.exists():
            raise FileNotFoundError(f"Base project not found: {self.base_project}")

        os.environ["GM_PROJECT_ROOT"] = str(self.base_project)
        os.environ["PROJECT_ROOT"] = str(self.base_project)

        self.mcp = build_server()
        tool_specs = await self.mcp.list_tools()
        self.tools = sorted(t.name for t in tool_specs)
        self.tool_schemas = {t.name: (t.inputSchema or {}) for t in tool_specs}

        selected_tools = self._select_tools(self.tools)
        self._validate_required_tool_coverage(selected_tools)

        if self.work_root.exists():
            shutil.rmtree(self.work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)

        print(f"[INFO] Base project: {self.base_project}")
        print(f"[INFO] Work root: {self.work_root}")
        print(f"[INFO] Tools selected: {len(selected_tools)}")

        for index, tool_name in enumerate(selected_tools, start=1):
            workspace = self._prepare_workspace(tool_name, index)
            start = time.perf_counter()
            args: Dict[str, Any] = {}
            result: Any = None
            error: Optional[str] = None
            ok = False

            try:
                args, result = await self._run_tool(tool_name, workspace)
                ok = _is_ok(result)
                if not ok:
                    error = _error_text(result)
            except Exception as exc:  # noqa: BLE001 - capture for report
                ok = False
                error = f"{type(exc).__name__}: {exc}"
            finally:
                try:
                    await self._best_effort_stop_run(workspace)
                except Exception:
                    pass
                try:
                    stop_bridge_server(str(workspace))
                except Exception:
                    pass

            elapsed = time.perf_counter() - start
            record = ToolRunRecord(
                tool=tool_name,
                workspace=str(workspace),
                ok=ok,
                args=args,
                elapsed_seconds=round(elapsed, 3),
                result=result,
                error=error,
            )
            self.records.append(record)

            state = "PASS" if ok else "FAIL"
            print(f"[{state}] ({index:02d}/{len(selected_tools):02d}) {tool_name}")

            if not self.keep_workdirs:
                shutil.rmtree(workspace, ignore_errors=True)

            if self.fail_fast and not ok:
                break

        self._write_report(selected_tools)
        failed = [r for r in self.records if not r.ok]

        print("\n=== MCP TOOL SMOKE SUMMARY ===")
        print(f"Total tools run: {len(self.records)}")
        print(f"Passed: {len(self.records) - len(failed)}")
        print(f"Failed: {len(failed)}")
        print(f"Report: {self.output_path}")
        if failed:
            print("Failed tools:")
            for row in failed:
                print(f"- {row.tool}: {row.error or _error_text(row.result)}")
        return 1 if failed else 0

    def _select_tools(self, all_tools: List[str]) -> List[str]:
        tools = list(all_tools)
        if self.include_tools:
            include = set(self.include_tools)
            tools = [t for t in tools if t in include]
        if self.exclude_tools:
            tools = [t for t in tools if t not in self.exclude_tools]
        return tools

    def _prepare_workspace(self, tool_name: str, index: int) -> Path:
        folder_name = f"{index:02d}_{_sanitize_tool_name(tool_name)}"
        workspace = self.work_root / folder_name
        ignore = shutil.ignore_patterns(
            "__pycache__",
            ".gms_mcp",
            ".gml_index_cache.json",
            "mcp_tool_smoke_report.json",
            "*.old.yy",
        )
        shutil.copytree(self.base_project, workspace, ignore=ignore)
        return workspace

    def _schema_required(self, tool_name: str) -> set[str]:
        schema = self.tool_schemas.get(tool_name, {})
        required = schema.get("required", []) if isinstance(schema, dict) else []
        return {r for r in required if isinstance(r, str)}

    def _schema_properties(self, tool_name: str) -> set[str]:
        schema = self.tool_schemas.get(tool_name, {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        if not isinstance(properties, dict):
            return set()
        return {k for k in properties.keys() if isinstance(k, str)}

    def _with_project(self, tool_name: str, project_root: Path, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        args = dict(payload or {})
        if "project_root" in self._schema_properties(tool_name):
            args.setdefault("project_root", str(project_root))
        return args

    def _validate_required_tool_coverage(self, tools: List[str]) -> None:
        handled = set(self.create_tool_defaults) | set(self.scenarios)
        missing: List[str] = []
        for tool in tools:
            required = self._schema_required(tool) - {"project_root"}
            if required and tool not in handled:
                missing.append(f"{tool} (required: {sorted(required)})")
        if missing:
            joined = "\n".join(f"- {entry}" for entry in missing)
            raise RuntimeError(
                "Smoke runner missing scenario coverage for required-arg tools:\n"
                f"{joined}"
            )

    async def _call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        raw = await self.mcp.call_tool(tool_name, args)
        return _unwrap_call_tool(raw)

    async def _ensure_ok(self, tool_name: str, args: Dict[str, Any], *, label: str = "") -> Any:
        result = await self._call_tool(tool_name, args)
        if not _is_ok(result):
            prefix = f"{label} " if label else ""
            raise RuntimeError(f"{prefix}{tool_name} failed: {_error_text(result)}")
        return result

    async def _best_effort_stop_run(self, project_root: Path) -> None:
        args = self._with_project("gm_run_stop", project_root, {"quiet": True})
        result = await self._call_tool("gm_run_stop", args)
        if isinstance(result, dict) and result.get("message") == "No game session found":
            return

    async def _run_tool(self, tool_name: str, project_root: Path) -> tuple[Dict[str, Any], Any]:
        if tool_name in self.create_tool_defaults:
            payload = self.create_tool_defaults[tool_name]
            args = self._with_project(tool_name, project_root, payload)
            result = await self._call_tool(tool_name, args)
            return args, result

        scenario = self.scenarios.get(tool_name)
        if scenario:
            return await scenario(project_root)

        args = self._with_project(tool_name, project_root, {})
        result = await self._call_tool(tool_name, args)
        return args, result

    # ------------------------------------------------------------------
    # Generic prep helpers
    # ------------------------------------------------------------------

    async def _create_script(self, project_root: Path, name: str) -> None:
        args = self._with_project("gm_create_script", project_root, {"name": name, "skip_maintenance": True})
        await self._ensure_ok("gm_create_script", args, label="precondition")

    async def _create_object(self, project_root: Path, name: str) -> None:
        args = self._with_project("gm_create_object", project_root, {"name": name, "skip_maintenance": True})
        await self._ensure_ok("gm_create_object", args, label="precondition")

    async def _create_room(self, project_root: Path, name: str) -> None:
        args = self._with_project("gm_create_room", project_root, {"name": name, "skip_maintenance": True})
        await self._ensure_ok("gm_create_room", args, label="precondition")

    async def _create_sprite(self, project_root: Path, name: str, frame_count: int = 1) -> None:
        args = self._with_project(
            "gm_create_sprite",
            project_root,
            {"name": name, "frame_count": frame_count, "skip_maintenance": True},
        )
        await self._ensure_ok("gm_create_sprite", args, label="precondition")

    async def _create_texture_group(self, project_root: Path, name: str) -> None:
        args = self._with_project(
            "gm_texture_group_create",
            project_root,
            {"name": name, "template": "Default", "dry_run": False},
        )
        await self._ensure_ok("gm_texture_group_create", args, label="precondition")

    # ------------------------------------------------------------------
    # Tool scenarios
    # ------------------------------------------------------------------

    async def _scenario_asset_delete(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        name = "scr_delete_smoke"
        await self._create_script(project_root, name)
        args = self._with_project(
            "gm_asset_delete",
            project_root,
            {"asset_type": "script", "name": name, "dry_run": True},
        )
        result = await self._call_tool("gm_asset_delete", args)
        return args, result

    async def _scenario_cli(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        args = self._with_project("gm_cli", project_root, {"args": ["--help"]})
        result = await self._call_tool("gm_cli", args)
        return args, result

    async def _scenario_doc_lookup(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        _ = project_root
        args = {"function_name": "draw_sprite"}
        result = await self._call_tool("gm_doc_lookup", args)
        return args, result

    async def _scenario_doc_search(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        _ = project_root
        args = {"query": "draw_"}
        result = await self._call_tool("gm_doc_search", args)
        return args, result

    async def _prepare_event_object(self, project_root: Path, *, with_step_event: bool) -> str:
        obj_name = "o_evt_smoke"
        await self._create_object(project_root, obj_name)
        if with_step_event:
            add_args = self._with_project(
                "gm_event_add",
                project_root,
                {"object": obj_name, "event": "step"},
            )
            await self._ensure_ok("gm_event_add", add_args, label="precondition")
        return obj_name

    async def _scenario_event_add(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        obj_name = await self._prepare_event_object(project_root, with_step_event=False)
        args = self._with_project("gm_event_add", project_root, {"object": obj_name, "event": "step"})
        result = await self._call_tool("gm_event_add", args)
        return args, result

    async def _scenario_event_duplicate(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        obj_name = await self._prepare_event_object(project_root, with_step_event=True)
        args = self._with_project(
            "gm_event_duplicate",
            project_root,
            {"object": obj_name, "source_event": "step:0", "target_num": 1},
        )
        result = await self._call_tool("gm_event_duplicate", args)
        return args, result

    async def _scenario_event_fix(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        obj_name = await self._prepare_event_object(project_root, with_step_event=True)
        args = self._with_project("gm_event_fix", project_root, {"object": obj_name})
        result = await self._call_tool("gm_event_fix", args)
        return args, result

    async def _scenario_event_list(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        obj_name = await self._prepare_event_object(project_root, with_step_event=True)
        args = self._with_project("gm_event_list", project_root, {"object": obj_name})
        result = await self._call_tool("gm_event_list", args)
        return args, result

    async def _scenario_event_remove(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        obj_name = await self._prepare_event_object(project_root, with_step_event=True)
        args = self._with_project(
            "gm_event_remove",
            project_root,
            {"object": obj_name, "event": "step:0"},
        )
        result = await self._call_tool("gm_event_remove", args)
        return args, result

    async def _scenario_event_validate(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        obj_name = await self._prepare_event_object(project_root, with_step_event=True)
        # gm_create_object can leave a default Create_0.gml file without a matching
        # event entry; normalize first so validate checks a healthy object.
        fix_args = self._with_project("gm_event_fix", project_root, {"object": obj_name})
        await self._ensure_ok("gm_event_fix", fix_args, label="precondition")
        args = self._with_project("gm_event_validate", project_root, {"object": obj_name})
        result = await self._call_tool("gm_event_validate", args)
        return args, result

    async def _scenario_find_definition(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        symbol = "scr_symbol_smoke"
        await self._create_script(project_root, symbol)
        args = self._with_project("gm_find_definition", project_root, {"symbol_name": symbol})
        result = await self._call_tool("gm_find_definition", args)
        return args, result

    async def _scenario_find_references(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        symbol = "scr_symbol_smoke"
        await self._create_script(project_root, symbol)
        args = self._with_project("gm_find_references", project_root, {"symbol_name": symbol})
        result = await self._call_tool("gm_find_references", args)
        return args, result

    async def _scenario_read_asset(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        script_name = "scr_read_smoke"
        await self._create_script(project_root, script_name)
        args = self._with_project(
            "gm_read_asset",
            project_root,
            {"asset_identifier": f"scripts/{script_name}/{script_name}.yy"},
        )
        result = await self._call_tool("gm_read_asset", args)
        return args, result

    async def _prepare_room_object_layer(self, project_root: Path) -> tuple[str, str, str]:
        room = "r_room_smoke"
        obj = "o_room_smoke"
        layer = "SmokeInstances"
        await self._create_room(project_root, room)
        await self._create_object(project_root, obj)
        add_layer_args = self._with_project(
            "gm_room_layer_add",
            project_root,
            {"room_name": room, "layer_type": "instance", "layer_name": layer, "depth": 0},
        )
        await self._ensure_ok("gm_room_layer_add", add_layer_args, label="precondition")
        return room, obj, layer

    def _first_instance_id(self, project_root: Path, room_name: str) -> str:
        room_yy = project_root / "rooms" / room_name / f"{room_name}.yy"
        room_data = load_json_loose(room_yy)
        if not isinstance(room_data, dict):
            raise RuntimeError(f"Failed to read room data: {room_yy}")
        for layer in room_data.get("layers", []):
            if not isinstance(layer, dict):
                continue
            for inst in layer.get("instances", []):
                if isinstance(inst, dict) and isinstance(inst.get("name"), str):
                    return inst["name"]
        raise RuntimeError(f"No instance found in room {room_name}")

    async def _scenario_room_instance_add(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room, obj, layer = await self._prepare_room_object_layer(project_root)
        args = self._with_project(
            "gm_room_instance_add",
            project_root,
            {"room_name": room, "object_name": obj, "x": 64, "y": 64, "layer": layer},
        )
        result = await self._call_tool("gm_room_instance_add", args)
        return args, result

    async def _scenario_room_instance_list(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room, obj, layer = await self._prepare_room_object_layer(project_root)
        add_args = self._with_project(
            "gm_room_instance_add",
            project_root,
            {"room_name": room, "object_name": obj, "x": 64, "y": 64, "layer": layer},
        )
        await self._ensure_ok("gm_room_instance_add", add_args, label="precondition")
        args = self._with_project("gm_room_instance_list", project_root, {"room_name": room})
        result = await self._call_tool("gm_room_instance_list", args)
        return args, result

    async def _scenario_room_instance_remove(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room, obj, layer = await self._prepare_room_object_layer(project_root)
        add_args = self._with_project(
            "gm_room_instance_add",
            project_root,
            {"room_name": room, "object_name": obj, "x": 64, "y": 64, "layer": layer},
        )
        await self._ensure_ok("gm_room_instance_add", add_args, label="precondition")
        instance_id = self._first_instance_id(project_root, room)
        args = self._with_project(
            "gm_room_instance_remove",
            project_root,
            {"room_name": room, "instance_id": instance_id},
        )
        result = await self._call_tool("gm_room_instance_remove", args)
        return args, result

    async def _scenario_room_layer_add(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room = "r_layer_smoke"
        await self._create_room(project_root, room)
        args = self._with_project(
            "gm_room_layer_add",
            project_root,
            {"room_name": room, "layer_type": "instance", "layer_name": "LayerSmoke", "depth": 0},
        )
        result = await self._call_tool("gm_room_layer_add", args)
        return args, result

    async def _scenario_room_layer_list(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room = "r_layer_smoke"
        await self._create_room(project_root, room)
        args = self._with_project("gm_room_layer_list", project_root, {"room_name": room})
        result = await self._call_tool("gm_room_layer_list", args)
        return args, result

    async def _scenario_room_layer_remove(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room = "r_layer_smoke"
        await self._create_room(project_root, room)
        add_args = self._with_project(
            "gm_room_layer_add",
            project_root,
            {"room_name": room, "layer_type": "instance", "layer_name": "LayerSmoke", "depth": 0},
        )
        await self._ensure_ok("gm_room_layer_add", add_args, label="precondition")
        args = self._with_project(
            "gm_room_layer_remove",
            project_root,
            {"room_name": room, "layer_name": "LayerSmoke"},
        )
        result = await self._call_tool("gm_room_layer_remove", args)
        return args, result

    async def _scenario_room_ops_delete(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room = "r_ops_delete_smoke"
        await self._create_room(project_root, room)
        args = self._with_project("gm_room_ops_delete", project_root, {"room_name": room, "dry_run": True})
        result = await self._call_tool("gm_room_ops_delete", args)
        return args, result

    async def _scenario_room_ops_duplicate(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        source = "r_ops_src_smoke"
        target = "r_ops_dup_smoke"
        await self._create_room(project_root, source)
        args = self._with_project(
            "gm_room_ops_duplicate",
            project_root,
            {"source_room": source, "new_name": target},
        )
        result = await self._call_tool("gm_room_ops_duplicate", args)
        return args, result

    async def _scenario_room_ops_rename(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        room = "r_ops_rename_src"
        await self._create_room(project_root, room)
        args = self._with_project(
            "gm_room_ops_rename",
            project_root,
            {"room_name": room, "new_name": "r_ops_rename_dst"},
        )
        result = await self._call_tool("gm_room_ops_rename", args)
        return args, result

    async def _start_background_run(self, project_root: Path, *, enable_bridge: str = "false") -> Any:
        args = self._with_project(
            "gm_run",
            project_root,
            {
                "background": True,
                "runtime": "VM",
                "enable_bridge": enable_bridge,
                "output_mode": "tail",
                "tail_lines": 40,
                "quiet": True,
            },
        )
        return await self._ensure_ok("gm_run", args, label="precondition")

    async def _scenario_run(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        args = self._with_project(
            "gm_run",
            project_root,
            {
                "background": True,
                "runtime": "VM",
                "enable_bridge": "false",
                "output_mode": "tail",
                "tail_lines": 40,
                "quiet": True,
            },
        )
        result = await self._call_tool("gm_run", args)
        return args, result

    async def _scenario_run_status(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        await self._start_background_run(project_root, enable_bridge="false")
        args = self._with_project("gm_run_status", project_root, {"quiet": True})
        result = await self._call_tool("gm_run_status", args)
        return args, result

    async def _scenario_run_stop(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        await self._start_background_run(project_root, enable_bridge="false")
        args = self._with_project("gm_run_stop", project_root, {"quiet": True})
        result = await self._call_tool("gm_run_stop", args)
        return args, result

    async def _scenario_run_logs(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        client = FakeBridgeClient(project_root)
        client.start()
        try:
            args = self._with_project("gm_run_logs", project_root, {"lines": 5})
            result = await self._call_tool("gm_run_logs", args)
            return args, result
        finally:
            client.stop()

    async def _scenario_run_command(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        client = FakeBridgeClient(project_root)
        client.start()
        try:
            args = self._with_project(
                "gm_run_command",
                project_root,
                {"command": "ping", "timeout": 2.0},
            )
            result = await self._call_tool("gm_run_command", args)
            return args, result
        finally:
            client.stop()

    async def _scenario_runtime_pin(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        list_args = self._with_project("gm_runtime_list", project_root, {})
        listing = await self._call_tool("gm_runtime_list", list_args)
        version = None
        if isinstance(listing, dict):
            version = listing.get("active_version")
            if not version:
                runtimes = listing.get("runtimes") or []
                if runtimes and isinstance(runtimes[0], dict):
                    version = runtimes[0].get("version")
        if not isinstance(version, str) or not version:
            raise RuntimeError("Could not determine runtime version for gm_runtime_pin")
        args = self._with_project("gm_runtime_pin", project_root, {"version": version})
        result = await self._call_tool("gm_runtime_pin", args)
        return args, result

    async def _scenario_runtime_unpin(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        pin_args, _ = await self._scenario_runtime_pin(project_root)
        _ = pin_args
        args = self._with_project("gm_runtime_unpin", project_root, {})
        result = await self._call_tool("gm_runtime_unpin", args)
        return args, result

    async def _scenario_search_references(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        args = self._with_project(
            "gm_search_references",
            project_root,
            {"pattern": "textureGroupId", "scope": "all", "max_results": 20},
        )
        result = await self._call_tool("gm_search_references", args)
        return args, result

    async def _scenario_sprite_add_frame(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        sprite = "spr_frames_add_smoke"
        await self._create_sprite(project_root, sprite, frame_count=1)
        args = self._with_project(
            "gm_sprite_add_frame",
            project_root,
            {"sprite_path": f"sprites/{sprite}/{sprite}.yy"},
        )
        result = await self._call_tool("gm_sprite_add_frame", args)
        return args, result

    async def _scenario_sprite_duplicate_frame(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        sprite = "spr_frames_dup_smoke"
        await self._create_sprite(project_root, sprite, frame_count=2)
        args = self._with_project(
            "gm_sprite_duplicate_frame",
            project_root,
            {"sprite_path": f"sprites/{sprite}/{sprite}.yy", "source_position": 0, "target_position": 1},
        )
        result = await self._call_tool("gm_sprite_duplicate_frame", args)
        return args, result

    async def _scenario_sprite_frame_count(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        sprite = "spr_frames_count_smoke"
        await self._create_sprite(project_root, sprite, frame_count=3)
        args = self._with_project(
            "gm_sprite_frame_count",
            project_root,
            {"sprite_path": f"sprites/{sprite}/{sprite}.yy"},
        )
        result = await self._call_tool("gm_sprite_frame_count", args)
        return args, result

    async def _scenario_sprite_import_strip(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        source = project_root / "smoke_strip.png"
        if not source.exists():
            source = project_root / "smoke_a.png"
        if not source.exists():
            source = project_root / "smoke_import.png"
            _write_minimal_png(source)
        args = self._with_project(
            "gm_sprite_import_strip",
            project_root,
            {"name": "spr_strip_smoke", "source": str(source), "layout": "horizontal"},
        )
        result = await self._call_tool("gm_sprite_import_strip", args)
        return args, result

    async def _scenario_sprite_remove_frame(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        sprite = "spr_frames_remove_smoke"
        await self._create_sprite(project_root, sprite, frame_count=2)
        args = self._with_project(
            "gm_sprite_remove_frame",
            project_root,
            {"sprite_path": f"sprites/{sprite}/{sprite}.yy", "position": 1},
        )
        result = await self._call_tool("gm_sprite_remove_frame", args)
        return args, result

    async def _scenario_texture_group_create(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        args = self._with_project(
            "gm_texture_group_create",
            project_root,
            {"name": "tg_create_smoke", "template": "Default", "dry_run": False},
        )
        result = await self._call_tool("gm_texture_group_create", args)
        return args, result

    async def _scenario_texture_group_read(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        args = self._with_project("gm_texture_group_read", project_root, {"name": "Default"})
        result = await self._call_tool("gm_texture_group_read", args)
        return args, result

    async def _scenario_texture_group_members(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        args = self._with_project("gm_texture_group_members", project_root, {"group_name": "Default"})
        result = await self._call_tool("gm_texture_group_members", args)
        return args, result

    async def _scenario_texture_group_update(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        group = "tg_update_smoke"
        await self._create_texture_group(project_root, group)
        args = self._with_project(
            "gm_texture_group_update",
            project_root,
            {"name": group, "patch": {"autocrop": False, "border": 4}, "update_existing_configs": True, "dry_run": False},
        )
        result = await self._call_tool("gm_texture_group_update", args)
        return args, result

    async def _scenario_texture_group_rename(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        old_name = "tg_rename_smoke"
        new_name = "tg_rename_smoke_dst"
        await self._create_texture_group(project_root, old_name)
        args = self._with_project(
            "gm_texture_group_rename",
            project_root,
            {"old_name": old_name, "new_name": new_name, "update_references": True, "dry_run": False},
        )
        result = await self._call_tool("gm_texture_group_rename", args)
        return args, result

    async def _scenario_texture_group_assign(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        group = "tg_assign_smoke"
        sprite = "spr_tg_assign_smoke"
        await self._create_texture_group(project_root, group)
        await self._create_sprite(project_root, sprite, frame_count=1)
        args = self._with_project(
            "gm_texture_group_assign",
            project_root,
            {
                "group_name": group,
                "asset_identifiers": [sprite],
                "include_top_level": True,
                "update_existing_configs": True,
                "dry_run": False,
            },
        )
        result = await self._call_tool("gm_texture_group_assign", args)
        return args, result

    async def _scenario_texture_group_delete(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        group = "tg_delete_smoke"
        sprite = "spr_tg_delete_smoke"
        await self._create_texture_group(project_root, group)
        await self._create_sprite(project_root, sprite, frame_count=1)
        assign_args = self._with_project(
            "gm_texture_group_assign",
            project_root,
            {
                "group_name": group,
                "asset_identifiers": [sprite],
                "include_top_level": True,
                "update_existing_configs": True,
                "dry_run": False,
            },
        )
        await self._ensure_ok("gm_texture_group_assign", assign_args, label="precondition")
        args = self._with_project(
            "gm_texture_group_delete",
            project_root,
            {"name": group, "reassign_to": "Default", "dry_run": False},
        )
        result = await self._call_tool("gm_texture_group_delete", args)
        return args, result

    async def _scenario_workflow_delete(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        script = "scr_workflow_delete_smoke"
        await self._create_script(project_root, script)
        args = self._with_project(
            "gm_workflow_delete",
            project_root,
            {"asset_path": f"scripts/{script}/{script}.yy", "dry_run": True},
        )
        result = await self._call_tool("gm_workflow_delete", args)
        return args, result

    async def _scenario_workflow_duplicate(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        script = "scr_workflow_dup_src"
        await self._create_script(project_root, script)
        args = self._with_project(
            "gm_workflow_duplicate",
            project_root,
            {"asset_path": f"scripts/{script}/{script}.yy", "new_name": "scr_workflow_dup_dst"},
        )
        result = await self._call_tool("gm_workflow_duplicate", args)
        return args, result

    async def _scenario_workflow_rename(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        script = "scr_workflow_rename_src"
        await self._create_script(project_root, script)
        args = self._with_project(
            "gm_workflow_rename",
            project_root,
            {"asset_path": f"scripts/{script}/{script}.yy", "new_name": "scr_workflow_rename_dst"},
        )
        result = await self._call_tool("gm_workflow_rename", args)
        return args, result

    async def _scenario_workflow_swap_sprite(self, project_root: Path) -> tuple[Dict[str, Any], Any]:
        sprite = "spr_workflow_swap_smoke"
        await self._create_sprite(project_root, sprite, frame_count=1)
        png = project_root / "smoke_swap.png"
        _write_minimal_png(png)
        args = self._with_project(
            "gm_workflow_swap_sprite",
            project_root,
            {"asset_path": f"sprites/{sprite}/{sprite}.yy", "png": str(png), "frame": 0},
        )
        result = await self._call_tool("gm_workflow_swap_sprite", args)
        return args, result

    def _write_report(self, selected_tools: List[str]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        failed = [r for r in self.records if not r.ok]
        called = [r.tool for r in self.records]
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "base_project": str(self.base_project),
            "work_root": str(self.work_root),
            "total_registered_tools": len(self.tools),
            "registered_tools": self.tools,
            "selected_tools": selected_tools,
            "unique_tools_called": len(called),
            "called_tools": called,
            "missing_tools": [t for t in selected_tools if t not in set(called)],
            "tools_all_attempts_failed": [r.tool for r in failed],
            "pass_count": len(self.records) - len(failed),
            "fail_count": len(failed),
            "results": [asdict(r) for r in self.records],
        }
        self.output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic smoke checks for every MCP tool")
    parser.add_argument(
        "--base-project",
        type=Path,
        default=REPO_ROOT / "gamemaker" / "BLANK GAME1",
        help="Path to BLANK project fixture (default: gamemaker/BLANK GAME1)",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=REPO_ROOT / "gamemaker" / ".mcp_tool_smoke_work",
        help="Workspace root used for isolated per-tool project copies",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "gamemaker" / "BLANK GAME1" / "mcp_tool_smoke_report.json",
        help="Output JSON report path",
    )
    parser.add_argument(
        "--tools",
        nargs="*",
        default=None,
        help="Optional explicit tool names to run (default: all)",
    )
    parser.add_argument(
        "--exclude-tools",
        nargs="*",
        default=None,
        help="Tool names to skip",
    )
    parser.add_argument(
        "--keep-workdirs",
        action="store_true",
        help="Keep per-tool workspace directories after run",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first failure",
    )
    return parser.parse_args()


async def _async_main() -> int:
    args = parse_args()
    runner = MCPToolSmokeRunner(
        base_project=args.base_project,
        work_root=args.work_root,
        output_path=args.output,
        include_tools=args.tools,
        exclude_tools=args.exclude_tools,
        keep_workdirs=args.keep_workdirs,
        fail_fast=args.fail_fast,
    )
    return await runner.run()


def main() -> int:
    try:
        return asyncio.run(_async_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
