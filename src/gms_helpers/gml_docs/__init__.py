"""
GML Documentation module.

Provides on-demand fetching and caching of GameMaker Language documentation
from manual.gamemaker.io.

Usage:
    from gms_helpers.gml_docs import lookup, search, list_functions, clear_cache

    # Look up a specific function
    doc = lookup("draw_sprite")

    # Search for functions
    results = search("collision")

    # List functions by category
    funcs = list_functions(category="Drawing")
"""

from .cache import DocCache, clear_cache, get_cache_stats
from .fetcher import fetch_function_doc, fetch_function_index
from .search import lookup, search, list_functions, list_categories

__all__ = [
    "lookup",
    "search",
    "list_functions",
    "list_categories",
    "clear_cache",
    "get_cache_stats",
    "fetch_function_doc",
    "fetch_function_index",
    "DocCache",
]
