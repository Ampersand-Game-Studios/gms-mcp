from __future__ import annotations

from typing import Any, Dict, Optional


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # =========================================================================
    # GML Documentation Tools
    # =========================================================================

    @mcp.tool()
    async def gm_doc_lookup(
        function_name: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Look up documentation for a specific GML function.

        Fetches documentation from manual.gamemaker.io and caches it locally.

        Args:
            function_name: The name of the GML function (e.g., "draw_sprite").
            force_refresh: If True, bypass cache and fetch fresh documentation.

        Returns:
            Dictionary with function documentation including description, syntax,
            parameters, return value, and examples. Returns suggestions if the
            function is not found.
        """
        from gms_helpers.gml_docs import lookup
        return lookup(function_name, force_refresh=force_refresh)

    @mcp.tool()
    async def gm_doc_search(
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Search for GML functions matching a query.

        Searches function names using fuzzy matching and filters.

        Args:
            query: Search query (matches function names).
            category: Optional category filter (e.g., "Drawing", "Strings").
            limit: Maximum number of results (default: 20).

        Returns:
            Dictionary with matching functions sorted by relevance.
        """
        from gms_helpers.gml_docs import search
        return search(query, category=category, limit=limit)

    @mcp.tool()
    async def gm_doc_list(
        category: Optional[str] = None,
        pattern: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        List GML functions, optionally filtered by category or pattern.

        Args:
            category: Filter by category name (partial match, e.g., "Drawing").
            pattern: Filter by regex pattern on function name (e.g., "^draw_").
            limit: Maximum number of results (default: 100).

        Returns:
            Dictionary with list of functions matching the filters.
        """
        from gms_helpers.gml_docs import list_functions
        return list_functions(category=category, pattern=pattern, limit=limit)

    @mcp.tool()
    async def gm_doc_categories() -> Dict[str, Any]:
        """
        List all GML documentation categories.

        Returns:
            Dictionary with all available categories and their function counts.
        """
        from gms_helpers.gml_docs import list_categories
        return list_categories()

    @mcp.tool()
    async def gm_doc_cache_stats() -> Dict[str, Any]:
        """
        Get statistics about the GML documentation cache.

        Returns:
            Dictionary with cache size, age, and function counts.
        """
        from gms_helpers.gml_docs import get_cache_stats
        return get_cache_stats()

    @mcp.tool()
    async def gm_doc_cache_clear(functions_only: bool = False) -> Dict[str, Any]:
        """
        Clear the GML documentation cache.

        Args:
            functions_only: If True, only clear cached functions, keep the index.

        Returns:
            Dictionary with statistics about what was cleared.
        """
        from gms_helpers.gml_docs import clear_cache
        return clear_cache(functions_only=functions_only)
