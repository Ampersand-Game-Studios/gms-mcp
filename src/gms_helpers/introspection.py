"""
Introspection helpers for GameMaker projects.
Provides functions to list assets, read asset data, search for references,
and build project indices and asset dependency graphs.

This module is designed for production use with comprehensive error handling,
support for all GameMaker asset types, and deep analysis capabilities.
"""

import json
import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field

from .utils import load_json_loose


# =============================================================================
# Asset Type Definitions
# =============================================================================

# Complete mapping of GameMaker folder names to singular asset types
ASSET_TYPE_MAP = {
    # Core asset types
    "scripts": "script",
    "objects": "object",
    "sprites": "sprite",
    "rooms": "room",
    "sounds": "sound",
    "fonts": "font",
    "shaders": "shader",
    "paths": "path",
    "timelines": "timeline",
    "tilesets": "tileset",
    "animcurves": "animcurve",
    "sequences": "sequence",
    "notes": "note",
    "folders": "folder",
    # Extension and datafile types
    "extensions": "extension",
    "datafiles": "includedfile",
    # Additional types that may appear
    "particlesystems": "particlesystem",
}

# GML patterns for deep reference scanning
GML_REFERENCE_PATTERNS = {
    "instance_create": [
        r"instance_create_layer\s*\([^,]+,\s*[^,]+,\s*[^,]+,\s*(\w+)\s*\)",
        r"instance_create_depth\s*\([^,]+,\s*[^,]+,\s*[^,]+,\s*(\w+)\s*\)",
        r"instance_create\s*\([^,]+,\s*[^,]+,\s*(\w+)\s*\)",
    ],
    "sprite_assignment": [
        r"sprite_index\s*=\s*(\w+)",
        r"sprite_set\s*\([^,]+,\s*(\w+)\s*\)",
        r"draw_sprite(?:_ext)?\s*\(\s*(\w+)\s*,",
    ],
    "sound_play": [
        r"audio_play_sound\s*\(\s*(\w+)\s*,",
        r"audio_play_sound_at\s*\(\s*(\w+)\s*,",
        r"audio_play_sound_on\s*\([^,]+,\s*(\w+)\s*,",
    ],
    "room_goto": [
        r"room_goto\s*\(\s*(\w+)\s*\)",
        r"room_goto_previous\s*\(\s*\)",
        r"room_goto_next\s*\(\s*\)",
        r"room\s*=\s*(\w+)",
    ],
    "font_set": [
        r"draw_set_font\s*\(\s*(\w+)\s*\)",
        r"font_add\s*\(\s*(\w+)\s*,",
    ],
    "shader_set": [
        r"shader_set\s*\(\s*(\w+)\s*\)",
        r"shader_is_compiled\s*\(\s*(\w+)\s*\)",
    ],
    "path_assign": [
        r"path_start\s*\(\s*(\w+)\s*,",
        r"mp_grid_path\s*\([^,]+,\s*(\w+)\s*,",
    ],
    "timeline_assign": [
        r"timeline_index\s*=\s*(\w+)",
    ],
    "tileset_assign": [
        r"tilemap_set\s*\([^,]+,\s*(\w+)\s*,",
        r"layer_tilemap_create\s*\([^,]+,\s*[^,]+,\s*[^,]+,\s*(\w+)\s*,",
    ],
    "sequence_create": [
        r"sequence_create\s*\(\s*(\w+)\s*\)",
        r"layer_sequence_create\s*\([^,]+,\s*[^,]+,\s*[^,]+,\s*(\w+)\s*\)",
    ],
    "script_execute": [
        r"script_execute\s*\(\s*(\w+)\s*",
        r"script_execute_ext\s*\(\s*(\w+)\s*",
    ],
    "asset_get": [
        r"asset_get_index\s*\(\s*[\"'](\w+)[\"']\s*\)",
        r"asset_get_type\s*\(\s*[\"'](\w+)[\"']\s*\)",
    ],
}


# =============================================================================
# Helper Functions
# =============================================================================

