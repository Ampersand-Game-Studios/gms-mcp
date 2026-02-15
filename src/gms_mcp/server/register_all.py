from __future__ import annotations

from typing import Any

from . import resources
from .tools import (
    asset_creation,
    bridge,
    code_intel,
    docs,
    events,
    introspection,
    maintenance,
    project_health,
    rooms,
    runner,
    runtime,
    workflow,
)


def register_all(mcp: Any, Context: Any) -> None:
    project_health.register(mcp, Context)
    asset_creation.register(mcp, Context)
    maintenance.register(mcp, Context)
    runtime.register(mcp, Context)
    runner.register(mcp, Context)
    bridge.register(mcp, Context)
    events.register(mcp, Context)
    workflow.register(mcp, Context)
    rooms.register(mcp, Context)
    introspection.register(mcp, Context)
    code_intel.register(mcp, Context)
    docs.register(mcp, Context)
    resources.register(mcp)

