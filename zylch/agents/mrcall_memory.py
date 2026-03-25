"""MrCall Config Memory — Persist configuration decisions as entity blobs.

After each successful configure_* operation, a human-readable summary is saved
as a blob in namespace {owner_id}:mrcall:{business_id}. This memory is injected
into the system prompt on subsequent runs, giving the agent context about past
configuration decisions ("this business is a tire shop with roadside assistance").

Uses the existing blob infrastructure (blob_storage, embeddings, PostgreSQL).
One blob per business, updated (appended) on each configuration change.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level singleton to avoid re-init on every call
_blob_storage = None


def _get_blob_storage():
    """Lazy-init BlobStorage singleton."""
    global _blob_storage
    if _blob_storage is None:
        try:
            from zylch.memory.blob_storage import BlobStorage
            from zylch.memory.embeddings import EmbeddingEngine
            from zylch.memory.config import MemoryConfig
            from zylch.storage.database import get_session

            mem_config = MemoryConfig()
            engine = EmbeddingEngine(mem_config)
            _blob_storage = BlobStorage(get_session, engine)
        except Exception as e:
            logger.warning(f"[mrcall_memory] Could not init BlobStorage: {e}")
    return _blob_storage


def config_memory_namespace(owner_id: str, business_id: str) -> str:
    """Namespace for a business's config memory blobs."""
    return f"{owner_id}:mrcall:{business_id}"


def save_config_memory(
    owner_id: str,
    business_id: str,
    feature: str,
    summary: str,
) -> None:
    """Save a configuration change summary as a blob.

    Creates or updates a single blob per business in the mrcall namespace.
    The blob accumulates a log of all configuration decisions made.

    Args:
        owner_id: Firebase UID
        business_id: MrCall business ID
        feature: Feature name (e.g. 'welcome_inbound')
        summary: Human-readable summary of what was changed
    """
    blob_storage = _get_blob_storage()
    if not blob_storage:
        return

    namespace = config_memory_namespace(owner_id, business_id)
    feature_display = feature.replace('_', ' ').title()
    entry = f"[{feature_display}] {summary}"

    try:
        from zylch.storage.models import Blob
        from zylch.storage.database import get_session

        # Find existing blob for this namespace
        existing_id = None
        new_content = None
        with get_session() as session:
            existing = session.query(Blob).filter(
                Blob.owner_id == owner_id,
                Blob.namespace == namespace,
            ).first()

            if existing:
                existing_id = str(existing.id)
                new_content = existing.content + "\n" + entry

        if existing_id:
            blob_storage.update_blob(
                blob_id=existing_id,
                owner_id=owner_id,
                content=new_content,
                event_description=f"configure_{feature}",
            )
            logger.debug(
                f"[mrcall_memory] Updated config memory blob {existing_id}"
            )
        else:
            blob_storage.store_blob(
                owner_id=owner_id,
                namespace=namespace,
                content=entry,
                event_description=f"configure_{feature}",
            )
            logger.debug(
                f"[mrcall_memory] Created config memory blob for {namespace}"
            )

    except Exception as e:
        # Non-fatal: config memory is best-effort
        logger.warning(f"[mrcall_memory] Failed to save config memory: {e}")


def load_config_memory(owner_id: str, business_id: str) -> Optional[str]:
    """Load accumulated config memory for a business.

    Args:
        owner_id: Firebase UID
        business_id: MrCall business ID

    Returns:
        Config memory content string, or None if no memory exists
    """
    blob_storage = _get_blob_storage()
    if not blob_storage:
        return None

    namespace = config_memory_namespace(owner_id, business_id)

    try:
        from zylch.storage.models import Blob
        from zylch.storage.database import get_session

        with get_session() as session:
            blob = session.query(Blob).filter(
                Blob.owner_id == owner_id,
                Blob.namespace == namespace,
            ).first()

            if blob:
                logger.debug(
                    f"[mrcall_memory] Loaded config memory: "
                    f"{len(blob.content)} chars"
                )
                return blob.content

    except Exception as e:
        logger.warning(f"[mrcall_memory] Failed to load config memory: {e}")

    return None
