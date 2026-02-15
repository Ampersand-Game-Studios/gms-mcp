#!/usr/bin/env python3
"""Generate CI-ready quality reports for gms-mcp.

This script produces:
- documentation-style markdown reports (coverage + MCP validation)
- a machine-readable JSON summary
and is intended to be used by CI to publish artifacts.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Mapping
from xml.etree import ElementTree as ET


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
        "tests_dir": root / args.tests_dir,
        "server_file": root / "src" / "gms_mcp" / "gamemaker_mcp_server.py",
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


def run_quality_suite(paths: Mapping[str, Path], skip_final_verification: bool) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(paths["root"] / "src")
    env["GMS_TEST_SUITE"] = "1"
    if sys.platform == "win32":
        env["PYTHONIOENCODING"] = "utf-8"

    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    gamemaker_dir = ensure_gamemaker_context(paths["root"])

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(paths["tests_dir"]),
        "-q",
        "--junit-xml",
        str(paths["junit_xml"]),
        f"--cov={paths['root'] / 'src'}",
        f"--cov-report=xml:{paths['coverage_xml']}",
        "--maxfail=1",
    ]
    result = run_command(cmd, gamemaker_dir, env)
    if result.returncode != 0:
        return result.returncode

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
    totals = {
        "tests": int(root.attrib.get("tests", "0")),
        "failures": int(root.attrib.get("failures", "0")),
        "errors": int(root.attrib.get("errors", "0")),
        "skipped": int(root.attrib.get("skipped", "0")),
        "time": root.attrib.get("time", "0.0"),
        "suites": len(list(root)) if list(root) else 0,
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


def discover_mcp_tools(server_file: Path) -> List[str]:
    source = server_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    tools: List[str] = []

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
            tools.append(node.name)

    tools.sort()
    return tools


def categorize_tool(name: str) -> str:
    if name in {
        "gm_project_info",
        "gm_mcp_health",
        "gm_cli",
        "gm_diagnostics",
    }:
        return "Project & Health"
    if name.startswith("gm_create_") or name == "gm_asset_delete":
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
    if name.startswith((
        "gm_list_",
        "gm_read_",
        "gm_search_",
        "gm_get_",
    )):
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


def write_coverage_report(coverage: Dict[str, object], junit: Dict[str, object], out_path: Path) -> None:
    failures = int(junit["failures"]) + int(junit["errors"])
    pass_rate = 0.0
    if junit["tests"]:
        pass_rate = (int(junit["passed"]) / int(junit["tests"])) * 100

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
        f"| **Test Failures** | {failures} |",
        f"| **Test Duration** | {float(junit['time']):.2f}s |",
        "",
        "## Coverage Breakdown by Module",
        "",
        "| Module | Coverage | Notes |",
        "| --- | --- | --- |",
    ]

    for entry in coverage["modules"]:
        notes = (
            "" if entry["coverage"] >= 75 else "Low coverage area, likely heavy external integration paths."
        )
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

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_tool_report(
    tools: List[str],
    referenced: List[str],
    junit: Dict[str, object],
    out_path: Path,
) -> None:
    tested = {name: name in referenced for name in tools}
    total = len(tools)
    tested_count = sum(1 for value in tested.values() if value)
    expected_failures = max(0, total - tested_count)

    lines = [
        "# MCP Tool Validation Report",
        "",
        "Generated from test-source references in the repository.",
        "",
        "## Summary",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total MCP Tools | {total} |",
        f"| Tools with Direct Test References | {tested_count} |",
        f"| Untested Tools (by repo scan) | {expected_failures} |",
        f"| Python Tests Run | {junit['tests']} |",
        f"| Tests Passing | {junit['passed']} |",
        f"| Skipped | {junit['skipped']} |",
        "",
        "## Tool Categories",
    ]

    by_category: Dict[str, Dict[str, int]] = {}
    for tool in tools:
        category = categorize_tool(tool)
        bucket = by_category.setdefault(category, {"total": 0, "tested": 0})
        bucket["total"] += 1
        if tested[tool]:
            bucket["tested"] += 1

    for category in sorted(by_category):
        bucket = by_category[category]
        lines.append(f"### {category} ({bucket['tested']}/{bucket['total']} TESTED)")
        if bucket["tested"] == 0:
            lines.append("No direct test references found in the repository for this category.")
        for tool in sorted(tools):
            if categorize_tool(tool) != category:
                continue
            status = "PASS" if tested[tool] else "PENDING"
            lines.append(f"- `{tool}`: {status}")
        lines.append("")

    lines.append("## Notes")
    lines.append("- Coverage is computed from static test-source references and executed pytest results, not from a dedicated MCP test framework.")
    lines.append("- Keep this report as an implementation-time signal; update when coverage tooling changes.")

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
    tools = discover_mcp_tools(paths["server_file"])
    referenced = scan_tool_references(paths["root"] / "cli/tests/python", tools)

    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    write_coverage_report(coverage, junit, paths["coverage_report_md"])
    write_tool_report(tools, referenced, junit, paths["tool_report_md"])

    summary = {
        "generated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "project": "gms-mcp",
        "coverage": coverage,
        "tests": junit,
        "mcp_tools": {
            "total": len(tools),
            "tested_by_reference": len(referenced),
            "untested": len(tools) - len(referenced),
        },
    }
    paths["summary_json"].write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
