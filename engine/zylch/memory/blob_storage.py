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
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from .text_processing import split_sentences
from .embeddings import EmbeddingEngine
from .commit_permit import CREATE, UPDATE, ConflictError, check_permit, spend_permit
from .company_key import require_company_key
from .scope import blob_contributed, blob_owned_rules, blob_visible
from zylch.storage.models import Blob, BlobSentence

from .blob_reads import BlobReads
from .blob_versions import APPEND, CONSOLIDATE, prune_versions, restore_version, retain_version

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


class BlobStorage(BlobReads):
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
        reason: str = APPEND,
        operation_id: Optional[str] = None,
    ) -> Blob:
        # The text this rewrite replaces is kept BEFORE anything changes, in
        # this same session: a rewrite that fails after this point rolls the
        # version back with it, and one that succeeds leaves the old text
        # exactly when the new one lands. `reason` is a parameter because
        # this method cannot know its caller, and the sweep's own rewrites
        # must not count as a sink's growth.
        retain_version(session, blob, reason=reason, owner_id=owner_id, operation_id=operation_id)
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
        reason: str = APPEND,
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
            reason=reason,
            operation_id=getattr(checked, "event_id", None),
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
        reason: str = APPEND,
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
                reason=reason,
            )
            self._notify_mutation(session)
            return blob.to_dict()

    def delete_blob(self, blob_id: str, owner_id: str, *, retain: bool = False) -> bool:
        """Delete a visible blob (sentences cascade via FK).

        ``retain=True`` is the consolidation sweep dropping a donor: the row's
        final text is kept as a version first, so a bad merge is reversible.
        The default is the owner's delete, and an owner who deletes means it —
        the blob's versions go with it, explicitly, because ``blob_versions``
        carries no cascade on purpose.
        """
        key = require_company_key()
        with self._get_session() as session:
            blob = (
                session.query(Blob)
                .filter(Blob.id == blob_id, blob_visible(owner_id, key))
                .one_or_none()
            )
            if blob is None:
                return False
            if retain:
                retain_version(session, blob, reason=CONSOLIDATE, owner_id=owner_id)
            else:
                prune_versions(session, [blob.id])
            # The bulk form, by id, on purpose: the frozen writer inventory
            # recognises `query(Blob)…delete()` as a Blob deletion and would
            # not see `session.delete(blob)`, and a deletion the guard cannot
            # see is the kind of bypass the guard exists to catch.
            count = session.query(Blob).filter(Blob.id == blob.id).delete(synchronize_session=False)
            if count > 0:
                self._notify_mutation(session)
            return count > 0

    def restore_version(self, blob_id: str, owner_id: str, version_id: str) -> Dict[str, Any]:
        """Bring a visible blob back to one of its retained versions.

        Mechanical and reversible — the text it replaces is retained first.
        See :func:`~zylch.memory.blob_versions.restore_version`.
        """
        return restore_version(self, blob_id, version_id, owner_id=owner_id)

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
            # Ids first, then the bulk delete, then the versions of exactly
            # those ids. Never a prune by owner: a version's owner is the
            # writer's provenance, and on a shared store that is often another
            # account — filtering on it would leave this account's deleted
            # blobs' versions behind and take other accounts' living ones.
            ids = [row.id for row in session.query(Blob.id).filter(predicate).all()]
            count = session.query(Blob).filter(predicate).delete(synchronize_session=False)
            pruned = prune_versions(session, ids)
            if count > 0:
                self._notify_mutation(session)
            logger.info(
                f"delete_all_blobs owner={owner_id} shared_store={shared} -> {count} blob(s), "
                f"{pruned} retained version(s)"
            )
            return count
