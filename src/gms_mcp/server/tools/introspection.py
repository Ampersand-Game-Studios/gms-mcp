from __future__ import annotations

import json
from typing import Annotated, Any, Dict, Literal, Optional

from pydantic import Field

from ..mcp_types import Context
from ..project import _resolve_project_directory


# A typical object or script .yy is a few hundred characters; rooms and sprites run to megabytes.
_AUTO_YY_CHARS = 12_000
# All of one asset's code in a single result, up to roughly ten thousand tokens.
_INCLUDED_CODE_CHARS = 40_000


def _dense_listing(rows: list, *, include_folder: bool = False) -> Dict[str, Any]:
    """Asset rows written by folder and name: the path is implied, never repeated per asset."""
    from gms_helpers.dense import asset_folders, assets_by_settings, by_folder, name_ranges

    out: Dict[str, Any] = {}
    included = [row for row in rows if row.get("type") == "includedfile"]
    folders = [row for row in rows if row.get("type") == "folder"]
    assets = [row for row in rows if row.get("type") not in ("includedfile", "folder")]
    if assets:
        if include_folder:
            out["by_folder"] = assets_by_settings(assets, lambda row: {"folder": row.get("folder")})
        else:
            grouped, other = asset_folders(str(row["path"]) for row in assets)
            out["assets"] = {folder: name_ranges(names) for folder, names in grouped.items()}
            if other:
                out["files"] = other
    if folders:
        out["folders"] = by_folder(str(row["path"]) for row in folders)
    if included:
        out["included_files"] = by_folder(str(row["path"]) for row in included)
        unusual = {
            str(row["path"]): {"copy_to_mask": row.get("copy_to_mask")}
            for row in included
            if row.get("copy_to_mask", -1) != -1
        }
        if unusual:
            out["included_file_settings"] = unusual
    return out


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Introspection tools
    # -----------------------------
    @mcp.tool()
    def gm_list_assets(
        asset_type: Annotated[
            Optional[str],
            Field(
                description=(
                    "One type to list: object, script, sprite, room, sound, shader, font, sequence, "
                    "animcurve, tileset, timeline, path, note, extension, includedfile, or folder "
                    "(the asset-browser folders, whose paths are what `parent_path` arguments take)."
                )
            ),
        ] = None,
        name_contains: Annotated[
            Optional[str],
            Field(
                description=(
                    "Keep assets whose name contains this text (case-insensitive). "
                    "For asset_type=folder it matches anywhere in the folder path."
                )
            ),
        ] = None,
        folder_prefix: Annotated[
            Optional[str],
            Field(description='Keep assets whose file path starts with or contains this folder, e.g. "objects".'),
        ] = None,
        include_included_files: Annotated[
            bool, Field(description="Include datafiles (included files) when no type is given.")
        ] = True,
        include_folder: Annotated[
            bool,
            Field(description="Add each listed asset's asset-browser folder (reads each asset's .yy)."),
        ] = False,
        limit: Annotated[
            Optional[int],
            Field(description="Return only this many matches (default: every match).", ge=1),
        ] = None,
        offset: Annotated[int, Field(description="Skip this many matching assets, to page through.", ge=0)] = 0,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List the project's assets, optionally only those of one type, name or folder.

        Every match is returned, by name. `assets` maps a folder to asset names whose files are
        <folder>/<name>/<name>.yy (objects/o_player/o_player.yy); `included_files` maps a folder
        under datafiles to its file names; `folders` lists asset-browser folders the same way;
        `files` holds any path named otherwise. A numbered run of names is written as a brace range
        (Keyboard_{0..9} is Keyboard_0 to Keyboard_9). `count` and `by_type` count every match; with `limit` or `offset`,
        `truncated` and `next_offset` say whether more remain. include_folder groups the assets by
        their asset-browser folder instead.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import ASSET_TYPE_MAP, list_asset_folders, list_assets_by_type

        known_types = sorted(set(ASSET_TYPE_MAP.values()))
        if asset_type is not None and asset_type not in known_types:
            # An unknown type used to return an empty list, which reads as "the project has none".
            import difflib

            failure: Dict[str, Any] = {
                "ok": False,
                "error": f"Unknown asset_type '{asset_type}'",
                "valid_asset_types": known_types,
            }
            close = difflib.get_close_matches(asset_type.lower(), known_types, n=1, cutoff=0.6)
            if close:
                failure["did_you_mean"] = close[0]
            return failure
        if asset_type == "folder":
            matches = {"folder": list_asset_folders(project_directory, name_contains=name_contains)}
        else:
            matches = list_assets_by_type(
                project_directory,
                asset_type,
                include_included_files,
                name_contains=name_contains,
                folder_prefix=folder_prefix,
            )
        by_type = {kind: len(items) for kind, items in matches.items()}
        count = sum(by_type.values())
        result: Dict[str, Any] = {"ok": True, "count": count, "by_type": by_type}

        rows = [item for items in matches.values() for item in items][offset:]
        if limit is not None:
            rows = rows[:limit]
        if include_folder:
            from gms_helpers.introspection import read_asset_yy

            for item in rows:
                if item.get("type") in ("folder", "includedfile") or not str(item.get("path", "")).endswith(".yy"):
                    continue
                data = read_asset_yy(project_directory, item["path"]) or {}
                parent = data.get("parent")
                item["folder"] = parent.get("path") if isinstance(parent, dict) else None
        result.update(_dense_listing(rows, include_folder=include_folder))
        if offset or len(rows) < count - offset:
            truncated = offset + len(rows) < count
            result.update(
                returned=len(rows),
                truncated=truncated,
                next_offset=offset + len(rows) if truncated else None,
            )
        return result

    @mcp.tool()
    def gm_read_asset(
        asset_identifier: Annotated[
            str,
            Field(
                description=(
                    'An asset name ("o_player"), its .yy path, or the path of one of its code files '
                    '("objects/o_player/Create_0.gml") to read that code.'
                )
            ),
        ],
        yy: Annotated[
            Literal["auto", "full", "none"],
            Field(
                description=(
                    "Whether to include the raw .yy data: auto leaves it out when it is large "
                    "(rooms, sprites), full always includes it, none never does."
                )
            ),
        ] = "auto",
        include_code: Annotated[
            bool,
            Field(description="Also return the source of the asset's code files (each event, or the script)."),
        ] = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Describe one asset, or read one of its code files.

        For an asset: its type, asset-browser folder, and where its behaviour lives. An object lists
        each event by the name the IDE shows ("Begin Step", "Draw GUI") with the .gml file and its
        length; scripts and shaders list their code files; rooms list layers and instance counts.
        `include_code=true` returns the source of every code file with the description; or pass one
        code file path from the list to read just that file. Paths are relative to the project.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import (
            closest_asset_names,
            describe_asset,
            read_asset_yy,
            read_project_text_file,
        )

        if not asset_identifier.endswith(".yy") and "." in asset_identifier.rsplit("/", 1)[-1]:
            code = read_project_text_file(project_directory, asset_identifier)
            if code is not None:
                return {"ok": True, **code}

        summary = describe_asset(project_directory, asset_identifier)
        if summary is None:
            failure: Dict[str, Any] = {"ok": False, "error": f"Asset '{asset_identifier}' not found"}
            suggestions = closest_asset_names(project_directory, asset_identifier)
            if suggestions:
                failure["did_you_mean"] = suggestions
            else:
                failure["hint"] = "List names with gm_list_assets(name_contains=...)."
            return failure

        result: Dict[str, Any] = {"ok": True, **summary}
        if include_code:
            remaining = _INCLUDED_CODE_CHARS
            for entry in [*summary.get("events", []), *summary.get("code_files", [])]:
                code = read_project_text_file(project_directory, entry["file"]) if entry.get("file") else None
                if code is None:
                    continue
                if len(code["code"]) > remaining:
                    result["code_omitted"] = (
                        "Some code was left out to keep this result readable; read those files by path."
                    )
                    continue
                entry["code"] = code["code"]
                remaining -= len(code["code"])
        if yy != "none":
            asset_data = read_asset_yy(project_directory, asset_identifier)
            size = len(json.dumps(asset_data, ensure_ascii=False))
            if yy == "full" or size <= _AUTO_YY_CHARS:
                result["asset_data"] = asset_data
            else:
                result["asset_data_omitted"] = f'The .yy is {size} characters; pass yy="full" to include it.'
        return result

    @mcp.tool()
    def gm_search_references(
        pattern: str,
        scope: str = "all",
        is_regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Search for a pattern in project files.

        Scopes: 'all', 'gml', 'yy', 'scripts', 'objects', 'extensions', 'datafiles'.
        `results` maps each file to its matching lines as "<line> <text>" (a line longer than
        200 characters is shown around the match, marked with …).
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import search_references

        results = search_references(
            project_directory,
            pattern,
            scope=scope,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )
        if results and "error" in results[0]:
            return {"ok": False, "error": results[0]["error"]}
        by_file: Dict[str, list] = {}
        for hit in results:
            by_file.setdefault(hit["file"], []).append(f"{hit['line']} {hit['context']}")
        found: Dict[str, Any] = {"count": len(results), "results": by_file}
        if len(results) >= max_results > 0:
            found["limited"] = f"Stopped at max_results={max_results}; there may be more."
        return found

    @mcp.tool()
    def gm_get_asset_graph(
        asset: Annotated[
            Optional[str],
            Field(description="An asset name. Returns what it uses and what uses it, instead of the whole graph."),
        ] = None,
        deep: Annotated[
            bool,
            Field(description="Also scan all GML code for references between assets (slower, more complete)."),
        ] = False,
        full: Annotated[
            bool,
            Field(description="Return every node and edge. Large: thousands of entries on a real project."),
        ] = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Show how assets depend on each other: parents, sprites, sounds, rooms and (with deep) code.

        Pass `asset` to answer "what does this use, and who uses it?": `uses` covers its data links
        and every asset its own code names (scripts called, objects and sprites referred to), and
        `used_by` lists every asset whose data or code names it (the scan gm_safe_delete relies on).
        Without `asset` you get a summary (counts by relation and the most-used assets); pass
        `full=true` for every node and edge.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import build_asset_graph, closest_asset_names

        graph = build_asset_graph(project_directory, deep=deep)
        if full and asset is None:
            return graph
        nodes = {node["id"]: node for node in graph["nodes"]}
        edges = graph["edges"]
        if asset is not None:
            if asset not in nodes:
                failure: Dict[str, Any] = {"ok": False, "error": f"Asset '{asset}' not found"}
                suggestions = closest_asset_names(project_directory, asset)
                if suggestions:
                    failure["did_you_mean"] = suggestions
                return failure
            from gms_helpers.introspection import asset_code_uses
            from gms_helpers.workflow import find_asset_users

            users = find_asset_users(project_directory, asset, graph)
            uses = [
                {"asset": e["to"], "type": nodes.get(e["to"], {}).get("type"), "relation": e["relation"]}
                for e in edges
                if e["from"] == asset
            ]
            already = {entry["asset"] for entry in uses}
            asset_types = {name: node.get("type", "unknown") for name, node in nodes.items()}
            uses += [
                entry
                for entry in asset_code_uses(project_directory, asset, asset_types)
                if entry["asset"] not in already
            ]
            return {
                "ok": True,
                "asset": nodes[asset],
                # What this asset's data links to, and every asset its own code names.
                "uses": uses,
                # Every asset whose .yy data or code names this one: the same scan gm_safe_delete uses.
                "used_by": [
                    {"asset": user["asset_name"], "type": user["asset_type"], "relation": user["relation"]}
                    for user in users
                ],
                "deep_scan": graph["deep_scan"],
            }
        by_relation: Dict[str, int] = {}
        used: Dict[str, int] = {}
        for edge in edges:
            by_relation[edge["relation"]] = by_relation.get(edge["relation"], 0) + 1
            used[edge["to"]] = used.get(edge["to"], 0) + 1
        most_used = sorted(used.items(), key=lambda item: (-item[1], item[0]))[:20]
        return {
            "ok": True,
            "node_count": graph["node_count"],
            "edge_count": graph["edge_count"],
            "edges_by_relation": by_relation,
            "most_used": [{"asset": name, "used_by": count} for name, count in most_used],
            "deep_scan": graph["deep_scan"],
            "message": "Pass asset=<name> for one asset's links, or full=true for every node and edge.",
        }

    @mcp.tool()
    def gm_get_project_stats(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Get quick statistics about a project (asset counts by type).
        Faster than building a full index.
        """
        _ = ctx
        project_directory = _resolve_project_directory(project_root)
        from gms_helpers.introspection import get_project_stats

        return get_project_stats(project_directory)