def _find_yyp(project_root: Path) -> Optional[Path]:
    """Find the .yyp file in the project root."""
    try:
        yyp_files = list(project_root.glob("*.yyp"))
        if not yyp_files:
            return None
        return yyp_files[0]
    except Exception:
        return None


def _safe_load_yyp(project_root: Path) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
    """Safely load the .yyp file and return both path and data."""
    yyp_path = _find_yyp(project_root)
    if not yyp_path:
        return None, None
    yyp_data = load_json_loose(yyp_path)
    return yyp_path, yyp_data


def _infer_asset_type(path: str) -> str:
    """Infer asset type from its path."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) < 1:
        return "unknown"
    
    type_folder = parts[0].lower()
    return ASSET_TYPE_MAP.get(type_folder, type_folder.rstrip('s'))


# =============================================================================
# Core Introspection Functions
# =============================================================================

def list_assets_by_type(
    project_root: Path, 
    asset_type_filter: Optional[str] = None,
    include_included_files: bool = True,
    name_contains: Optional[str] = None,
    folder_prefix: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    List all assets from the .yyp file, categorized by type.
    
    Args:
        project_root: Path to the GameMaker project root.
        asset_type_filter: Optional type to filter by (e.g., 'script', 'object', 'extension').
        include_included_files: Whether to include IncludedFiles (datafiles) in the listing.
        name_contains: Optional string to filter asset names by (case-insensitive).
        folder_prefix: Optional string to filter asset paths by (case-insensitive).
        
    Returns:
        Dict mapping asset types to lists of asset info dicts.
        Each asset dict contains: name, path, type, and optionally additional metadata.
    """
    yyp_path, yyp_data = _safe_load_yyp(project_root)
    if not yyp_data:
        return {}
    
    assets: Dict[str, List[Dict[str, Any]]] = {}
    
    # Prep filters
    name_filter = name_contains.lower() if name_contains else None
    folder_filter = folder_prefix.lower() if folder_prefix else None
    
    # Process standard resources
    for res in yyp_data.get("resources", []):
        res_id = res.get("id", {})
        name = res_id.get("name")
        path = res_id.get("path")
        
        if not name or not path:
            continue
        
        inferred_type = _infer_asset_type(path)
        
        if asset_type_filter and inferred_type != asset_type_filter:
            continue
            
        # Apply name filter
        if name_filter and name_filter not in name.lower():
            continue
            
        # Apply folder filter (on the path relative to project root)
        if folder_filter and not path.lower().startswith(folder_filter):
            # Also check if it's just inside a folder of that name
            if folder_filter not in path.lower():
                continue
        
        if inferred_type not in assets:
            assets[inferred_type] = []
        
        assets[inferred_type].append({
            "name": name,
            "path": path,
            "type": inferred_type
        })
    
    # Process IncludedFiles (datafiles) separately - they have a different structure
    if include_included_files and (not asset_type_filter or asset_type_filter == "includedfile"):
        included_files = yyp_data.get("IncludedFiles", [])
        if included_files:
            if "includedfile" not in assets:
                assets["includedfile"] = []
            
            for inc_file in included_files:
                # IncludedFiles have a different structure than regular resources
                name = inc_file.get("name", inc_file.get("fileName", ""))
                file_path = inc_file.get("filePath", "")
                
                if not name:
                    continue
                    
                # Apply name filter
                if name_filter and name_filter not in name.lower():
                    continue
                    
                # Apply folder filter
                full_path = file_path or f"datafiles/{name}"
                if folder_filter and folder_filter not in full_path.lower():
                    continue

                assets["includedfile"].append({
                    "name": name,
                    "path": full_path,
                    "type": "includedfile",
                    "copy_to_mask": inc_file.get("CopyToMask", -1),
                    "resource_type": inc_file.get("resourceType", "GMIncludedFile")
                })
    
    # Sort each list by name
    for t in assets:
        assets[t].sort(key=lambda x: x["name"].lower())
    
    return assets


