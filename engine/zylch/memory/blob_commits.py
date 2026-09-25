"""The committed writers: every semantic write into a transaction the harness owns.

``semantic_create``, ``semantic_update`` and ``semantic_merge`` write into a
transaction the caller already owns — so a blob, its sentences, its
identifiers, its source links, an alias and the operation receipt land
together or not at all — and they refuse to run without a
:class:`~zylch.memory.commit_permit.CommitPermit` bound to the exact company,
owner, event, proposal, write set and expected versions. A missing, forged or
already-spent permit is refused *here*, at the storage boundary, and so is a
write over someone else's change: the compare-and-swap is done against the row
the caller re-read inside the transaction, not against what it remembered.

They are a mixin of :class:`~zylch.memory.blob_storage.BlobStorage`, which
supplies the shared internals (``_insert``, ``_rewrite``, ``delete_blob``);
the legacy standalone writers stay there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from zylch.storage.models import Blob

from .blob_versions import APPEND, CONSOLIDATE
from .commit_permit import (
    CREATE,
    MERGE,
    UPDATE,
    ConflictError,
    PermitError,
    check_permit,
    spend_permit,
)


def _iso(value) -> str:
    """One comparable form for updated_at, whether it came from the ORM
    (naive datetime) or from a to_dict() round-trip (isoformat string)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    return str(value).replace("+00:00", "").replace("Z", "")


class CommittedWrites:
    """``semantic_create`` / ``semantic_update`` / ``semantic_merge``, under a permit."""

    def semantic_create(
        self,
        session: Session,
        permit: Any,
        *,
        owner_id: str,
        namespace: str,
        prepared: Any,
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
        prepared: Any,
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

    def semantic_merge(
        self,
        session: Session,
        permit: Any,
        *,
        keeper: Blob,
        donor: Blob,
        owner_id: str,
        prepared: Any,
        keeper_version: str,
        donor_version: str,
        event_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fold ``donor`` into ``keeper`` under one spent MERGE permit.

        Both rows must be the ones :meth:`visible_target` returned inside this
        same transaction, and both versions the ones the proposal was decided
        against: a stale keeper and a stale donor are each a ``ConflictError``
        naming which. Nothing is lost — the keeper's replaced text is retained
        as a ``consolidate`` version by the rewrite, and the donor's final text
        by ``delete_blob(retain=True)`` in this same session, both under the
        operation's id — so a wrong merge is reversed by restoring a version.
        The caller writes the links, the identifiers and the alias; this is the
        blob half, and it bumps no sequence: the commit bumps it once.
        """
        checked = check_permit(
            permit,
            action=MERGE,
            owner_id=owner_id,
            content=prepared.content,
            namespace=keeper.namespace,
            target=(str(keeper.id), str(keeper_version)),
        )
        if (str(donor.id), str(donor_version)) not in checked.write_set:
            raise PermitError("the donor/version pair is not in the permit's write set")
        if donor.namespace != checked.namespace:
            raise PermitError("the donor lives in a namespace the permit does not authorize")
        for role, row, expected in (
            ("keeper", keeper, keeper_version),
            ("donor", donor, donor_version),
        ):
            if _iso(row.updated_at) != _iso(expected):
                raise ConflictError(
                    f"the {role} {row.id} changed since it was read "
                    f"(expected {expected}, now {_iso(row.updated_at)})"
                )
        self._rewrite(
            session,
            keeper,
            owner_id=owner_id,
            prepared=prepared,
            event_description=event_description,
            reason=CONSOLIDATE,
            operation_id=checked.event_id,
        )
        dropped = self.delete_blob(
            str(donor.id),
            owner_id,
            retain=True,
            session=session,
            operation_id=checked.event_id,
        )
        if not dropped:
            raise ConflictError(f"the donor {donor.id} could not be dropped")
        spend_permit(checked)
        return keeper.to_dict()


__all__ = ["CommittedWrites", "_iso"]
