#!/usr/bin/env python3
"""workflow.py - High-level project utilities (Part C)

This module provides advanced helper features on top of the basic CRUD
implemented in asset_helper.py.  All functions are intentionally thin and
focus on filesystem / .yyp manipulation.  They **never** call GameMaker
proper; they work purely on raw files.

Implemented Features:
    C-1 duplicate_asset
    C-2 rename_asset
    C-3 delete_asset
    C-4 swap_sprite_png
    C-5 lint_project

Optional Extras (6):
    - Progress bars (tqdm) where useful
    - Colourised output (colorama)
    - Global `yes` flag handled by callers (cli_ext)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Direct imports - no complex fallbacks needed
from .utils import (
    load_json_loose,
    save_pretty_json_gm,
    strip_trailing_commas,
    ensure_directory,
    find_yyp,
    insert_into_resources,
    insert_into_folders,
)
from .assets import ASSET_TYPES
from .exceptions import (
    AssetExistsError,
    AssetNotFoundError,
    InvalidAssetTypeError,
    JSONParseError,
)
from .results import OperationResult, AssetResult, MaintenanceResult

# ---------------------------------------------------------------------------
# Optional extras - tqdm + colorama
# ---------------------------------------------------------------------------

def _try_import(name: str):
    try:
        return __import__(name)
    except ModuleNotFoundError:
        return None

tqdm = _try_import("tqdm")
colorama = _try_import("colorama")
if colorama:
    colorama.init()


def _c(text: str, colour: str | None = None):
    """Return colorised text if colorama is present & output is a TTY."""
    if not sys.stdout.isatty() or not colorama or not colour:
        return text
    return getattr(colorama.Fore, colour.upper(), "") + text + colorama.Style.RESET_ALL

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_from_path(project_root: Path, asset_path: str):
    """Return (asset_type, asset_folder_path, asset_name) using .yyp-style path."""
    p = Path(asset_path)
    if len(p.parts) < 2:
        raise InvalidAssetTypeError(f"Invalid asset path '{asset_path}'. Expected '<folder>/<name>/<name>.yy'.")
    plural = p.parts[0]
    mapping = {
        "scripts": "script",
        "objects": "object",
        "sprites": "sprite",
        "rooms": "room",
        "folders": "folder",
        "fonts": "font",
        "shaders": "shader",
        "animcurves": "animcurve",
        "sounds": "sound",
        "paths": "path",
        "tilesets": "tileset",
        "timelines": "timeline",
        "sequences": "sequence",
        "notes": "note",
    }
    asset_type = mapping.get(plural, plural)
    if asset_type not in ASSET_TYPES:
        raise InvalidAssetTypeError(f"Unrecognised asset path prefix '{plural}'.")
    folder_path = project_root / plural / p.parts[1]
    asset_name = p.parts[1]
    return asset_type, folder_path, asset_name


# ---------------------------------------------------------------------------
# C-1: Duplicate Asset
# ---------------------------------------------------------------------------

def duplicate_asset(project_root: Path, asset_path: str, new_name: str, *, yes: bool = False) -> AssetResult:
    project_root = Path(project_root)
    asset_type, src_folder, old_name = _asset_from_path(project_root, asset_path)

    # Get the plural form for directory path
    plural_mapping = {"script": "scripts", "object": "objects", "sprite": "sprites", "room": "rooms", "folder": "folders"}
    asset_dir = plural_mapping.get(asset_type, asset_type + "s")
    
    dst_folder = project_root / asset_dir / new_name
    if dst_folder.exists():
        raise AssetExistsError(f"Destination asset '{new_name}' already exists.")

    # Copy with progress bar
    shutil.copytree(src_folder, dst_folder)

    # Rename key files (yy + optional gml)
    old_yy = dst_folder / f"{old_name}.yy"
    new_yy = dst_folder / f"{new_name}.yy"
    old_yy.rename(new_yy)

    # Rename script gml stub if applicable
    if asset_type == "script":
        old_gml = dst_folder / f"{old_name}.gml"
        if old_gml.exists():
            new_gml = dst_folder / f"{new_name}.gml"
            old_gml.rename(new_gml)
            _patch_gml_stub(new_gml, new_name)

    # Patch YY names (but NOT UUIDs)
    yy_data = load_json_loose(new_yy)
    if yy_data is None:
        raise JSONParseError(f"Could not load {new_yy} for updating")
    yy_data["name"] = new_name
    if "%Name" in yy_data:
        yy_data["%Name"] = new_name
    save_pretty_json_gm(new_yy, yy_data)

    # Update .yyp
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if yyp_data is None:
        raise JSONParseError(f"Could not load {yyp_path} for updating")
    rel_path = f"{asset_dir}/{new_name}/{new_name}.yy"
    resources = yyp_data.setdefault("resources", [])
    insert_into_resources(resources, new_name, rel_path)
    save_pretty_json_gm(yyp_path, yyp_data)

    message = f"[OK] Duplicated asset -> {new_name}"
    print(_c(message, "green"))
    
    warnings = []
    # Run post-operation maintenance (disabled in test environments)
    import os
    if not os.environ.get('PYTEST_CURRENT_TEST'):
        try:
            from .auto_maintenance import run_auto_maintenance
            print(_c("[MAINT] Running post-duplicate maintenance...", "blue"))
            m_result = run_auto_maintenance(str(project_root), fix_issues=True, verbose=True)
            
            if m_result.has_errors:
                warn_msg = "Asset duplicated but maintenance found issues."
                print(_c(f"[WARN] {warn_msg}", "yellow"))
                warnings.append(warn_msg)
            else:
                print(_c("[OK] Asset duplicated and validated successfully!", "green"))
        except ImportError:
            # Fallback if auto_maintenance not available
            pass
    else:
        print(_c("[OK] Asset duplicated successfully! (maintenance skipped in test)", "green"))
        
    return AssetResult(
        success=True,
        message=message,
        warnings=warnings,
        asset_name=new_name,
        asset_type=asset_type,
        asset_path=rel_path
    )


# ---------------------------------------------------------------------------
# C-2: Rename Asset
# ---------------------------------------------------------------------------

def rename_asset(project_root: Path, asset_path: str, new_name: str) -> AssetResult:
    project_root = Path(project_root)
    asset_type, src_folder, old_name = _asset_from_path(project_root, asset_path)

    # Get the plural form for directory path
    plural_mapping = {"script": "scripts", "object": "objects", "sprite": "sprites", "room": "rooms", "folder": "folders"}
    asset_dir = plural_mapping.get(asset_type, asset_type + "s")
    
    dst_folder = project_root / asset_dir / new_name
    if dst_folder.exists():
        raise AssetExistsError(f"Destination name '{new_name}' already exists.")

    src_folder.rename(dst_folder)

    # Rename key files
    old_yy = dst_folder / f"{old_name}.yy"
    new_yy = dst_folder / f"{new_name}.yy"
    old_yy.rename(new_yy)

    if asset_type == "script":
        old_gml = dst_folder / f"{old_name}.gml"
        if old_gml.exists():
            new_gml = dst_folder / f"{new_name}.gml"
            old_gml.rename(new_gml)
            _patch_gml_stub(new_gml, new_name)

    # Patch YY
    yy_data = load_json_loose(new_yy)
    if yy_data is None:
        raise JSONParseError(f"Could not load {new_yy} for updating")
    yy_data["name"] = new_name
    if "%Name" in yy_data:
        yy_data["%Name"] = new_name
    save_pretty_json_gm(new_yy, yy_data)

    # Update .yyp entry
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if yyp_data is None:
        raise JSONParseError(f"Could not load {yyp_path} for updating")
    
    new_rel_path = f"{asset_dir}/{new_name}/{new_name}.yy"
    for res in yyp_data.get("resources", []):
        if res["id"]["path"] == asset_path:
            res["id"]["name"] = new_name
            res["id"]["path"] = new_rel_path
            break
    # Resort resources array
    yyp_data["resources"].sort(key=lambda r: r["id"]["name"].lower())
    save_pretty_json_gm(yyp_path, yyp_data)

    message = f"[OK] Renamed {old_name} -> {new_name}"
    print(_c(message, "green"))
    
    warnings = []
    # COMPREHENSIVE REFERENCE UPDATE: Scan and update ALL references to the old asset
    try:
        from .reference_scanner import comprehensive_rename_asset
        print(_c("[SCAN] Performing comprehensive reference scan and update...", "blue"))
        ref_success = comprehensive_rename_asset(project_root, old_name, new_name, asset_type)
        if not ref_success:
            warn_msg = "Some references may not have been fully updated"
            print(_c(f"[WARN] {warn_msg}", "yellow"))
            warnings.append(warn_msg)
    except ImportError:
        try:
            # Try absolute import for test environments
            from reference_scanner import comprehensive_rename_asset
            print(_c("[SCAN] Performing comprehensive reference scan and update...", "blue"))
            ref_success = comprehensive_rename_asset(project_root, old_name, new_name, asset_type)
            if not ref_success:
                warn_msg = "Some references may not have been fully updated"
                print(_c(f"[WARN] {warn_msg}", "yellow"))
                warnings.append(warn_msg)
        except ImportError:
            warn_msg = "Reference scanner not available - manual reference checks may be needed"
            print(_c(f"[WARN] {warn_msg}", "yellow"))
            warnings.append(warn_msg)
    
    # Run post-operation maintenance (disabled in test environments)
    import os
    if not os.environ.get('PYTEST_CURRENT_TEST'):
        try:
            from .auto_maintenance import run_auto_maintenance
            print(_c("[MAINT] Running post-rename maintenance...", "blue"))
            m_result = run_auto_maintenance(str(project_root), fix_issues=True, verbose=True)
            
            if m_result.has_errors:
                warn_msg = "Asset renamed but maintenance found issues."
                print(_c(f"[WARN] {warn_msg}", "yellow"))
                warnings.append(warn_msg)
            else:
                print(_c("[OK] Asset renamed and validated successfully!", "green"))
        except ImportError:
            # Fallback if auto_maintenance not available
            pass
    else:
        print(_c("[OK] Asset renamed successfully! (maintenance skipped in test)", "green"))
        
    return AssetResult(
        success=True,
        message=message,
        warnings=warnings,
        asset_name=new_name,
        asset_type=asset_type,
        asset_path=new_rel_path
    )

# ---------------------------------------------------------------------------
# C-3: Delete Asset
# ---------------------------------------------------------------------------

def delete_asset(project_root: Path, asset_path: str, *, dry_run: bool = False) -> OperationResult:
    project_root = Path(project_root)
    asset_type, folder_path, asset_name = _asset_from_path(project_root, asset_path)

    if dry_run:
        message = "[dry-run] Would delete folder " + str(folder_path)
        print(_c(message, "yellow"))
    else:
        shutil.rmtree(folder_path, ignore_errors=True)
        message = "Deleted folder " + str(folder_path)
        print(_c(message, "red"))

    # Update .yyp
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if yyp_data is None:
        raise JSONParseError(f"Could not load {yyp_path} for updating")
        
    resources_before = len(yyp_data.get("resources", []))
    yyp_data["resources"] = [r for r in yyp_data.get("resources", []) if r["id"]["name"] != asset_name]
    
    warnings = []
    if len(yyp_data["resources"]) != resources_before:
        if dry_run:
            print(_c("[dry-run] Would remove .yyp resource entry", "yellow"))
        else:
            save_pretty_json_gm(yyp_path, yyp_data)
            print(_c("Removed .yyp entry", "red"))
    
    # Run post-operation maintenance (only if not dry run)
    if not dry_run:
        try:
            from .auto_maintenance import run_auto_maintenance
            print(_c("[MAINT] Running post-delete maintenance...", "blue"))
            m_result = run_auto_maintenance(str(project_root), fix_issues=True, verbose=True)
            
            if m_result.has_errors:
                warn_msg = "Asset deleted but maintenance found issues."
                print(_c(f"[WARN] {warn_msg}", "yellow"))
                warnings.append(warn_msg)
            else:
                print(_c("[OK] Asset deleted and project validated successfully!", "green"))
        except ImportError:
            # Fallback if auto_maintenance not available
            pass
            
    return OperationResult(
        success=True,
        message=message,
        warnings=warnings
    )


def _resolve_asset_path(project_root: Path, asset_type: str, asset_name: str) -> Optional[str]:
    """Resolve an asset type/name pair to a .yy path from the .yyp resource list."""
    from .introspection import list_assets_by_type

    assets = list_assets_by_type(project_root, asset_type_filter=asset_type, include_included_files=True)
    for asset in assets.get(asset_type, []):
        if asset.get("name") == asset_name:
            path = asset.get("path")
            if isinstance(path, str):
                return path
    return None


def _collect_incoming_dependencies(project_root: Path, asset_name: str) -> List[Dict[str, Any]]:
    """Find all incoming graph edges that point to the target asset."""
    from .introspection import build_asset_graph

    graph = build_asset_graph(project_root, deep=True)
    node_by_id = {
        node.get("id"): node for node in graph.get("nodes", []) if isinstance(node, dict)
    }

    incoming: List[Dict[str, Any]] = []
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if edge.get("to") != asset_name:
            continue
        source_name = edge.get("from")
        if not isinstance(source_name, str) or source_name == asset_name:
            continue

        source_node = node_by_id.get(source_name, {})
        incoming.append(
            {
                "asset_name": source_name,
                "asset_type": source_node.get("type", "unknown"),
                "asset_path": source_node.get("path", ""),
                "relation": edge.get("relation", "unknown"),
            }
        )

    incoming.sort(key=lambda d: (str(d.get("asset_type", "")), str(d.get("asset_name", ""))))
    return incoming


def _cleanup_symbol_references(project_root: Path, asset_name: str) -> Dict[str, Any]:
    """
    Best-effort cleanup: replace direct symbol references in GML code with `undefined`.
    This intentionally avoids rewriting JSON metadata structure.
    """
    pattern = re.compile(rf"\b{re.escape(asset_name)}\b")
    roots = [project_root / "scripts", project_root / "objects", project_root / "rooms"]
    touched_files: List[str] = []
    replacements = 0

    for root in roots:
        if not root.exists():
            continue
        for gml_path in root.rglob("*.gml"):
            try:
                content = gml_path.read_text(encoding="utf-8")
            except Exception:
                continue

            match_count = len(pattern.findall(content))
            if match_count == 0:
                continue

            patched = pattern.sub("undefined", content)
            if patched == content:
                continue

            gml_path.write_text(patched, encoding="utf-8")
            replacements += match_count
            touched_files.append(str(gml_path.relative_to(project_root).as_posix()))

    return {
        "replacement_token": "undefined",
        "replacements": replacements,
        "files": sorted(touched_files),
    }


def safe_delete_asset(
    project_root: Path,
    asset_type: str,
    asset_name: str,
    *,
    force: bool = False,
    clean_refs: bool = False,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Dependency-aware delete workflow.
    Defaults to dry-run and blocks apply when incoming dependencies exist unless force=True.
    """
    project_root = Path(project_root)

    asset_path = _resolve_asset_path(project_root, asset_type, asset_name)
    if not asset_path:
        return {
            "ok": False,
            "blocked": False,
            "asset_type": asset_type,
            "asset_name": asset_name,
            "error": f"Asset '{asset_name}' of type '{asset_type}' was not found.",
            "dependencies": [],
            "dependency_count": 0,
            "deleted": False,
            "cleaned_refs": {"replacements": 0, "files": []},
            "warnings": [],
        }

    dependencies = _collect_incoming_dependencies(project_root, asset_name)
    blocked = len(dependencies) > 0 and not force
    warnings: List[str] = []
    cleaned_refs: Dict[str, Any] = {"replacements": 0, "files": []}

    if blocked:
        warnings.append(
            "Deletion blocked because dependent assets reference this target. Use force=True to continue."
        )

    if dry_run or blocked:
        message = (
            f"[SAFE DELETE] {'Blocked' if blocked else 'Dry-run'} for {asset_type} '{asset_name}' "
            f"({len(dependencies)} dependent reference(s))."
        )
        print(_c(message, "yellow"))
        return {
            "ok": not blocked,
            "blocked": blocked,
            "asset_type": asset_type,
            "asset_name": asset_name,
            "asset_path": asset_path,
            "dry_run": dry_run,
            "force": force,
            "clean_refs": clean_refs,
            "dependencies": dependencies,
            "dependency_count": len(dependencies),
            "deleted": False,
            "cleaned_refs": cleaned_refs,
            "warnings": warnings,
        }

    if clean_refs and dependencies:
        cleaned_refs = _cleanup_symbol_references(project_root, asset_name)
        warnings.append(
            "Reference cleanup is best-effort and currently rewrites direct GML symbol tokens only."
        )

    delete_result = delete_asset(project_root, asset_path, dry_run=False)
    warnings.extend(delete_result.warnings)

    return {
        "ok": bool(delete_result.success),
        "blocked": False,
        "asset_type": asset_type,
        "asset_name": asset_name,
        "asset_path": asset_path,
        "dry_run": False,
        "force": force,
        "clean_refs": clean_refs,
        "dependencies": dependencies,
        "dependency_count": len(dependencies),
        "deleted": bool(delete_result.success),
        "cleaned_refs": cleaned_refs,
        "warnings": warnings,
        "message": delete_result.message,
    }

