"""Blob storage with sentence-level embeddings using SQLAlchemy."""

import logging
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timezone
import uuid

import numpy as np
from sqlalchemy import func

from .text_processing import split_sentences
from .embeddings import EmbeddingEngine
from .company_key import require_company_key
from .scope import blob_contributed, blob_owned_rules, blob_visible, sentences_in_scope
from zylch.storage.models import Blob, BlobSentence

logger = logging.getLogger(__name__)


def _iso(value) -> str:
    """One comparable form for updated_at, whether it came from the ORM
    (naive datetime) or from a to_dict() round-trip (isoformat string)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    return str(value).replace("+00:00", "").replace("Z", "")


class BlobStorage:
    """Storage for entity blobs with sentence-level embeddings.

    Every read, write, update, delete and list is scoped by
    :func:`zylch.memory.scope.blob_visible` — the company key decides
    company families, key AND owner decide rule families. ``owner_id`` on
    a row is provenance. No method here filters on owner alone.
    """

    def __init__(
        self,
        get_session,
        embedding_engine: EmbeddingEngine,
        on_mutation: Optional[Callable[[], None]] = None,
    ):
        self._get_session = get_session
        self.embeddings = embedding_engine
        self._on_mutation = on_mutation

    def _notify_mutation(self, session=None):
        """Blob data changed: bump the store's mutation sequence, tell listeners.

        The sequence lives in the company store (``memory_meta``), so the
        in-process vector index of EVERY engine on this store — not just
        this one — sees the change on its next search. The optional
        callback is the same-process fast path that predates it.
        """
        if session is not None:
            try:
                from .store import bump_mutation_seq

                bump_mutation_seq(session)
            except Exception as e:  # a store without the meta row (tests, legacy)
                logger.debug(f"[BlobStorage] mutation_seq bump skipped: {e}")
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
            self._notify_mutation(session)
            return blob.to_dict()

    def update_blob(
        self,
        blob_id: str,
        owner_id: str,
        content: str,
        event_description: Optional[str] = None,
        expected_updated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update blob content and regenerate sentence embeddings.

        Compare-and-swap: the caller read the blob, merged new facts into
        it (an LLM call taking seconds — never inside a transaction), and
        now writes back. With ``expected_updated_at`` set to the value it
        read, a blob that another writer changed in between is NOT
        overwritten: the return carries ``conflict: True`` plus the
        current row, and the caller re-merges onto that. The transaction
        takes the store's write lock as its first statement, so the
        check and the write happen under one lock.

        Returns ``{}`` when the blob is not visible to this owner.
        """
        # Generate new embeddings before entering transaction
        blob_embedding = self.embeddings.encode(content)
        sentences = split_sentences(content)
        sentence_embeddings = self.embeddings.encode(sentences) if sentences else []

        key = require_company_key()
        with self._get_session() as session:
            # Hold the store's write lock across read + compare + write.
            try:
                from .store import take_write_lock

                take_write_lock(session)
            except Exception as e:  # a store without the meta row (tests, legacy)
                logger.debug(f"[BlobStorage] write-lock upgrade skipped: {e}")
            blob = (
                session.query(Blob)
                .filter(Blob.id == blob_id, blob_visible(owner_id, key))
                .one_or_none()
            )

            if blob is None:
                logger.warning(
                    f"update_blob: blob {blob_id} is not visible to owner {owner_id} "
                    f"(missing, or another account's rule)"
                )
                return {}

            if expected_updated_at is not None and _iso(blob.updated_at) != _iso(
                expected_updated_at
            ):
                logger.info(
                    f"update_blob: blob {blob_id} changed since it was read "
                    f"(expected {expected_updated_at}, now {_iso(blob.updated_at)}) — conflict"
                )
                current = blob.to_dict()
                current["conflict"] = True
                return current

            # Append event
            events = list(blob.events or [])
            if event_description:
                events.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "description": event_description,
                    }
                )

            # Update blob fields (embedding as bytes). updated_at is what the
            # compare-and-swap keys on, so it must move on every write.
            blob.content = content
            blob.embedding = blob_embedding.tobytes()
            blob.events = events
            blob.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

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
            self._notify_mutation(session)
            return blob.to_dict()

    def get_blob(self, blob_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get a blob by id, if this owner may see it."""
        key = require_company_key()
        with self._get_session() as session:
            blob = (
                session.query(Blob)
                .filter(Blob.id == blob_id, blob_visible(owner_id, key))
                .one_or_none()
            )
            return blob.to_dict() if blob else None

    def delete_blob(self, blob_id: str, owner_id: str) -> bool:
        """Delete a visible blob (sentences cascade via FK)."""
        key = require_company_key()
        with self._get_session() as session:
            count = (
                session.query(Blob)
                .filter(Blob.id == blob_id, blob_visible(owner_id, key))
                .delete(synchronize_session=False)
            )
            if count > 0:
                self._notify_mutation(session)
            return count > 0

    def list_blobs(
        self,
        owner_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Recent blobs visible to this owner, newest update first."""
        key = require_company_key()
        with self._get_session() as session:
            rows = (
                session.query(Blob)
                .filter(blob_visible(owner_id, key))
                .order_by(Blob.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [r.to_dict() for r in rows]

    def other_owners_present(self, owner_id: str) -> bool:
        """Has any OTHER account contributed to this company's memory?

        Decides what a per-account reset may remove: a store with a single
        contributor is that account's own company, and the account is its
        key holder.
        """
        key = require_company_key()
        with self._get_session() as session:
            other = (
                session.query(Blob.owner_id)
                .filter(Blob.company_key == key, Blob.owner_id != owner_id)
                .limit(1)
                .first()
            )
            return other is not None

    def delete_all_blobs(self, owner_id: str) -> int:
        """Per-account memory reset. Returns the number of blobs removed.

        Company memory is deleted by whoever holds the key, never by one
        account leaving or rebuilding. So: when other accounts share this
        store, only this account's own RULE rows go — its contributions to
        company knowledge stay, provenance included. When this account is
        the store's sole contributor it is the key holder, and everything
        it wrote goes, exactly as before sharing existed.
        """
        key = require_company_key()
        shared = self.other_owners_present(owner_id)
        predicate = blob_owned_rules(owner_id, key) if shared else blob_contributed(owner_id, key)
        with self._get_session() as session:
            count = session.query(Blob).filter(predicate).delete(synchronize_session=False)
            if count > 0:
                self._notify_mutation(session)
            logger.info(
                f"delete_all_blobs owner={owner_id} shared_store={shared} -> {count} blob(s)"
            )
            return count

    def get_stats(self, owner_id: str) -> Dict[str, Any]:
        """Memory statistics over what this owner may see."""
        key = require_company_key()
        with self._get_session() as session:
            blobs = (
                session.query(Blob.id, Blob.namespace, Blob.content)
                .filter(blob_visible(owner_id, key))
                .all()
            )
            visible_ids = [str(b.id) for b in blobs]
            sentence_count = (
                session.query(func.count(BlobSentence.id))
                .filter(sentences_in_scope(key), BlobSentence.blob_id.in_(visible_ids))
                .scalar()
                if visible_ids
                else 0
            ) or 0

            namespaces = list(set(b.namespace for b in blobs))
            avg_sentences = sentence_count / len(blobs) if blobs else 0

            return {
                "total_blobs": len(blobs),
                "total_sentences": sentence_count,
                "namespaces": namespaces,
                "avg_blob_size": round(avg_sentences, 2),
            }
