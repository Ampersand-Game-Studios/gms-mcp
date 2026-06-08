#!/usr/bin/env python3
"""Run a real GameMaker compile smoke for smart mutation verification."""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.runtime_manager import RuntimeManager
from gms_helpers.transactions import validate_project_after_mutation
from gms_mcp.gamemaker_mcp_server import build_server


_TRUE_VALUES = {"1", "true", "yes", "on"}
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


def _find_default_project() -> Path | None:
    configured = os.environ.get("GMS_MCP_REAL_SMOKE_PROJECT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return None


def _validate_source_project(project_root: Path) -> str | None:
    if not project_root.exists() or not project_root.is_dir():
        return f"GameMaker smoke project not found: {project_root}"
    yyp_files = sorted(project_root.glob("*.yyp"))
    if not yyp_files:
        return f"GameMaker smoke project has no .yyp file: {project_root}"
    if len(yyp_files) > 1:
        return f"GameMaker smoke project must contain exactly one .yyp file: {project_root}"
    validation = validate_project_after_mutation(project_root)
    if not validation.success:
        first_error = validation.errors[0] if validation.errors else "unknown validation error"
        return f"GameMaker smoke project failed preflight validation: {first_error}"
    return None


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _COPY_IGNORE}


def _copy_project(source: Path, work_root: Path) -> Path:
    destination = work_root / "real-gamemaker-smoke-project"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=_copy_ignore)
    return destination


def _runtime_report(project_root: Path) -> Dict[str, Any]:
    runtime = RuntimeManager(project_root).select()
    if not runtime:
        return {
            "ok": False,
            "message": "No GameMaker runtime discovered.",
        }
    return {
        "ok": bool(runtime.is_valid),
        "version": runtime.version,
        "channel": getattr(runtime, "release_channel", getattr(runtime, "channel", "unknown")),
        "path": runtime.path,
        "igor_path": runtime.igor_path,
        "message": "GameMaker runtime discovered." if runtime.is_valid else "GameMaker runtime exists but Igor is missing.",
    }


def _runtime_version_matches(version: str, expected: str) -> bool:
    if not expected:
        return True
    return version == expected or version.startswith(expected) or fnmatch.fnmatch(version, expected)


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
        return {"ok": False, "stage": "gm_create_sprite", "result": create_sprite}

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

    flush = await call_tool("gm_verification_flush", {"project_root": str(project_root)})
    if not flush.get("ok") or not flush.get("compiled"):
        return {"ok": False, "stage": "gm_verification_flush", "result": flush}

    return {
        "ok": True,
        "status": "passed",
        "project_root": str(project_root),
        "checks": {
            "high_risk_mutation_compiled": True,
            "batchable_mutation_deferred": True,
            "deferred_batch_flushed": True,
        },
        "results": {
            "gm_create_sprite": create_sprite,
            "gm_sprite_add_frame": add_frame,
            "gm_verification_flush": flush,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real GameMaker smart verification smoke test.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Source GameMaker project to copy before running the smoke. Defaults to GMS_MCP_REAL_SMOKE_PROJECT.",
    )
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
    parser.add_argument("--required", action="store_true", help="Fail instead of skipping when prerequisites are absent.")
    parser.add_argument(
        "--fixture-name",
        default=os.environ.get("GMS_MCP_REAL_SMOKE_FIXTURE_NAME", "default"),
        help="Human-readable fixture name to include in the JSON report.",
    )
    parser.add_argument(
        "--expected-runtime-version",
        default=os.environ.get("GMS_MCP_REAL_SMOKE_EXPECTED_RUNTIME", ""),
        help="Required GameMaker runtime version or fnmatch pattern for this fixture.",
    )
    parser.add_argument("--platform", default="", help="Optional GameMaker platform override for compile verification.")
    parser.add_argument("--runtime", default="", help="Optional GameMaker runtime override for compile verification.")
    parser.add_argument("--timeout-seconds", type=int, default=0, help="Optional compile timeout override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = (REPO_ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
    required = bool(args.required or _truthy(os.environ.get("GMS_MCP_REQUIRE_REAL_GAMEMAKER_SMOKE")))
    expected_runtime_version = str(args.expected_runtime_version or "").strip()
    fixture: Dict[str, Any] = {
        "name": str(args.fixture_name or "default"),
        "expected_runtime_version": expected_runtime_version,
    }

    source_project = args.project_root or _find_default_project()
    if source_project is None:
        return _skip(
            "No real GameMaker smoke project configured. Set GMS_MCP_REAL_SMOKE_PROJECT or pass --project-root.",
            required=required,
            output_path=output_path,
            fixture=fixture,
        )

    source_project = source_project.resolve()
    fixture["source_project"] = str(source_project)
    validation_error = _validate_source_project(source_project)
    if validation_error:
        return _skip(validation_error, required=required, output_path=output_path, fixture=fixture)

    runtime_report = _runtime_report(source_project)
    if not runtime_report["ok"]:
        return _skip(str(runtime_report["message"]), required=required, output_path=output_path, fixture=fixture)
    runtime_version = str(runtime_report.get("version") or "")
    if expected_runtime_version and not _runtime_version_matches(runtime_version, expected_runtime_version):
        return _fail(
            f"GameMaker runtime version {runtime_version!r} does not match fixture expectation {expected_runtime_version!r}.",
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

    previous_env = {key: os.environ.get(key) for key in (
        "GMS_MCP_POST_MUTATION_VERIFY",
        "GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION",
        "GMS_MCP_POST_MUTATION_PLATFORM",
        "GMS_MCP_POST_MUTATION_RUNTIME",
        "GMS_MCP_POST_MUTATION_VERIFY_TIMEOUT_SECONDS",
    )}
    os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = "smart"
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

    result.setdefault("runtime", runtime_report)
    result.setdefault("source_project", str(source_project))
    result.setdefault("fixture", fixture)
    if args.keep_workdir or args.work_root is not None:
        result["work_project"] = str(project_copy)

    _write_report(output_path, result)

    if result.get("ok"):
        print("[OK] Real GameMaker smart verification smoke passed.")
        return 0
    print(f"[ERROR] Real GameMaker smart verification smoke failed at {result.get('stage', 'unknown')}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