# ---------------------------------------------------------------------------
# C-4: Swap Sprite PNG
# ---------------------------------------------------------------------------

def swap_sprite_png(project_root: Path, sprite_asset_path: str, png_source: Path, frame_index: int = 0) -> OperationResult:
    """Replace a sprite frame's PNG source.
    
    Args:
        project_root: Project root directory
        sprite_asset_path: Sprite asset path (e.g., "sprites/spr_player/spr_player.yy")
        png_source: Path to new PNG file
        frame_index: Frame index to replace (0-indexed, default: 0 for backwards compat)
    """
    project_root = Path(project_root)
    asset_type, folder_path, sprite_name = _asset_from_path(project_root, sprite_asset_path)
    if asset_type != "sprite":
        raise InvalidAssetTypeError("swap_sprite_png only valid for sprites")

    yy_path = folder_path / f"{sprite_name}.yy"
    yy_data = load_json_loose(yy_path)
    if yy_data is None:
        raise JSONParseError(f"Could not load {yy_path}")
    
    # Validate frame_index
    frame_count = len(yy_data["frames"])
    if frame_index < 0 or frame_index >= frame_count:
        raise ValueError(
            f"Invalid frame_index {frame_index}: sprite '{sprite_name}' has "
            f"{frame_count} frame(s) (valid: 0-{frame_count-1})"
        )
        
    frame_uuid = yy_data["frames"][frame_index]["name"]
    layer_uuid = yy_data["layers"][0]["name"]
    target_png = folder_path / f"{frame_uuid}.png"
    layer_png = folder_path / "layers" / frame_uuid / f"{layer_uuid}.png"

    png_source = Path(png_source)
    if not png_source.is_absolute():
        png_source = (project_root / png_source).resolve()

    if not png_source.exists():
        raise FileNotFoundError(f"PNG source not found: {png_source}")

    # If the user accidentally points at the current sprite frame PNG, treat as a no-op.
    try:
        if png_source.resolve() == target_png.resolve():
            message = f"[OK] Sprite image for {sprite_name} frame {frame_index} already matches the provided PNG (no-op)"
            print(_c(message, "green"))
            return OperationResult(success=True, message=message)
    except Exception:
        # If resolve fails for any reason, fall back to attempting the copy.
        pass

    # Windows can lock files; use a temp file + replace, with small retries.
    tmp_png = target_png.with_name(target_png.name + ".swap_tmp")
    last_err: Exception | None = None
    for attempt in range(1, 6):
        try:
            shutil.copy2(png_source, tmp_png)
            try:
                os.replace(tmp_png, target_png)
            finally:
                if tmp_png.exists():
                    # Best-effort cleanup
                    try:
                        tmp_png.unlink()
                    except Exception:
                        pass
            
            # Also update the layer PNG if it exists
            if layer_png.parent.exists():
                shutil.copy2(png_source, layer_png)
            
            frame_msg = f" frame {frame_index}" if frame_count > 1 else ""
            message = f"[OK] Replaced sprite image for {sprite_name}{frame_msg}"
            print(_c(message, "green"))
            return OperationResult(success=True, message=message)
        except PermissionError as e:
            last_err = e
            time.sleep(0.1 * attempt)
        except Exception as e:
            last_err = e
            break

    raise PermissionError(
        f"Could not replace sprite PNG for {sprite_name}. Target may be locked by another process. "
        f"Close GameMaker/Explorer preview and retry. Last error: {last_err}"
    )

