"""Execution policy management for GameMaker MCP tools."""
import os
from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, Optional

class ExecutionMode(Enum):
    """How a tool should be executed."""
    DIRECT = auto()      # In-process (fast, but blocks server and not cancellable)
    SUBPROCESS = auto()  # External process (safer, cancellable, but slower)

@dataclass
class ToolPolicy:
    """Configuration for how a specific tool should run."""
    mode: ExecutionMode
    timeout_seconds: Optional[int] = None

class PolicyManager:
    """Central registry for tool execution policies."""
    
    def __init__(self):
        self._policies: Dict[str, ToolPolicy] = {}
        self._default_mode = self._detect_default_mode()
        self._setup_defaults()

    def _detect_default_mode(self) -> ExecutionMode:
        """Detect the system-wide default mode from environment variables."""
        # Legacy support for GMS_MCP_ENABLE_DIRECT
        if os.environ.get("GMS_MCP_ENABLE_DIRECT", "0").strip().lower() in ("1", "true", "yes", "on"):
            return ExecutionMode.DIRECT
        return ExecutionMode.SUBPROCESS

    def _setup_defaults(self):
        """Set up default policies for known tool categories."""
        # Introspection tools should always be DIRECT (fast)
        introspection_tools = [
            "gm-list-assets", "gm-read-asset", "gm-search-references", 
            "gm-get-asset-graph", "gm-get-project-stats", "gm-project-info",
            "gm-mcp-health"
        ]
        for tool in introspection_tools:
            self.set_policy(tool, ToolPolicy(mode=ExecutionMode.DIRECT))

        # Runner tools should always be SUBPROCESS (resilient/killable)
        runner_tools = ["run-start", "run-compile", "run-stop"]
        for tool in runner_tools:
            self.set_policy(tool, ToolPolicy(mode=ExecutionMode.SUBPROCESS, timeout_seconds=None))

        # Asset/Event creation tools default to DIRECT if global direct is enabled, 
        # but we can force them to DIRECT for speed even if global is SUBPROCESS 
        # (since they are generally safe and fast).
        fast_write_tools = [
            "asset-create-script", "asset-create-object", "asset-create-sprite",
            "workflow-duplicate", "workflow-rename", "workflow-delete",
            "event-add", "event-remove"
        ]
        for tool in fast_write_tools:
            self.set_policy(tool, ToolPolicy(mode=ExecutionMode.DIRECT))

    def set_policy(self, tool_name: str, policy: ToolPolicy):
        """Register or override a policy for a tool."""
        self._policies[tool_name] = policy

    def get_policy(self, tool_name: str) -> ToolPolicy:
        """Get the policy for a tool, falling back to global default."""
        return self._policies.get(tool_name, ToolPolicy(mode=self._default_mode))

# Global instance
policy_manager = PolicyManager()
