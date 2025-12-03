"""Simple JSON-based file cache for contact enrichment data."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class JSONCache:
    """Simple JSON file-based cache with TTL support."""

    def __init__(self, cache_dir: str = "cache/", ttl_days: int = 30):
        """Initialize JSON cache.

        Args:
            cache_dir: Directory to store cache files
            ttl_days: Time-to-live in days for cached entries
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_days = ttl_days
        logger.info(f"Initialized JSONCache at {self.cache_dir} with TTL={ttl_days} days")

    def _get_cache_file(self, key: str) -> Path:
        """Get cache file path for a key.

        Args:
            key: Cache key (e.g., email address)

        Returns:
            Path to cache file
        """
        # Use hash to avoid filesystem issues with special characters
        import hashlib
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached data for a key.

        Args:
            key: Cache key

        Returns:
            Cached data if found and not expired, None otherwise
        """
        cache_file = self._get_cache_file(key)

        if not cache_file.exists():
            logger.debug(f"Cache miss: {key} (file not found)")
            return None

        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)

            # Check expiration
            cached_at = datetime.fromisoformat(cached["cached_at"])
            expires_at = cached_at + timedelta(days=self.ttl_days)

            if datetime.now() > expires_at:
                logger.debug(f"Cache expired: {key} (cached at {cached_at})")
                cache_file.unlink()  # Delete expired cache
                return None

            logger.debug(f"Cache hit: {key}")
            return cached["data"]

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to read cache for {key}: {e}")
            # Delete corrupted cache file
            cache_file.unlink(missing_ok=True)
            return None

    def set(self, key: str, data: Dict[str, Any]) -> None:
        """Set cached data for a key.

        Args:
            key: Cache key
            data: Data to cache
        """
        cache_file = self._get_cache_file(key)

        cached = {
            "key": key,
            "cached_at": datetime.now().isoformat(),
            "data": data,
        }

        try:
            with open(cache_file, "w") as f:
                json.dump(cached, f, indent=2)
            logger.debug(f"Cached data for {key}")
        except Exception as e:
            logger.error(f"Failed to write cache for {key}: {e}")

    def invalidate(self, key: str) -> None:
        """Invalidate cached data for a key.

        Args:
            key: Cache key to invalidate
        """
        cache_file = self._get_cache_file(key)
        cache_file.unlink(missing_ok=True)
        logger.debug(f"Invalidated cache for {key}")

    def clear(self) -> None:
        """Clear all cached data."""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        logger.info("Cleared all cache files")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Statistics about cached entries
        """
        files = list(self.cache_dir.glob("*.json"))
        total = len(files)
        expired = 0

        for cache_file in files:
            try:
                with open(cache_file, "r") as f:
                    cached = json.load(f)
                cached_at = datetime.fromisoformat(cached["cached_at"])
                expires_at = cached_at + timedelta(days=self.ttl_days)
                if datetime.now() > expires_at:
                    expired += 1
            except:
                expired += 1

        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
            "ttl_days": self.ttl_days,
        }
