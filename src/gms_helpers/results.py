"""Typed result objects for GMS helper operations."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

@dataclass
class OperationResult:
    """Base result for all operations."""
    success: bool
    message: str
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to a dictionary for JSON-RPC/MCP compatibility."""
        return asdict(self)

@dataclass
class AssetResult(OperationResult):
    """Result from asset creation/modification."""
    asset_name: Optional[str] = None
    asset_type: Optional[str] = None
    asset_path: Optional[str] = None

@dataclass
class MaintenanceResult(OperationResult):
    """Result from maintenance operations."""
    issues_found: int = 0
    issues_fixed: int = 0
    details: List[str] = field(default_factory=list)
    
@dataclass
class RunnerResult(OperationResult):
    """Result from compile/run operations."""
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    output_path: Optional[str] = None

@dataclass 
class IntrospectionResult(OperationResult):
    """Result from project introspection."""
    data: Dict[str, Any] = field(default_factory=dict)
