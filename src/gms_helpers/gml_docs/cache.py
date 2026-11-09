"""
Local caching for GML documentation.

Stores fetched documentation in ~/.gms-mcp/doc_cache/ with TTL-based expiration.
"""

from __future__ import annotations

import json
import os
import tempfile
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
    return cache_dir


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON next to ``path`` and rename it into place, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


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
        self._index: Optional[Dict[str, FunctionIndexEntry]] = None
        self._index_loaded_at: float = 0

    def _get_index_path(self) -> Path:
        return self.cache_dir / "index.json"

    def _get_function_path(self, name: str) -> Path:
        """Get the cache file path for a function."""
        # Normalize name to lowercase for consistent caching
        safe_name = name.lower().replace("/", "_").replace("\\", "_")
        return self.functions_dir / f"{safe_name}.json"

    def get_index(self, *, allow_stale: bool = False) -> Optional[Dict[str, FunctionIndexEntry]]:
        """Get the cached function index.

        ``allow_stale`` returns an expired index too (used when a refresh fails).
        """
        if self._index is not None and not allow_stale:
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
            entries = data.get("entries", {})
            index = {name: FunctionIndexEntry.from_dict(entry) for name, entry in entries.items()}
            if time.time() > cached_at + INDEX_TTL_SECONDS:
                return index if allow_stale else None

            self._index = index
            self._index_loaded_at = time.time()
            return self._index
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save_index(self, entries: Dict[str, FunctionIndexEntry]) -> None:
        """Save the function index to cache."""
        data = {
            "cached_at": time.time(),
            "entries": {name: entry.to_dict() for name, entry in entries.items()},
        }
        _atomic_write_json(self._get_index_path(), data)

        self._index = entries
        self._index_loaded_at = time.time()

    def get_function(self, name: str, *, allow_stale: bool = False) -> Optional[CachedDoc]:
        """Get a cached function documentation (``allow_stale`` also returns expired entries)."""
        path = self._get_function_path(name)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            doc = CachedDoc.from_dict(data)
            if doc.is_expired() and not allow_stale:
                # Reading stale cache data must not delete it implicitly.
                return None
            return doc
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save_function(self, doc: CachedDoc) -> None:
        """Save function documentation to cache."""
        _atomic_write_json(self._get_function_path(doc.name), doc.to_dict())

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
