"""Blob storage with sentence-level embeddings using SQLAlchemy."""

import logging
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timezone
import uuid

import numpy as np
from sqlalchemy import func

from .text_processing import split_sentences
from .embeddings import EmbeddingEngine
from zylch.storage.models import Blob, BlobSentence

logger = logging.getLogger(__name__)


class BlobStorage:
    """Storage for entity blobs with sentence-level embeddings."""

    def __init__(
        self,
        get_session,
        embedding_engine: EmbeddingEngine,
        on_mutation: Optional[Callable[[], None]] = None,
    ):
        self._get_session = get_session
        self.embeddings = embedding_engine
        self._on_mutation = on_mutation

    def _notify_mutation(self):
        """Notify listeners that blob data changed."""
        if self._on_mutation:
            logger.debug("[BlobStorage] notifying mutation callback")
            self._on_mutation()

    def store_blob(
        self, owner_id: str, namespace: str, content: str, event_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Store new blob with sentence embeddings.

        Returns the created blob record.
        """
        blob_id = str(uuid.uuid4())

        # Generate blob-level embedding
        blob_embedding = self.embeddings.encode(content)

        # Split into sentences and embed each
        sentences = split_sentences(content)
        sentence_embeddings = self.embeddings.encode(sentences) if sentences else []

        # Build events array
        events = []
        if event_description:
            events.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "description": event_description,
                }
            )

        with self._get_session() as session:
            # Insert blob (embedding as bytes for SQLite BLOB)
            blob = Blob(
                id=blob_id,
                owner_id=owner_id,
                namespace=namespace,
                content=content,
                embedding=blob_embedding.tobytes(),
                events=events,
            )
            session.add(blob)
            session.flush()

            # Insert sentences (embeddings as bytes)
            for i, sent in enumerate(sentences):
                emb = (
                    sentence_embeddings[i]
                    if len(sentence_embeddings) > i
                    else self.embeddings.encode(sent)
                )
                emb_bytes = (
                    emb.tobytes()
                    if hasattr(emb, "tobytes")
                    else np.array(emb, dtype=np.float32).tobytes()
                )
                sentence = BlobSentence(
                    blob_id=blob_id,
                    owner_id=owner_id,
                    sentence_text=sent,
                    embedding=emb_bytes,
                )
                session.add(sentence)

            session.flush()
            self._notify_mutation()
            return blob.to_dict()

    def update_blob(
        self, blob_id: str, owner_id: str, content: str, event_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update blob content and regenerate sentence embeddings.

        Atomic: reads blob with FOR UPDATE lock, deletes old sentences,
        inserts new ones — all in a single transaction.
        """
        # Generate new embeddings before entering transaction
        blob_embedding = self.embeddings.encode(content)
        sentences = split_sentences(content)
        sentence_embeddings = self.embeddings.encode(sentences) if sentences else []

        with self._get_session() as session:
            # Lock the blob row for atomic read-then-write
            blob = (
                session.query(Blob)
                .filter(Blob.id == blob_id, Blob.owner_id == owner_id)
                .with_for_update()
                .one_or_none()
            )

            if blob is None:
                logger.warning(f"update_blob: blob {blob_id} not found for owner {owner_id}")
                return {}

            # Append event
            events = list(blob.events or [])
            if event_description:
                events.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "description": event_description,
                    }
                )

            # Update blob fields (embedding as bytes)
            blob.content = content
            blob.embedding = blob_embedding.tobytes()
            blob.events = events

            # Delete old sentences
            session.query(BlobSentence).filter(BlobSentence.blob_id == blob_id).delete(
                synchronize_session=False
            )

            # Insert new sentences (embeddings as bytes)
            for i, sent in enumerate(sentences):
                emb = (
                    sentence_embeddings[i]
                    if len(sentence_embeddings) > i
                    else self.embeddings.encode(sent)
                )
                emb_bytes = (
                    emb.tobytes()
                    if hasattr(emb, "tobytes")
                    else np.array(emb, dtype=np.float32).tobytes()
                )
                bid = str(blob_id) if not isinstance(blob_id, str) else blob_id
                sentence = BlobSentence(
                    blob_id=bid,
                    owner_id=owner_id,
                    sentence_text=sent,
                    embedding=emb_bytes,
                )
                session.add(sentence)

            session.flush()
            self._notify_mutation()
            return blob.to_dict()

    def get_blob(self, blob_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get blob by ID."""
        with self._get_session() as session:
            blob = (
                session.query(Blob)
                .filter(Blob.id == blob_id, Blob.owner_id == owner_id)
                .one_or_none()
            )
            return blob.to_dict() if blob else None

    def delete_blob(self, blob_id: str, owner_id: str) -> bool:
        """Delete blob (sentences cascade automatically via FK)."""
        with self._get_session() as session:
            count = (
                session.query(Blob)
                .filter(
                    Blob.id == blob_id,
                    Blob.owner_id == owner_id,
                )
                .delete(synchronize_session=False)
            )
            if count > 0:
                self._notify_mutation()
            return count > 0

    def list_blobs(
        self,
        owner_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """List recent blobs for owner, ordered by updated_at desc."""
        with self._get_session() as session:
            rows = (
                session.query(Blob)
                .filter(Blob.owner_id == owner_id)
                .order_by(Blob.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [r.to_dict() for r in rows]

    def delete_all_blobs(self, owner_id: str) -> int:
        """Delete all blobs (and sentences via cascade) for owner."""
        with self._get_session() as session:
            count = (
                session.query(Blob)
                .filter(Blob.owner_id == owner_id)
                .delete(synchronize_session=False)
            )
            if count > 0:
                self._notify_mutation()
            return count

    def get_stats(self, owner_id: str) -> Dict[str, Any]:
        """Get memory statistics for owner."""
        with self._get_session() as session:
            blobs = (
                session.query(Blob.id, Blob.namespace, Blob.content)
                .filter(Blob.owner_id == owner_id)
                .all()
            )

            sentence_count = (
                session.query(func.count(BlobSentence.id))
                .filter(BlobSentence.owner_id == owner_id)
                .scalar()
                or 0
            )

            namespaces = list(set(b.namespace for b in blobs))
            avg_sentences = sentence_count / len(blobs) if blobs else 0

            return {
                "total_blobs": len(blobs),
                "total_sentences": sentence_count,
                "namespaces": namespaces,
                "avg_blob_size": round(avg_sentences, 2),
            }
