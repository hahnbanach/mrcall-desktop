"""What a blob storage reads, kept apart from what it writes.

Every method here opens a session, filters through the one visibility
predicate (:func:`zylch.memory.scope.blob_visible`) and returns rows or
dictionaries. None of them writes, none of them needs a permit, and none of
them is a transaction boundary a caller has to respect — which is exactly why
they can live apart from :class:`~zylch.memory.blob_storage.BlobStorage`'s
writers without changing what any caller sees: ``BlobStorage`` inherits them.

The split is the engine's 500-line rule, applied by responsibility: milestone 5
made every writer retain the text it replaces, and the file that owns the
writers is the file that grew.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from zylch.storage.models import Blob, BlobSentence

from .company_key import require_company_key
from .scope import blob_visible, sentences_in_scope


class BlobReads:
    """Read-only queries over one owner's view of a company store.

    Expects ``self._get_session`` from the concrete storage class.
    """

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
