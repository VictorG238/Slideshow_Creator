"""Disk-first cache service with optional in-memory staging."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Optional


class CacheService:
    """Manage cache paths and optional RAM mirrors for image bytes."""

    def __init__(self, cache_dir: Path, use_memory_staging: bool = False) -> None:
        self.cache_dir = cache_dir
        self.use_memory_staging = use_memory_staging
        self._memory_cache: Dict[str, bytes] = {}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, cache_key: str, suffix: str = ".img") -> Path:
        """Return a stable on-disk cache path for a cache key."""
        safe_key = self._safe_key(cache_key)
        return self.cache_dir / f"{safe_key}{suffix}"

    @staticmethod
    def key_for_url(source_url: str) -> str:
        """Create a deterministic cache key for an image URL."""
        return hashlib.sha256(source_url.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_key(cache_key: str) -> str:
        """Normalize a cache key to a filename-safe value."""
        if cache_key.isalnum() and len(cache_key) >= 16:
            return cache_key
        return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

    def remember_bytes(self, cache_key: str, payload: bytes, suffix: str = ".img") -> Path:
        """Persist bytes on disk and optionally keep them in memory."""
        target = self.path_for(cache_key, suffix=suffix)
        target.write_bytes(payload)
        if self.use_memory_staging:
            self._memory_cache[cache_key] = payload
        return target

    def remember_url_bytes(self, source_url: str, payload: bytes, suffix: str = ".img") -> Path:
        """Persist payload using a URL-derived cache key."""
        return self.remember_bytes(self.key_for_url(source_url), payload, suffix=suffix)

    def load_bytes(self, cache_key: str, suffix: str = ".img") -> Optional[bytes]:
        """Load cached bytes from memory or disk."""
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        target = self.path_for(cache_key, suffix=suffix)
        if target.exists():
            data = target.read_bytes()
            if self.use_memory_staging:
                self._memory_cache[cache_key] = data
            return data
        return None

    def has(self, cache_key: str, suffix: str = ".img") -> bool:
        """Return True when bytes are available in RAM or on disk."""
        return cache_key in self._memory_cache or self.path_for(cache_key, suffix=suffix).exists()

    def evict(self, cache_key: str, suffix: str = ".img") -> None:
        """Remove one cache item from memory and disk."""
        self._memory_cache.pop(cache_key, None)
        target = self.path_for(cache_key, suffix=suffix)
        if target.exists():
            target.unlink()

    def clear_memory(self) -> None:
        """Clear only in-memory staged cache entries."""
        self._memory_cache.clear()

    def cleanup_disk_cache(self, keep_latest: int = 500) -> int:
        """Prune oldest disk cache files and return how many were removed."""
        if keep_latest < 0:
            raise ValueError("keep_latest must be 0 or greater")

        files = sorted(
            [path for path in self.cache_dir.glob("*") if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        stale = files[keep_latest:]
        for path in stale:
            path.unlink(missing_ok=True)
        return len(stale)
