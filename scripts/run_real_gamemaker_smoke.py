#!/usr/bin/env python3
"""Run a real GameMaker compile smoke for smart mutation verification."""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.runtime_manager import RuntimeManager
from gms_helpers.synthetic_project import create_synthetic_project
from gms_helpers.transactions import validate_project_after_mutation
from gms_helpers.utils import load_json_loose
from gms_mcp.gamemaker_mcp_server import build_server


_TRUE_VALUES = {"1", "true", "yes", "on"}
_MIN_COMPILE_TIMEOUT_SECONDS = 120
_SYNTHETIC_FIXTURES = {
    "gm-2024": {"project_name": "gms_mcp_smoke_2024", "ide_version": "2024.14.3.217"},
    "gm-2026-lts": {"project_name": "gms_mcp_smoke_2026_lts", "ide_version": "2026.0.0.16"},
}
_HOST_PLATFORM_NAMES = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}
_SAFE_DIAGNOSTIC_FIELDS = {
    "category",
    "exit_code",
    "compile_stage_ok",
    "timed_out",
    "attempt_count",
    "missing_library",
    "exception_type",
    "stdout_sha256",
    "stderr_sha256",
}
_COPY_IGNORE = {
    ".git",
    ".gms_mcp",
    ".gms-mcp",
    ".gml_index_cache",
    "__pycache__",
    "output",
}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def _unwrap_call_tool(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], dict):
        payload = value[1]
        if "result" in payload:
            return payload["result"]
    return value


def _write_report(output_path: Path, payload: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _skip(message: str, *, required: bool, output_path: Path, fixture: Dict[str, Any] | None = None) -> int:
    payload = {
        "ok": not required,
        "status": "failed" if required else "skipped",
        "message": message,
    }
    if fixture is not None:
        payload["fixture"] = fixture
    _write_report(output_path, payload)
    print(f"[{'ERROR' if required else 'SKIP'}] {message}")
    return 1 if required else 0


def _fail(message: str, *, output_path: Path, fixture: Dict[str, Any], runtime: Dict[str, Any] | None = None) -> int:
    payload: Dict[str, Any] = {
        "ok": False,
        "status": "failed",
        "message": message,
        "fixture": fixture,
    }
    if runtime is not None:
        payload["runtime"] = runtime
    _write_report(output_path, payload)
    print(f"[ERROR] {message}")
    return 1


def _validate_source_project(project_root: Path) -> str | None:
    if not project_root.exists() or not project_root.is_dir():
        return "GameMaker smoke project not found."
    yyp_files = sorted(project_root.glob("*.yyp"))
    if not yyp_files:
        return "GameMaker smoke project has no .yyp file."
    if len(yyp_files) > 1:
        return "GameMaker smoke project must contain exactly one .yyp file."
    validation = validate_project_after_mutation(project_root)
    if not validation.success:
        return "GameMaker smoke project failed preflight validation."
    return None


def _source_project_provenance(project_root: Path) -> Dict[str, str]:
    """Return privacy-safe identity fields for a validated, single-YYP fixture."""
    yyp_path = next(project_root.glob("*.yyp")).resolve()
    project = load_json_loose(yyp_path)
    metadata = project.get("MetaData") if isinstance(project, dict) else None
    ide_version = str(metadata.get("IDEVersion") or "") if isinstance(metadata, dict) else ""
    return {
        "source_yyp_name": yyp_path.name,
        "source_yyp_sha256": hashlib.sha256(yyp_path.read_bytes()).hexdigest(),
        "source_ide_version": ide_version,
    }


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _COPY_IGNORE}


def _copy_project(source: Path, work_root: Path) -> Path:
    destination = work_root / "real-gamemaker-smoke-project"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=_copy_ignore)
    return destination


