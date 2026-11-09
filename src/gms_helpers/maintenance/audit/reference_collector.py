"""
Reference Collection Engine - Phase 1 & 2 Implementation

This module implements:
- Phase 1: Authoritative JSON graph parsing and naming convention inference
- Phase 2: Case-insensitive path handling and static string search
"""

import os
import json
from pathlib import Path
from typing import Any, Set, Dict, List, Tuple, Optional
from collections import defaultdict

from ...diagnostics import Diagnostic, CODE_REFERENCE_MISSING, CODE_ORPHAN_FILE, CODE_CASE_MISMATCH
from ...event_model import event_filename
from ...exceptions import ValidationError
from ...path_safety import project_file_path
from ...utils import load_json, find_yyp_file
from ..path_utils import (
    build_filesystem_map,
    get_gamemaker_files,
    normalize_path,
)
from ..static_search import (
    find_string_references_in_gml,
    cross_reference_strings_to_files,
    identify_derivable_orphans,
)


class ReferenceCollector:
    """Collects all asset references from GameMaker project files."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.referenced_files: Set[str] = set()
        self.primary_assets: Dict[str, Dict] = {}
        self.parsing_queue: List[Path] = []

    def _add_reference(self, file_path: str):
        """Record a project-relative reference, keeping its exact spelling.

        Spelling is preserved so the audit can detect references whose case
        differs from the file on disk.
        """
        self.referenced_files.add(str(file_path).replace("\\", "/"))

    def _add_existing(self, path: Path) -> None:
        if path.is_file():
            self._add_reference(path.relative_to(self.project_root).as_posix())

    def collect_all_references(self) -> Set[str]:
        """
        Main entry point - collect all referenced files in the project.

        Returns:
            Set of relative file paths that are referenced by the project
        """
        print("[SCAN] Phase 1: Collecting references from authoritative JSON graph...")

        # Step 1: Load primary assets from .yyp
        self._load_primary_assets()

        # Step 2: Process all .yy files to find companions
        self._process_asset_queue()

        # Step 3: Apply naming convention inference
        self._apply_naming_conventions()

        print(f"[OK] Reference collection complete: {len(self.referenced_files)} files referenced")
        return self.referenced_files

    def _load_primary_assets(self):
        """Load all primary assets from the .yyp file."""
        try:
            # Change to the project directory first
            original_cwd = os.getcwd()
            os.chdir(self.project_root)
            try:
                yyp_path = find_yyp_file()
                yyp_data = load_json(yyp_path)
            finally:
                os.chdir(original_cwd)

            print(f"[REPORT] Loading primary assets from {os.path.basename(yyp_path)}")

            # Add the .yyp file itself as referenced
            self._add_reference(yyp_path)
            self._add_project_level_files(yyp_path, yyp_data)

            # Process all resources in the .yyp
            resources = yyp_data.get("resources", [])
            for resource in resources:
                if "id" in resource and "path" in resource["id"]:
                    asset_path = resource["id"]["path"]
                    self._add_reference(asset_path)

                    # Queue .yy files for detailed parsing
                    if asset_path.endswith(".yy"):
                        full_path = project_file_path(asset_path, project_root=self.project_root)
                        if full_path.exists():
                            self.parsing_queue.append(full_path)

            print(f"[PACKAGE] Found {len(resources)} primary resources")
            print(f"[SYNC] Queued {len(self.parsing_queue)} .yy files for parsing")

        except Exception as e:
            print(f"[ERROR] Error loading .yyp file: {e}")
            raise

    def _add_project_level_files(self, yyp_name: str, yyp_data: Dict) -> None:
        """Reference files the project owns outside its resource list."""
        # The IDE's resource-order sidecar.
        self._add_existing(self.project_root / f"{Path(yyp_name).stem}.resource_order")

        # Platform options (options/<platform>/options_<platform>.yy, icons, splash
        # images) are managed by the IDE and loaded whether or not they are listed.
        options_dir = self.project_root / "options"
        if options_dir.is_dir():
            for option_file in options_dir.rglob("*"):
                self._add_existing(option_file)

        # Included files (datafiles) are registered by folder + name.
        for included in yyp_data.get("IncludedFiles", []) or []:
            if not isinstance(included, dict):
                continue
            name = included.get("name") or included.get("fileName")
            folder = str(included.get("filePath") or "datafiles").replace("\\", "/").removeprefix("${project_dir}/")
            if isinstance(name, str) and name:
                try:
                    self._add_existing(
                        project_file_path(f"{folder.rstrip('/')}/{name}", project_root=self.project_root)
                    )
                except ValidationError:
                    continue

    def _process_asset_queue(self):
        """Process all queued .yy files to find their companion files."""
        processed = 0

        while self.parsing_queue:
            asset_path = self.parsing_queue.pop(0)
            try:
                self._process_single_asset(asset_path)
                processed += 1
            except Exception as e:
                print(f"[WARN]  Error processing {asset_path}: {e}")

        print(f"[MAINT] Processed {processed} asset files")

    def _process_single_asset(self, asset_path: Path):
        """Process a single .yy file to find its companion files."""
        try:
            asset_data = load_json(str(asset_path))
            asset_type = self._determine_asset_type(asset_data, asset_path)

            if asset_type == "object":
                self._process_object_asset(asset_path, asset_data)
            elif asset_type == "script":
                self._process_script_asset(asset_path, asset_data)
            elif asset_type == "sprite":
                self._process_sprite_asset(asset_path, asset_data)
            elif asset_type == "sound":
                self._process_sound_asset(asset_path, asset_data)
            elif asset_type == "room":
                self._process_room_asset(asset_path, asset_data)
            elif asset_type == "font":
                self._process_font_asset(asset_path, asset_data)
            elif asset_type == "shader":
                self._process_shader_asset(asset_path, asset_data)
            elif asset_type == "animcurve":
                self._process_animcurve_asset(asset_path, asset_data)
            elif asset_type == "sequence":
                self._process_sequence_asset(asset_path, asset_data)
            elif asset_type == "tileset":
                self._process_tileset_asset(asset_path, asset_data)
            elif asset_type == "timeline":
                self._process_timeline_asset(asset_path, asset_data)
            elif asset_type == "path":
                self._process_path_asset(asset_path, asset_data)
            elif asset_type == "extension":
                self._process_extension_asset(asset_path, asset_data)
            elif asset_type == "note":
                self._add_existing(asset_path.parent / f"{asset_path.stem}.txt")
            # Note: folders have no companion files

        except Exception as e:
            print(f"[WARN]  Error processing asset {asset_path}: {e}")

    def _determine_asset_type(self, asset_data: Dict, asset_path: Path) -> str:
        """Determine the type of GameMaker asset from its data."""
        # Check the $GM type tag, then the older resourceType field
        tags = [key[3:] for key in asset_data.keys() if key.startswith("$GM")]
        resource_type = asset_data.get("resourceType")
        if isinstance(resource_type, str) and resource_type.startswith("GM"):
            tags.append(resource_type[2:])
        for tag in tags:
            gm_type = tag.lower()
            return "note" if gm_type == "notes" else gm_type

        # Path-based detection from the project-relative top-level directory
        try:
            top = asset_path.resolve().relative_to(self.project_root).parts[0].casefold()
        except (ValueError, IndexError):
            top = ""
        by_directory = {
            "objects": "object",
            "sprites": "sprite",
            "sounds": "sound",
            "rooms": "room",
            "fonts": "font",
            "shaders": "shader",
            "scripts": "script",
            "folders": "folder",
            "tilesets": "tileset",
            "timelines": "timeline",
            "extensions": "extension",
            "notes": "note",
        }
        if top in by_directory:
            return by_directory[top]
        parent_dir = asset_path.parent.name
        if parent_dir.startswith("o_"):
            return "object"
        elif parent_dir.startswith("spr_"):
            return "sprite"
        elif parent_dir.startswith("snd_") or parent_dir.startswith("mus_"):
            return "sound"
        elif parent_dir.startswith("r_"):
            return "room"
        elif parent_dir.startswith("fnt_"):
            return "font"
        elif parent_dir.startswith("shd_"):
            return "shader"
        elif "scripts" in str(asset_path):
            return "script"
        elif "folders" in str(asset_path):
            return "folder"

        return "unknown"

    def _process_object_asset(self, asset_path: Path, asset_data: Dict):
        """Process object asset to find event files."""
        event_list = asset_data.get("eventList", [])
        asset_dir = asset_path.parent

        for event in event_list:
            event_type = event.get("eventType", 0)
            event_num = event.get("eventNum", 0)
            collision_object = event.get("collisionObjectId", None)

            # Generate event filename using GameMaker conventions
            event_filename = self._get_event_filename(event_type, event_num, collision_object)
            # GameMaker always pairs a listed event with its .gml, so the exact path is a
            # reference even when the file is missing or only matches case-insensitively.
            if event_filename:
                self._add_reference((asset_dir / event_filename).relative_to(self.project_root).as_posix())

    def _process_script_asset(self, asset_path: Path, asset_data: Dict):
        """Process script asset to find companion .gml file."""
        script_name = asset_path.stem
        script_dir = asset_path.parent
        gml_path = script_dir / f"{script_name}.gml"

        # A script's .gml is required, so its exact path is always a reference.
        self._add_reference(gml_path.relative_to(self.project_root).as_posix())

    def _process_sprite_asset(self, asset_path: Path, asset_data: Dict):
        """Process sprite asset to find image files."""
        sprite_dir = asset_path.parent

        # Add main sprite images
        frames = asset_data.get("frames", [])
        for frame in frames:
            if isinstance(frame, dict) and "name" in frame:
                image_name = frame["name"]
                image_path = sprite_dir / f"{image_name}.png"
                if image_path.exists():
                    rel_path = str(image_path.relative_to(self.project_root))
                    self._add_reference(rel_path)

        # Add layer images
        layers_dir = sprite_dir / "layers"
        if layers_dir.exists():
            for layer_dir in layers_dir.iterdir():
                if layer_dir.is_dir():
                    for image_file in layer_dir.glob("*.png"):
                        rel_path = str(image_file.relative_to(self.project_root))
                        self._add_reference(rel_path)

    def _process_sound_asset(self, asset_path: Path, asset_data: Dict):
        """Process sound asset to find audio files."""
        sound_file = asset_data.get("soundFile")
        if sound_file:
            sound_dir = asset_path.parent
            sound_path = sound_dir / sound_file
            if sound_path.exists():
                rel_path = str(sound_path.relative_to(self.project_root))
                self._add_reference(rel_path)

    def _process_room_asset(self, asset_path: Path, asset_data: Dict):
        """Process room asset to find room and instance creation-code files."""
        room_dir = asset_path.parent
        creation_code = asset_data.get("creationCodeFile")
        if isinstance(creation_code, str) and creation_code:
            relative = creation_code.replace("\\", "/").removeprefix("${project_dir}/")
            try:
                self._add_existing(project_file_path(relative, project_root=self.project_root))
            except ValidationError:
                pass

        def walk_layers(layers: Any) -> None:
            for layer in layers if isinstance(layers, list) else []:
                if not isinstance(layer, dict):
                    continue
                for instance in layer.get("instances", []) or []:
                    if isinstance(instance, dict) and instance.get("hasCreationCode") and instance.get("name"):
                        self._add_existing(room_dir / f"InstanceCreationCode_{instance['name']}.gml")
                walk_layers(layer.get("layers"))

        walk_layers(asset_data.get("layers"))

    def _process_font_asset(self, asset_path: Path, asset_data: Dict):
        """Process font asset: GameMaker stores the generated glyph sheet as <name>.png."""
        self._add_existing(asset_path.parent / f"{asset_path.stem}.png")

    def _process_shader_asset(self, asset_path: Path, asset_data: Dict):
        """Process shader asset to find shader files."""
        shader_dir = asset_path.parent
        shader_name = asset_path.stem

        # Look for vertex and fragment shader files
        for shader_type in ["vsh", "fsh"]:
            shader_file = shader_dir / f"{shader_name}.{shader_type}"
            if shader_file.exists():
                rel_path = str(shader_file.relative_to(self.project_root))
                self._add_reference(rel_path)

    def _process_animcurve_asset(self, asset_path: Path, asset_data: Dict):
        """Process animation curve asset."""
        # AnimCurves typically don't have companion files
        pass

    def _process_sequence_asset(self, asset_path: Path, asset_data: Dict):
        """Process sequence asset."""
        # Sequences typically don't have companion files
        pass

    def _process_tileset_asset(self, asset_path: Path, asset_data: Dict):
        """Process tileset asset: the IDE writes the packed tiles to output_tileset.png."""
        self._add_existing(asset_path.parent / "output_tileset.png")

    def _process_timeline_asset(self, asset_path: Path, asset_data: Dict):
        """Process timeline asset to find its moment_<n>.gml files."""
        for moment in asset_data.get("momentList", []) or []:
            if isinstance(moment, dict) and isinstance(moment.get("moment"), int):
                self._add_existing(asset_path.parent / f"moment_{moment['moment']}.gml")

    def _process_extension_asset(self, asset_path: Path, asset_data: Dict):
        """Process extension asset to find the library/source files it lists."""
        for entry in asset_data.get("files", []) or []:
            filename = entry.get("filename") if isinstance(entry, dict) else None
            if isinstance(filename, str) and filename and "/" not in filename and "\\" not in filename:
                self._add_existing(asset_path.parent / filename)

    def _process_path_asset(self, asset_path: Path, asset_data: Dict):
        """Process path asset."""
        # Paths typically don't have companion files
        pass

    def _get_event_filename(self, event_type: int, event_num: int, collision_object: Any = None) -> Optional[str]:
        """
        Generate event filename based on GameMaker's naming convention.

        Args:
            event_type: The eventType from the object's eventList
            event_num: The eventNum from the object's eventList
            collision_object: The collisionObjectId (for collision events)

        Returns:
            Event filename or None if invalid
        """
        try:
            return event_filename(event_type, event_num, collision_object)
        except ValidationError:
            return None

    def _apply_naming_conventions(self):
        """Apply naming convention inference for additional files."""
        # This is where we could add logic to infer additional files
        # based on naming patterns, but for now the explicit parsing
        # should cover most cases
        pass


def collect_project_references(project_root: str = ".") -> Set[str]:
    """
    Convenience function to collect all project references.

    Args:
        project_root: Path to the GameMaker project root

    Returns:
        Set of relative file paths that are referenced by the project
    """
    collector = ReferenceCollector(project_root)
    return collector.collect_all_references()


def comprehensive_analysis(project_root: str = ".") -> Dict:
    """
    Perform comprehensive Phase 1 + Phase 2 analysis of the project.

    Args:
        project_root: Path to the GameMaker project root

    Returns:
        Dict containing complete analysis results
    """
    print("[SCAN] Starting comprehensive analysis (Phase 1 + Phase 2)...")

    # Phase 1: Collect references from JSON graph
    collector = ReferenceCollector(project_root)
    referenced_files = collector.collect_all_references()

    print("[SCAN] Phase 2: Building filesystem map and performing static analysis...")

    # Phase 2: Build filesystem maps. References keep their exact spelling, so
    # a reference that only matches a file case-insensitively is a case mismatch.
    filesystem_map = build_filesystem_map(project_root)
    filesystem_files = get_gamemaker_files(project_root)
    all_files = set(filesystem_map.values()) | set(filesystem_files)
    all_by_fold: Dict[str, str] = {}
    for actual in sorted(all_files):
        all_by_fold.setdefault(actual.casefold(), actual)

    path_categories: Dict[str, List[str]] = {"found_exact": [], "found_case_diff": [], "missing": []}
    for reference in sorted(referenced_files):
        if reference in all_files:
            path_categories["found_exact"].append(reference)
        elif reference.casefold() in all_by_fold:
            path_categories["found_case_diff"].append(f"{reference} -> {all_by_fold[reference.casefold()]}")
        else:
            path_categories["missing"].append(reference)

    referenced_folded = {reference.casefold() for reference in referenced_files}
    referenced_files_normalized = {normalize_path(p, project_root) for p in referenced_files}
    filesystem_files_normalized = {normalize_path(p, project_root) for p in filesystem_files}

    # Static string search in .gml files
    string_refs = find_string_references_in_gml(project_root)
    string_cross_ref = cross_reference_strings_to_files(string_refs, filesystem_files, filesystem_map, project_root)

    # Identify derivable orphans (use normalized sets for comparison)
    derivable_orphans = identify_derivable_orphans(
        filesystem_files_normalized, referenced_files_normalized, string_refs
    )

    # Orphans: files on disk no reference matches, even case-insensitively.
    true_orphans = {path for path in filesystem_files if path.casefold() not in referenced_folded}

    # Remove files that were found via string references
    for string_ref_entry in string_cross_ref["string_refs_found_exact"]:
        if " -> " in string_ref_entry:
            actual_path = string_ref_entry.split(" -> ")[1]
            true_orphans.discard(actual_path)

    for string_ref_entry in string_cross_ref["string_refs_found_case_diff"]:
        if " -> " in string_ref_entry:
            actual_path = string_ref_entry.split(" -> ")[1]
            true_orphans.discard(actual_path)

    # Compile results
    results = {
        "timestamp": str(Path(project_root).resolve()),
        "phase_1_results": {
            "referenced_files_count": len(referenced_files_normalized),
            "referenced_files": sorted(list(referenced_files_normalized)),
        },
        "phase_2_results": {
            "filesystem_files_count": len(filesystem_files),
            "path_categories": {
                "found_exact": path_categories["found_exact"],
                "found_case_diff": path_categories["found_case_diff"],
                "missing": path_categories["missing"],
            },
            "string_references": {
                "by_type": {k: sorted(list(v)) for k, v in string_refs.items()},
                "cross_reference": string_cross_ref,
            },
            "derivable_orphans": derivable_orphans,
        },
        "final_analysis": {
            "true_orphans_count": len(true_orphans),
            "true_orphans": sorted(list(true_orphans)),
            "missing_but_referenced_count": len(path_categories["missing"]),
            "missing_but_referenced": path_categories["missing"],
            "case_sensitivity_issues_count": len(path_categories["found_case_diff"]),
            "case_sensitivity_issues": path_categories["found_case_diff"],
        },
    }

    print(f"[OK] Comprehensive analysis complete!")
    print(f"   [SUMMARY] Phase 1: {len(referenced_files)} referenced files")
    print(f"   [SUMMARY] Phase 2: {len(filesystem_files)} filesystem files")
    print(f"   [SUMMARY] Final: {len(true_orphans)} true orphans")
    print(f"   [SUMMARY] Issues: {len(path_categories['missing'])} missing files")
    print(f"   [SUMMARY] Issues: {len(path_categories['found_case_diff'])} case sensitivity issues")

    return results


def audit_to_diagnostics(audit_results: Dict) -> List[Diagnostic]:
    """Convert comprehensive analysis results to structured diagnostics."""
    diagnostics = []
    final = audit_results.get("final_analysis", {})
    phase_2 = audit_results.get("phase_2_results", {})

    # 1. Missing but referenced files (Errors)
    for missing in final.get("missing_but_referenced", []):
        diagnostics.append(
            Diagnostic(
                severity="error",
                category="reference",
                file_path=missing,
                message="File is referenced in project but missing from disk.",
                code=CODE_REFERENCE_MISSING,
                source="audit",
            )
        )

    # 2. Case sensitivity issues (Warnings)
    for case_issue in final.get("case_sensitivity_issues", []):
        if " -> " in case_issue:
            ref, actual = case_issue.split(" -> ")
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category="case",
                    file_path=ref,
                    message=f"Case mismatch: referenced as '{ref}' but exists as '{actual}' on disk. This will fail on non-Windows platforms.",
                    code=CODE_CASE_MISMATCH,
                    source="audit",
                    can_auto_fix=False,
                    suggested_fix=f"Rename file to match reference exactly, or update reference to match disk.",
                )
            )

    # 3. True orphans (Warnings)
    for orphan in final.get("true_orphans", []):
        diagnostics.append(
            Diagnostic(
                severity="warning",
                category="orphan",
                file_path=orphan,
                message="File exists on disk but is not referenced by the project file.",
                code=CODE_ORPHAN_FILE,
                source="audit",
                can_auto_fix=False,
                suggested_fix="Delete the file if unused, or add it to the project.",
            )
        )

    # 4. Derivable orphans (Info)
    for derivable in phase_2.get("derivable_orphans", []):
        # Format is usually "path (reason)"
        path = derivable
        message = "File is not directly referenced but may be used via naming conventions or string references."
        if "(" in derivable:
            path, reason = derivable.split(" (", 1)
            message = f"File may be used via {reason.rstrip(')')}."

        diagnostics.append(
            Diagnostic(
                severity="info",
                category="orphan",
                file_path=path,
                message=message,
                code=CODE_ORPHAN_FILE,
                source="audit",
            )
        )

    return diagnostics


if __name__ == "__main__":
    # Test the reference collector
    references = collect_project_references()
    print(f"\nCollected {len(references)} referenced files:")
    for ref in sorted(references)[:20]:  # Show first 20
        print(f"  {ref}")
    if len(references) > 20:
        print(f"  ... and {len(references) - 20} more files")
