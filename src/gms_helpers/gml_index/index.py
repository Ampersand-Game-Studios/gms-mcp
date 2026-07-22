"""GML Symbol Index - manages the symbol database for a project."""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from .symbols import Symbol, SymbolKind, SymbolLocation, SymbolReference
from .scanner import GMLScanner


class GMLIndex:
    """Manages the symbol index for a GameMaker project.

    Provides:
    - Building/rebuilding the index from GML files
    - Finding symbol definitions
    - Finding symbol references
    - Listing all symbols (optionally filtered)
    """

    CACHE_FILE = ".gml_index_cache.json"
    CACHE_VERSION = 3

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve(strict=True)
        self.scanner = GMLScanner()

        # Symbol name -> list of Symbol definitions (can have multiple with same name)
        self.definitions: Dict[str, List[Symbol]] = {}

        # Symbol name -> list of SymbolReference
        self.references: Dict[str, List[SymbolReference]] = {}

        # Track which files have been indexed. We use cheap metadata so we can
        # detect changes without reading every file on every build.
        self.file_mtimes_ns: Dict[str, int] = {}
        self.file_sizes: Dict[str, int] = {}

        self._is_built = False

    @property
    def cache_path(self) -> Path:
        """Store generated code intelligence outside the shareable project tree."""
        configured = os.environ.get("GMS_MCP_GML_INDEX_CACHE_DIR", "").strip()
        cache_root = Path(configured).expanduser() if configured else Path.home() / ".gms-mcp" / "gml-index"
        project_key = hashlib.sha256(str(self.project_root).encode("utf-8")).hexdigest()
        return cache_root / f"{project_key}.json"

    @staticmethod
    def _valid_relative_path(raw_path: str) -> bool:
        path = Path(raw_path)
        return bool(raw_path) and not path.is_absolute() and ".." not in path.parts

    def _remove_legacy_project_cache(self) -> None:
        legacy_path = self.project_root / self.CACHE_FILE
        try:
            legacy_path.unlink(missing_ok=True)
        except OSError:
            pass

    def build(self, force: bool = False) -> dict:
        """Build or rebuild the symbol index.

        Args:
            force: If True, rebuild from scratch. If False, use cache if valid.

        Returns:
            Dict with build statistics
        """
        self._remove_legacy_project_cache()
        cache_path = self.cache_path

        # Try to load cache if not forcing rebuild
        if not force and cache_path.exists():
            if self._load_cache(cache_path):
                # Incremental update: only rescan changed/new files and purge deleted files.
                current_files = {f.relative_to(self.project_root).as_posix() for f in self._find_gml_files()}
                cached_files = set(self.file_mtimes_ns.keys())

                added_files = current_files - cached_files
                removed_files = cached_files - current_files

                changed_files: Set[str] = set()
                for rel_path in sorted(current_files & cached_files):
                    file_path = self.project_root / rel_path
                    try:
                        stat = file_path.stat()
                    except Exception:
                        # If we can't stat a file now, treat as changed so we drop stale entries.
                        changed_files.add(rel_path)
                        continue

                    if stat.st_mtime_ns != self.file_mtimes_ns.get(rel_path) or stat.st_size != self.file_sizes.get(
                        rel_path
                    ):
                        changed_files.add(rel_path)

                if not added_files and not removed_files and not changed_files:
                    return {
                        "status": "cached",
                        "symbols": sum(len(defs) for defs in self.definitions.values()),
                        "references": sum(len(refs) for refs in self.references.values()),
                        "files": len(self.file_mtimes_ns),
                    }

                # Purge entries for removed/changed files, then rescan changed/new files.
                touched_files = set(added_files) | set(changed_files)
                for rel_path in sorted(set(removed_files) | set(changed_files)):
                    self._remove_file_entries(rel_path)
                    self.file_mtimes_ns.pop(rel_path, None)
                    self.file_sizes.pop(rel_path, None)

                files_scanned = 0
                total_symbols = sum(len(defs) for defs in self.definitions.values())
                total_refs = sum(len(refs) for refs in self.references.values())

                for rel_path in sorted(touched_files):
                    file_path = self.project_root / rel_path
                    try:
                        stat = file_path.stat()
                        content = file_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    self.file_mtimes_ns[rel_path] = stat.st_mtime_ns
                    self.file_sizes[rel_path] = stat.st_size

                    symbols, refs = self.scanner.scan_content(content, Path(rel_path))
                    for symbol in symbols:
                        self.definitions.setdefault(symbol.name, []).append(symbol)
                        total_symbols += 1
                    for ref in refs:
                        self.references.setdefault(ref.symbol_name, []).append(ref)
                        total_refs += 1
                    files_scanned += 1

                self._is_built = True
                self._save_cache(cache_path)
                return {
                    "status": "incremental",
                    "symbols": total_symbols,
                    "references": total_refs,
                    "files": files_scanned,
                    "added_files": len(added_files),
                    "changed_files": len(changed_files),
                    "removed_files": len(removed_files),
                }

        # Find all GML files
        gml_files = self._find_gml_files()

        # Clear existing data
        self.definitions.clear()
        self.references.clear()
        self.file_mtimes_ns.clear()
        self.file_sizes.clear()

        files_scanned = 0
        total_symbols = 0
        total_refs = 0

        for gml_file in gml_files:
            try:
                stat = gml_file.stat()
                content = gml_file.read_text(encoding="utf-8", errors="replace")
                rel_path = gml_file.relative_to(self.project_root).as_posix()
                self.file_mtimes_ns[rel_path] = stat.st_mtime_ns
                self.file_sizes[rel_path] = stat.st_size

                # Scan the file
                symbols, refs = self.scanner.scan_content(content, Path(rel_path))

                # Add symbols to index
                for symbol in symbols:
                    if symbol.name not in self.definitions:
                        self.definitions[symbol.name] = []
                    self.definitions[symbol.name].append(symbol)
                    total_symbols += 1

                # Add references to index
                for ref in refs:
                    if ref.symbol_name not in self.references:
                        self.references[ref.symbol_name] = []
                    self.references[ref.symbol_name].append(ref)
                    total_refs += 1

                files_scanned += 1

            except Exception:
                # Skip files that can't be read
                continue

        self._is_built = True

        # Save cache
        self._save_cache(cache_path)

        return {
            "status": "built",
            "symbols": total_symbols,
            "references": total_refs,
            "files": files_scanned,
        }

    def find_definition(self, symbol_name: str) -> List[Symbol]:
        """Find all definitions of a symbol.

        Args:
            symbol_name: Name of the symbol to find

        Returns:
            List of Symbol objects (empty if not found)
        """
        if not self._is_built:
            self.build()

        return self.definitions.get(symbol_name, [])

    def find_references(self, symbol_name: str) -> List[SymbolReference]:
        """Find all references to a symbol.

        Args:
            symbol_name: Name of the symbol to find references for

        Returns:
            List of SymbolReference objects
        """
        if not self._is_built:
            self.build()

        return self.references.get(symbol_name, [])

    def list_symbols(
        self,
        kind: Optional[SymbolKind] = None,
        name_filter: Optional[str] = None,
        file_filter: Optional[str] = None,
    ) -> List[Symbol]:
        """List all symbols, optionally filtered.

        Args:
            kind: Filter by symbol kind
            name_filter: Filter by name (case-insensitive substring match)
            file_filter: Filter by file path (case-insensitive substring match)

        Returns:
            List of matching Symbol objects
        """
        if not self._is_built:
            self.build()

        results = []

        for symbol_list in self.definitions.values():
            for symbol in symbol_list:
                # Apply filters
                if kind and symbol.kind != kind:
                    continue
                if name_filter and name_filter.lower() not in symbol.name.lower():
                    continue
                if file_filter:
                    file_str = str(symbol.location.file_path).lower()
                    if file_filter.lower() not in file_str:
                        continue

                results.append(symbol)

        # Sort by name for consistent output
        results.sort(key=lambda s: s.name.lower())

        return results

    def get_symbols_in_file(self, file_path: Path) -> List[Symbol]:
        """Get all symbols defined in a specific file.

        Args:
            file_path: Path to the file

        Returns:
            List of Symbol objects defined in that file
        """
        if not self._is_built:
            self.build()

        results = []

        # Normalize both absolute caller paths and project-relative index paths.
        try:
            if file_path.is_absolute():
                normalized = file_path.resolve(strict=False).relative_to(self.project_root).as_posix()
            else:
                normalized = file_path.as_posix()
        except (OSError, ValueError):
            return []

        for symbol_list in self.definitions.values():
            for symbol in symbol_list:
                if symbol.location.file_path.as_posix() == normalized:
                    results.append(symbol)

        # Sort by line number
        results.sort(key=lambda s: s.location.line)

        return results

    def _find_gml_files(self) -> List[Path]:
        """Find all GML files in the project."""
        gml_files = []

        # Standard GameMaker directories that contain GML
        gml_dirs = ["scripts", "objects", "rooms", "extensions"]

        for dir_name in gml_dirs:
            dir_path = self.project_root / dir_name
            if dir_path.exists():
                for candidate in dir_path.rglob("*.gml"):
                    try:
                        candidate.resolve(strict=True).relative_to(self.project_root)
                    except (FileNotFoundError, OSError, ValueError):
                        continue
                    if candidate.is_file():
                        gml_files.append(candidate)

        # Also check for any .gml files in root (less common)
        for candidate in self.project_root.glob("*.gml"):
            try:
                candidate.resolve(strict=True).relative_to(self.project_root)
            except (FileNotFoundError, OSError, ValueError):
                continue
            if candidate.is_file():
                gml_files.append(candidate)

        return sorted(set(gml_files))

    def _load_cache(self, cache_path: Path) -> bool:
        """Load index from cache file.

        Returns True if cache is valid and loaded successfully.
        """
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Verify cache version
            if data.get("version") != self.CACHE_VERSION:
                return False

            cached_mtimes = data.get("file_mtimes_ns", {}) or {}
            cached_sizes = data.get("file_sizes", {}) or {}
            if not isinstance(cached_mtimes, dict) or not isinstance(cached_sizes, dict):
                return False
            if not all(self._valid_relative_path(str(path)) for path in {*cached_mtimes, *cached_sizes}):
                return False

            # Load the cached data (validation happens in build(), which can also do incremental updates).
            self.file_mtimes_ns = {str(k): int(v) for k, v in cached_mtimes.items()}
            self.file_sizes = {str(k): int(v) for k, v in cached_sizes.items()}

            # Reconstruct definitions
            self.definitions.clear()
            for sym_data in data.get("definitions", []):
                symbol = self._symbol_from_dict(sym_data)
                if not self._valid_relative_path(symbol.location.file_path.as_posix()):
                    return False
                if symbol.name not in self.definitions:
                    self.definitions[symbol.name] = []
                self.definitions[symbol.name].append(symbol)

            # Reconstruct references
            self.references.clear()
            for ref_data in data.get("references", []):
                ref = self._reference_from_dict(ref_data)
                if not self._valid_relative_path(ref.location.file_path.as_posix()):
                    return False
                if ref.symbol_name not in self.references:
                    self.references[ref.symbol_name] = []
                self.references[ref.symbol_name].append(ref)

            self._is_built = True
            return True

        except Exception:
            return False

    def _remove_file_entries(self, rel_path: str) -> None:
        """Remove all cached symbol/refs that originate from a specific project-relative file."""
        normalized = Path(rel_path).as_posix()

        def _same_file(path: Path) -> bool:
            return path.as_posix() == normalized

        for name in list(self.definitions.keys()):
            kept = [s for s in self.definitions.get(name, []) if not _same_file(s.location.file_path)]
            if kept:
                self.definitions[name] = kept
            else:
                self.definitions.pop(name, None)

        for name in list(self.references.keys()):
            kept = [r for r in self.references.get(name, []) if not _same_file(r.location.file_path)]
            if kept:
                self.references[name] = kept
            else:
                self.references.pop(name, None)

    def _save_cache(self, cache_path: Path):
        """Save index to cache file."""
        try:
            # Flatten definitions and references for JSON
            all_definitions = []
            for symbol_list in self.definitions.values():
                for symbol in symbol_list:
                    all_definitions.append(symbol.to_dict())

            all_references = []
            for ref_list in self.references.values():
                for ref in ref_list:
                    all_references.append(ref.to_dict())

            data = {
                "version": self.CACHE_VERSION,
                "file_mtimes_ns": self.file_mtimes_ns,
                "file_sizes": self.file_sizes,
                "definitions": all_definitions,
                "references": all_references,
            }

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                cache_path.parent.chmod(0o700)
            except OSError:
                pass
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            try:
                cache_path.chmod(0o600)
            except OSError:
                pass

        except Exception:
            # Cache save failure is not critical
            pass

    def _symbol_from_dict(self, data: dict) -> Symbol:
        """Reconstruct a Symbol from dict data."""
        loc_data = data["location"]
        location = SymbolLocation(
            file_path=Path(loc_data["file"]),
            line=loc_data["line"],
            column=loc_data.get("column", 0),
            end_line=loc_data.get("end_line"),
            end_column=loc_data.get("end_column"),
        )
        return Symbol(
            name=data["name"],
            kind=SymbolKind(data["kind"]),
            location=location,
            doc_comment=data.get("doc"),
            parameters=data.get("parameters", []),
            parent_enum=data.get("parent_enum"),
        )

    def _reference_from_dict(self, data: dict) -> SymbolReference:
        """Reconstruct a SymbolReference from dict data."""
        loc_data = data["location"]
        location = SymbolLocation(
            file_path=Path(loc_data["file"]),
            line=loc_data["line"],
            column=loc_data.get("column", 0),
        )
        return SymbolReference(
            symbol_name=data["symbol"],
            location=location,
            context=data.get("context"),
        )
