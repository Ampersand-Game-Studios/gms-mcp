"""
Diagnostic schema for project-level issues.
Compatible with IDE problem panels and structured reporting.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

@dataclass
class Diagnostic:
    """Represents a structured project issue."""
    severity: str           # "error" | "warning" | "info" | "hint"
    category: str           # "json" | "naming" | "structure" | "reference" | "orphan" | "case"
    file_path: str          # Relative path to the affected file
    message: str            # Human-readable description
    code: Optional[str] = None     # Machine-readable code (e.g., "GM001")
    line: Optional[int] = None     # 1-based line number (if applicable)
    column: Optional[int] = None   # 1-based column (if applicable)
    end_line: Optional[int] = None
    end_column: Optional[int] = None
    source: str = "lint"           # "lint" | "audit" | "path_validation" etc.
    can_auto_fix: bool = False      # Whether gms can fix this automatically
    suggested_fix: Optional[str] = None  # Human-readable fix suggestion

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MCP/JSON output."""
        return asdict(self)

# Diagnostic Code Constants
CODE_JSON_INVALID = "GM001"
CODE_NAMING_VIOLATION = "GM002"
CODE_STRUCTURE_DUPLICATE = "GM003"
CODE_REFERENCE_MISSING = "GM004"
CODE_ORPHAN_FILE = "GM005"
CODE_CASE_MISMATCH = "GM006"
CODE_PROJECT_LOAD_FAIL = "GM000"
