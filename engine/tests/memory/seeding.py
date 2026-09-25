"""Test-only seeding of memory rows: the one door a test uses to put a blob in place.

A test that needs memory to exist before it runs the harness seeds it here
rather than calling a storage writer itself, so every test seeds through one
module. Both functions take the test's ``BlobStorage``, delegate to its
``store_blob`` / ``update_blob`` and answer what those answer.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def store_blob(
    storage: Any,
    owner_id: str,
    namespace: str,
    content: str,
    event_description: Optional[str] = None,
) -> Dict[str, Any]:
    """A new blob with its sentence embeddings; returns the created row."""
    return storage.store_blob(owner_id, namespace, content, event_description)


def update_blob(
    storage: Any,
    blob_id: str,
    owner_id: str,
    content: str,
    event_description: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Rewrite a seeded blob; ``kwargs`` are ``update_blob``'s CAS and reason keywords."""
    return storage.update_blob(blob_id, owner_id, content, event_description, **kwargs)


__all__ = ["store_blob", "update_blob"]
