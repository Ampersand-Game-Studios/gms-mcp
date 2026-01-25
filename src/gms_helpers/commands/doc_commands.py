"""
Command handlers for GML documentation operations.
"""

from __future__ import annotations

import json
from typing import Any, Dict


def handle_doc_lookup(args) -> bool:
    """Handle the doc lookup command."""
    from gms_helpers.gml_docs import lookup

    result = lookup(args.function_name, force_refresh=getattr(args, 'refresh', False))

    if result.get("ok"):
        print(f"\n{result['name']}")
        print("=" * len(result['name']))
        print(f"Category: {result['category']}")
        if result.get('subcategory'):
            print(f"Subcategory: {result['subcategory']}")
        print(f"URL: {result['url']}")
        print()

        if result.get('description'):
            print("Description:")
            print("-" * 40)
            print(result['description'])
            print()

        if result.get('syntax'):
            print("Syntax:")
            print("-" * 40)
            print(f"  {result['syntax']}")
            print()

        if result.get('parameters'):
            print("Parameters:")
            print("-" * 40)
            for param in result['parameters']:
                print(f"  {param['name']} ({param['type']})")
                print(f"      {param['description']}")
            print()

        print(f"Returns: {result.get('returns', 'N/A')}")

        if result.get('examples'):
            print()
            print("Examples:")
            print("-" * 40)
            for i, example in enumerate(result['examples'], 1):
                if len(result['examples']) > 1:
                    print(f"\nExample {i}:")
                print(example)

        return True
    else:
        print(f"[ERROR] {result.get('error', 'Unknown error')}")
        if result.get('suggestions'):
            print("\nDid you mean:")
            for suggestion in result['suggestions']:
                print(f"  - {suggestion}")
        return False


def handle_doc_search(args) -> bool:
    """Handle the doc search command."""
    from gms_helpers.gml_docs import search

    result = search(
        args.query,
        category=getattr(args, 'category', None),
        limit=getattr(args, 'limit', 20),
    )

    if result.get("ok"):
        print(f"\nSearch results for '{result['query']}'")
        if result.get('category_filter'):
            print(f"Category filter: {result['category_filter']}")
        print(f"Found {result['count']} matches\n")

        if result['results']:
            # Find max name length for formatting
            max_name = max(len(r['name']) for r in result['results'])

            for r in result['results']:
                cat = f"{r['category']}"
                if r.get('subcategory'):
                    cat += f" > {r['subcategory']}"
                print(f"  {r['name']:<{max_name}}  [{cat}]")
        else:
            print("No matching functions found.")

        return True
    else:
        print(f"[ERROR] {result.get('error', 'Unknown error')}")
        return False


def handle_doc_list(args) -> bool:
    """Handle the doc list command."""
    from gms_helpers.gml_docs import list_functions

    result = list_functions(
        category=getattr(args, 'category', None),
        pattern=getattr(args, 'pattern', None),
        limit=getattr(args, 'limit', 100),
    )

    if result.get("ok"):
        filters = []
        if result.get('category_filter'):
            filters.append(f"category: {result['category_filter']}")
        if result.get('pattern_filter'):
            filters.append(f"pattern: {result['pattern_filter']}")

        filter_str = f" ({', '.join(filters)})" if filters else ""
        print(f"\nGML Functions{filter_str}")
        print(f"Showing {result['count']} of {result['total_in_index']} total\n")

        if result['results']:
            # Group by category
            by_category: Dict[str, list] = {}
            for r in result['results']:
                cat = r['category']
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(r['name'])

            for cat in sorted(by_category.keys()):
                print(f"[{cat}]")
                funcs = by_category[cat]
                # Print in columns
                col_width = max(len(f) for f in funcs) + 2
                cols = max(1, 80 // col_width)
                for i in range(0, len(funcs), cols):
                    row = funcs[i:i + cols]
                    print("  " + "".join(f.ljust(col_width) for f in row))
                print()
        else:
            print("No matching functions found.")

        return True
    else:
        print(f"[ERROR] {result.get('error', 'Unknown error')}")
        return False


def handle_doc_categories(args) -> bool:
    """Handle the doc categories command."""
    from gms_helpers.gml_docs import list_categories

    result = list_categories()

    if result.get("ok"):
        print(f"\nGML Documentation Categories ({result['count']} total)\n")

        for cat in result['categories']:
            print(f"  {cat['name']} ({cat['function_count']} functions)")
            if cat.get('subcategories'):
                for sub in cat['subcategories']:
                    print(f"    └─ {sub['name']} ({sub['count']})")

        return True
    else:
        print(f"[ERROR] {result.get('error', 'Unknown error')}")
        return False


def handle_doc_cache_stats(args) -> bool:
    """Handle the doc cache stats command."""
    from gms_helpers.gml_docs import get_cache_stats

    stats = get_cache_stats()

    print("\nGML Documentation Cache Statistics")
    print("=" * 40)
    print(f"Cache directory: {stats['cache_dir']}")
    print(f"Index exists: {stats['index_exists']}")

    if stats['index_age_seconds'] is not None:
        age_hours = stats['index_age_seconds'] / 3600
        if age_hours < 24:
            age_str = f"{age_hours:.1f} hours"
        else:
            age_str = f"{age_hours / 24:.1f} days"
        print(f"Index age: {age_str}")

    print(f"Functions in index: {stats['index_function_count']}")
    print(f"Cached function docs: {stats['cached_function_count']}")
    print(f"Cache size: {stats['cache_size_kb']:.1f} KB")

    return True


def handle_doc_cache_clear(args) -> bool:
    """Handle the doc cache clear command."""
    from gms_helpers.gml_docs import clear_cache

    functions_only = getattr(args, 'functions_only', False)
    result = clear_cache(functions_only=functions_only)

    print("\nCache cleared:")
    print(f"  Functions removed: {result['functions_removed']}")
    if not functions_only:
        print(f"  Index removed: {result['index_removed']}")

    return True