def _runtime_report(project_root: Path, expected_version: str = "") -> Dict[str, Any]:
    manager = RuntimeManager(project_root)
    runtime = None
    if expected_version:
        runtime = next(
            (
                candidate
                for candidate in manager.list_installed()
                if candidate.is_valid and _runtime_version_matches(candidate.version, expected_version)
            ),
            None,
        )
        if runtime is None:
            runtime = manager.select()
    else:
        runtime = manager.select()
    if not runtime:
        return {
            "ok": False,
            "message": (
                f"No valid GameMaker runtime matches {expected_version!r}."
                if expected_version
                else "No GameMaker runtime discovered."
            ),
        }
    return {
        "ok": bool(runtime.is_valid),
        "version": runtime.version,
        "channel": getattr(runtime, "release_channel", getattr(runtime, "channel", "unknown")),
        "message": "GameMaker runtime discovered."
        if runtime.is_valid
        else "GameMaker runtime exists but Igor is missing.",
    }


def _certification_report(
    result: Dict[str, Any], *, fixture: Dict[str, Any], runtime: Dict[str, Any]
) -> Dict[str, Any]:
    """Allowlist public certification fields so CI artifacts never expose host paths."""
    report: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "status": str(result.get("status") or ("passed" if result.get("ok") else "failed")),
        "fixture": fixture,
        "runtime": runtime,
    }
    for field in ("stage", "message"):
        value = result.get(field)
        if isinstance(value, str) and value:
            report[field] = value
    checks = result.get("checks")
    if isinstance(checks, dict):
        report["checks"] = checks
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, dict):
        report["diagnostics"] = {
            key: value
            for key, value in diagnostics.items()
            if key in _SAFE_DIAGNOSTIC_FIELDS and isinstance(value, (str, int, bool))
        }
    return report


