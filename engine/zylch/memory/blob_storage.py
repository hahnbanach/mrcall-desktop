"""Blob storage with sentence-level embeddings using SQLAlchemy.

Two ways in, deliberately unequal.

``store_blob`` and ``update_blob`` are the **legacy** writers: they open their
own session, decide their own transaction boundary, and trust whoever called
them. Every unconverted writer in the engine still uses them, and the mnemonic
harness converts those callers milestone by milestone.

``semantic_create`` and ``semantic_update`` are the **committed** writers. They
write into a transaction the caller already owns — so a blob, its sentences,
its identifiers, its source link and the operation receipt land together or not
at all — and they refuse to run without a :class:`CommitPermit` bound to the
exact company, owner, event, proposal, write set and expected versions. The
permit lives in :mod:`zylch.memory.commit_permit`; a missing, forged or
already-spent one is refused *here*, at the storage boundary.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from .text_processing import split_sentences
from .embeddings import EmbeddingEngine
from .commit_permit import CREATE, UPDATE, ConflictError, check_permit, spend_permit
from .company_key import require_company_key
from .scope import blob_contributed, blob_owned_rules, blob_visible, sentences_in_scope
from zylch.storage.models import Blob, BlobSentence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedContent:
    """Embeddings computed OUTSIDE any transaction.

    Encoding is seconds of CPU and can fail; doing it under the company write
    lock would hold every other writer behind it, and doing it inside the
    transaction would make an embedding failure a rolled-back commit rather
    than a refusal that never started one.
    """

    content: str
    blob_embedding: bytes
    sentences: Tuple[str, ...]
    sentence_embeddings: Tuple[bytes, ...]


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

    def mark_mutated(self, session) -> None:
        """Bump the mutation sequence inside a caller-owned transaction.

        Bumped ONCE for a whole semantic commit, not once per table touched —
        and, unlike :meth:`_notify_mutation`, a failure is **not** swallowed.
        The sequence is how every other engine on this store learns its vector
        index is stale, so a commit whose bump quietly failed would leave them
        answering from memory that no longer exists while looking like a clean
        success. Inside a transaction that is a rollback, not a debug line.
        """
        from .store import bump_mutation_seq

        bump_mutation_seq(session)
        if self._on_mutation:
            self._on_mutation()

    # ─── Content preparation (outside any transaction) ────────────────

    def prepare(self, content: str) -> PreparedContent:
        """Encode the content and its sentences. Raises on an embedding failure.

        Called before the write lock is taken. A failure here means no
        transaction was ever opened, which is why an embedding outage is a
        refusal and never a half-written memory.
        """
        blob_embedding = self.embeddings.encode(content)
        sentences = split_sentences(content)
        raw = self.embeddings.encode(sentences) if sentences else []
        encoded = []
        for index, sentence in enumerate(sentences):
            emb = raw[index] if len(raw) > index else self.embeddings.encode(sentence)
            encoded.append(
                emb.tobytes()
                if hasattr(emb, "tobytes")
                else np.array(emb, dtype=np.float32).tobytes()
            )
        return PreparedContent(
            content=content,
            blob_embedding=blob_embedding.tobytes(),
            sentences=tuple(sentences),
            sentence_embeddings=tuple(encoded),
        )

    # ─── Transaction-scoped internals, shared by both ways in ─────────

    def _add_sentences(self, session, blob_id: str, owner_id: str, prepared) -> None:
        for sentence, embedding in zip(prepared.sentences, prepared.sentence_embeddings):
            session.add(
                BlobSentence(
                    blob_id=str(blob_id),
                    owner_id=owner_id,
                    sentence_text=sentence,
                    embedding=embedding,
                )
            )

    def _insert(
        self,
        session,
        *,
        owner_id: str,
        namespace: str,
        prepared: PreparedContent,
        event_description: Optional[str],
    ) -> Blob:
        blob_id = str(uuid.uuid4())
        events = []
        if event_description:
            events.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "description": event_description,
                }
            )
        blob = Blob(
            id=blob_id,
            owner_id=owner_id,
            namespace=namespace,
            content=prepared.content,
            embedding=prepared.blob_embedding,
            events=events,
        )
        session.add(blob)
        session.flush()
        self._add_sentences(session, blob_id, owner_id, prepared)
        session.flush()
        return blob

    def _rewrite(
        self,
        session,
        blob: Blob,
        *,
        owner_id: str,
        prepared: PreparedContent,
        event_description: Optional[str],
    ) -> Blob:
        events = list(blob.events or [])
        if event_description:
            events.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "description": event_description,
                }
            )
        blob.content = prepared.content
        blob.embedding = prepared.blob_embedding
        blob.events = events
        # updated_at is what the compare-and-swap keys on, so it must move on
        # every write.
        blob.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.query(BlobSentence).filter(BlobSentence.blob_id == blob.id).delete(
            synchronize_session=False
        )
        self._add_sentences(session, blob.id, owner_id, prepared)
        session.flush()
        return blob

    # ─── The committed writers ────────────────────────────────────────

    def visible_target(self, session: Session, blob_id: str, owner_id: str) -> Optional[Blob]:
        """The live ORM row for a visible blob, inside the caller's transaction.

        The semantic commit re-reads its target here AFTER taking the write
        lock, so the version it compares against is the version it writes over
        — not the one it read seconds ago while a model was thinking.
        """
        key = require_company_key()
        return (
            session.query(Blob)
            .filter(Blob.id == blob_id, blob_visible(owner_id, key))
            .one_or_none()
        )

    def semantic_create(
        self,
        session: Session,
        permit: Any,
        *,
        owner_id: str,
        namespace: str,
        prepared: PreparedContent,
        event_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a blob inside the caller's transaction, under a spent permit."""
        checked = check_permit(
            permit,
            action=CREATE,
            owner_id=owner_id,
            content=prepared.content,
            namespace=namespace,
        )
        blob = self._insert(
            session,
            owner_id=owner_id,
            namespace=namespace,
            prepared=prepared,
            event_description=event_description,
        )
        spend_permit(checked)
        return blob.to_dict()

    def semantic_update(
        self,
        session: Session,
        permit: Any,
        *,
        blob: Blob,
        owner_id: str,
        prepared: PreparedContent,
        expected_version: str,
        event_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rewrite a re-read, version-checked blob under a spent permit.

        ``blob`` must be the row :meth:`visible_target` returned inside this
        same transaction, and ``expected_version`` the version the proposal was
        decided against. The comparison happens here rather than in the caller
        so the storage boundary — not a caller's good intentions — is what
        refuses a write over someone else's change.
        """
        checked = check_permit(
            permit,
            action=UPDATE,
            owner_id=owner_id,
            content=prepared.content,
            namespace=blob.namespace,
            target=(str(blob.id), str(expected_version)),
        )
        if _iso(blob.updated_at) != _iso(expected_version):
            raise ConflictError(
                f"blob {blob.id} changed since it was read "
                f"(expected {expected_version}, now {_iso(blob.updated_at)})"
            )
        self._rewrite(
            session,
            blob,
            owner_id=owner_id,
            prepared=prepared,
            event_description=event_description,
        )
        spend_permit(checked)
        return blob.to_dict()

    def store_blob(
        self, owner_id: str, namespace: str, content: str, event_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Store new blob with sentence embeddings.

        Returns the created blob record.
        """
        prepared = self.prepare(content)
        with self._get_session() as session:
            blob = self._insert(
                session,
                owner_id=owner_id,
                namespace=namespace,
                prepared=prepared,
                event_description=event_description,
            )
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
        prepared = self.prepare(content)

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

            self._rewrite(
                session,
                blob,
                owner_id=owner_id,
                prepared=prepared,
                event_description=event_description,
            )
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
