"""Discovery for the curated GameMaker MCP tool surface."""

from __future__ import annotations

from typing import Any, Dict

from ..mcp_types import Context

# What each optional toolset adds, by tool-name pattern. Clients that load tools on demand show
# an agent only the server instructions until it searches, so this is how it learns what exists.
TOOLSET_TOOLS = {
    "assets": "gm_create_* (scripts, objects, sprites, rooms, folders and more), gm_asset_move, gm_yyp_*",
    "bridge": "gm_bridge_*, gm_game_* (start the game, send commands, screenshots, its log)",
    "docs": "gm_doc_* (GML manual)",
    "events": "gm_event_* (object events)",
    "live-reload": "gm_live_reload_*",
    "maintenance": "gm_maintenance_* (lint, orphans, cleanup)",
    "map": "gm_room_tilemap_*, gm_room_map_validate",
    "resourcetool": "gm_resourcetool_validate",
    "rooms": "gm_room_ops_*, gm_room_layer_*, gm_room_instance_*",
    "runtime": "gm_runtime_* (list, pin, verify runtimes)",
    "texture-groups": "gm_texture_group_*",
}


def server_instructions(*, enabled: tuple[str, ...], optional: tuple[str, ...], read_only: bool) -> str:
    """Describe this server process for a client's system prompt, briefly.

    Some clients repeat a server's instructions beside every tool a search returns, so this
    holds only what must be known before the first call. gm_project_info returns the guide to
    the tools by task.
    """
    lines = [
        "GameMaker tools for the one project this server is pinned to; paths are project-relative. "
        "Call gm_project_info first: it confirms the checkout and branch the tools act on and lists "
        "the tools by task. Where the project's own instructions (AGENTS.md, CLAUDE.md) name a tool "
        "for a job, follow them.",
        "Most used: gm_list_assets, gm_read_asset, gm_get_asset_graph, gm_find_references"
        + ("." if read_only else ", gm_snapshot_compile, gm_test_run, gm_safe_delete."),
    ]
    if read_only:
        lines.append("This session is read-only: tools that change, build or run the project are not registered.")
    else:
        lines.append("A build not done in 20 s returns STILL_RUNNING: follow it with gm_build_status.")
    enabled_set = set(enabled)
    off = [name for name in optional if name not in enabled_set]
    if off and not read_only:
        lines.append(
            "Not enabled in this session: "
            + "; ".join(f"{name}: {TOOLSET_TOOLS[name]}" for name in off)
            + ". A search will not find these. To use one, add it to GMS_MCP_TOOLSETS in this server's "
            'client config (e.g. "core,assets,rooms" or "all") and start a new session.'
        )
    return "\n".join(lines)


def tool_guide(*, enabled: tuple[str, ...], read_only: bool) -> Dict[str, str]:
    """Name the tools for each kind of job in this session, for gm_project_info to return."""
    enabled_set = set(enabled)
    guide = {
        "read": (
            "gm_list_assets (filter by asset_type or name; asset_type=folder lists asset-browser folders), "
            "gm_read_asset (an object's events by name with their code files, or the code of one file), "
            "gm_get_asset_graph (asset=<name>: what it uses and what uses it), gm_search_references, "
            "gm_find_definition, gm_find_references, gm_list_symbols."
        ),
        "check": "gm_project_check and gm_diagnostics report problems without building.",
    }
    if read_only:
        return guide
    guide["check"] = (
        "gm_snapshot_compile compiles a throwaway copy of the project and gm_test_run runs test code in "
        "the game from one: prefer them, they cannot disturb the working tree or another session. "
        "gm_compile builds inside the working tree (its run label is working_tree) and holds up changes "
        "to the project while it runs. gm_project_check and gm_diagnostics report problems "
        "without building. A build takes minutes: a call with no result after 20 s returns "
        "STILL_RUNNING (background=true returns at once), and gm_build_status reports the stage "
        "and log lines, then the result; gm_build_stop ends it (no label: your latest run). Builds take turns across sessions on this machine: gm_lock_status shows who holds the turn."
    )
    if "bridge" in enabled_set:
        guide["run"] = (
            "gm_game_start builds a throwaway copy, starts the game and connects to it (background=true and "
            "gm_build_status to follow the build); then "
            "gm_game_command, gm_game_screenshot (returns the image), gm_game_log and gm_game_stop. "
            "gm_run with background=true launches from the working tree instead (gm_run_status, gm_run_log, "
            "gm_run_stop)."
        )
    else:
        guide["run"] = (
            "gm_run with background=true launches the game from the working tree; then gm_run_status, "
            "gm_run_log and gm_run_stop."
        )
    guide["change"] = (
        "Use gm_workflow_rename, gm_workflow_duplicate, gm_safe_delete and gm_sprite_* rather than editing "
        ".yy or .yyp files; write GML in the .gml files directly. Changes are transactional and may be "
        "followed by a verifying compile. A change's result lists what it changed (a folder it created "
        'whole as "folder/") and counts as preexisting_issues the problems the project already had, '
        "which gm_project_check lists."
    )
    if "assets" in enabled_set:
        guide["change"] += " gm_create_* make new assets (gm_create_script takes the code)."
    return guide


def register(
    mcp: Any,
    ContextType: Any,
    *,
    enabled: tuple[str, ...],
    optional: tuple[str, ...],
) -> None:
    globals()["Context"] = ContextType

    @mcp.tool()
    def gm_capabilities(ctx: Context | None = None) -> Dict[str, Any]:
        """List enabled MCP toolsets and the single restart-time setting used to enable optional domains."""
        _ = ctx
        enabled_set = set(enabled)
        return {
            "ok": True,
            "profile": "all" if enabled_set == {"core", *optional} else "curated",
            "enabled_toolsets": list(enabled),
            "optional_toolsets": list(optional),
            "disabled_toolsets": [name for name in optional if name not in enabled_set],
            "configuration": {
                "environment_variable": "GMS_MCP_TOOLSETS",
                "all_value": "all",
                "example": "maintenance,texture-groups",
                "restart_required": True,
            },
        }