def get_asset_yy_path(project_root: Path, asset_identifier: str) -> Optional[Path]:
    """
    Resolve an asset identifier to its .yy file path.
    
    Args:
        project_root: Path to the GameMaker project root.
        asset_identifier: Either an asset name (e.g., "o_player") or a relative path.
        
    Returns:
        Path to the .yy file, or None if not found.
    """
    # If it's already a path
    if "/" in asset_identifier or "\\" in asset_identifier or asset_identifier.endswith(".yy"):
        p = project_root / asset_identifier
        if p.exists() and p.suffix == ".yy":
            return p
    
    # Search by name in .yyp
    _, yyp_data = _safe_load_yyp(project_root)
    if not yyp_data:
        return None
    
    for res in yyp_data.get("resources", []):
        res_id = res.get("id", {})
        if res_id.get("name") == asset_identifier:
            path = res_id.get("path")
            if path:
                full_path = project_root / path
                if full_path.exists():
                    return full_path
    
    return None


def read_asset_yy(project_root: Path, asset_identifier: str) -> Optional[Dict[str, Any]]:
    """
    Read the .yy JSON data for a given asset.
    
    Args:
        project_root: Path to the GameMaker project root.
        asset_identifier: Either an asset name or path.
        
    Returns:
        The parsed JSON content of the .yy file, or None if not found.
    """
    yy_path = get_asset_yy_path(project_root, asset_identifier)
    if not yy_path or not yy_path.exists():
        return None
    
    return load_json_loose(yy_path)


def search_references(
    project_root: Path,
    pattern: str,
    *,
    scope: str = "all",
    is_regex: bool = False,
    case_sensitive: bool = False,
    max_results: int = 100
) -> List[Dict[str, Any]]:
    """
    Search for a pattern in project files.
    
    Args:
        project_root: Path to the GameMaker project root.
        pattern: The search pattern (literal string or regex).
        scope: Search scope - 'all', 'gml', 'yy', 'scripts', 'objects', 'extensions', 'datafiles'.
        is_regex: Whether pattern is a regular expression.
        case_sensitive: Whether search is case-sensitive.
        max_results: Maximum number of results to return.
        
    Returns:
        List of match dicts containing: file, line, match, context.
    """
    results = []
    
    # Define file patterns based on scope
    scope_patterns = {
        "all": ["**/*.gml", "**/*.yy", "**/*.yyp"],
        "gml": ["**/*.gml"],
        "yy": ["**/*.yy"],
        "scripts": ["scripts/**/*.gml"],
        "objects": ["objects/**/*.gml"],
        "extensions": ["extensions/**/*"],
        "datafiles": ["datafiles/**/*"],
    }
    
    file_patterns = scope_patterns.get(scope, scope_patterns["all"])
    
    regex_flags = 0 if case_sensitive else re.IGNORECASE
    search_pattern = pattern if is_regex else re.escape(pattern)
    
    try:
        prog = re.compile(search_pattern, regex_flags)
    except re.error as e:
        # Return empty list with error info on invalid regex
        return [{"error": f"Invalid regex: {e}"}]
    
    count = 0
    skip_dirs = {".git", "node_modules", ".cursor", ".gms_mcp", "__pycache__"}
    
    for pattern_glob in file_patterns:
        if count >= max_results:
            break
        
        try:
            for file_path in project_root.glob(pattern_glob):
                if count >= max_results:
                    break
                
                # Skip ignored directories
                if any(part in skip_dirs for part in file_path.parts):
                    continue
                
                if not file_path.is_file():
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f):
                            match = prog.search(line)
                            if match:
                                results.append({
                                    "file": str(file_path.relative_to(project_root)),
                                    "line": i + 1,
                                    "match": match.group(0),
                                    "context": line.strip()[:200]  # Limit context length
                                })
                                count += 1
                                if count >= max_results:
                                    break
                except Exception:
                    continue
        except Exception:
            continue
    
    return results


# =============================================================================
# Project Index and Asset Graph
# =============================================================================

