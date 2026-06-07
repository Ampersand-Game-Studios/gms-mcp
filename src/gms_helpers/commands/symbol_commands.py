"""Symbol/Code Intelligence command implementations.

These handlers use print() for output, which is captured by _capture_output
when called via MCP tools.
"""

from pathlib import Path
from typing import Any, Optional

from ..results import OperationResult, structured_error


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


def handle_build_index(args) -> OperationResult:
    """Build or rebuild the GML symbol index."""
    from ..gml_index import GMLIndex

    try:
        project_root = _get_project_root(args)
        force = getattr(args, "force", False)

        print(f"[INDEX] Building symbol index for: {project_root}")

        index = GMLIndex(project_root)
        stats = index.build(force=force)

        status = stats.get("status", "unknown")
        if status == "cached":
            print("[OK] Using cached index (files unchanged)")
        else:
            print("[OK] Index built successfully")

        print(f"  Files scanned: {stats.get('files', 0)}")
        print(f"  Symbols found: {stats.get('symbols', 0)}")
        print(f"  References found: {stats.get('references', 0)}")

        return OperationResult.ok("Symbol index built", data=stats)

    except Exception as e:
        print(f"[ERROR] Failed to build index: {e}")
        return OperationResult.fail(
            f"Failed to build index: {e}",
            code="build_index_failed",
            error_type=type(e).__name__,
            details={"operation": "build_index"},
        )


def handle_find_definition(args) -> dict:
    """Find definition(s) of a symbol."""
    from ..gml_index import GMLIndex

    try:
        project_root = _get_project_root(args)
        symbol_name = getattr(args, "symbol_name", None)

        if not symbol_name:
            print("[ERROR] Symbol name required")
            return _error_payload(
                "Symbol name required",
                code="symbol_name_required",
                operation="find_definition",
                definitions=[],
            )

        print(f"[SEARCH] Finding definition of '{symbol_name}'...")

        index = GMLIndex(project_root)
        index.build()

        definitions = index.find_definition(symbol_name)

        if not definitions:
            print(f"[INFO] No definition found for '{symbol_name}'")
            return _ok_payload({"symbol": symbol_name, "definitions": [], "found": False})

        print(f"[OK] Found {len(definitions)} definition(s):")

        result_defs = []
        for defn in definitions:
            loc = defn.location
            rel_path = _make_relative(loc.file_path, project_root)
            print(f"  {defn.kind.value}: {defn.name}")
            print(f"    File: {rel_path}:{loc.line}")
            if defn.parameters:
                print(f"    Params: ({', '.join(defn.parameters)})")
            if defn.doc_comment:
                doc_preview = defn.doc_comment[:80].replace("\n", " ")
                print(f"    Doc: {doc_preview}...")

            result_defs.append(defn.to_dict())

        return _ok_payload(
            {
                "symbol": symbol_name,
                "definitions": result_defs,
                "found": True,
                "count": len(definitions),
            }
        )

    except Exception as e:
        print(f"[ERROR] Error finding definition: {e}")
        return _error_payload(
            str(e),
            code="find_definition_failed",
            operation="find_definition",
            definitions=[],
        )


def handle_find_references(args) -> dict:
    """Find all references to a symbol."""
    from ..gml_index import GMLIndex

    try:
        project_root = _get_project_root(args)
        symbol_name = getattr(args, "symbol_name", None)
        max_results = getattr(args, "max_results", 50)

        if not symbol_name:
            print("[ERROR] Symbol name required")
            return _error_payload(
                "Symbol name required",
                code="symbol_name_required",
                operation="find_references",
                references=[],
            )

        print(f"[SEARCH] Finding references to '{symbol_name}'...")

        index = GMLIndex(project_root)
        index.build()

        references = index.find_references(symbol_name)

        if not references:
            print(f"[INFO] No references found for '{symbol_name}'")
            return _ok_payload({"symbol": symbol_name, "references": [], "found": False})

        total_count = len(references)
        truncated = total_count > max_results
        display_refs = references[:max_results]

        print(f"[OK] Found {total_count} reference(s)" + (f" (showing first {max_results})" if truncated else "") + ":")

        result_refs = []
        for ref in display_refs:
            loc = ref.location
            rel_path = _make_relative(loc.file_path, project_root)
            context_preview = (
                (ref.context[:60] + "...") if ref.context and len(ref.context) > 60 else (ref.context or "")
            )
            print(f"  {rel_path}:{loc.line} - {context_preview}")
            result_refs.append(ref.to_dict())

        return _ok_payload(
            {
                "symbol": symbol_name,
                "references": result_refs,
                "found": True,
                "count": total_count,
                "truncated": truncated,
            }
        )

    except Exception as e:
        print(f"[ERROR] Error finding references: {e}")
        return _error_payload(
            str(e),
            code="find_references_failed",
            operation="find_references",
            references=[],
        )


def handle_list_symbols(args) -> dict:
    """List all symbols, optionally filtered."""
    from ..gml_index import GMLIndex, SymbolKind

    try:
        project_root = _get_project_root(args)
        kind_filter = getattr(args, "kind", None)
        name_filter = getattr(args, "name_filter", None)
        file_filter = getattr(args, "file_filter", None)
        max_results = getattr(args, "max_results", 100)

        print("[SEARCH] Listing symbols...")

        # Convert kind string to enum if provided
        kind_enum = None
        if kind_filter:
            try:
                kind_enum = SymbolKind(kind_filter.lower())
            except ValueError:
                print(f"[WARN] Unknown symbol kind '{kind_filter}', ignoring filter")

        index = GMLIndex(project_root)
        index.build()

        symbols = index.list_symbols(
            kind=kind_enum,
            name_filter=name_filter,
            file_filter=file_filter,
        )

        if not symbols:
            print("[INFO] No symbols found matching criteria")
            return _ok_payload({"symbols": [], "count": 0})

        total_count = len(symbols)
        truncated = total_count > max_results
        display_symbols = symbols[:max_results]

        filters_desc = []
        if kind_filter:
            filters_desc.append(f"kind={kind_filter}")
        if name_filter:
            filters_desc.append(f"name contains '{name_filter}'")
        if file_filter:
            filters_desc.append(f"file contains '{file_filter}'")

        filter_str = f" (filters: {', '.join(filters_desc)})" if filters_desc else ""

        print(
            f"[OK] Found {total_count} symbol(s){filter_str}"
            + (f" (showing first {max_results})" if truncated else "")
            + ":"
        )

        result_symbols = []
        for symbol in display_symbols:
            loc = symbol.location
            rel_path = _make_relative(loc.file_path, project_root)
            print(f"  [{symbol.kind.value}] {symbol.name} - {rel_path}:{loc.line}")
            result_symbols.append(symbol.to_dict())

        return _ok_payload(
            {
                "symbols": result_symbols,
                "count": total_count,
                "truncated": truncated,
            }
        )

    except Exception as e:
        print(f"[ERROR] Error listing symbols: {e}")
        return _error_payload(str(e), code="list_symbols_failed", operation="list_symbols", symbols=[])


def _get_project_root(args) -> Path:
    """Extract project root from args, defaulting to cwd."""
    if hasattr(args, "project_root") and args.project_root:
        return Path(args.project_root).resolve()
    return Path.cwd()


def _make_relative(path: Path, project_root: Path) -> str:
    """Make a path relative to project root if possible."""
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)
