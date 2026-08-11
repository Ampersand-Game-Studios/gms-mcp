"""MCP 2026 runtime services shared by the GameMaker server boundary."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from anyio import to_thread
from mcp.server import CacheHint
from mcp.server.caching import CacheableMethod
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.subscriptions import InMemorySubscriptionBus, ResourceUpdated

from .project import ProjectAccessPolicy
from .resolution import ResolutionRuntime


PROJECT_INDEX_URI = "gms://project/index"
ASSET_GRAPH_URI = "gms://project/asset-graph"

MCP_CACHE_HINTS: Mapping[CacheableMethod, CacheHint] = {
    "server/discover": CacheHint(ttl_ms=300_000, scope="public"),
    "tools/list": CacheHint(ttl_ms=300_000, scope="public"),
    "resources/list": CacheHint(ttl_ms=300_000, scope="public"),
    "resources/templates/list": CacheHint(ttl_ms=300_000, scope="public"),
    "prompts/list": CacheHint(ttl_ms=300_000, scope="public"),
    # Project resources are authorization-context-specific and may change on disk.
    "resources/read": CacheHint(ttl_ms=1_000, scope="private"),
}

_WATCHED_SUFFIXES = frozenset(
    {
        ".fnt",
        ".fsh",
        ".gml",
        ".jpeg",
        ".jpg",
        ".json",
        ".mp3",
        ".ogg",
        ".png",
        ".txt",
        ".vsh",
        ".wav",
        ".yy",
        ".yyp",
    }
)
_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".gms-backups",
        ".gms-mcp",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
)

ProjectSnapshot = tuple[tuple[str, int, int], ...]


def _snapshot_project(project_root: Path) -> ProjectSnapshot:
    """Return a stable, inexpensive signature of MCP-visible project files."""
    entries: list[tuple[str, int, int]] = []
    for directory, directory_names, file_names in os.walk(project_root, followlinks=False):
        directory_names[:] = sorted(name for name in directory_names if name not in _IGNORED_DIRECTORY_NAMES)
        base = Path(directory)
        for file_name in sorted(file_names):
            path = base / file_name
            if path.suffix.lower() not in _WATCHED_SUFFIXES:
                continue
            try:
                stat = path.stat(follow_symlinks=False)
                relative = path.relative_to(project_root).as_posix()
            except (FileNotFoundError, OSError, ValueError):
                continue
            entries.append((relative, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


class MCPV2Runtime:
    """Own project change delivery and mutation concurrency for one server."""

    def __init__(
        self,
        project_access_policy: ProjectAccessPolicy,
        *,
        poll_seconds: float = 0.5,
        debounce_seconds: float = 0.2,
    ) -> None:
        self.project_access_policy = project_access_policy
        self.project_root = project_access_policy.project_root
        self.resolution = ResolutionRuntime(project_access_policy)
        self.subscriptions = InMemorySubscriptionBus()
        self.poll_seconds = poll_seconds
        self.debounce_seconds = debounce_seconds
        self.mutation_lock = anyio.Lock()
        self._snapshot_lock = anyio.Lock()
        self._mutation_active = False
        self._mutation_generation = 0
        self._published_snapshot = _snapshot_project(self.project_root)
        self._observed_snapshot = self._published_snapshot
        self._changed_at: float | None = None

    @asynccontextmanager
    async def mutation_scope(self):
        """Serialize mutating tools without adding routine approval gates."""
        async with self.mutation_lock:
            self._mutation_active = True
            self._mutation_generation += 1
            try:
                yield
            finally:
                self._mutation_active = False
                self._mutation_generation += 1

    async def publish_committed_mutation(self) -> None:
        """Publish cache invalidations after a transaction has committed."""
        snapshot = await to_thread.run_sync(_snapshot_project, self.project_root)
        async with self._snapshot_lock:
            self._published_snapshot = snapshot
            self._observed_snapshot = snapshot
            self._changed_at = None
        await self._publish_project_resources_changed()

    async def _publish_project_resources_changed(self) -> None:
        await self.subscriptions.publish(ResourceUpdated(uri=PROJECT_INDEX_URI))
        await self.subscriptions.publish(ResourceUpdated(uri=ASSET_GRAPH_URI))

    async def watch_project(self) -> None:
        """Poll deterministically, debounce bursts, and publish external edits."""
        while True:
            await anyio.sleep(self.poll_seconds)
            scan_generation = self._mutation_generation
            snapshot = await to_thread.run_sync(_snapshot_project, self.project_root)
            now = time.monotonic()
            publish = False
            async with self._snapshot_lock:
                if self._mutation_active or scan_generation != self._mutation_generation:
                    # Tool-owned changes are published by publish_committed_mutation;
                    # Ignore any scan that overlapped a mutation, even when the
                    # mutation ended before the filesystem walk returned. Preserve
                    # the pre-mutation observation so a surviving external edit is
                    # detected by the next clean scan after rollback.
                    self._changed_at = None
                    continue
                if snapshot != self._observed_snapshot:
                    self._observed_snapshot = snapshot
                    self._changed_at = now
                if (
                    self._changed_at is not None
                    and now - self._changed_at >= self.debounce_seconds
                    and self._observed_snapshot != self._published_snapshot
                ):
                    self._published_snapshot = self._observed_snapshot
                    self._changed_at = None
                    publish = True
            if publish:
                await self._publish_project_resources_changed()

    @asynccontextmanager
    async def lifespan(self, _server):
        """Start one watcher per process and cancel it deterministically."""
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(self.watch_project)
            try:
                yield self
            finally:
                task_group.cancel_scope.cancel()


class MutationSerializationMiddleware:
    """Serialize mutating tools while leaving independent reads concurrent."""

    def __init__(
        self,
        runtime: MCPV2Runtime,
        is_read_only_tool: Callable[[str], bool],
        is_committed_mutation_result: Callable[[Any], bool],
    ) -> None:
        self._runtime = runtime
        self._is_read_only_tool = is_read_only_tool
        self._is_committed_mutation_result = is_committed_mutation_result

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        if isinstance(ctx.params, Mapping):
            tool_name = ctx.params.get("name")
        else:
            tool_name = getattr(ctx.params, "name", None)
        if not isinstance(tool_name, str) or self._is_read_only_tool(tool_name):
            return await call_next(ctx)
        async with self._runtime.mutation_scope():
            result = await call_next(ctx)
            if self._is_committed_mutation_result(result):
                await self._runtime.publish_committed_mutation()
            return result