# ---------------------------------------------------------------------------
# C-5: Project Linter
# ---------------------------------------------------------------------------

def lint_project(project_root: Path) -> MaintenanceResult:
    """Check for common project issues."""
    project_root = Path(project_root)
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if yyp_data is None:
        raise JSONParseError(f"Could not load {yyp_path}")

    problems: List[str] = []

    # 1. Resource order
    sorted_names = sorted(r["id"]["name"] for r in yyp_data.get("resources", []))
    actual_names = [r["id"]["name"] for r in yyp_data.get("resources", [])]
    if sorted_names != actual_names:
        problems.append("Resources not alphabetically ordered in .yyp")

    # 2. Missing files
    for res in yyp_data.get("resources", []):
        p = project_root / res["id"]["path"]
        if not p.exists():
            problems.append(f"Missing file: {p}")

    # 3. Extra folders not in .yyp (only scripts/objects/sprites/rooms)
    resource_paths = set(r["id"]["path"] for r in yyp_data.get("resources", []))
    for top in ["scripts", "objects", "sprites", "rooms"]:
        top_dir = project_root / top
        if top_dir.exists():
            for yy in top_dir.rglob("*.yy"):
                rel = yy.relative_to(project_root).as_posix()
                if rel not in resource_paths:
                    problems.append(f"Orphan .yy file not in .yyp: {rel}")

    # 4. JSON validity of each .yy
    for yy in project_root.rglob("*.yy"):
        try:
            if load_json_loose(yy) is None:
                problems.append(f"Invalid JSON: {yy}")
        except Exception as e:
            problems.append(f"Invalid JSON: {yy} - {e}")

    # ------------------------------------------------------------------
    # Report
    if not problems:
        message = "[OK] Project looks good!"
        print(_c(message, "green"))
        return MaintenanceResult(
            success=True,
            message=message,
            issues_found=0,
            issues_fixed=0
        )

    for p in problems:
        print(_c("[ERROR] " + p, "red"))
    
    error_msg = f"Found {len(problems)} problem(s)"
    print(_c(error_msg, "red"))
    
    return MaintenanceResult(
        success=False,
        message=error_msg,
        issues_found=len(problems),
        issues_fixed=0,
        details=problems
    )

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _copy_tree(src: Path, dst: Path):
    """Recursive copy with optional progress bar."""
    src = Path(src)
    dst = Path(dst)
    # Gather list for progress bar
    all_files = [p for p in src.rglob("*") if p.is_file()]
    iterator = all_files
    if tqdm and sys.stdout.isatty():
        iterator = tqdm.tqdm(all_files, desc="Copy", unit="file", leave=False)
    for p in iterator:
        rel = p.relative_to(src)
        target = dst / rel
        ensure_directory(target.parent)
        shutil.copy2(p, target)


def _patch_gml_stub(gml_file: Path, new_name: str):
    """Replace function name inside auto-generated stub."""
    try:
        text = gml_file.read_text(encoding="utf-8")
        # Very naive replacement of first word after "function "
        patched = []
        for line in text.splitlines():
            if line.strip().startswith("function "):
                patched.append(f"function {new_name}() {{")
            else:
                patched.append(line)
        gml_file.write_text("\n".join(patched), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    print("This module is intended to be imported, not run directly. Use cli_ext.py instead.") 
