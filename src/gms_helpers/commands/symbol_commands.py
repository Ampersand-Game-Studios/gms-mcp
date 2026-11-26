"""Symbol/Code Intelligence commands.

Each query is a report function that returns the whole answer as data; the MCP tools return
that data, and the ``handle_*`` command handlers print it for a person and return it as well.
Reports group by file and name each location once, so a long answer stays readable and cheap
for an agent without leaving anything out.
"""

from pathlib import Path
from typing import Any, Optional

from ..results import structured_error


def _ok_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("ok", True)
    payload.setdefault("success", True)
    return payload


def _error_payload(message: str, *, code: str, operation: str, **payload: Any) -> dict[str, Any]:
    payload.setdefault("message", message)
    payload["ok"] = False
    payload["success"] = False
    payload["error"] = structured_error(
        code,
        message,
        error_type="symbol_index_error",
        details={"operation": operation},
    ).to_dict()
    return payload


def _index_note(build_report: dict) -> Optional[str]:
    """Why a lookup was slow, and whether the next one will be fast."""
    from ..operation_policy import read_only_mode_enabled

    if build_report.get("status") != "built" or read_only_mode_enabled():
        return None
    if build_report.get("saved"):
        return (
            "First symbol lookup in this checkout: every code file was scanned and the index saved, "
            "so later lookups are fast."
        )
    return (
        "Every code file was scanned for this lookup: the saved index was not available (another "
        "lookup may be writing it now). Lookups made one at a time reuse it."
    )


def _with_note(payload: dict[str, Any], note: Optional[str]) -> dict[str, Any]:
    if note:
        payload["note"] = note
    return payload


# ----------------------------------------------------------------------
# Reports (data only)
# ----------------------------------------------------------------------
def build_index_report(project_root: Path, *, force: bool = False) -> dict[str, Any]:
    """Build or refresh the symbol index; report what it holds."""
    from ..gml_index import GMLIndex

    stats = GMLIndex(Path(project_root)).build(force=force)
    return _ok_payload(dict(stats))


def definitions_report(project_root: Path, symbol_name: str) -> dict[str, Any]:
    """Every definition of ``symbol_name``: kind, ``at`` (file:line), parameters and doc comment."""
    from ..gml_index import GMLIndex

    if not symbol_name:
        return _error_payload(
            "Symbol name required", code="symbol_name_required", operation="find_definition", definitions=[]
        )
    root = Path(project_root)
    index = GMLIndex(root)
    note = _index_note(index.build())
    definitions = []
    for definition in index.find_definition(symbol_name):
        entry: dict[str, Any] = {
            "kind": definition.kind.value,
            "at": f"{_make_relative(definition.location.file_path, root)}:{definition.location.line}",
        }
        if definition.parameters:
            entry["params"] = definition.parameters
        if definition.parent_enum:
            entry["enum"] = definition.parent_enum
        if definition.doc_comment:
            entry["doc"] = definition.doc_comment
        definitions.append(entry)
    return _with_note(_ok_payload({"symbol": symbol_name, "definitions": definitions}), note)


def _code_file(path: str) -> str:
    """A code file named the GameMaker way, ``<folder>/<name>/<name>.gml``, as ``<folder>/<name>``."""
    parts = path.split("/")
    return "/".join(parts[:-1]) if len(parts) >= 3 and parts[-1] == f"{parts[-2]}.gml" else path


def _code_path(file: str) -> str:
    """The file a ``_code_file`` name stands for (only .gml files are indexed)."""
    return file if file.endswith(".gml") else f"{file}/{file.rsplit('/', 1)[-1]}.gml"


def _page(items: list, offset: int, max_results: Optional[int]) -> tuple[list, Optional[int]]:
    """The ``max_results`` items from ``offset`` on, and the offset of the next page (None: no more)."""
    start = max(0, offset)
    end = len(items) if max_results is None or max_results < 0 else start + max_results
    return items[start:end], (end if end < len(items) else None)


