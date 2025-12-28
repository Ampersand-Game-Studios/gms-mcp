#!/usr/bin/env python3
"""workflow.py – High-level project utilities (Part C)

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
    • Progress bars (tqdm) where useful
    • Colourised output (colorama)
    • Global `yes` flag handled by callers (cli_ext)
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple

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

# ---------------------------------------------------------------------------
# Optional extras – tqdm + colorama
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
    plural = p.parts[0]
    mapping = {
        "scripts": "script",
        "objects": "object",
        "sprites": "sprite",
        "rooms": "room",
        "folders": "folder",
    }
    asset_type = mapping.get(plural, plural)
    if asset_type not in ASSET_TYPES:
        sys.exit(f"ERROR: Unrecognised asset path prefix '{plural}'.")
    folder_path = project_root / plural / p.parts[1]
    asset_name = p.parts[1]
    return asset_type, folder_path, asset_name


# ---------------------------------------------------------------------------
# C-1: Duplicate Asset
# ---------------------------------------------------------------------------

def duplicate_asset(project_root: Path, asset_path: str, new_name: str, *, yes: bool = False):
    project_root = Path(project_root)
    asset_type, src_folder, old_name = _asset_from_path(project_root, asset_path)

    # Get the plural form for directory path
    plural_mapping = {"script": "scripts", "object": "objects", "sprite": "sprites", "room": "rooms", "folder": "folders"}
    asset_dir = plural_mapping.get(asset_type, asset_type + "s")
    
    dst_folder = project_root / asset_dir / new_name
    if dst_folder.exists():
        sys.exit(f"ERROR: Destination asset '{new_name}' already exists.")

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
        sys.exit(f"ERROR: Could not load {new_yy} for updating")
    yy_data["name"] = new_name
    if "%Name" in yy_data:
        yy_data["%Name"] = new_name
    save_pretty_json_gm(new_yy, yy_data)

    # Update .yyp
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if yyp_data is None:
        sys.exit(f"ERROR: Could not load {yyp_path} for updating")
    rel_path = f"{asset_dir}/{new_name}/{new_name}.yy"
    resources = yyp_data.setdefault("resources", [])
    insert_into_resources(resources, new_name, rel_path)
    save_pretty_json_gm(yyp_path, yyp_data)

    print(_c("[OK] Duplicated asset → " + new_name, "green"))
    
    # Run post-operation maintenance (disabled in test environments)
    import os
    if not os.environ.get('PYTEST_CURRENT_TEST'):
        try:
            from .auto_maintenance import run_auto_maintenance
            print(_c("[MAINT] Running post-duplicate maintenance...", "blue"))
            result = run_auto_maintenance(str(project_root), fix_issues=True, verbose=True)
            
            if result.has_errors:
                print(_c("[WARN] Asset duplicated but maintenance found issues.", "yellow"))
            else:
                print(_c("[OK] Asset duplicated and validated successfully!", "green"))
        except ImportError:
            # Fallback if auto_maintenance not available
            pass
    else:
        print(_c("[OK] Asset duplicated successfully! (maintenance skipped in test)", "green"))
    return True


# ---------------------------------------------------------------------------
# C-2: Rename Asset
# ---------------------------------------------------------------------------

def rename_asset(project_root: Path, asset_path: str, new_name: str):
    project_root = Path(project_root)
    asset_type, src_folder, old_name = _asset_from_path(project_root, asset_path)

    # Get the plural form for directory path
    plural_mapping = {"script": "scripts", "object": "objects", "sprite": "sprites", "room": "rooms", "folder": "folders"}
    asset_dir = plural_mapping.get(asset_type, asset_type + "s")
    
    dst_folder = project_root / asset_dir / new_name
    if dst_folder.exists():
        sys.exit(f"ERROR: Destination name '{new_name}' already exists.")

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
        sys.exit(f"ERROR: Could not load {new_yy} for updating")
    yy_data["name"] = new_name
    if "%Name" in yy_data:
        yy_data["%Name"] = new_name
    save_pretty_json_gm(new_yy, yy_data)

    # Update .yyp entry
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if yyp_data is None:
        sys.exit(f"ERROR: Could not load {yyp_path} for updating")
    for res in yyp_data.get("resources", []):
        if res["id"]["path"] == asset_path:
            res["id"]["name"] = new_name
            res["id"]["path"] = f"{asset_dir}/{new_name}/{new_name}.yy"
            break
    # Resort resources array
    yyp_data["resources"].sort(key=lambda r: r["id"]["name"].lower())
    save_pretty_json_gm(yyp_path, yyp_data)

    print(_c(f"[OK] Renamed {old_name} → {new_name}", "green"))
    
    # COMPREHENSIVE REFERENCE UPDATE: Scan and update ALL references to the old asset
    try:
        from .reference_scanner import comprehensive_rename_asset
        print(_c("[SCAN] Performing comprehensive reference scan and update...", "blue"))
        success = comprehensive_rename_asset(project_root, old_name, new_name, asset_type)
        if not success:
            print(_c("[WARN] Warning: Some references may not have been fully updated", "yellow"))
    except ImportError:
        try:
            # Try absolute import for test environments
            from reference_scanner import comprehensive_rename_asset
            print(_c("[SCAN] Performing comprehensive reference scan and update...", "blue"))
            success = comprehensive_rename_asset(project_root, old_name, new_name, asset_type)
            if not success:
                print(_c("[WARN] Warning: Some references may not have been fully updated", "yellow"))
        except ImportError:
            print(_c("[WARN] Reference scanner not available - manual reference checks may be needed", "yellow"))
    
    # Run post-operation maintenance (disabled in test environments)
    import os
    if not os.environ.get('PYTEST_CURRENT_TEST'):
        try:
            from .auto_maintenance import run_auto_maintenance
            print(_c("[MAINT] Running post-rename maintenance...", "blue"))
            result = run_auto_maintenance(str(project_root), fix_issues=True, verbose=True)
            
            if result.has_errors:
                print(_c("[WARN] Asset renamed but maintenance found issues.", "yellow"))
            else:
                print(_c("[OK] Asset renamed and validated successfully!", "green"))
        except ImportError:
            # Fallback if auto_maintenance not available
            pass
    else:
        print(_c("[OK] Asset renamed successfully! (maintenance skipped in test)", "green"))
    return True

# ---------------------------------------------------------------------------
# C-3: Delete Asset
# ---------------------------------------------------------------------------

def delete_asset(project_root: Path, asset_path: str, *, dry_run: bool = False):
    project_root = Path(project_root)
    asset_type, folder_path, asset_name = _asset_from_path(project_root, asset_path)

    if dry_run:
        print(_c("[dry-run] Would delete folder " + str(folder_path), "yellow"))
    else:
        shutil.rmtree(folder_path, ignore_errors=True)
        print(_c("Deleted folder " + str(folder_path), "red"))

    # Update .yyp
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    resources_before = len(yyp_data.get("resources", []))
    yyp_data["resources"] = [r for r in yyp_data.get("resources", []) if r["id"]["name"] != asset_name]
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
            result = run_auto_maintenance(str(project_root), fix_issues=True, verbose=True)
            
            if result.has_errors:
                print(_c("[WARN] Asset deleted but maintenance found issues.", "yellow"))
            else:
                print(_c("[OK] Asset deleted and project validated successfully!", "green"))
        except ImportError:
            # Fallback if auto_maintenance not available
            pass
    return True

# ---------------------------------------------------------------------------
# C-4: Swap Sprite PNG
# ---------------------------------------------------------------------------

def swap_sprite_png(project_root: Path, sprite_asset_path: str, png_source: Path):
    project_root = Path(project_root)
    asset_type, folder_path, sprite_name = _asset_from_path(project_root, sprite_asset_path)
    if asset_type != "sprite":
        sys.exit("ERROR: swap_sprite_png only valid for sprites")

    yy_path = folder_path / f"{sprite_name}.yy"
    yy_data = load_json_loose(yy_path)
    frame_uuid = yy_data["frames"][0]["name"]
    target_png = folder_path / f"{frame_uuid}.png"

    shutil.copy2(png_source, target_png)
    print(_c(f"[OK] Replaced sprite image for {sprite_name}", "green"))
    return True

# ---------------------------------------------------------------------------
# C-5: Project Linter
# ---------------------------------------------------------------------------

def lint_project(project_root: Path) -> int:
    """Return number of problems detected (0 = clean)."""
    project_root = Path(project_root)
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)

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
        for yy in (project_root / top).rglob("*.yy"):
            rel = yy.relative_to(project_root).as_posix()
            if rel not in resource_paths:
                problems.append(f"Orphan .yy file not in .yyp: {rel}")

    # 4. JSON validity of each .yy
    for yy in project_root.rglob("*.yy"):
        try:
            load_json_loose(yy)
        except Exception as e:
            problems.append(f"Invalid JSON: {yy} – {e}")

    # ------------------------------------------------------------------
    # Report
    if not problems:
        print(_c("[OK] Project looks good!", "green"))
        return 0

    for p in problems:
        print(_c("[ERROR] " + p, "red"))
    print(_c(f"Found {len(problems)} problem(s)", "red"))
    return len(problems)

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
