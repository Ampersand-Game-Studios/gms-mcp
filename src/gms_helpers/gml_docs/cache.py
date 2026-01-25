"""
Local caching for GML documentation.

Stores fetched documentation in ~/.gms-mcp/doc_cache/ with TTL-based expiration.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Default cache TTL: 30 days in seconds
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60

# Index refresh interval: 7 days
INDEX_TTL_SECONDS = 7 * 24 * 60 * 60


def _get_cache_dir() -> Path:
    """Get the cache directory, creating if needed."""
    cache_dir = Path.home() / ".gms-mcp" / "doc_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@dataclass
class CachedDoc:
    """A cached function documentation entry."""

    name: str
    category: str
    subcategory: str
    url: str
    description: str
    syntax: str
    parameters: List[Dict[str, str]]
    returns: str
    examples: List[str]
    cached_at: float
    ttl: float = DEFAULT_TTL_SECONDS

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return time.time() > (self.cached_at + self.ttl)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedDoc":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class FunctionIndexEntry:
    """An entry in the function index."""

    name: str
    category: str
    subcategory: str
    url: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "FunctionIndexEntry":
        return cls(**data)


class DocCache:
    """Cache manager for GML documentation."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or _get_cache_dir()
        self.functions_dir = self.cache_dir / "functions"
        self.functions_dir.mkdir(parents=True, exist_ok=True)
        self._index: Optional[Dict[str, FunctionIndexEntry]] = None
        self._index_loaded_at: float = 0

    def _get_index_path(self) -> Path:
        return self.cache_dir / "index.json"

    def _get_function_path(self, name: str) -> Path:
        """Get the cache file path for a function."""
        # Normalize name to lowercase for consistent caching
        safe_name = name.lower().replace("/", "_").replace("\\", "_")
        return self.functions_dir / f"{safe_name}.json"

    def get_index(self) -> Optional[Dict[str, FunctionIndexEntry]]:
        """Get the cached function index."""
        if self._index is not None:
            # Check if in-memory index is still fresh
            if time.time() - self._index_loaded_at < 300:  # 5 min memory cache
                return self._index

        index_path = self._get_index_path()
        if not index_path.exists():
            return None

        try:
            with index_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            # Check if index has expired
            cached_at = data.get("cached_at", 0)
            if time.time() > cached_at + INDEX_TTL_SECONDS:
                return None

            entries = data.get("entries", {})
            self._index = {
                name: FunctionIndexEntry.from_dict(entry)
                for name, entry in entries.items()
            }
            self._index_loaded_at = time.time()
            return self._index
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save_index(self, entries: Dict[str, FunctionIndexEntry]) -> None:
        """Save the function index to cache."""
        index_path = self._get_index_path()
        data = {
            "cached_at": time.time(),
            "entries": {name: entry.to_dict() for name, entry in entries.items()},
        }
        with index_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self._index = entries
        self._index_loaded_at = time.time()

    def get_function(self, name: str) -> Optional[CachedDoc]:
        """Get a cached function documentation."""
        path = self._get_function_path(name)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            doc = CachedDoc.from_dict(data)
            if doc.is_expired():
                # Remove expired entry
                path.unlink(missing_ok=True)
                return None
            return doc
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save_function(self, doc: CachedDoc) -> None:
        """Save function documentation to cache."""
        path = self._get_function_path(doc.name)
        with path.open("w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, indent=2)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        index_path = self._get_index_path()
        index_exists = index_path.exists()
        index_age = None
        index_count = 0

        if index_exists:
            try:
                with index_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                cached_at = data.get("cached_at", 0)
                index_age = int(time.time() - cached_at)
                index_count = len(data.get("entries", {}))
            except Exception:
                pass

        # Count cached functions
        func_count = len(list(self.functions_dir.glob("*.json")))

        # Calculate cache size
        cache_size = sum(f.stat().st_size for f in self.cache_dir.rglob("*.json"))

        return {
            "cache_dir": str(self.cache_dir),
            "index_exists": index_exists,
            "index_age_seconds": index_age,
            "index_function_count": index_count,
            "cached_function_count": func_count,
            "cache_size_bytes": cache_size,
            "cache_size_kb": round(cache_size / 1024, 2),
        }


def clear_cache(functions_only: bool = False) -> Dict[str, Any]:
    """
    Clear the documentation cache.

    Args:
        functions_only: If True, only clear cached functions, keep the index.

    Returns:
        Statistics about what was cleared.
    """
    cache = DocCache()
    stats = {"functions_removed": 0, "index_removed": False}

    # Clear function cache
    for f in cache.functions_dir.glob("*.json"):
        f.unlink()
        stats["functions_removed"] += 1

    # Clear index unless functions_only
    if not functions_only:
        index_path = cache._get_index_path()
        if index_path.exists():
            index_path.unlink()
            stats["index_removed"] = True

    return stats


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return DocCache().get_stats()