def references_report(
    project_root: Path, symbol_name: str, *, max_results: Optional[int] = None, offset: int = 0
) -> dict[str, Any]:
    """Every reference to ``symbol_name``, grouped by file: ``"<line> <the line of code>"``.

    A line that names the symbol twice is listed once. ``defined_at`` names the definition lines,
    which also name the symbol. A file ``<folder>/<name>/<name>.gml`` is written ``<folder>/<name>``.
    ``max_results`` keeps that many references from ``offset`` on; ``next_offset`` says where the
    next page starts.
    """
    from ..gml_index import GMLIndex

    if not symbol_name:
        return _error_payload(
            "Symbol name required", code="symbol_name_required", operation="find_references", references={}
        )
    root = Path(project_root)
    index = GMLIndex(root)
    note = _index_note(index.build())
    references = index.find_references(symbol_name)
    total = len(references)
    references, next_offset = _page(references, offset, max_results)
    by_file: dict[str, list[str]] = {}
    seen: set[tuple[str, int]] = set()
    for reference in references:
        file = _code_file(_make_relative(reference.location.file_path, root))
        key = (file, reference.location.line)
        if key in seen:
            continue
        seen.add(key)
        by_file.setdefault(file, []).append(f"{reference.location.line} {reference.context or ''}".rstrip())
    payload: dict[str, Any] = {"symbol": symbol_name, "count": total}
    defined_at = [
        f"{_code_file(_make_relative(definition.location.file_path, root))}:{definition.location.line}"
        for definition in index.find_definition(symbol_name)
    ]
    if defined_at:
        payload["defined_at"] = defined_at
    payload["references"] = by_file
    if len(references) < total:
        payload["returned"] = len(references)
        payload["truncated"] = True
        if next_offset is not None:
            payload["next_offset"] = next_offset
    return _with_note(_ok_payload(payload), note)


