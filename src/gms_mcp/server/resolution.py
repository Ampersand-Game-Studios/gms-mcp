"""Typed, policy-scoped Resolve helpers for mutating GameMaker tools.

The MCP SDK owns multi-round request-state integrity.  This module only builds
stable, safe resolver questions from freshly-authorized project evidence.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar, cast

from mcp.server.mcpserver import Context, Elicit
from mcp.shared.exceptions import MCPError
from mcp_types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    MissingRequiredClientCapabilityErrorData,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .project import ProjectAccessPolicy


_MAX_PROMPT_CHARS = 560
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_ABSOLUTE_PATH = re.compile(r"(?<!\w)(?:[A-Za-z]:[\\/]|/)[^\s,;:()\[\]{}<>]+")


class ResolutionPolicy(str, Enum):
    """The mutation policy a resolver is asking a client to decide."""

    SAFE_DELETE = "safe_delete"
    ROOM_DELETE = "room_delete"
    NAME_COLLISION = "name_collision"
    TEXTURE_GROUP = "texture_group"


class SafeDeleteDecision(BaseModel):
    """Decision for a dependency-aware asset deletion."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["delete", "force", "cancel"] = Field(
        description="delete when safe, force only when dependencies are understood, or cancel"
    )


class RoomDeleteDecision(BaseModel):
    """Decision for deleting a room."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["delete", "force", "cancel"] = Field(
        description="delete when safe, force despite current dependencies, or cancel"
    )


class NameCollisionDecision(BaseModel):
    """Decision for a requested name that already exists."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["rename", "cancel"] = Field(description="provide a different valid name or cancel")
    replacement_name: str | None = Field(
        default=None,
        description="Required only when action is rename; a GameMaker resource name, not a path",
    )

    @model_validator(mode="after")
    def require_safe_alternative_name(self) -> "NameCollisionDecision":
        if self.action == "cancel":
            if self.replacement_name is not None:
                raise ValueError("replacement_name is only valid when action is rename")
            return self
        candidate = (self.replacement_name or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate):
            raise ValueError("rename requires a valid GameMaker resource name")
        self.replacement_name = candidate
        return self


