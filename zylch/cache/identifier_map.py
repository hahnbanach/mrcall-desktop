"""Identifier-to-memory mapping cache for person-centric lookups.

ZYLCH IS PERSON-CENTRIC: A person can have multiple emails, phones, etc.
This cache provides O(1) lookup from any identifier to the person's memory_id.

Structure:
{
    "{owner}:{assistant}": {
        "email:luigi@example.com": {"memory_id": 123, "updated_at": "..."},
        "phone:+393331234567": {"memory_id": 123, "updated_at": "..."},
        "name:luigi scrosati": {"memory_id": 123, "updated_at": "..."}
    }
}
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """Normalize phone number by removing all non-digit characters except leading +.

    Args:
        phone: Phone number string

    Returns:
        Normalized phone (e.g., "+393331234567")
    """
    if not phone:
        return ""
    # Keep leading + if present, remove all other non-digits
    has_plus = phone.startswith("+")
    digits = re.sub(r"\D", "", phone)
    return f"+{digits}" if has_plus else digits


def normalize_name(name: str) -> str:
    """Normalize name for matching.

    Args:
        name: Person name

    Returns:
        Lowercase, stripped, single-spaced name
    """
    if not name:
        return ""
    return " ".join(name.lower().split())


class IdentifierMapCache:
    """Cache for mapping identifiers (email, phone, name) to memory IDs.

    Provides O(1) lookup from any identifier to find the person's memory.
    Supports multiple identifiers pointing to the same memory_id (person-centric).
    """

    def __init__(self, cache_dir: str = "cache/", ttl_days: int = 7):
        """Initialize identifier map cache.

        Args:
            cache_dir: Directory to store the cache file
            ttl_days: Time-to-live in days for freshness check
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "identifier_map.json"
        self.ttl_days = ttl_days
        self._data: Dict[str, Dict[str, Dict[str, Any]]] = self._load()

        logger.info(f"Initialized IdentifierMapCache at {self.cache_file} with TTL={ttl_days} days")

    def _load(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Load cache from disk.

        Returns:
            Cache data structure
        """
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to load identifier map: {e}")
                return {}
        return {}

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, "w") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save identifier map: {e}")

    def _get_namespace_key(self, owner_id: str, assistant_id: str) -> str:
        """Build namespace key.

        Args:
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier

        Returns:
            Namespace key string
        """
        return f"{owner_id}:{assistant_id}"

    def _get_identifier_key(self, identifier_type: str, value: str) -> str:
        """Build identifier key.

        Args:
            identifier_type: Type ("email", "phone", "name")
            value: The identifier value

        Returns:
            Identifier key string
        """
        return f"{identifier_type}:{value}"

    def lookup(
        self,
        query: str,
        owner_id: str,
        assistant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Look up a person by any identifier.

        Tries to match as email, phone, then name.

        Args:
            query: The search query (email, phone, or name)
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier

        Returns:
            Match info dict with memory_id and updated_at, or None
        """
        ns_key = self._get_namespace_key(owner_id, assistant_id)
        ns_data = self._data.get(ns_key, {})

        if not ns_data:
            logger.debug(f"No data for namespace {ns_key}")
            return None

        query_lower = query.lower().strip()

        # Try as email
        email_key = self._get_identifier_key("email", query_lower)
        if email_key in ns_data:
            logger.debug(f"Found match by email: {query_lower}")
            return ns_data[email_key]

        # Try as phone
        phone_normalized = normalize_phone(query)
        if phone_normalized:
            phone_key = self._get_identifier_key("phone", phone_normalized)
            if phone_key in ns_data:
                logger.debug(f"Found match by phone: {phone_normalized}")
                return ns_data[phone_key]

        # Try as name
        name_normalized = normalize_name(query)
        if name_normalized:
            name_key = self._get_identifier_key("name", name_normalized)
            if name_key in ns_data:
                logger.debug(f"Found match by name: {name_normalized}")
                return ns_data[name_key]

        logger.debug(f"No match found for query: {query}")
        return None

    def register(
        self,
        identifiers: List[Tuple[str, str]],
        memory_id: int,
        owner_id: str,
        assistant_id: str
    ) -> None:
        """Register identifiers for a person's memory.

        All identifiers will point to the same memory_id (person-centric).

        Args:
            identifiers: List of (type, value) tuples, e.g., [("email", "a@b.com"), ("name", "John")]
            memory_id: The ZylchMemory ID for this person
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier
        """
        ns_key = self._get_namespace_key(owner_id, assistant_id)

        if ns_key not in self._data:
            self._data[ns_key] = {}

        now = datetime.now().isoformat()
        entry = {
            "memory_id": memory_id,
            "updated_at": now
        }

        registered = []
        for id_type, id_value in identifiers:
            if not id_value:
                continue

            # Normalize based on type
            if id_type == "email":
                normalized = id_value.lower().strip()
            elif id_type == "phone":
                normalized = normalize_phone(id_value)
            elif id_type == "name":
                normalized = normalize_name(id_value)
            else:
                normalized = id_value.lower().strip()

            if normalized:
                key = self._get_identifier_key(id_type, normalized)
                self._data[ns_key][key] = entry
                registered.append(f"{id_type}:{normalized}")

        self._save()
        logger.info(f"Registered {len(registered)} identifiers for memory_id={memory_id}: {registered}")

    def is_fresh(
        self,
        query: str,
        owner_id: str,
        assistant_id: str,
        ttl_days: Optional[int] = None
    ) -> bool:
        """Check if a cached entry is fresh (not stale).

        Args:
            query: The search query
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier
            ttl_days: Override default TTL

        Returns:
            True if entry exists and is fresh, False otherwise
        """
        entry = self.lookup(query, owner_id, assistant_id)
        if not entry:
            return False

        ttl = ttl_days if ttl_days is not None else self.ttl_days

        try:
            updated_at = datetime.fromisoformat(entry["updated_at"])
            expires_at = updated_at + timedelta(days=ttl)
            is_fresh = datetime.now() < expires_at

            if not is_fresh:
                logger.debug(f"Entry for {query} is stale (updated {updated_at})")

            return is_fresh
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to check freshness: {e}")
            return False

    def get_memory_id(
        self,
        query: str,
        owner_id: str,
        assistant_id: str
    ) -> Optional[int]:
        """Get memory ID for a query.

        Args:
            query: The search query
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier

        Returns:
            Memory ID or None
        """
        entry = self.lookup(query, owner_id, assistant_id)
        return entry.get("memory_id") if entry else None

    def remove_by_memory_id(
        self,
        memory_id: int,
        owner_id: str,
        assistant_id: str
    ) -> int:
        """Remove all identifiers for a memory ID.

        Args:
            memory_id: Memory ID to remove
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier

        Returns:
            Number of identifiers removed
        """
        ns_key = self._get_namespace_key(owner_id, assistant_id)
        ns_data = self._data.get(ns_key, {})

        keys_to_remove = [
            key for key, entry in ns_data.items()
            if entry.get("memory_id") == memory_id
        ]

        for key in keys_to_remove:
            del self._data[ns_key][key]

        if keys_to_remove:
            self._save()
            logger.info(f"Removed {len(keys_to_remove)} identifiers for memory_id={memory_id}")

        return len(keys_to_remove)

    def get_all_for_memory(
        self,
        memory_id: int,
        owner_id: str,
        assistant_id: str
    ) -> List[Tuple[str, str]]:
        """Get all identifiers for a memory ID.

        Args:
            memory_id: Memory ID
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier

        Returns:
            List of (type, value) tuples for this person
        """
        ns_key = self._get_namespace_key(owner_id, assistant_id)
        ns_data = self._data.get(ns_key, {})

        result = []
        for key, entry in ns_data.items():
            if entry.get("memory_id") == memory_id:
                # Parse "type:value" key
                parts = key.split(":", 1)
                if len(parts) == 2:
                    result.append((parts[0], parts[1]))

        return result

    def get_stats(self, owner_id: str, assistant_id: str) -> Dict[str, Any]:
        """Get cache statistics for a namespace.

        Args:
            owner_id: Owner identifier
            assistant_id: Assistant/business identifier

        Returns:
            Statistics dict
        """
        ns_key = self._get_namespace_key(owner_id, assistant_id)
        ns_data = self._data.get(ns_key, {})

        # Count unique memory IDs (persons)
        unique_persons = len(set(
            entry.get("memory_id") for entry in ns_data.values()
            if entry.get("memory_id")
        ))

        # Count by type
        by_type: Dict[str, int] = {}
        for key in ns_data.keys():
            id_type = key.split(":")[0]
            by_type[id_type] = by_type.get(id_type, 0) + 1

        # Count fresh vs stale
        fresh = 0
        stale = 0
        cutoff = datetime.now() - timedelta(days=self.ttl_days)

        for entry in ns_data.values():
            try:
                updated_at = datetime.fromisoformat(entry.get("updated_at", ""))
                if updated_at > cutoff:
                    fresh += 1
                else:
                    stale += 1
            except:
                stale += 1

        return {
            "namespace": ns_key,
            "total_identifiers": len(ns_data),
            "unique_persons": unique_persons,
            "by_type": by_type,
            "fresh": fresh,
            "stale": stale,
            "ttl_days": self.ttl_days
        }
