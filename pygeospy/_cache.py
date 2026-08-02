"""
pygeospy._cache — Persistent disk cache for API responses.
Prevents hitting rate limits on repeat queries; respects TTL per-entry.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("pygeospy.cache")

def _default_cache_dir() -> Path:
    """
    Platform-appropriate cache directory:

    - ``PYGEOSPY_CACHE_DIR`` env var, if set (all platforms)
    - Windows: ``%LOCALAPPDATA%\\pygeospy\\cache``
    - macOS:   ``~/Library/Caches/pygeospy``
    - Linux:   ``$XDG_CACHE_HOME/pygeospy`` or ``~/.cache/pygeospy``
    """
    env = os.environ.get("PYGEOSPY_CACHE_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "pygeospy" / "cache"
        return Path.home() / "AppData" / "Local" / "pygeospy" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "pygeospy"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "pygeospy"
    return Path.home() / ".cache" / "pygeospy"


_DEFAULT_CACHE_DIR = _default_cache_dir()


class DiskCache:
    """
    Simple JSON-based disk cache with per-entry TTL.

    Usage::

        cache = DiskCache("elevation")
        key   = cache.make_key(lat=1.0, lon=2.0)
        result = cache.get(key)
        if result is None:
            result = expensive_api_call(...)
            cache.set(key, result, ttl=86400)  # 1 day
    """

    def __init__(self, namespace: str, cache_dir: Optional[Path] = None, default_ttl: int = 86400):
        self.namespace  = namespace
        self.cache_dir  = (cache_dir or _DEFAULT_CACHE_DIR) / namespace
        self.default_ttl = default_ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        hashed = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{hashed}.json"

    def make_key(self, **kwargs) -> str:
        """Build a deterministic cache key from keyword args."""
        return json.dumps(kwargs, sort_keys=True)

    def get(self, key: str) -> Optional[Any]:
        """Return cached value or None if missing / expired."""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as f:
                entry = json.load(f)
            expires = entry.get("expires", 0)
            if expires and time.time() > expires:
                path.unlink(missing_ok=True)
                return None
            return entry.get("value")
        except (json.JSONDecodeError, KeyError):
            path.unlink(missing_ok=True)
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store value with optional TTL (seconds). ttl=None = never expires."""
        ttl = ttl if ttl is not None else self.default_ttl
        entry = {
            "key":     key,
            "value":   value,
            "created": time.time(),
            "expires": time.time() + ttl if ttl else 0,
        }
        path = self._path(key)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(entry, f)
        except OSError as e:
            logger.warning(f"Cache write failed for {path}: {e}")

    def invalidate(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def clear(self) -> int:
        """Delete all entries in this namespace. Returns number deleted."""
        count = 0
        for p in self.cache_dir.glob("*.json"):
            p.unlink()
            count += 1
        return count

    def stats(self) -> dict:
        """Return cache statistics."""
        files = list(self.cache_dir.glob("*.json"))
        total_bytes = sum(p.stat().st_size for p in files)
        return {
            "namespace":   self.namespace,
            "entries":     len(files),
            "size_bytes":  total_bytes,
            "cache_dir":   str(self.cache_dir),
        }


# ── Module-level cache singletons ─────────────────────────────────────────────

_caches: dict[str, DiskCache] = {}


def get_cache(namespace: str, **kwargs) -> DiskCache:
    """Get or create a DiskCache for the given namespace."""
    if namespace not in _caches:
        _caches[namespace] = DiskCache(namespace, **kwargs)
    return _caches[namespace]


# ── Decorator ────────────────────────────────────────────────────────────────

def cached(namespace: str, ttl: int = 86400):
    """
    Decorator that caches function results by (args, kwargs) key.

    Example::

        @cached("elevation", ttl=7 * 86400)
        def get_elevation(lat, lon):
            ...
    """
    import functools

    def decorator(fn):
        cache = get_cache(namespace)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = cache.make_key(fn=fn.__name__, args=str(args), kwargs=kwargs)
            result = cache.get(key)
            if result is not None:
                logger.debug(f"Cache HIT: {namespace}/{fn.__name__}")
                return result
            result = fn(*args, **kwargs)
            cache.set(key, result, ttl=ttl)
            logger.debug(f"Cache SET: {namespace}/{fn.__name__}")
            return result

        return wrapper
    return decorator
