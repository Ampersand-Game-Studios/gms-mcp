#!/usr/bin/env python3
"""Generate CI-ready quality reports for gms-mcp.

This script produces:
- documentation-style markdown reports (coverage + MCP validation)
- a machine-readable JSON summary
and is intended to be used by CI to publish artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Mapping
from xml.etree import ElementTree as ET


DEFAULT_MIN_OVERALL_COVERAGE = 85.0
DEFAULT_MIN_MODULE_COVERAGE = 50.0


def _parse_int_attr(node: ET.Element, name: str) -> int:
    value = node.attrib.get(name, "0")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_float_attr(node: ET.Element, name: str) -> float:
    value = node.attrib.get(name, "0")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_setting(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _split_csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate coverage + MCP validation artifacts")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current working directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build") / "reports",
        help="Where report artifacts are written",
    )
    parser.add_argument(
        "--junit-xml",
        type=Path,
        default=None,
        help="Optional explicit junit xml output path",
    )
    parser.add_argument(
        "--coverage-xml",
        type=Path,
        default=None,
        help="Optional explicit coverage xml output path",
    )
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=Path("cli/tests/python"),
        help="Test directory to execute",
    )
    parser.add_argument(
        "--skip-test-run",
        action="store_true",
        help="Skip test execution and use existing artifact files",
    )
    parser.add_argument(
        "--no-final-verification",
        action="store_true",
        help="Do not run test_final_verification.py",
    )
    parser.add_argument(
        "--min-overall-coverage",
        type=float,
        default=_float_setting("GMS_MCP_MIN_OVERALL_COVERAGE", DEFAULT_MIN_OVERALL_COVERAGE),
        help="Minimum overall statement coverage percentage.",
    )
    parser.add_argument(
        "--min-module-coverage",
        type=float,
        default=_float_setting("GMS_MCP_MIN_MODULE_COVERAGE", DEFAULT_MIN_MODULE_COVERAGE),
        help="Minimum per-module statement coverage percentage.",
    )
    parser.add_argument(
        "--coverage-gate-exclude",
        action="append",
        default=_split_csv(os.environ.get("GMS_MCP_COVERAGE_GATE_EXCLUDE")),
        help="Module path or fnmatch pattern to exclude from per-module coverage gates. Repeatable.",
    )
    return parser.parse_args()


def project_paths(args: argparse.Namespace) -> Mapping[str, Path]:
    root = args.project_root
    output_dir = root / args.output_dir
    junit_xml = args.junit_xml or (output_dir / "pytest_results.xml")
    coverage_xml = args.coverage_xml or (output_dir / "coverage.xml")
    return {
        "root": root,
        "output_dir": output_dir,
        "junit_xml": junit_xml,
        "coverage_xml": coverage_xml,
        "cov_config": root / "pyproject.toml",
        "tests_dir": root / args.tests_dir,
        "gamemaker_dir": root / "gamemaker",
        "server_sources_dir": root / "src" / "gms_mcp" / "server",
        "coverage_report_md": output_dir / "TEST_COVERAGE_REPORT.md",
        "tool_report_md": output_dir / "MCP_TOOL_VALIDATION_REPORT.md",
        "summary_json": output_dir / "quality_summary.json",
    }


def run_command(cmd: List[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    print(f"[RUN] {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=dict(env),
        text=True,
        capture_output=False,
    )


def ensure_gamemaker_context(project_root: Path) -> Path:
    gamemaker_dir = project_root / "gamemaker"
    gamemaker_dir.mkdir(parents=True, exist_ok=True)
    if not any(gamemaker_dir.glob("*.yyp")):
        (gamemaker_dir / "minimal.yyp").write_text('{"resources":[], "MetaData":{"name":"minimal"}}', encoding="utf-8")
    return gamemaker_dir


def cleanup_coverage_data(paths: Mapping[str, Path]) -> None:
    for directory in (paths["root"], paths["gamemaker_dir"]):
        for candidate in directory.glob(".coverage*"):
            if candidate.is_file():
                candidate.unlink()


def has_parallel_coverage_data(paths: Mapping[str, Path]) -> bool:
    for directory in (paths["root"], paths["gamemaker_dir"]):
        for candidate in directory.glob(".coverage*"):
            if candidate.is_file() and candidate.name != ".coverage":
                return True
    return False


def write_coverage_xml(paths: Mapping[str, Path], env: Mapping[str, str]) -> int:
    if has_parallel_coverage_data(paths):
        combine_cmd = [
            sys.executable,
            "-m",
            "coverage",
            "combine",
            "--rcfile",
            str(paths["cov_config"]),
            str(paths["root"]),
            str(paths["gamemaker_dir"]),
        ]
        result = run_command(combine_cmd, paths["root"], env)
        if result.returncode != 0:
            return result.returncode

    if not (paths["root"] / ".coverage").exists():
        print("[ERROR] Coverage data file was not generated.")
        return 1

    xml_cmd = [
        sys.executable,
        "-m",
        "coverage",
        "xml",
        "--rcfile",
        str(paths["cov_config"]),
        "-o",
        str(paths["coverage_xml"]),
    ]
    result = run_command(xml_cmd, paths["root"], env)
    return result.returncode


def run_quality_suite(paths: Mapping[str, Path], skip_final_verification: bool) -> int:
    env = os.environ.copy()
    pythonpath_entries = [str(paths["root"]), str(paths["root"] / "src")]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    env["GMS_TEST_SUITE"] = "1"
    env["COVERAGE_FILE"] = str(paths["root"] / ".coverage")
    if sys.platform == "win32":
        env["PYTHONIOENCODING"] = "utf-8"

    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    gamemaker_dir = ensure_gamemaker_context(paths["root"])
    cleanup_coverage_data(paths)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(paths["tests_dir"]),
        "-q",
        "--junit-xml",
        str(paths["junit_xml"]),
        f"--cov={paths['root'] / 'src'}",
        "--cov-config",
        str(paths["cov_config"]),
        "--cov-report=",
        "--maxfail=1",
    ]
    result = run_command(cmd, gamemaker_dir, env)
    if result.returncode != 0:
        return result.returncode

    coverage_status = write_coverage_xml(paths, env)
    if coverage_status != 0:
        return coverage_status

    final_verification = paths["root"] / "cli/tests/python/test_final_verification.py"
    if final_verification.exists() and not skip_final_verification:
        result = run_command(
            [sys.executable, "-m", "pytest", str(final_verification), "-q"],
            gamemaker_dir,
            env,
        )
        if result.returncode != 0:
            return result.returncode

    return 0


def parse_junit(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {
            "tests": 0,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "passed": 0,
            "time": "0.0",
            "suites": 0,
        }

    root = ET.parse(path).getroot()
    suites = []
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))

    if suites:
        totals = {
            "tests": sum(_parse_int_attr(suite, "tests") for suite in suites),
            "failures": sum(_parse_int_attr(suite, "failures") for suite in suites),
            "errors": sum(_parse_int_attr(suite, "errors") for suite in suites),
            "skipped": sum(_parse_int_attr(suite, "skipped") for suite in suites),
            "time": f"{sum(_parse_float_attr(suite, 'time') for suite in suites):.3f}",
            "suites": len(suites),
        }
    else:
        totals = {
            "tests": _parse_int_attr(root, "tests"),
            "failures": _parse_int_attr(root, "failures"),
            "errors": _parse_int_attr(root, "errors"),
            "skipped": _parse_int_attr(root, "skipped"),
            "time": f"{_parse_float_attr(root, 'time'):.3f}",
            "suites": 1 if root.tag == "testsuite" else len(list(root)),
        }

    totals["passed"] = max(0, totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"])
    return totals


def parse_coverage(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {
            "overall": 0.0,
            "modules": [],
            "timestamp": "",
        }

    root = ET.parse(path).getroot()
    overall = float(root.attrib.get("line-rate", "0") or 0) * 100
    modules = []

    module_coverage: Dict[str, Dict[str, float]] = {}
    for package in root.findall("packages/package"):
        for class_elem in package.findall("classes/class"):
            filename = class_elem.attrib.get("filename", "")
            if not filename:
                continue
            line_rate = float(class_elem.attrib.get("line-rate", "0") or 0)
            branch_rate = float(class_elem.attrib.get("branch-rate", "0") or 0)
            module_name = filename.replace("src/", "")
            existing = module_coverage.get(module_name)
            next_module = {
                "coverage": round(line_rate * 100, 2),
                "branch_coverage": round(branch_rate * 100, 2),
            }
            if existing is None or existing["coverage"] < next_module["coverage"]:
                module_coverage[module_name] = next_module

    modules = [
        {
            "module": module_name,
            "coverage": values["coverage"],
            "branch_coverage": values["branch_coverage"],
        }
        for module_name, values in module_coverage.items()
    ]
    modules.sort(key=lambda item: item["module"].lower())
    return {"overall": round(overall, 2), "modules": modules}


def _is_module_excluded(module_name: str, patterns: List[str]) -> bool:
    return any(module_name == pattern or fnmatch.fnmatch(module_name, pattern) for pattern in patterns)


def evaluate_coverage_gates(
    coverage: Dict[str, object],
    *,
    min_overall: float,
    min_module: float,
    exclude_modules: List[str],
) -> Dict[str, object]:
    modules = coverage.get("modules", [])
    failures: List[Dict[str, object]] = []
    excluded: List[str] = []

    overall = float(coverage.get("overall", 0.0))
    if overall < min_overall:
        failures.append(
            {
                "scope": "overall",
                "coverage": round(overall, 2),
                "minimum": round(min_overall, 2),
            }
        )

    for entry in modules if isinstance(modules, list) else []:
        if not isinstance(entry, dict):
            continue
        module_name = str(entry.get("module", ""))
        if not module_name:
            continue
        if _is_module_excluded(module_name, exclude_modules):
            excluded.append(module_name)
            continue
        module_coverage = float(entry.get("coverage", 0.0))
        if module_coverage < min_module:
            failures.append(
                {
                    "scope": "module",
                    "module": module_name,
                    "coverage": round(module_coverage, 2),
                    "minimum": round(min_module, 2),
                }
            )

    return {
        "ok": not failures,
        "min_overall": round(min_overall, 2),
        "min_module": round(min_module, 2),
        "excluded_modules": sorted(excluded),
        "failures": failures,
    }


def discover_mcp_tools(server_sources_dir: Path) -> List[str]:
    tools: set[str] = set()

    for path in sorted(server_sources_dir.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue

        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            has_tool = False
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    decorator = decorator.func
                if isinstance(decorator, ast.Attribute) and decorator.attr == "tool":
                    has_tool = True
                elif isinstance(decorator, ast.Name) and decorator.id == "tool":
                    has_tool = True
            if has_tool and node.name.startswith("gm_"):
                tools.add(node.name)

    return sorted(tools)


def categorize_tool(name: str) -> str:
    if name in {
        "gm_project_info",
        "gm_mcp_health",
        "gm_diagnostics",
    }:
        return "Project & Health"
    if name.startswith("gm_create_"):
        return "Asset Creation"
    if name.startswith("gm_maintenance_"):
        return "Maintenance"
    if name.startswith("gm_runtime_"):
        return "Runtime Management"
    if name.startswith("gm_compile") or name.startswith("gm_run"):
        return "Runner"
    if name in {
        "gm_build_index",
        "gm_find_definition",
        "gm_find_references",
        "gm_list_symbols",
    }:
        return "Code Intelligence"
    if name.startswith("gm_bridge_"):
        return "Bridge"
    if name.startswith("gm_event_"):
        return "Event Management"
    if name.startswith("gm_workflow_"):
        return "Workflow"
    if name.startswith("gm_room_"):
        return "Room Management"
    if name.startswith(
        (
            "gm_list_",
            "gm_read_",
            "gm_search_",
            "gm_get_",
        )
    ):
        return "Introspection"
    return "Other"


def scan_tool_references(tests_dir: Path, tools: List[str]) -> List[str]:
    referenced: List[str] = []
    if not tests_dir.exists():
        return referenced

    tests_text = []
    for path in sorted(tests_dir.glob("test_*.py")):
        try:
            tests_text.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue

    full_text = "\n".join(tests_text)
    for tool in tools:
        if re.search(rf"\b{re.escape(tool)}\b", full_text):
            referenced.append(tool)
    return referenced


def discover_registered_mcp_tools(profile: str) -> List[object]:
    from gms_mcp.gamemaker_mcp_server import build_server

    previous_toolsets = os.environ.get("GMS_MCP_TOOLSETS")
    previous_project_root = os.environ.get("GM_PROJECT_ROOT")
    with tempfile.TemporaryDirectory(prefix="gms-mcp-quality-project-") as temp_dir:
        project_root = Path(temp_dir)
        (project_root / "quality_report.yyp").write_text('{"resources":[]}', encoding="utf-8")
        os.environ["GMS_MCP_TOOLSETS"] = profile
        os.environ["GM_PROJECT_ROOT"] = str(project_root)
        try:
            return list(asyncio.run(build_server().list_tools()))
        finally:
            if previous_toolsets is None:
                os.environ.pop("GMS_MCP_TOOLSETS", None)
            else:
                os.environ["GMS_MCP_TOOLSETS"] = previous_toolsets
            if previous_project_root is None:
                os.environ.pop("GM_PROJECT_ROOT", None)
            else:
                os.environ["GM_PROJECT_ROOT"] = previous_project_root


def parse_mcp_smoke(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"status": "not_run", "selected": 0, "executed": 0, "passed": 0, "failed": 0, "tools": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "invalid", "selected": 0, "executed": 0, "passed": 0, "failed": 0, "tools": []}

    records = payload.get("records") or payload.get("results") or []
    if not isinstance(records, list):
        records = []
    selected = payload.get("selected_tools") or []
    selected_count = len(selected) if isinstance(selected, list) else 0
    passed = sum(1 for record in records if isinstance(record, dict) and bool(record.get("ok")))
    failed = sum(1 for record in records if isinstance(record, dict) and not bool(record.get("ok")))
    tools = [str(record.get("tool")) for record in records if isinstance(record, dict) and record.get("tool")]
    return {
        "status": "passed" if records and failed == 0 else "failed" if failed else "empty",
        "selected": selected_count,
        "executed": len(records),
        "passed": passed,
        "failed": failed,
        "tools": tools,
    }


def write_coverage_report(
    coverage: Dict[str, object],
    junit: Dict[str, object],
    gate: Dict[str, object],
    out_path: Path,
) -> None:
    failures = int(junit["failures"]) + int(junit["errors"])
    pass_rate = 0.0
    if junit["tests"]:
        pass_rate = (int(junit["passed"]) / int(junit["tests"])) * 100
    gate_ok = bool(gate.get("ok"))
    min_overall = float(gate.get("min_overall", 0.0))
    min_module = float(gate.get("min_module", 0.0))

    lines = [
        "# Test Coverage Report",
        f"Date: generated at build time",
        "Project: gms-mcp",
        "",
        "## Summary",
        "| Metric | Value |",
        "| --- | --- |",
        f"| **Total Tests** | {junit['tests']} |",
        f"| **Pass Rate** | {pass_rate:.1f}% |",
        f"| **Overall Statement Coverage** | {coverage['overall']:.1f}% |",
        f"| **Minimum Overall Coverage** | {min_overall:.1f}% |",
        f"| **Minimum Module Coverage** | {min_module:.1f}% |",
        f"| **Coverage Gate** | {'PASS' if gate_ok else 'FAIL'} |",
        f"| **Test Failures** | {failures} |",
        f"| **Test Duration** | {float(junit['time']):.2f}s |",
        "",
        "## Coverage Breakdown by Module",
        "",
        "| Module | Coverage | Notes |",
        "| --- | --- | --- |",
    ]

    for entry in coverage["modules"]:
        notes = "" if entry["coverage"] >= 75 else "Low coverage area, likely heavy external integration paths."
        lines.append(f"| `{entry['module']}` | {entry['coverage']:.1f}% | {notes} |")

    lines.append("")
    lines.append("## Coverage Recommendations")
    low = [entry for entry in coverage["modules"] if float(entry["coverage"]) < 50.0]
    if low:
        lines.append("Low coverage modules:")
        for entry in low:
            lines.append(f"- `{entry['module']}` ({entry['coverage']:.1f}%)")
    else:
        lines.append("No modules currently below 50% coverage.")

    gate_failures = gate.get("failures", [])
    lines.append("")
    lines.append("## Coverage Gate")
    if isinstance(gate_failures, list) and gate_failures:
        lines.append("Gate failures:")
        for failure in gate_failures:
            if not isinstance(failure, dict):
                continue
            coverage_value = float(failure.get("coverage", 0.0))
            minimum_value = float(failure.get("minimum", 0.0))
            if failure.get("scope") == "overall":
                lines.append(f"- Overall coverage {coverage_value:.1f}% is below {minimum_value:.1f}%.")
            else:
                module_name = str(failure.get("module", "unknown"))
                lines.append(f"- `{module_name}` coverage {coverage_value:.1f}% is below {minimum_value:.1f}%.")
    else:
        lines.append("Coverage gates passed.")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_tool_report(
    tools: List[str],
    referenced: List[str],
    core_tools: List[str],
    registered_tools: List[str],
    smoke: Dict[str, object],
    junit: Dict[str, object],
    out_path: Path,
) -> None:
    referenced_map = {name: name in referenced for name in tools}
    total = len(tools)
    referenced_count = sum(1 for value in referenced_map.values() if value)

    lines = [
        "# MCP Tool Validation Report",
        "",
        "Generated from runtime tool registration, dedicated MCP smoke execution, and a static test-source scan.",
        "",
        "## Summary",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Curated Core Tools Registered | {len(core_tools)} |",
        f"| All-Profile Tools Registered | {len(registered_tools)} |",
        f"| MCP Tools Found in Source | {total} |",
        f"| MCP Tools Executed by Dedicated Smoke | {smoke['executed']} |",
        f"| Dedicated Smoke Calls Passing | {smoke['passed']} |",
        f"| Dedicated Smoke Calls Failing | {smoke['failed']} |",
        f"| Tool Names Referenced in Test Source | {referenced_count} |",
        f"| Python Tests Run | {junit['tests']} |",
        f"| Tests Passing | {junit['passed']} |",
        f"| Skipped | {junit['skipped']} |",
        "",
        "## Tool Categories",
    ]

    by_category: Dict[str, Dict[str, int]] = {}
    for tool in tools:
        category = categorize_tool(tool)
        bucket = by_category.setdefault(category, {"total": 0, "referenced": 0})
        bucket["total"] += 1
        if referenced_map[tool]:
            bucket["referenced"] += 1

    for category in sorted(by_category):
        bucket = by_category[category]
        lines.append(f"### {category} ({bucket['referenced']}/{bucket['total']} REFERENCED)")
        if bucket["referenced"] == 0:
            lines.append("No test-source references found in the repository for this category.")
        for tool in sorted(tools):
            if categorize_tool(tool) != category:
                continue
            status = "REFERENCED" if referenced_map[tool] else "NO REFERENCE"
            lines.append(f"- `{tool}`: {status}")
        lines.append("")

    lines.append("## Notes")
    lines.append(
        "- Dedicated smoke counts are executed MCP calls; static references are never labelled as passing tests."
    )
    lines.append("- Pytest totals show suite breadth but do not imply every MCP tool received a behavioral call.")
    lines.append(
        "- Source and all-profile registration counts must match; CI fails if a decorated tool is not registered."
    )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    paths = project_paths(args)

    if not args.skip_test_run:
        status = run_quality_suite(paths, args.no_final_verification)
        if status != 0:
            return status

    junit = parse_junit(paths["junit_xml"])
    coverage = parse_coverage(paths["coverage_xml"])
    gate = evaluate_coverage_gates(
        coverage,
        min_overall=args.min_overall_coverage,
        min_module=args.min_module_coverage,
        exclude_modules=args.coverage_gate_exclude,
    )
    tools = discover_mcp_tools(paths["server_sources_dir"])
    referenced = scan_tool_references(paths["root"] / "cli/tests/python", tools)
    core_specs = discover_registered_mcp_tools("core")
    all_specs = discover_registered_mcp_tools("all")
    core_tools = sorted(str(getattr(spec, "name", "")) for spec in core_specs if getattr(spec, "name", ""))
    registered_tools = sorted(str(getattr(spec, "name", "")) for spec in all_specs if getattr(spec, "name", ""))
    smoke = parse_mcp_smoke(paths["output_dir"] / "mcp_tool_smoke_report.json")

    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    write_coverage_report(coverage, junit, gate, paths["coverage_report_md"])
    write_tool_report(tools, referenced, core_tools, registered_tools, smoke, junit, paths["tool_report_md"])

    summary = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "project": "gms-mcp",
        "coverage": coverage,
        "coverage_gate": gate,
        "tests": junit,
        "mcp_tools": {
            "source_total": len(tools),
            "core_registered": len(core_tools),
            "all_registered": len(registered_tools),
            "referenced_in_test_source": len(referenced),
            "dedicated_smoke": smoke,
        },
    }
    paths["summary_json"].write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if tools != registered_tools:
        print("[ERROR] Runtime all-profile registration does not match decorated MCP tool source.")
        print(f"[ERROR] Source-only: {sorted(set(tools) - set(registered_tools))}")
        print(f"[ERROR] Registration-only: {sorted(set(registered_tools) - set(tools))}")
        return 1
    if not bool(gate.get("ok")):
        print("[ERROR] Coverage gate failed.")
        gate_failures = gate.get("failures", [])
        for failure in gate_failures if isinstance(gate_failures, list) else []:
            if not isinstance(failure, dict):
                continue
            coverage_value = float(failure.get("coverage", 0.0))
            minimum_value = float(failure.get("minimum", 0.0))
            if failure.get("scope") == "overall":
                print(f"[ERROR] Overall coverage {coverage_value:.1f}% is below {minimum_value:.1f}%.")
            else:
                module_name = str(failure.get("module", "unknown"))
                print(f"[ERROR] {module_name} coverage {coverage_value:.1f}% is below {minimum_value:.1f}%.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