def symbols_report(
    project_root: Path,
    *,
    kind: Optional[str] = None,
    name_filter: Optional[str] = None,
    file_filter: Optional[str] = None,
    max_results: Optional[int] = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Symbols by kind, then file: ``{"function": {"scripts/a": ["name:line", ...]}}``.

    A file ``<folder>/<name>/<name>.gml`` is written ``<folder>/<name>``. Symbols are taken in
    name order; ``max_results`` keeps that many from ``offset`` on, and ``next_offset`` says where
    the next page starts.
    """
    from ..gml_index import GMLIndex, SymbolKind

    root = Path(project_root)
    kind_enum = None
    if kind:
        try:
            kind_enum = SymbolKind(kind.lower())
        except ValueError:
            return {
                "ok": False,
                "success": False,
                "error": f"Unknown symbol kind '{kind}'.",
                "message": f"Unknown symbol kind '{kind}'.",
                "valid_kinds": [item.value for item in SymbolKind],
            }
    index = GMLIndex(root)
    note = _index_note(index.build())
    symbols = index.list_symbols(kind=kind_enum, name_filter=name_filter, file_filter=file_filter)
    total = len(symbols)
    symbols, next_offset = _page(symbols, offset, max_results)
    grouped: dict[str, dict[str, list[str]]] = {}
    for symbol in symbols:
        file = _code_file(_make_relative(symbol.location.file_path, root))
        name = f"{symbol.parent_enum}.{symbol.name}" if symbol.parent_enum else symbol.name
        grouped.setdefault(symbol.kind.value, {}).setdefault(file, []).append(f"{name}:{symbol.location.line}")
    payload: dict[str, Any] = {"count": total, "symbols": grouped}
    if len(symbols) < total:
        payload["returned"] = len(symbols)
        payload["truncated"] = True
        if next_offset is not None:
            payload["next_offset"] = next_offset
    return _with_note(_ok_payload(payload), note)


# ----------------------------------------------------------------------
# Command handlers (print for a person, return the report)
# ----------------------------------------------------------------------
def _print_note(report: dict[str, Any]) -> None:
    if report.get("note"):
        print(f"[INFO] {report['note']}")


def handle_build_index(args) -> dict:
    """Build or rebuild the GML symbol index."""
    try:
        project_root = _get_project_root(args)
        print(f"[INDEX] Building symbol index for: {project_root}")
        stats = build_index_report(project_root, force=getattr(args, "force", False))
        print("[OK] Using cached index (files unchanged)" if stats.get("status") == "cached" else "[OK] Index built")
        print(f"  Files scanned: {stats.get('files', 0)}")
        print(f"  Symbols found: {stats.get('symbols', 0)}")
        print(f"  References found: {stats.get('references', 0)}")
        return stats
    except Exception as e:
        print(f"[ERROR] Failed to build index: {e}")
        return _error_payload(f"Failed to build index: {e}", code="build_index_failed", operation="build_index")


def handle_find_definition(args) -> dict:
    """Find definition(s) of a symbol."""
    symbol_name = getattr(args, "symbol_name", None)
    try:
        report = definitions_report(_get_project_root(args), symbol_name or "")
    except Exception as e:
        print(f"[ERROR] Error finding definition: {e}")
        return _error_payload(str(e), code="find_definition_failed", operation="find_definition", definitions=[])
    if not report["ok"]:
        print(f"[ERROR] {report['message']}")
        return report
    _print_note(report)
    definitions = report["definitions"]
    if not definitions:
        print(f"[INFO] No definition found for '{symbol_name}'")
    else:
        print(f"[OK] Found {len(definitions)} definition(s) of '{symbol_name}':")
    for definition in definitions:
        params = f"({', '.join(definition['params'])})" if "params" in definition else ""
        print(f"  {definition['kind']} {symbol_name}{params}  {definition['at']}")
        if definition.get("doc"):
            for line in str(definition["doc"]).splitlines():
                print(f"    {line}")
    return report


def handle_find_references(args) -> dict:
    """Find all references to a symbol."""
    symbol_name = getattr(args, "symbol_name", None)
    try:
        report = references_report(
            _get_project_root(args),
            symbol_name or "",
            max_results=getattr(args, "max_results", None),
            offset=getattr(args, "offset", 0) or 0,
        )
    except Exception as e:
        print(f"[ERROR] Error finding references: {e}")
        return _error_payload(str(e), code="find_references_failed", operation="find_references", references={})
    if not report["ok"]:
        print(f"[ERROR] {report['message']}")
        return report
    _print_note(report)
    if not report["count"]:
        print(f"[INFO] No references found for '{symbol_name}'")
        return report
    shown = report.get("returned", report["count"])
    print(
        f"[OK] Found {report['count']} reference(s) to '{symbol_name}'"
        + (f" (showing {shown} from {getattr(args, 'offset', 0) or 0})" if report.get("truncated") else "")
        + ":"
    )
    definitions = set(report.get("defined_at", []))
    for file, lines in report["references"].items():
        for entry in lines:
            line_number, _, code = entry.partition(" ")
            marker = "  [definition]" if f"{file}:{line_number}" in definitions else ""
            print(f"  {_code_path(file)}:{line_number} - {code}{marker}")
    return report


def handle_list_symbols(args) -> dict:
    """List all symbols, optionally filtered."""
    try:
        report = symbols_report(
            _get_project_root(args),
            kind=getattr(args, "kind", None),
            name_filter=getattr(args, "name_filter", None),
            file_filter=getattr(args, "file_filter", None),
            max_results=getattr(args, "max_results", None),
            offset=getattr(args, "offset", 0) or 0,
        )
    except Exception as e:
        print(f"[ERROR] Error listing symbols: {e}")
        return _error_payload(str(e), code="list_symbols_failed", operation="list_symbols", symbols={})
    if not report["ok"]:
        print(f"[ERROR] {report['message']}")
        return report
    _print_note(report)
    if not report["count"]:
        print("[INFO] No symbols found matching criteria")
        return report
    shown = report.get("returned", report["count"])
    print(
        f"[OK] Found {report['count']} symbol(s)"
        + (f" (showing {shown} from {getattr(args, 'offset', 0) or 0})" if report.get("truncated") else "")
        + ":"
    )
    for kind, files in report["symbols"].items():
        for file, entries in files.items():
            for entry in entries:
                name, line = entry.rsplit(":", 1)
                print(f"  [{kind}] {name} - {_code_path(file)}:{line}")
    return report


def _get_project_root(args) -> Path:
    """Extract project root from args, defaulting to cwd."""
    if hasattr(args, "project_root") and args.project_root:
        return Path(args.project_root).resolve()
    return Path.cwd()


def _make_relative(path: Path, project_root: Path) -> str:
    """Name a file relative to the project, with forward slashes on every platform."""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path) if path.is_absolute() else path.as_posix()
