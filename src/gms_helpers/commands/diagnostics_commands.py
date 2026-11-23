"""Diagnostics command implementations."""

from typing import List, Dict, Any
from pathlib import Path, PurePosixPath

from ..diagnostics import Diagnostic
from ..maintenance.lint import ProjectLinter
from ..maintenance.audit import comprehensive_analysis
from ..maintenance.audit.reference_collector import audit_to_diagnostics


_MAX_PRINTED_DIAGNOSTICS = 40


def _shown_path(file_path: str, project_root: Path) -> str:
    """Name a file the way the other tools do: relative to the project, with forward slashes."""
    try:
        return Path(file_path).resolve().relative_to(project_root).as_posix()
    except (OSError, ValueError):
        return file_path


def handle_diagnostics(args) -> Dict[str, Any]:
    """
    Handle project diagnostics command.
    Returns structured results for MCP or JSON reporting.
    """
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    depth = getattr(args, "depth", "quick")
    include_info = getattr(args, "include_info", False)

    diagnostics: List[Diagnostic] = []

    # 1. Always run quick lint (it's fast and covers basic JSON/naming)
    linter = ProjectLinter(str(project_root))
    issues = linter.scan_project()
    diagnostics.extend(issue.to_diagnostic() for issue in issues)

    # 2. If deep mode, run comprehensive audit
    if depth == "deep":
        analysis_results = comprehensive_analysis(str(project_root))
        audit_diagnostics = audit_to_diagnostics(analysis_results)

        # Avoid duplicate diagnostics if both lint and audit find the same thing
        # (though usually audit finds orphans/case while lint finds JSON/naming)
        seen_keys = {(d.file_path, d.code, d.message) for d in diagnostics}
        for d in audit_diagnostics:
            key = (d.file_path, d.code, d.message)
            if key not in seen_keys:
                diagnostics.append(d)
                seen_keys.add(key)

    # 3. Filter by severity if requested
    if not include_info:
        diagnostics = [d for d in diagnostics if d.severity != "info"]

    # 4. Generate summary
    summary = {"error": 0, "warning": 0, "info": 0, "hint": 0}
    for d in diagnostics:
        summary[d.severity] = summary.get(d.severity, 0) + 1

    # The command runs in its own process when a tool calls it, where only printed lines reach
    # the caller. Printing nothing left "no problems" and "the check did not run" looking alike.
    counted = ", ".join(f"{count} {severity}(s)" for severity, count in summary.items() if count)
    if not diagnostics:
        print(f"[OK] No problems found ({depth} check).")
    else:
        print(f"[DIAGNOSTICS] {counted} ({depth} check):")
        for d in diagnostics[:_MAX_PRINTED_DIAGNOSTICS]:
            shown = _shown_path(d.file_path, project_root)
            location = f"{shown}:{d.line}" if d.line else shown
            code = f" {d.code}" if d.code else ""
            fix = f" Fix: {d.suggested_fix}" if d.suggested_fix else ""
            print(f"  {d.severity}{code}  {location}  {d.message}{fix}")
        if len(diagnostics) > _MAX_PRINTED_DIAGNOSTICS:
            print(f"  ... and {len(diagnostics) - _MAX_PRINTED_DIAGNOSTICS} more.")
    if depth != "deep":
        print('[INFO] Quick check only (JSON and naming). Use depth="deep" for references and orphans.')

    return {
        "ok": summary["error"] == 0,
        "diagnostics": [d.to_dict() for d in diagnostics],
        "summary": summary,
        "depth": depth,
        "project_root": str(project_root),
    }


def _template(text: str | None, name: str) -> str | None:
    """Write the asset's own name in a message as {name}, so one message describes many assets."""
    if not text or len(name) < 3:
        return text
    return text.replace(name, "{name}")


def dense_diagnostics(report: Dict[str, Any]) -> Dict[str, Any]:
    """Group a diagnostics report by problem: each message once, with every file it applies to.

    In a message, ``{name}`` stands for the file's own name. ``assets`` maps a folder to asset
    names whose files are ``<folder>/<name>/<name>.yy``; ``files`` maps a folder to the names of any
    other files in it, with ``:line`` when the problem has a line.
    """
    from ..dense import asset_folders, by_folder

    project_root = Path(str(report.get("project_root") or "."))
    groups: Dict[tuple, Dict[str, Any]] = {}
    for item in report.get("diagnostics", []):
        shown = _shown_path(str(item.get("file_path") or ""), project_root)
        name = PurePosixPath(shown).stem
        message = _template(item.get("message"), name)
        fix = _template(item.get("suggested_fix"), name)
        located = bool(item.get("line"))
        key = (
            item.get("severity"),
            item.get("code"),
            item.get("category"),
            item.get("source"),
            bool(item.get("can_auto_fix")),
            message,
            fix,
        )
        group = groups.get(key)
        if group is None:
            group = {"severity": item.get("severity"), "code": item.get("code"), "category": item.get("category")}
            if item.get("source") not in (None, "lint"):
                group["source"] = item.get("source")
            group["message"] = message
            if fix:
                group["fix"] = fix
            if item.get("can_auto_fix"):
                group["can_auto_fix"] = True
            group["_paths"] = []
            groups[key] = group
        location = shown
        if located:
            location = f"{shown}:{item['line']}"
            if item.get("column"):
                location += f":{item['column']}"
        group["_paths"].append(location)
    issues = []
    for group in groups.values():
        paths = group.pop("_paths")
        assets, files = asset_folders(paths)
        if assets:
            group["assets"] = assets
        if files:
            group["files"] = by_folder(files)
        issues.append({key: value for key, value in group.items() if value is not None})
    summary = {severity: count for severity, count in (report.get("summary") or {}).items() if count}
    return {"ok": report.get("ok", True), "depth": report.get("depth"), "summary": summary, "issues": issues}