class TextureGroupDecision(BaseModel):
    """Decision for a texture-group operation with existing members."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["delete", "reassign", "cancel"] = Field(
        description="delete unreferenced group, reassign its members, or cancel"
    )
    reassign_to: str | None = Field(
        default=None,
        description="Required only when action is reassign; a texture group name, not a path",
    )

    @model_validator(mode="after")
    def require_reassignment_target(self) -> "TextureGroupDecision":
        target = (self.reassign_to or "").strip()
        if self.action == "reassign" and not target:
            raise ValueError("reassign requires reassign_to")
        if self.action != "reassign" and self.reassign_to is not None:
            raise ValueError("reassign_to is only valid when action is reassign")
        if target:
            self.reassign_to = target
        return self


ResolutionDecision = SafeDeleteDecision | RoomDeleteDecision | NameCollisionDecision | TextureGroupDecision
DecisionT = TypeVar("DecisionT", bound=BaseModel)


@dataclass(frozen=True)
class ResolutionEvidence:
    """Sanitized, current evidence used to render one resolver question."""

    summary: str
    affected_count: int = 0
    stale: bool = False
    facts: Mapping[str, str | int | bool] = field(default_factory=dict)


class ResolutionEvidenceReader(Protocol):
    """Read evidence only from the already-authorized pinned project root."""

    def __call__(
        self,
        project_root: Any,
        arguments: Mapping[str, Any],
    ) -> ResolutionEvidence | Awaitable[ResolutionEvidence]: ...


ResolutionTelemetrySink = Callable[[Mapping[str, str | int | bool]], None]


def sanitize_resolution_prompt(value: object, *, project_root: object | None = None) -> str:
    """Make evidence safe for an elicitation prompt and bounded across retries."""
    text = str(value)
    if project_root is not None:
        text = text.replace(str(project_root), "<project>")
    text = _ABSOLUTE_PATH.sub("<path>", text)
    text = _CONTROL_CHARACTERS.sub(" ", text)
    text = " ".join(text.split())
    if len(text) > _MAX_PROMPT_CHARS:
        return f"{text[: _MAX_PROMPT_CHARS - 1].rstrip()}…"
    return text


def _fingerprint(policy: ResolutionPolicy, evidence: ResolutionEvidence) -> str:
    safe_facts = {
        sanitize_resolution_prompt(key): sanitize_resolution_prompt(value)
        for key, value in sorted(evidence.facts.items(), key=lambda item: str(item[0]))
    }
    payload = json.dumps(
        {
            "policy": policy.value,
            "summary": sanitize_resolution_prompt(evidence.summary),
            "affected_count": max(0, int(evidence.affected_count)),
            "facts": safe_facts,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scenario_key(policy: ResolutionPolicy, arguments: Mapping[str, Any]) -> str:
    """Keep only a process-local opaque key; never emit raw operation inputs."""
    rendered = json.dumps(arguments, sort_keys=True, default=str, separators=(",", ":"))
    return f"{policy.value}:{hashlib.sha256(rendered.encode('utf-8')).hexdigest()}"


def _opaque_digest(value: object) -> str:
    """Fingerprint private evidence without exposing its names or paths."""
    rendered = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def require_form_elicitation_capability(ctx: Context[Any, Any]) -> None:
    """Require currently declared form elicitation support on every resolver round."""
    capabilities = ctx.client_capabilities
    elicitation = capabilities.elicitation if capabilities is not None else None
    if elicitation is not None and (elicitation.form is not None or elicitation.url is None):
        return
    required = ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability()))
    data = MissingRequiredClientCapabilityErrorData(required_capabilities=required)
    raise MCPError(
        code=MISSING_REQUIRED_CLIENT_CAPABILITY,
        message="Client did not declare the form elicitation capability required for this operation.",
        data=data.model_dump(by_alias=True, mode="json", exclude_none=True),
    )


def _safe_delete_evidence(project_root: Any, arguments: Mapping[str, Any]) -> ResolutionEvidence:
    """Read the existing safe-delete preflight without starting a mutation."""
    from gms_helpers.workflow import safe_delete_preflight

    preflight = safe_delete_preflight(
        project_root,
        str(arguments.get("asset_type") or ""),
        str(arguments.get("asset_name") or ""),
        force=bool(arguments.get("force")),
    )
    dependencies = preflight.get("dependencies")
    dependency_count = len(dependencies) if isinstance(dependencies, list) else 0
    exists = bool(preflight.get("asset_path"))
    blocked = bool(preflight.get("blocked"))
    if not exists:
        summary = "The requested asset is no longer present. Cancel rather than applying a stale delete."
    elif blocked:
        summary = "Current dependency scan found references that block an ordinary delete."
    elif dependency_count:
        summary = "Current dependency scan found references; force is required to proceed."
    else:
        summary = "Current dependency scan found no incoming references."
    return ResolutionEvidence(
        summary=summary,
        affected_count=dependency_count,
        facts={
            "asset_exists": exists,
            "blocked": blocked,
            "dependency_count": dependency_count,
            "dependency_set_digest": _opaque_digest(dependencies or []),
        },
    )


def _room_delete_evidence(project_root: Any, arguments: Mapping[str, Any]) -> ResolutionEvidence:
    """Read current room existence and incoming dependency evidence."""
    from gms_helpers.workflow import safe_delete_preflight

    room_name = str(arguments.get("room_name") or "")
    preflight = safe_delete_preflight(project_root, "room", room_name)
    exists = bool(preflight.get("asset_path"))
    dependency_count = int(preflight.get("dependency_count", 0))
    blocked = bool(preflight.get("blocked"))
    return ResolutionEvidence(
        summary=(
            "Current dependency scan found references that block an ordinary room delete."
            if blocked
            else "The room is present and has no incoming references."
            if exists
            else "The room is no longer present; cancel this delete."
        ),
        affected_count=dependency_count,
        facts={
            "room_exists": exists,
            "blocked": blocked,
            "dependency_count": dependency_count,
            "dependency_set_digest": _opaque_digest(preflight.get("dependencies") or []),
        },
    )


def _name_collision_evidence(project_root: Any, arguments: Mapping[str, Any]) -> ResolutionEvidence:
    """Read the project index for an exact current resource-name collision."""
    from gms_helpers.introspection import list_assets_by_type
    from gms_helpers.utils import find_yyp, load_json_loose

    requested_name = str(arguments.get("new_name") or "")
    assets = list_assets_by_type(project_root, include_included_files=False)
    registered_matches = {
        str(item.get("path") or item.get("name") or "").replace("\\", "/").casefold()
        for entries in assets.values()
        if isinstance(entries, list)
        for item in entries
        if isinstance(item, Mapping) and str(item.get("name", "")).casefold() == requested_name.casefold()
    }
    resource_directories = {
        "animcurves",
        "fonts",
        "notes",
        "objects",
        "paths",
        "rooms",
        "scripts",
        "sequences",
        "shaders",
        "sounds",
        "sprites",
        "tilesets",
        "timelines",
    }
    requested_folded = requested_name.casefold()
    physical_matches: set[str] = set()
    for resource_directory in resource_directories:
        directory = project_root / resource_directory
        if not directory.is_dir():
            continue
        for candidate in directory.iterdir():
            if candidate.name.casefold() == requested_folded:
                physical_matches.add(candidate.relative_to(project_root).as_posix().casefold())
            if candidate.is_dir():
                for yy_path in candidate.glob("*.yy"):
                    if yy_path.stem.casefold() == requested_folded:
                        physical_matches.add(yy_path.relative_to(project_root).as_posix().casefold())
    folder_matches: set[str] = set()
    project_data = load_json_loose(find_yyp(project_root))
    if isinstance(project_data, Mapping):
        raw_folders = project_data.get("Folders", project_data.get("folders", []))
        if isinstance(raw_folders, list):
            for folder in raw_folders:
                if not isinstance(folder, Mapping):
                    continue
                folder_name = str(folder.get("name") or "")
                folder_path = str(folder.get("folderPath") or "").replace("\\", "/")
                if folder_name.casefold() == requested_folded or Path(folder_path).stem.casefold() == requested_folded:
                    folder_matches.add(folder_path.casefold())
    matches = len(registered_matches | physical_matches | folder_matches)
    return ResolutionEvidence(
        summary=(
            "The requested name currently collides with an existing resource; provide a different valid name."
            if matches
            else "The requested name is currently available; cancel this stale collision resolution."
        ),
        affected_count=matches,
        facts={
            "collision_count": matches,
            "collision_set_digest": _opaque_digest(sorted((*registered_matches, *physical_matches, *folder_matches))),
        },
    )


def _texture_group_evidence(project_root: Any, arguments: Mapping[str, Any]) -> ResolutionEvidence:
    """Read all asset/config/group-parent references before asking how to delete."""
    from gms_helpers.texture_group.mutations import texture_group_reference_evidence
    from gms_helpers.texture_group.project import find_texture_group, load_project_yyp

    name = str(arguments.get("name") or "")
    _, project_data = load_project_yyp(project_root)
    exists = find_texture_group(project_data, name) is not None
    reference_evidence = texture_group_reference_evidence(project_root, name) if exists else {"references": []}
    references = reference_evidence.get("references", [])
    count = len(references) if isinstance(references, list) else 0
    if not exists:
        summary = "The texture group is no longer defined; cancel this stale operation."
    elif count:
        summary = "Current scan found assets assigned to this texture group; choose a valid reassignment or cancel."
    else:
        summary = "Current scan found no assigned assets in this texture group."
    return ResolutionEvidence(
        summary=summary,
        affected_count=max(0, count),
        facts={
            "group_exists": exists,
            "member_count": max(0, count),
            "reference_set_digest": _opaque_digest(references),
        },
    )


class ResolutionRuntime:
    """Per-server resolver state bound to one immutable ProjectAccessPolicy."""

    def __init__(
        self,
        project_access_policy: ProjectAccessPolicy,
        *,
        evidence_readers: Mapping[ResolutionPolicy, ResolutionEvidenceReader] | None = None,
        telemetry_sink: ResolutionTelemetrySink | None = None,
    ) -> None:
        self.project_access_policy = project_access_policy
        self._evidence_readers: dict[ResolutionPolicy, ResolutionEvidenceReader] = {
            ResolutionPolicy.SAFE_DELETE: _safe_delete_evidence,
            ResolutionPolicy.ROOM_DELETE: _room_delete_evidence,
            ResolutionPolicy.NAME_COLLISION: _name_collision_evidence,
            ResolutionPolicy.TEXTURE_GROUP: _texture_group_evidence,
        }
        self._evidence_readers.update(evidence_readers or {})
        self._telemetry_sink = telemetry_sink
        self._previous_evidence: dict[str, tuple[str, bool, int]] = {}

    def set_evidence_reader(self, policy: ResolutionPolicy, reader: ResolutionEvidenceReader) -> None:
        """Install a policy-specific read seam before tools are registered."""
        self._evidence_readers[policy] = reader

    def _telemetry(
        self,
        *,
        policy: ResolutionPolicy,
        phase: str,
        affected_count: int = 0,
        stale_evidence: bool = False,
    ) -> None:
        if self._telemetry_sink is None:
            return
        self._telemetry_sink(
            {
                "event": "mcp.resolution",
                "policy": policy.value,
                "phase": phase,
                "affected_count": max(0, affected_count),
                "stale_evidence": stale_evidence,
            }
        )

    async def _evidence(
        self,
        policy: ResolutionPolicy,
        *,
        project_root: str,
        arguments: Mapping[str, Any],
        ctx: Context[Any, Any],
    ) -> tuple[Any, ResolutionEvidence, bool, int]:
        # Do these checks before each evidence read.  The resolver can run again on
        # every input round, and an echoed request_state is never an authorization.
        authorized_root = self.project_access_policy.authorize(project_root)
        reader = self._evidence_readers[policy]
        result = reader(authorized_root, arguments)
        evidence = await result if inspect.isawaitable(result) else result
        if not isinstance(evidence, ResolutionEvidence):
            raise TypeError("Resolution evidence readers must return ResolutionEvidence.")
        # A reader must not grant itself durable authority. Revalidate the pinned
        # boundary and capability after it completes, before rendering a prompt.
        authorized_root = self.project_access_policy.authorize(project_root)
        key = _scenario_key(policy, arguments)
        fingerprint = _fingerprint(policy, evidence)
        previous = self._previous_evidence.get(key)
        if previous is None:
            stale = evidence.stale
            revision = 1
        elif previous[0] == fingerprint:
            # Keep the rendered question byte-for-byte stable across a retry so
            # the SDK can validate and consume the sealed response digest.
            stale = previous[1]
            revision = previous[2]
        else:
            stale = True
            revision = previous[2] + 1
        self._previous_evidence[key] = (fingerprint, stale, revision)
        return authorized_root, evidence, stale, revision

    @staticmethod
    def _message(
        policy: ResolutionPolicy,
        evidence: ResolutionEvidence,
        stale: bool,
        revision: int,
        project_root: object,
    ) -> str:
        summary = sanitize_resolution_prompt(evidence.summary, project_root=project_root)
        current = " Evidence changed since the previous question; review the current state." if stale else ""
        count = max(0, int(evidence.affected_count))
        impact = f" Affected items: {count}." if count else ""
        if policy is ResolutionPolicy.SAFE_DELETE:
            prefix = "Approve the requested safe delete."
        elif policy is ResolutionPolicy.ROOM_DELETE:
            prefix = "Approve deletion of the requested room."
        elif policy is ResolutionPolicy.NAME_COLLISION:
            prefix = "Resolve the requested resource-name collision."
        else:
            prefix = "Resolve the requested texture-group operation."
        return sanitize_resolution_prompt(
            f"{prefix}{impact} {summary}{current} Evidence revision: {revision}.",
            project_root=project_root,
        )

    @staticmethod
    def _automatic_decision(
        policy: ResolutionPolicy,
        evidence: ResolutionEvidence,
        arguments: Mapping[str, Any],
    ) -> ResolutionDecision | None:
        """Return the safe normal-path decision; ``None`` needs policy-specific handling."""
        facts = evidence.facts
        if policy is ResolutionPolicy.SAFE_DELETE:
            if not bool(facts.get("asset_exists")):
                return SafeDeleteDecision(action="cancel")
            if bool(arguments.get("force")):
                return SafeDeleteDecision(action="force")
            if bool(arguments.get("dry_run")) or not bool(facts.get("blocked")):
                return SafeDeleteDecision(action="delete")
            return None
        if policy is ResolutionPolicy.ROOM_DELETE:
            if not bool(facts.get("room_exists")):
                return RoomDeleteDecision(action="cancel")
            if bool(arguments.get("dry_run")) or not bool(facts.get("blocked")):
                return RoomDeleteDecision(action="delete")
            return None
        if policy is ResolutionPolicy.NAME_COLLISION:
            return None
        if not bool(facts.get("group_exists")):
            return TextureGroupDecision(action="cancel")
        if bool(arguments.get("dry_run")):
            return TextureGroupDecision(action="delete")
        if int(facts.get("member_count", 0)) == 0:
            return TextureGroupDecision(action="delete")
        target = str(arguments.get("reassign_to") or "").strip()
        if target:
            return TextureGroupDecision(action="reassign", reassign_to=target)
        return None

    async def _resolve(
        self,
        policy: ResolutionPolicy,
        schema: type[DecisionT],
        *,
        project_root: str,
        arguments: Mapping[str, Any],
        ctx: Context[Any, Any],
    ) -> Elicit[DecisionT] | DecisionT | None:
        authorized_root, evidence, stale, revision = await self._evidence(
            policy,
            project_root=project_root,
            arguments=arguments,
            ctx=ctx,
        )
        automatic = self._automatic_decision(policy, evidence, arguments)
        # Name collisions use None as their no-conflict outcome. All other None
        # outcomes are exceptional and need the client to choose a safe action.
        if automatic is not None or policy is ResolutionPolicy.NAME_COLLISION and evidence.affected_count == 0:
            self._telemetry(
                policy=policy,
                phase="automatic",
                affected_count=evidence.affected_count,
                stale_evidence=stale,
            )
            return cast(DecisionT | None, automatic)
        self._telemetry(
            policy=policy,
            phase="elicited",
            affected_count=evidence.affected_count,
            stale_evidence=stale,
        )
        require_form_elicitation_capability(ctx)
        return Elicit(self._message(policy, evidence, stale, revision, authorized_root), schema)

    def safe_delete_resolver(self):
        async def resolve_safe_delete(
            asset_type: str,
            asset_name: str,
            force: bool = False,
            dry_run: bool = True,
            project_root: str = ".",
            ctx: Context[Any, Any] | None = None,
        ) -> Elicit[SafeDeleteDecision] | SafeDeleteDecision:
            if ctx is None:
                raise ValueError("Resolution requires an active MCP context.")
            return cast(
                "Elicit[SafeDeleteDecision] | SafeDeleteDecision",
                await self._resolve(
                    ResolutionPolicy.SAFE_DELETE,
                    SafeDeleteDecision,
                    project_root=project_root,
                    arguments={"asset_type": asset_type, "asset_name": asset_name, "force": force, "dry_run": dry_run},
                    ctx=ctx,
                ),
            )

        return resolve_safe_delete

    def room_delete_resolver(self):
        async def resolve_room_delete(
            room_name: str,
            dry_run: bool = False,
            project_root: str = ".",
            ctx: Context[Any, Any] | None = None,
        ) -> Elicit[RoomDeleteDecision] | RoomDeleteDecision:
            if ctx is None:
                raise ValueError("Resolution requires an active MCP context.")
            return cast(
                "Elicit[RoomDeleteDecision] | RoomDeleteDecision",
                await self._resolve(
                    ResolutionPolicy.ROOM_DELETE,
                    RoomDeleteDecision,
                    project_root=project_root,
                    arguments={"room_name": room_name, "dry_run": dry_run},
                    ctx=ctx,
                ),
            )

        return resolve_room_delete

    def name_collision_resolver(self):
        async def resolve_name_collision(
            new_name: str,
            project_root: str = ".",
            ctx: Context[Any, Any] | None = None,
        ) -> Elicit[NameCollisionDecision] | NameCollisionDecision | None:
            if ctx is None:
                raise ValueError("Resolution requires an active MCP context.")
            return cast(
                "Elicit[NameCollisionDecision] | NameCollisionDecision | None",
                await self._resolve(
                    ResolutionPolicy.NAME_COLLISION,
                    NameCollisionDecision,
                    project_root=project_root,
                    arguments={"new_name": new_name},
                    ctx=ctx,
                ),
            )

        return resolve_name_collision

    def asset_name_collision_resolver(self):
        """Return the collision resolver for asset-creation tools using ``name``."""

        async def resolve_asset_name_collision(
            name: str,
            project_root: str = ".",
            ctx: Context[Any, Any] | None = None,
        ) -> Elicit[NameCollisionDecision] | NameCollisionDecision | None:
            if ctx is None:
                raise ValueError("Resolution requires an active MCP context.")
            return cast(
                "Elicit[NameCollisionDecision] | NameCollisionDecision | None",
                await self._resolve(
                    ResolutionPolicy.NAME_COLLISION,
                    NameCollisionDecision,
                    project_root=project_root,
                    arguments={"new_name": name},
                    ctx=ctx,
                ),
            )

        return resolve_asset_name_collision

    def texture_group_resolver(self):
        async def resolve_texture_group(
            name: str,
            reassign_to: str | None = None,
            dry_run: bool = False,
            project_root: str = ".",
            ctx: Context[Any, Any] | None = None,
        ) -> Elicit[TextureGroupDecision] | TextureGroupDecision:
            if ctx is None:
                raise ValueError("Resolution requires an active MCP context.")
            return cast(
                "Elicit[TextureGroupDecision] | TextureGroupDecision",
                await self._resolve(
                    ResolutionPolicy.TEXTURE_GROUP,
                    TextureGroupDecision,
                    project_root=project_root,
                    arguments={"name": name, "reassign_to": reassign_to, "dry_run": dry_run},
                    ctx=ctx,
                ),
            )

        return resolve_texture_group


__all__ = [
    "NameCollisionDecision",
    "ResolutionDecision",
    "ResolutionEvidence",
    "ResolutionEvidenceReader",
    "ResolutionPolicy",
    "ResolutionRuntime",
    "RoomDeleteDecision",
    "SafeDeleteDecision",
    "TextureGroupDecision",
    "require_form_elicitation_capability",
    "sanitize_resolution_prompt",
]
