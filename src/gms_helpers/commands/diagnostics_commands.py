"""Diagnostics command implementations."""

from typing import List, Dict, Any, Optional
from pathlib import Path
import argparse

from ..diagnostics import Diagnostic
from ..maintenance.lint import ProjectLinter
from ..maintenance.audit import comprehensive_analysis
from ..maintenance.audit.reference_collector import audit_to_diagnostics


def handle_diagnostics(args) -> Dict[str, Any]:
    """
    Handle project diagnostics command.
    Returns structured results for MCP or JSON reporting.
    """
    project_root = Path(getattr(args, 'project_root', '.')).resolve()
    depth = getattr(args, 'depth', 'quick')
    include_info = getattr(args, 'include_info', False)
    
    diagnostics: List[Diagnostic] = []
    
    # 1. Always run quick lint (it's fast and covers basic JSON/naming)
    linter = ProjectLinter(str(project_root))
    issues = linter.scan_project()
    diagnostics.extend(issue.to_diagnostic() for issue in issues)
    
    # 2. If deep mode, run comprehensive audit
    if depth == 'deep':
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
        diagnostics = [d for d in diagnostics if d.severity != 'info']
    
    # 4. Generate summary
    summary = {'error': 0, 'warning': 0, 'info': 0, 'hint': 0}
    for d in diagnostics:
        summary[d.severity] = summary.get(d.severity, 0) + 1
        
    return {
        "ok": summary['error'] == 0,
        "diagnostics": [d.to_dict() for d in diagnostics],
        "summary": summary,
        "depth": depth,
        "project_root": str(project_root)
    }
