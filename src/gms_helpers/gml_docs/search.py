"""
Search and lookup functions for GML documentation.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional

from .cache import CachedDoc, DocCache, FunctionIndexEntry
from .fetcher import fetch_function_doc, fetch_function_index


def lookup(
    function_name: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Look up documentation for a specific GML function.

    Args:
        function_name: The name of the function to look up.
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        Dictionary with function documentation or error info.
    """
    cache = DocCache()
    name_lower = function_name.lower().strip()

    # Try exact match first
    doc = fetch_function_doc(name_lower, cache, force_refresh)

    if doc is not None:
        return {
            "ok": True,
            "name": doc.name,
            "category": doc.category,
            "subcategory": doc.subcategory,
            "url": doc.url,
            "description": doc.description,
            "syntax": doc.syntax,
            "parameters": doc.parameters,
            "returns": doc.returns,
            "examples": doc.examples,
            "cached": not force_refresh,
        }

    # Try fuzzy matching
    index = fetch_function_index(cache)
    suggestions = _find_similar_names(name_lower, list(index.keys()), limit=5)

    return {
        "ok": False,
        "error": f"Function '{function_name}' not found",
        "suggestions": suggestions,
    }


def search(
    query: str,
    category: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Search for GML functions matching a query.

    Args:
        query: Search query (matches function names and descriptions).
        category: Optional category filter.
        limit: Maximum number of results to return.

    Returns:
        Dictionary with search results.
    """
    cache = DocCache()
    index = fetch_function_index(cache)

    query_lower = query.lower().strip()
    results: List[Dict[str, Any]] = []

    # Score and filter functions
    scored: List[tuple] = []
    for name, entry in index.items():
        # Category filter
        if category:
            cat_lower = category.lower()
            if cat_lower not in entry.category.lower() and cat_lower not in entry.subcategory.lower():
                continue

        # Calculate relevance score
        score = 0

        # Exact name match
        if name == query_lower:
            score += 100

        # Name starts with query
        elif name.startswith(query_lower):
            score += 50

        # Name contains query
        elif query_lower in name:
            score += 30

        # Query words in name
        else:
            words = query_lower.split()
            for word in words:
                if word in name:
                    score += 10

        # Fuzzy match on name
        if score == 0:
            ratio = difflib.SequenceMatcher(None, query_lower, name).ratio()
            if ratio > 0.6:
                score += int(ratio * 20)

        if score > 0:
            scored.append((score, entry))

    # Sort by score descending, then by name
    scored.sort(key=lambda x: (-x[0], x[1].name))

    # Take top results
    for score, entry in scored[:limit]:
        results.append({
            "name": entry.name,
            "category": entry.category,
            "subcategory": entry.subcategory,
            "url": entry.url,
            "score": score,
        })

    return {
        "ok": True,
        "query": query,
        "category_filter": category,
        "count": len(results),
        "results": results,
    }


def list_functions(
    category: Optional[str] = None,
    pattern: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    List GML functions, optionally filtered by category or pattern.

    Args:
        category: Filter by category name (partial match).
        pattern: Filter by regex pattern on function name.
        limit: Maximum number of results.

    Returns:
        Dictionary with function list.
    """
    cache = DocCache()
    index = fetch_function_index(cache)

    results: List[Dict[str, Any]] = []
    regex = None

    if pattern:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return {
                "ok": False,
                "error": f"Invalid regex pattern: {e}",
            }

    for name, entry in sorted(index.items(), key=lambda x: x[1].name):
        # Category filter
        if category:
            cat_lower = category.lower()
            if cat_lower not in entry.category.lower() and cat_lower not in entry.subcategory.lower():
                continue

        # Pattern filter
        if regex and not regex.search(name):
            continue

        results.append({
            "name": entry.name,
            "category": entry.category,
            "subcategory": entry.subcategory,
        })

        if len(results) >= limit:
            break

    return {
        "ok": True,
        "category_filter": category,
        "pattern_filter": pattern,
        "count": len(results),
        "total_in_index": len(index),
        "results": results,
    }


def list_categories() -> Dict[str, Any]:
    """
    List all available function categories.

    Returns:
        Dictionary with category list.
    """
    cache = DocCache()
    index = fetch_function_index(cache)

    # Collect unique categories
    categories: Dict[str, Dict[str, int]] = {}

    for entry in index.values():
        cat = entry.category
        subcat = entry.subcategory

        if cat not in categories:
            categories[cat] = {"_total": 0, "_subcategories": {}}

        categories[cat]["_total"] += 1

        if subcat:
            if subcat not in categories[cat]["_subcategories"]:
                categories[cat]["_subcategories"][subcat] = 0
            categories[cat]["_subcategories"][subcat] += 1

    # Format output
    result_list = []
    for cat, data in sorted(categories.items()):
        item = {
            "name": cat,
            "function_count": data["_total"],
        }
        if data["_subcategories"]:
            item["subcategories"] = [
                {"name": sub, "count": count}
                for sub, count in sorted(data["_subcategories"].items())
            ]
        result_list.append(item)

    return {
        "ok": True,
        "count": len(result_list),
        "categories": result_list,
    }


def _find_similar_names(query: str, names: List[str], limit: int = 5) -> List[str]:
    """Find names similar to the query using fuzzy matching."""
    # Get close matches
    matches = difflib.get_close_matches(query, names, n=limit, cutoff=0.4)

    # Also add prefix matches
    prefix_matches = [n for n in names if n.startswith(query[:3]) and n not in matches]
    matches.extend(prefix_matches[:limit - len(matches)])

    return matches[:limit]
