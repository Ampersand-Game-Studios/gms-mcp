"""
Maintenance Audit Module - Phase 1+ Implementation

This module will contain the robust asset analysis system:
- Authoritative JSON graph parsing from .yyp and .yy files
- Naming convention inference for event files and script companions  
- Static string search across all .gml files for dynamic references
- Comprehensive reporting with categorized findings

Phase 0: Scaffolding complete
Phase 1: Reference collection engine (JSON + naming rules)
Phase 2: Static string search enrichment  
Phase 3: Filesystem audit & JSON report generation
"""

# Phase 1 + 2: Reference collection engine with comprehensive analysis
from .reference_collector import ReferenceCollector, collect_project_references, comprehensive_analysis

__all__ = ['ReferenceCollector', 'collect_project_references', 'comprehensive_analysis'] 