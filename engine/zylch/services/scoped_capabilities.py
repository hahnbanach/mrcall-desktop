"""Read-only engine operations shared by future authorized channel adapters.

This service never establishes caller identity. It consumes immutable grants;
the remote transport must first authenticate its dedicated service identity.
No URLs, store credentials, company keys or queries come from the model/request.
"""

import hashlib
import os
import time
from collections.abc import Callable

from zylch.services.capability_contract import (
    OPERATIONS,
    CapabilityBinding,
    CapabilityRequest,
    ContactGrant,
)
from zylch.services.order_existence import lookup_order_existence


def current_profile_scope() -> tuple[str, str]:
    return os.environ.get("OWNER_ID", ""), os.environ.get("MEMORY_KEY", "").strip()


class ScopedCapabilities:
    def __init__(
        self,
        binding: CapabilityBinding,
        read_customers: Callable,
        session_factory: Callable,
        profile_scope: Callable = current_profile_scope,
        now_ms: Callable = lambda: time.time_ns() // 1_000_000,
        allowed_operations: frozenset[str] = OPERATIONS,
    ):
        self.binding = binding
        self._read_customers = read_customers
        self._session_factory = session_factory
        self._profile_scope = profile_scope
        self._now_ms = now_ms
        if not allowed_operations or not allowed_operations.issubset(OPERATIONS):
            raise ValueError("invalid operation grant")
        self._allowed_operations = frozenset(allowed_operations)

    def check_scope(self) -> None:
        if self._profile_scope() != (self.binding.profile_uid, self.binding.company_key):
            raise PermissionError("capability scope changed")

    def execute_authorized(self, request: CapabilityRequest) -> dict:
        """Synchronous bounded-data read; run on the transport's bounded IO executor.

        Matching the installed grants is not transport authentication. Local email
        adapters must also establish their authority before calling this method.
        Recheck scope and expiry after IO so a join cannot redirect a pending read.
        """
        CapabilityRequest.parse(request.public_dict(), self.binding, self._now_ms())
        self.check_scope()
        if request.operation not in self._allowed_operations:
            raise PermissionError("operation not granted")
        grant = next(g for g in self.binding.contacts if g.contact_ref == request.contact_ref)
        if request.operation == "order.exists":
            result = {"status": lookup_order_existence(grant.email, self._read_customers).value}
        else:
            result = self._memory(grant)
        self.check_scope()
        if self._now_ms() >= request.expires_at_ms:
            raise TimeoutError("capability expired")
        return result

    def _memory(self, grant: ContactGrant) -> dict:
        from zylch.memory.scope import blob_visible
        from zylch.storage.models import Blob, BlobSentence

        key = self.binding.company_key
        sentences = []
        with self._session_factory() as session:
            for approved in grant.sentences:
                row = (
                    session.query(BlobSentence.sentence_text)
                    .join(Blob, Blob.id == BlobSentence.blob_id)
                    .filter(
                        BlobSentence.id == approved.sentence_id,
                        BlobSentence.company_key == key,
                        blob_visible(self.binding.profile_uid, key),
                        Blob.company_key == key,
                        Blob.namespace.in_((f"user:{key}", f"facts:{key}")),
                    )
                    .one_or_none()
                )
                # Membership is not permission to disclose the whole entity. The
                # approved sentence is the unit; any revision needs fresh approval.
                if row is None or not 0 < len(row[0]) <= 1000:
                    return {"status": "unavailable"}
                digest = hashlib.sha256(row[0].encode("utf-8")).hexdigest()
                if digest != approved.digest:
                    return {"status": "unavailable"}
                sentences.append({"text": row[0], "revision": digest})
        return {"status": "memory_found", "sentences": sentences}