def build_project_index(project_root: Path) -> Dict[str, Any]:
    """
    Build a comprehensive index of the project.
    
    Returns a complete snapshot of the project structure including:
    - All assets by type (including extensions and datafiles)
    - Folder structure
    - Audio groups, texture groups
    - Room order
    - Project metadata
    """
    yyp_path, yyp_data = _safe_load_yyp(project_root)
    if not yyp_data:
        return {"error": "Could not load project file"}
    
    assets_by_type = list_assets_by_type(project_root, include_included_files=True)
    
    # Extract folders
    folders = []
    for f in yyp_data.get("Folders", []):
        folders.append({
            "name": f.get("name"),
            "path": f.get("folderPath")
        })
    
    # Extract room order
    room_order = []
    for node in yyp_data.get("RoomOrderNodes", []):
        room_id = node.get("roomId", {})
        if room_id.get("name"):
            room_order.append(room_id.get("name"))
    
    # Extract audio groups
    audio_groups = [
        {"name": ag.get("name"), "targets": ag.get("targets")}
        for ag in yyp_data.get("AudioGroups", [])
    ]
    
    # Extract texture groups
    texture_groups = [
        {"name": tg.get("name"), "autocrop": tg.get("autocrop"), "border": tg.get("border")}
        for tg in yyp_data.get("TextureGroups", [])
    ]
    
    # Project metadata
    metadata = yyp_data.get("MetaData", {})
    
    return {
        "project_name": yyp_path.stem if yyp_path else "Unknown",
        "project_path": str(project_root),
        "ide_version": metadata.get("IDEVersion", "Unknown"),
        "assets": assets_by_type,
        "folders": folders,
        "room_order": room_order,
        "audio_groups": audio_groups,
        "texture_groups": texture_groups,
        "total_assets": sum(len(l) for l in assets_by_type.values()),
        "asset_counts": {k: len(v) for k, v in assets_by_type.items()}
    }


def build_asset_graph(
    project_root: Path,
    *,
    deep: bool = False,
    include_code_refs: bool = False
) -> Dict[str, Any]:
    """
    Build a dependency graph of assets.
    
    Args:
        project_root: Path to the GameMaker project root.
        deep: If True, parse all GML code for references (slower but more complete).
        include_code_refs: Alias for deep (kept for backwards compatibility).
        
    Returns:
        Dict containing nodes (assets) and edges (relationships).
        Edge relations include: parent, sprite, sound, room, font, shader, path,
        tileset, timeline, sequence, script, code_reference.
    """
    use_deep = deep or include_code_refs
    
    assets_by_type = list_assets_by_type(project_root, include_included_files=True)
    nodes = []
    edges = []
    seen_edges: Set[Tuple[str, str, str]] = set()
    
    # Build a name->type lookup for code reference resolution
    asset_names: Dict[str, str] = {}
    for asset_type, asset_list in assets_by_type.items():
        for asset in asset_list:
            asset_names[asset["name"]] = asset_type
    
    def add_edge(from_name: str, to_name: str, relation: str):
        """Add edge if not duplicate."""
        key = (from_name, to_name, relation)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"from": from_name, "to": to_name, "relation": relation})
    
    # Process all assets
    for asset_type, asset_list in assets_by_type.items():
        for asset in asset_list:
            nodes.append({
                "id": asset["name"],
                "type": asset["type"],
                "path": asset["path"]
            })
            
            # Parse .yy for structural references
            yy_data = read_asset_yy(project_root, asset["path"])
            if yy_data:
                _extract_yy_references(asset, yy_data, add_edge)
    
    # Deep mode: scan GML for code references
    if use_deep:
        _scan_gml_references(project_root, asset_names, add_edge)
    
    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "deep_scan": use_deep
    }


