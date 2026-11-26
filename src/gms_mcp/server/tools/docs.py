from __future__ import annotations

from typing import Any, Dict, Optional


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # =========================================================================
    # GML Documentation Tools
    # =========================================================================

    @mcp.tool()
    def gm_doc_lookup(
        function_name: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Look up manual.gamemaker.io docs for a GML function (cached; force_refresh bypasses cache).
        Returns description, syntax, parameters, return value and examples, or suggestions if missing."""
        from gms_helpers.gml_docs import lookup

        return lookup(function_name, force_refresh=force_refresh)

    @mcp.tool()
    def gm_doc_search(
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Fuzzy-search GML function names, optionally within category (e.g. "Drawing"); up to limit results."""
        from gms_helpers.gml_docs import search

        return search(query, category=category, limit=limit)

    @mcp.tool()
    def gm_doc_list(
        category: Optional[str] = None,
        pattern: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List GML functions, optionally filtered by partial category or name regex pattern (e.g. "^draw_")."""
        from gms_helpers.gml_docs import list_functions

        return list_functions(category=category, pattern=pattern, limit=limit)

    @mcp.tool()
    def gm_doc_categories() -> Dict[str, Any]:
        """List all GML documentation categories and their function counts."""
        from gms_helpers.gml_docs import list_categories

        return list_categories()

    @mcp.tool()
    def gm_doc_cache_stats() -> Dict[str, Any]:
        """Return GML documentation cache size, age and function counts."""
        from gms_helpers.gml_docs import get_cache_stats

        return get_cache_stats()

    @mcp.tool()
    def gm_doc_cache_clear(functions_only: bool = False) -> Dict[str, Any]:
        """Clear the GML documentation cache (functions_only=true keeps the index)."""
        from gms_helpers.gml_docs import clear_cache

        return clear_cache(functions_only=functions_only)
