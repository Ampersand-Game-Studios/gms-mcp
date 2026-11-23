"""GML Symbol Index - manages the symbol database for a project."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path, PureWindowsPath
from typing import Dict, Iterable, List, Optional, Set

from .symbols import Symbol, SymbolKind, SymbolLocation, SymbolReference
from .scanner import GMLScanner
from ..operation_policy import read_only_mode_enabled

_SCHEMA = """
CREATE TABLE files (path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL);
CREATE TABLE definitions (
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    col INTEGER NOT NULL,
    end_line INTEGER,
    end_col INTEGER,
    doc TEXT,
    parameters TEXT,
    parent_enum TEXT
);
CREATE TABLE refs (symbol TEXT NOT NULL, file TEXT NOT NULL, line INTEGER NOT NULL, col INTEGER NOT NULL);
CREATE INDEX definitions_by_name ON definitions (name);
CREATE INDEX definitions_by_file ON definitions (file);
CREATE INDEX refs_by_symbol ON refs (symbol);
CREATE INDEX refs_by_file ON refs (file);
"""
_TABLES = {"files", "definitions", "refs"}


class GMLIndex:
    """Manages the symbol index for a GameMaker project.

    Provides:
    - Building/rebuilding the index from GML files
    - Finding symbol definitions
    - Finding symbol references
    - Listing all symbols (optionally filtered)

    The index is a SQLite database kept outside the project. A lookup reads only the rows it
    needs, where the earlier JSON cache had to be parsed whole (hundreds of megabytes on a large
    project) before the first answer. A build that must not write (``persist=False`` or read-only
    mode) still reads an existing database and applies newer file changes in memory.
    """

    CACHE_FILE = ".gml_index_cache.json"
    CACHE_VERSION = 4

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve(strict=True)
        self.scanner = GMLScanner()
        self._connection: Optional[sqlite3.Connection] = None
        self._is_built = False

    @property
    def cache_path(self) -> Path:
        """Store generated code intelligence outside the shareable project tree."""
        configured = os.environ.get("GMS_MCP_GML_INDEX_CACHE_DIR", "").strip()
        cache_root = Path(configured).expanduser() if configured else Path.home() / ".gms-mcp" / "gml-index"
        project_key = hashlib.sha256(str(self.project_root).encode("utf-8")).hexdigest()
        return cache_root / f"{project_key}.sqlite3"

    @staticmethod
    def _valid_relative_path(raw_path: str) -> bool:
        path = Path(raw_path)
        windows_path = PureWindowsPath(raw_path)
        return (
            bool(raw_path)
            and not path.is_absolute()
            and not windows_path.root
            and not windows_path.drive
            and ".." not in path.parts
            and ".." not in windows_path.parts
        )

    def _remove_legacy_project_cache(self) -> None:
        legacy_paths = [self.project_root / self.CACHE_FILE]
        cache_path = self.cache_path
        if cache_path.suffix == ".sqlite3":
            # The JSON cache this database replaces, under the same project key.
            legacy_paths.append(cache_path.with_suffix(".json"))
        for legacy_path in legacy_paths:
            try:
                legacy_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Database handling
    # ------------------------------------------------------------------

    @staticmethod
    def _new_memory_database() -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.executescript(_SCHEMA)
        return connection

    def _usable(self, connection: sqlite3.Connection) -> bool:
        """Accept a stored database only if it has this version's shape and no path leaves the project."""
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != self.CACHE_VERSION:
                return False
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not _TABLES <= tables:
                return False
            stored_paths = [row[0] for row in connection.execute("SELECT path FROM files")]
            for table in ("definitions", "refs"):
                # Step through the file index one distinct value at a time; reading every row
                # to find a few thousand distinct files would cost more than the lookup itself.
                stored_paths += [
                    row[0]
                    for row in connection.execute(
                        f"WITH RECURSIVE distinct_files(file) AS ("
                        f"SELECT MIN(file) FROM {table} UNION ALL "
                        f"SELECT (SELECT MIN(file) FROM {table} WHERE file > distinct_files.file) "
                        f"FROM distinct_files WHERE distinct_files.file IS NOT NULL) "
                        f"SELECT file FROM distinct_files WHERE file IS NOT NULL"
                    )
                ]
            return all(isinstance(path, str) and self._valid_relative_path(path) for path in stored_paths)
        except (sqlite3.Error, TypeError, ValueError):
            return False

    def _open_stored(self, cache_path: Path, *, writable: bool) -> Optional[sqlite3.Connection]:
        """Open the stored database if it exists and can be trusted, else None."""
        if not cache_path.is_file():
            return None
        try:
            if writable:
                connection = sqlite3.connect(os.fspath(cache_path))
                # This is a cache: losing it to a power cut costs one rebuild, not correctness.
                connection.execute("PRAGMA synchronous = OFF")
            else:
                connection = sqlite3.connect(f"{cache_path.as_uri()}?mode=ro", uri=True)
        except (sqlite3.Error, ValueError):
            return None
        if self._usable(connection):
            return connection
        connection.close()
        return None

    def _create_stored(self, cache_path: Path) -> Optional[sqlite3.Connection]:
        """Start an empty stored database, replacing whatever is at the path."""
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                cache_path.parent.chmod(0o700)
            except OSError:
                pass
            cache_path.unlink(missing_ok=True)
            connection = sqlite3.connect(os.fspath(cache_path))
            try:
                cache_path.chmod(0o600)
            except OSError:
                pass
            connection.execute("PRAGMA synchronous = OFF")
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {self.CACHE_VERSION}")
            return connection
        except (OSError, sqlite3.Error):
            # A cache that cannot be written is not a reason to fail the lookup.
            return None

    def _adopt(self, connection: sqlite3.Connection) -> None:
        if self._connection is not None and self._connection is not connection:
            self._connection.close()
        self._connection = connection

    def _counts(self) -> Dict[str, int]:
        assert self._connection is not None
        return {
            "symbols": self._connection.execute("SELECT COUNT(*) FROM definitions").fetchone()[0],
            "references": self._connection.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
        }

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    def build(self, force: bool = False, *, persist: bool = True) -> dict:
        """Build or rebuild the symbol index.

        Args:
            force: If True, rebuild from scratch. If False, use cache if valid.
            persist: If False, index in memory without saving or removing any cache.

        Returns:
            Dict with build statistics
        """
        read_only = not persist or read_only_mode_enabled()
        if not read_only:
            self._remove_legacy_project_cache()
            try:
                return self._build(force, read_only=False)
            except sqlite3.Error:
                # Another session is writing the same index, or the cache cannot be written.
                # The lookup still has to answer, so index in memory and leave the file alone.
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None
                force = True
        return self._build(force, read_only=True)

    def _build(self, force: bool, *, read_only: bool) -> dict:
        cache_path = self.cache_path

        stored = None if force else self._open_stored(cache_path, writable=not read_only)
        current_files = {f.relative_to(self.project_root).as_posix() for f in self._find_gml_files()}

        if stored is not None:
            cached = {path: (mtime_ns, size) for path, mtime_ns, size in stored.execute("SELECT * FROM files")}
            added_files = current_files - set(cached)
            removed_files = set(cached) - current_files
            changed_files: Set[str] = set()
            for rel_path in sorted(current_files & set(cached)):
                try:
                    stat = (self.project_root / rel_path).stat()
                except Exception:
                    # If we can't stat a file now, treat as changed so we drop stale entries.
                    changed_files.add(rel_path)
                    continue
                if (stat.st_mtime_ns, stat.st_size) != cached[rel_path]:
                    changed_files.add(rel_path)

            if not added_files and not removed_files and not changed_files:
                self._adopt(stored)
                self._is_built = True
                return {"status": "cached", **self._counts(), "files": len(cached), "saved": True}

            if read_only:
                # Bring the stored index up to date in memory, leaving the file as it is.
                working = sqlite3.connect(":memory:")
                stored.backup(working)
                stored.close()
            else:
                working = stored
            self._adopt(working)
            self._forget_files(sorted(removed_files | changed_files))
            files_scanned = self._scan_files(sorted(added_files | changed_files))
            working.commit()
            self._is_built = True
            return {
                "status": "incremental",
                **self._counts(),
                "files": files_scanned,
                "added_files": len(added_files),
                "changed_files": len(changed_files),
                "removed_files": len(removed_files),
                "saved": not read_only,
            }

        working = None if read_only else self._create_stored(cache_path)
        self._adopt(working if working is not None else self._new_memory_database())
        files_scanned = self._scan_files(sorted(current_files))
        assert self._connection is not None
        self._connection.commit()
        self._is_built = True
        return {"status": "built", **self._counts(), "files": files_scanned, "saved": working is not None}

    def _forget_files(self, rel_paths: Iterable[str]) -> None:
        """Remove every stored symbol, reference and file record for these project-relative files."""
        assert self._connection is not None
        for rel_path in rel_paths:
            normalized = Path(rel_path).as_posix()
            for table, column in (("definitions", "file"), ("refs", "file"), ("files", "path")):
                self._connection.execute(f"DELETE FROM {table} WHERE {column} IN (?, ?)", (rel_path, normalized))

    def _scan_files(self, rel_paths: Iterable[str]) -> int:
        assert self._connection is not None
        files_scanned = 0
        for rel_path in rel_paths:
            file_path = self.project_root / rel_path
            try:
                stat = file_path.stat()
                content = file_path.read_text(encoding="utf-8", errors="replace")
                symbols, refs = self.scanner.scan_content(content, Path(rel_path))
            except Exception:
                # Skip files that can't be read
                continue
            # Another session may have stored this file since this one looked: it can open a database
            # this session has only just created, or see the same new file. Replacing the file's rows
            # in the transaction that adds them keeps one copy whichever session commits last.
            self._connection.execute("DELETE FROM definitions WHERE file = ?", (rel_path,))
            self._connection.execute("DELETE FROM refs WHERE file = ?", (rel_path,))
            self._connection.execute(
                "INSERT OR REPLACE INTO files VALUES (?, ?, ?)", (rel_path, stat.st_mtime_ns, stat.st_size)
            )
            self._connection.executemany(
                "INSERT INTO definitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        symbol.name,
                        symbol.kind.value,
                        rel_path,
                        symbol.location.line,
                        symbol.location.column,
                        symbol.location.end_line,
                        symbol.location.end_column,
                        symbol.doc_comment,
                        json.dumps(symbol.parameters) if symbol.parameters else None,
                        symbol.parent_enum,
                    )
                    for symbol in symbols
                ),
            )
            self._connection.executemany(
                "INSERT INTO refs VALUES (?, ?, ?, ?)",
                ((ref.symbol_name, rel_path, ref.location.line, ref.location.column) for ref in refs),
            )
            files_scanned += 1
        return files_scanned

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _ready(self) -> sqlite3.Connection:
        if not self._is_built:
            self.build(persist=False)
        assert self._connection is not None
        return self._connection

    @staticmethod
    def _symbol_from_row(row: tuple) -> Symbol:
        name, kind, file, line, col, end_line, end_col, doc, parameters, parent_enum = row
        return Symbol(
            name=name,
            kind=SymbolKind(kind),
            location=SymbolLocation(file_path=Path(file), line=line, column=col, end_line=end_line, end_column=end_col),
            doc_comment=doc,
            parameters=json.loads(parameters) if parameters else [],
            parent_enum=parent_enum,
        )

    def find_definition(self, symbol_name: str) -> List[Symbol]:
        """Find definition(s) of a symbol.

        Args:
            symbol_name: Name of the symbol to find

        Returns:
            List of Symbol objects (may be multiple if overloaded/redefined)
        """
        rows = self._ready().execute("SELECT * FROM definitions WHERE name = ? ORDER BY file, line", (symbol_name,))
        return [self._symbol_from_row(row) for row in rows]

    def find_references(self, symbol_name: str) -> List[SymbolReference]:
        """Find all references to a symbol.

        Args:
            symbol_name: Name of the symbol to find references for

        Returns:
            List of SymbolReference objects
        """
        rows = (
            self._ready()
            .execute("SELECT file, line, col FROM refs WHERE symbol = ? ORDER BY file, line, col", (symbol_name,))
            .fetchall()
        )
        # The line of code beside each reference is read when asked for. Storing it for every
        # reference in the project made the index several times larger than the code it describes.
        lines_by_file: Dict[str, List[str]] = {}
        references = []
        for file, line, col in rows:
            if file not in lines_by_file:
                try:
                    text: str = (self.project_root / file).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                lines_by_file[file] = text.split("\n")
            lines = lines_by_file[file]
            context = lines[line - 1].strip() if 0 < line <= len(lines) else None
            references.append(
                SymbolReference(
                    symbol_name=symbol_name,
                    location=SymbolLocation(file_path=Path(file), line=line, column=col),
                    context=context or None,
                )
            )
        return references

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
        connection = self._ready()
        if kind:
            rows = connection.execute("SELECT * FROM definitions WHERE kind = ?", (kind.value,))
        else:
            rows = connection.execute("SELECT * FROM definitions")

        results = []
        for row in rows:
            if name_filter and name_filter.lower() not in row[0].lower():
                continue
            if file_filter and file_filter.lower() not in str(Path(row[2])).lower():
                continue
            results.append(self._symbol_from_row(row))

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
        connection = self._ready()

        # Normalize both absolute caller paths and project-relative index paths.
        try:
            if file_path.is_absolute():
                normalized = file_path.resolve(strict=False).relative_to(self.project_root).as_posix()
            else:
                normalized = file_path.as_posix()
        except (OSError, ValueError):
            return []

        results = [
            self._symbol_from_row(row)
            for row in connection.execute("SELECT * FROM definitions")
            if Path(row[2]).as_posix() == normalized
        ]

        # Sort by line number
        results.sort(key=lambda s: s.location.line)

        return results

    def _find_gml_files(self) -> List[Path]:
        """Find all GML files in the project."""
        gml_files = []

        def inside_project(candidate: Path) -> bool:
            try:
                candidate.resolve(strict=True).relative_to(self.project_root)
            except (FileNotFoundError, OSError, ValueError):
                return False
            return candidate.is_file()

        # Standard GameMaker directories that contain GML
        gml_dirs = ["scripts", "objects", "rooms", "extensions"]

        for dir_name in gml_dirs:
            dir_path = self.project_root / dir_name
            if not dir_path.exists():
                continue
            if dir_path.is_symlink():
                gml_files.extend(candidate for candidate in dir_path.rglob("*.gml") if inside_project(candidate))
                continue
            # The walk never enters a linked directory, so only a file that is itself a link can
            # lead outside the project. Resolving every file costs a second per few thousand.
            for directory, _directory_names, file_names in os.walk(dir_path, followlinks=False):
                for file_name in file_names:
                    if not file_name.endswith(".gml"):
                        continue
                    candidate = Path(directory) / file_name
                    if candidate.is_symlink():
                        if inside_project(candidate):
                            gml_files.append(candidate)
                    elif candidate.is_file():
                        gml_files.append(candidate)

        # Also check for any .gml files in root (less common)
        gml_files.extend(candidate for candidate in self.project_root.glob("*.gml") if inside_project(candidate))

        return sorted(set(gml_files))