def _extract_yy_references(asset: Dict, yy_data: Dict, add_edge):
    """Extract references from a .yy file structure."""
    asset_name = asset["name"]
    asset_type = asset["type"]
    
    # Object references
    if asset_type == "object":
        # Parent object
        parent = yy_data.get("parentObjectId")
        if parent and parent.get("name"):
            add_edge(asset_name, parent["name"], "parent")
        
        # Sprite
        sprite = yy_data.get("spriteId")
        if sprite and sprite.get("name"):
            add_edge(asset_name, sprite["name"], "sprite")
        
        # Sprite mask
        mask = yy_data.get("spriteMaskId")
        if mask and mask.get("name"):
            add_edge(asset_name, mask["name"], "sprite_mask")
    
    # Tileset sprite
    elif asset_type == "tileset":
        sprite = yy_data.get("spriteId")
        if sprite and sprite.get("name"):
            add_edge(asset_name, sprite["name"], "sprite")
    
    # Room references
    elif asset_type == "room":
        # Check layers for object instances
        for layer in yy_data.get("layers", []):
            for instance in layer.get("instances", []):
                obj_ref = instance.get("objectId")
                if obj_ref and obj_ref.get("name"):
                    add_edge(asset_name, obj_ref["name"], "contains")
            
            # Background sprite
            bg_sprite = layer.get("spriteId")
            if bg_sprite and bg_sprite.get("name"):
                add_edge(asset_name, bg_sprite["name"], "background")
    
    # Sequence tracks
    elif asset_type == "sequence":
        for track in yy_data.get("tracks", []):
            _extract_sequence_track_refs(asset_name, track, add_edge)
    
    # Extension files
    elif asset_type == "extension":
        for ext_file in yy_data.get("files", []):
            # Extensions can contain function definitions
            for func in ext_file.get("functions", []):
                func_name = func.get("name")
                if func_name:
                    add_edge(asset_name, func_name, "defines_function")


def _extract_sequence_track_refs(seq_name: str, track: Dict, add_edge):
    """Extract references from sequence tracks."""
    track_type = track.get("$GMSpriteFramesTrack") or track.get("$GMInstanceTrack") or track.get("$GMAudioTrack")
    
    sprite_id = track.get("spriteId")
    if sprite_id and sprite_id.get("name"):
        add_edge(seq_name, sprite_id["name"], "sprite")
    
    # Recurse into child tracks
    for child in track.get("tracks", []):
        _extract_sequence_track_refs(seq_name, child, add_edge)


def _scan_gml_references(project_root: Path, asset_names: Dict[str, str], add_edge):
    """Scan all GML files for code references to assets."""
    gml_files = list(project_root.glob("**/*.gml"))
    
    # Build combined pattern for all reference types
    all_patterns = []
    for patterns in GML_REFERENCE_PATTERNS.values():
        all_patterns.extend(patterns)
    
    for gml_path in gml_files:
        # Skip ignored directories
        if any(part in {".git", "node_modules", ".cursor"} for part in gml_path.parts):
            continue
        
        try:
            content = gml_path.read_text(encoding='utf-8', errors='ignore')
            
            # Determine the source asset (the file doing the referencing)
            rel_path = str(gml_path.relative_to(project_root))
            parts = rel_path.replace("\\", "/").split("/")
            
            # Extract source asset name from path
            source_asset = None
            if len(parts) >= 2:
                if parts[0] in ("scripts", "objects"):
                    source_asset = parts[1]
            
            if not source_asset:
                continue
            
            # Search for all patterns
            for pattern in all_patterns:
                try:
                    for match in re.finditer(pattern, content, re.IGNORECASE):
                        ref_name = match.group(1) if match.lastindex else None
                        if ref_name and ref_name in asset_names:
                            add_edge(source_asset, ref_name, "code_reference")
                except Exception:
                    continue
                    
        except Exception:
            continue


# =============================================================================
# Utility Functions for External Use
# =============================================================================

def get_project_stats(project_root: Path) -> Dict[str, Any]:
    """Get quick statistics about a project without building full index."""
    _, yyp_data = _safe_load_yyp(project_root)
    if not yyp_data:
        return {"error": "Could not load project file"}
    
    resources = yyp_data.get("resources", [])
    included_files = yyp_data.get("IncludedFiles", [])
    folders = yyp_data.get("Folders", [])
    
    # Count by type
    type_counts: Dict[str, int] = {}
    for res in resources:
        path = res.get("id", {}).get("path", "")
        asset_type = _infer_asset_type(path)
        type_counts[asset_type] = type_counts.get(asset_type, 0) + 1
    
    if included_files:
        type_counts["includedfile"] = len(included_files)
    
    return {
        "total_resources": len(resources),
        "total_included_files": len(included_files),
        "total_folders": len(folders),
        "counts_by_type": type_counts
    }