def _find_compile_verification(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        compile_verification = value.get("compile_verification")
        if isinstance(compile_verification, dict) and "exit_code" in compile_verification:
            return compile_verification
        for nested in value.values():
            found = _find_compile_verification(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_compile_verification(nested)
            if found is not None:
                return found
    return None


def _safe_compile_diagnostics(result: Dict[str, Any]) -> Dict[str, Any]:
    verification = _find_compile_verification(result)
    if verification is None:
        return {"category": "compile_verification_unavailable"}

    stdout_tail = str(verification.get("stdout_tail") or "")
    stderr_tail = str(verification.get("stderr_tail") or "")
    combined = f"{stdout_tail}\n{stderr_tail}"
    lowered = combined.lower()
    missing_library_match = re.search(r"([A-Za-z0-9_.+-]+\.so(?:\.[0-9]+)*)", combined)
    exception_match = re.search(
        r"\b((?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*(?:Exception|Error))\b",
        combined,
    )

    if verification.get("timed_out"):
        category = "timeout"
    elif "error while loading shared libraries" in lowered or "cannot open shared object file" in lowered:
        category = "missing_shared_library"
    elif "permission denied" in lowered:
        category = "permission_denied"
    elif "operation not permitted" in lowered:
        category = "operation_not_permitted"
    elif "no such file or directory" in lowered or "command not found" in lowered:
        category = "missing_file_or_command"
    elif "system.accessviolationexception" in lowered:
        category = "runtime_access_violation"
    elif verification.get("compile_stage_ok"):
        category = "post_compile_exit_failure"
    else:
        category = "compiler_exit_failure"

    diagnostics: Dict[str, Any] = {
        "category": category,
        "exit_code": int(verification.get("exit_code") or 0),
        "compile_stage_ok": bool(verification.get("compile_stage_ok")),
        "timed_out": bool(verification.get("timed_out")),
        "attempt_count": int(verification.get("attempt_count") or 0),
        "stdout_sha256": hashlib.sha256(stdout_tail.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr_tail.encode("utf-8")).hexdigest(),
    }
    if missing_library_match:
        diagnostics["missing_library"] = missing_library_match.group(1)
    if exception_match:
        diagnostics["exception_type"] = exception_match.group(1)[:120]
    return diagnostics


def _runtime_version_matches(version: str, expected: str) -> bool:
    if not expected:
        return True
    if any(marker in expected for marker in ("*", "?", "[")):
        return fnmatch.fnmatch(version, expected)
    return version == expected


async def _run_smoke(project_root: Path) -> Dict[str, Any]:
    mcp = build_server()

    async def call_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = _unwrap_call_tool(await mcp.call_tool(tool_name, arguments))
        if not isinstance(result, dict):
            return {"ok": False, "error": f"Unexpected result from {tool_name}: {result!r}"}
        return result

    create_sprite = await call_tool(
        "gm_create_sprite",
        {
            "name": "spr_real_smoke_verify",
            "project_root": str(project_root),
            "frame_count": 1,
        },
    )
    if not create_sprite.get("ok"):
        return {
            "ok": False,
            "stage": "gm_create_sprite",
            "diagnostics": _safe_compile_diagnostics(create_sprite),
            "result": create_sprite,
        }

    create_transaction = create_sprite.get("transaction") if isinstance(create_sprite.get("transaction"), dict) else {}
    create_policy = create_transaction.get("verification_policy") if isinstance(create_transaction, dict) else {}
    create_compile = create_transaction.get("compile_verification") if isinstance(create_transaction, dict) else {}
    if not isinstance(create_policy, dict) or create_policy.get("action") != "compile":
        return {"ok": False, "stage": "gm_create_sprite_policy", "result": create_sprite}
    if not isinstance(create_compile, dict) or not create_compile.get("ok"):
        return {"ok": False, "stage": "gm_create_sprite_compile", "result": create_sprite}

    add_frame = await call_tool(
        "gm_sprite_add_frame",
        {
            "sprite_path": "sprites/spr_real_smoke_verify/spr_real_smoke_verify.yy",
            "project_root": str(project_root),
        },
    )
    if not add_frame.get("ok"):
        return {"ok": False, "stage": "gm_sprite_add_frame", "result": add_frame}

    add_transaction = add_frame.get("transaction") if isinstance(add_frame.get("transaction"), dict) else {}
    add_policy = add_transaction.get("verification_policy") if isinstance(add_transaction, dict) else {}
    pending = add_transaction.get("pending_compile_verification") if isinstance(add_transaction, dict) else {}
    if not isinstance(add_policy, dict) or add_policy.get("action") != "defer":
        return {"ok": False, "stage": "gm_sprite_add_frame_policy", "result": add_frame}
    if not isinstance(pending, dict) or not pending.get("required"):
        return {"ok": False, "stage": "gm_sprite_add_frame_pending", "result": add_frame}

    previous_verify_mode = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY")
    os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = "off"
    try:
        create_collision_source = await call_tool(
            "gm_create_object",
            {
                "name": "o_real_smoke_collision_source",
                "project_root": str(project_root),
                "skip_maintenance": True,
            },
        )
        create_collision_target = await call_tool(
            "gm_create_object",
            {
                "name": "o_real_smoke_collision_target",
                "project_root": str(project_root),
                "skip_maintenance": True,
            },
        )
        create_room_order_source = await call_tool(
            "gm_create_room",
            {
                "name": "r_real_smoke_order_source",
                "project_root": str(project_root),
                "skip_maintenance": True,
            },
        )
    finally:
        if previous_verify_mode is None:
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
        else:
            os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = previous_verify_mode

    if not create_collision_source.get("ok"):
        return {"ok": False, "stage": "gm_create_collision_source", "result": create_collision_source}
    if not create_collision_target.get("ok"):
        return {"ok": False, "stage": "gm_create_collision_target", "result": create_collision_target}
    if not create_room_order_source.get("ok"):
        return {"ok": False, "stage": "gm_create_room_order_source", "result": create_room_order_source}

    collision_event = await call_tool(
        "gm_event_add",
        {
            "object": "o_real_smoke_collision_source",
            "event": "collision:o_real_smoke_collision_target",
            "project_root": str(project_root),
        },
    )
    if not collision_event.get("ok"):
        return {"ok": False, "stage": "gm_event_add_collision", "result": collision_event}
    collision_transaction = (
        collision_event.get("transaction") if isinstance(collision_event.get("transaction"), dict) else {}
    )
    collision_policy = (
        collision_transaction.get("verification_policy") if isinstance(collision_transaction, dict) else {}
    )
    if not isinstance(collision_policy, dict) or collision_policy.get("action") != "defer":
        return {"ok": False, "stage": "gm_event_add_collision_policy", "result": collision_event}

    source_object_path = project_root / "objects" / "o_real_smoke_collision_source" / "o_real_smoke_collision_source.yy"
    source_object = load_json_loose(source_object_path)
    if not isinstance(source_object, dict):
        return {
            "ok": False,
            "stage": "gm_event_add_collision_schema",
            "error": f"Could not parse GameMaker object metadata: {source_object_path}",
        }
    expected_collision_id = {
        "name": "o_real_smoke_collision_target",
        "path": "objects/o_real_smoke_collision_target/o_real_smoke_collision_target.yy",
    }
    raw_event_list = source_object.get("eventList")
    event_list: list[Any] = raw_event_list if isinstance(raw_event_list, list) else []
    collision_reference_emitted = any(
        isinstance(event, dict) and event.get("collisionObjectId") == expected_collision_id for event in event_list
    )
    collision_gml = source_object_path.parent / "Collision_o_real_smoke_collision_target.gml"
    if not collision_reference_emitted or not collision_gml.is_file():
        return {
            "ok": False,
            "stage": "gm_event_add_collision_schema",
            "result": collision_event,
            "expected_collision_id": expected_collision_id,
        }

    flush = await call_tool("gm_verification_flush", {"project_root": str(project_root)})
    if not flush.get("ok") or not flush.get("compiled"):
        return {"ok": False, "stage": "gm_verification_flush", "result": flush}

    previous_verify_mode = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY")
    os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = "off"
    try:
        duplicate_room = await call_tool(
            "gm_workflow_duplicate",
            {
                "asset_path": "rooms/r_real_smoke_order_source/r_real_smoke_order_source.yy",
                "new_name": "r_real_smoke_order_copy",
                "yes": True,
                "project_root": str(project_root),
            },
        )
        delete_room_source = await call_tool(
            "gm_safe_delete",
            {
                "asset_type": "room",
                "asset_name": "r_real_smoke_order_source",
                "force": True,
                "dry_run": False,
                "project_root": str(project_root),
            },
        )
    finally:
        if previous_verify_mode is None:
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
        else:
            os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = previous_verify_mode

    if not duplicate_room.get("ok"):
        return {"ok": False, "stage": "gm_workflow_duplicate_room", "result": duplicate_room}
    if not delete_room_source.get("ok"):
        return {"ok": False, "stage": "gm_safe_delete_room", "result": delete_room_source}
    project_data = load_json_loose(next(project_root.glob("*.yyp")))
    room_order = project_data.get("RoomOrderNodes", []) if isinstance(project_data, dict) else []
    room_order_names = [
        entry.get("roomId", {}).get("name")
        for entry in room_order
        if isinstance(entry, dict) and isinstance(entry.get("roomId"), dict)
    ]
    if "r_real_smoke_order_copy" not in room_order_names or "r_real_smoke_order_source" in room_order_names:
        return {
            "ok": False,
            "stage": "room_order_duplicate_delete_schema",
            "room_order_names": room_order_names,
        }

    rename_collision_target = await call_tool(
        "gm_workflow_rename",
        {
            "asset_path": "objects/o_real_smoke_collision_target/o_real_smoke_collision_target.yy",
            "new_name": "o_real_smoke_collision_renamed",
            "project_root": str(project_root),
        },
    )
    if not rename_collision_target.get("ok"):
        return {"ok": False, "stage": "gm_workflow_rename_collision_target", "result": rename_collision_target}
    rename_transaction = (
        rename_collision_target.get("transaction")
        if isinstance(rename_collision_target.get("transaction"), dict)
        else {}
    )
    rename_compile = rename_transaction.get("compile_verification") if isinstance(rename_transaction, dict) else {}
    if not isinstance(rename_compile, dict) or not rename_compile.get("ok"):
        return {"ok": False, "stage": "gm_workflow_rename_collision_compile", "result": rename_collision_target}

    renamed_source_object = load_json_loose(source_object_path)
    renamed_collision_id = {
        "name": "o_real_smoke_collision_renamed",
        "path": "objects/o_real_smoke_collision_renamed/o_real_smoke_collision_renamed.yy",
    }
    renamed_events = renamed_source_object.get("eventList", []) if isinstance(renamed_source_object, dict) else []
    renamed_event = next(
        (
            event
            for event in renamed_events
            if isinstance(event, dict) and event.get("collisionObjectId") == renamed_collision_id
        ),
        None,
    )
    renamed_collision_gml = source_object_path.parent / "Collision_o_real_smoke_collision_renamed.gml"
    if (
        not isinstance(renamed_event, dict)
        or renamed_event.get("%Name") != "Collision_o_real_smoke_collision_renamed"
        or renamed_event.get("name") != "Collision_o_real_smoke_collision_renamed"
        or not renamed_collision_gml.is_file()
        or collision_gml.exists()
    ):
        return {
            "ok": False,
            "stage": "collision_target_rename_schema",
            "result": rename_collision_target,
        }

    return {
        "ok": True,
        "status": "passed",
        "project_root": str(project_root),
        "checks": {
            "high_risk_mutation_compiled": True,
            "batchable_mutation_deferred": True,
            "deferred_batch_flushed": True,
            "collision_reference_emitted": True,
            "collision_event_compiled": True,
            "collision_target_rename_schema": True,
            "collision_target_rename_compiled": True,
            "room_order_duplicate_delete_schema": True,
            "room_order_changes_compiled": True,
        },
        "results": {
            "gm_create_sprite": create_sprite,
            "gm_sprite_add_frame": add_frame,
            "gm_create_collision_source": create_collision_source,
            "gm_create_collision_target": create_collision_target,
            "gm_create_room_order_source": create_room_order_source,
            "gm_event_add_collision": collision_event,
            "gm_verification_flush": flush,
            "gm_workflow_duplicate_room": duplicate_room,
            "gm_safe_delete_room": delete_room_source,
            "gm_workflow_rename_collision_target": rename_collision_target,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real GameMaker smart verification smoke test.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build") / "reports" / "real_gamemaker_smoke.json",
        help="Where to write the JSON smoke report.",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="Directory for the mutable project copy. Defaults to a temporary directory.",
    )
    parser.add_argument("--keep-workdir", action="store_true", help="Keep the copied project after the smoke.")
    parser.add_argument(
        "--required", action="store_true", help="Fail instead of skipping when prerequisites are absent."
    )
    parser.add_argument(
        "--fixture-name",
        choices=tuple(_SYNTHETIC_FIXTURES),
        required=True,
        help="Synthetic fixture family to generate and certify.",
    )
    parser.add_argument(
        "--expected-runtime-version",
        default=os.environ.get("GMS_MCP_REAL_SMOKE_EXPECTED_RUNTIME", ""),
        help="Required GameMaker runtime version or fnmatch pattern for this fixture.",
    )
    parser.add_argument("--platform", default="", help="Optional GameMaker platform override for compile verification.")
    parser.add_argument("--runtime", default="", help="Optional GameMaker runtime override for compile verification.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Optional compile timeout override; values below the platform's internal validation bound are rejected.",
    )
    parser.add_argument(
        "--privacy-safe-output",
        action="store_true",
        help="Suppress detailed GameMaker/tool output and print only the final pass/fail state.",
    )
    return parser.parse_args()


def _run(args: argparse.Namespace) -> int:
    output_path = (REPO_ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
    required = bool(args.required or _truthy(os.environ.get("GMS_MCP_REQUIRE_REAL_GAMEMAKER_SMOKE")))
    expected_runtime_version = str(args.expected_runtime_version or "").strip()
    host_platform = _HOST_PLATFORM_NAMES.get(platform.system(), platform.system().strip().lower())
    fixture: Dict[str, Any] = {
        "name": str(args.fixture_name),
        "host_platform": host_platform,
        "expected_runtime_version": expected_runtime_version,
    }
    synthetic_config = _SYNTHETIC_FIXTURES[args.fixture_name]
    source_context = tempfile.TemporaryDirectory(prefix="gms-mcp-synthetic-source-")
    try:
        source_project = Path(source_context.name) / str(synthetic_config["project_name"])
        create_synthetic_project(
            source_project,
            project_name=str(synthetic_config["project_name"]),
            ide_version=str(synthetic_config["ide_version"]),
        )
        validation_error = _validate_source_project(source_project)
        if validation_error:
            return _skip(validation_error, required=required, output_path=output_path, fixture=fixture)
        fixture.update(_source_project_provenance(source_project))

        runtime_report = _runtime_report(source_project, expected_runtime_version)
        if not runtime_report["ok"]:
            return _skip(str(runtime_report["message"]), required=required, output_path=output_path, fixture=fixture)
        runtime_version = str(runtime_report.get("version") or "")
        if expected_runtime_version and not _runtime_version_matches(runtime_version, expected_runtime_version):
            return _fail(
                f"GameMaker runtime version {runtime_version!r} does not match fixture expectation "
                f"{expected_runtime_version!r}.",
                output_path=output_path,
                fixture=fixture,
                runtime=runtime_report,
            )
        if 0 < args.timeout_seconds < _MIN_COMPILE_TIMEOUT_SECONDS:
            return _fail(
                f"Compile timeout must be 0 (default) or at least {_MIN_COMPILE_TIMEOUT_SECONDS} seconds "
                "so platform validation can stop and clean up safely.",
                output_path=output_path,
                fixture=fixture,
                runtime=runtime_report,
            )

        if args.work_root is not None:
            temp_context = None
            work_root = args.work_root
        elif args.keep_workdir:
            temp_context = None
            work_root = Path(tempfile.mkdtemp(prefix="gms-mcp-real-smoke-"))
        else:
            temp_context = tempfile.TemporaryDirectory(prefix="gms-mcp-real-smoke-")
            work_root = Path(temp_context.name)
        work_root.mkdir(parents=True, exist_ok=True)
        project_copy = _copy_project(source_project, work_root)

        previous_env = {
            key: os.environ.get(key)
            for key in (
                "GMS_MCP_POST_MUTATION_VERIFY",
                "GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION",
                "GMS_MCP_POST_MUTATION_PLATFORM",
                "GMS_MCP_POST_MUTATION_RUNTIME",
                "GMS_MCP_POST_MUTATION_VERIFY_TIMEOUT_SECONDS",
                "GMS_MCP_TOOLSETS",
                "GMS_RUNTIME_VERSION",
            )
        }
        os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = "smart"
        os.environ["GMS_MCP_TOOLSETS"] = "all"
        os.environ["GMS_RUNTIME_VERSION"] = runtime_version
        os.environ.pop("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", None)
        if args.platform:
            os.environ["GMS_MCP_POST_MUTATION_PLATFORM"] = args.platform
        if args.runtime:
            os.environ["GMS_MCP_POST_MUTATION_RUNTIME"] = args.runtime
        if args.timeout_seconds > 0:
            os.environ["GMS_MCP_POST_MUTATION_VERIFY_TIMEOUT_SECONDS"] = str(args.timeout_seconds)

        try:
            result = asyncio.run(_run_smoke(project_copy))
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if temp_context and not args.keep_workdir:
                temp_context.cleanup()

        result.setdefault("status", "passed" if result.get("ok") else "failed")
        report = _certification_report(result, fixture=fixture, runtime=runtime_report)
        _write_report(output_path, report)

        if result.get("ok"):
            print("[OK] Real GameMaker smart verification smoke passed.")
            return 0
        print(f"[ERROR] Real GameMaker smart verification smoke failed at {result.get('stage', 'unknown')}.")
        return 1
    finally:
        source_context.cleanup()


def main() -> int:
    args = parse_args()
    if not args.privacy_safe_output:
        return _run(args)

    with open(os.devnull, "w", encoding="utf-8") as sink:
        with redirect_stdout(sink), redirect_stderr(sink):
            result = _run(args)
    if result == 0:
        print("Real GameMaker smoke passed without publishing detailed build output.")
    else:
        print("Real GameMaker smoke failed; detailed vendor output was suppressed for privacy.", file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
