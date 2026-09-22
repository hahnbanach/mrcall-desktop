"""The single-use authority for one semantic memory write.

A permit is **opaque**: it carries no session, no engine and no callable. What
it carries is the binding — which company, which account, which event, which
proposal, which blobs at which versions, and the digest of the exact text — so
:mod:`zylch.memory.blob_storage` can check that the write in front of it is the
write that was authorized, not merely *a* write from a caller that once held a
permit.

It is minted by ``memory/mnemonic/commit.py`` and by nothing else. There is no
public token factory, adapters never receive one, and the submission facade
never returns one — a permit that reached an adapter would be a write
capability handed to a caller whose whole job is to submit an observation.
``tests/memory/test_mnemonic_commit.py`` asserts that statically, because
Python privacy is not a sandbox against arbitrary code in the same process; the
runtime checks here are what stop a caller that ignores the convention.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from .company_key import require_company_key

CREATE = "CREATE"
UPDATE = "UPDATE"


class PermitError(PermissionError):
    """A semantic write arrived without valid, matching write authority."""


class ConflictError(RuntimeError):
    """The target moved between the decision and the write: CAS refused it."""


def content_digest(content: str) -> str:
    """Stable digest of the exact text a permit authorizes."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CommitPermit:
    """Authority to perform ONE semantic write, and nothing else.

    Forgery is refused by object identity against :data:`_ISSUED`: a
    value-identical copy, including one built by ``dataclasses.replace``, is
    not the permit that was issued.
    """

    permit_id: str
    action: str
    company_key: str
    owner_id: str
    event_id: str
    proposal_digest: str
    content_digest: str
    namespace: str
    write_set: Tuple[Tuple[str, str], ...] = ()  # (blob_id, expected_version)


# Permits issued by this process, by id. Membership is not enough: the stored
# object must BE the presented one. A permit leaves here only when it is spent
# or abandoned, and a spent id is never honoured again.
_ISSUED: Dict[str, CommitPermit] = {}
_SPENT: set = set()
_SPENT_TRACKED = 4096


def issue_commit_permit(
    *,
    action: str,
    company_key: str,
    owner_id: str,
    event_id: str,
    proposal_digest: str,
    content: str,
    namespace: str,
    write_set: Sequence[Tuple[str, str]] = (),
) -> CommitPermit:
    """Mint the single-use authority for one semantic write.

    Called by ``memory/mnemonic/commit.py`` and by nothing else. It is not
    exported through the memory package, adapters never receive it, and the
    submission facade never returns one — a permit that reached an adapter
    would be a write capability handed to a caller that is only supposed to
    submit an observation.
    """
    if action not in (CREATE, UPDATE):
        raise PermitError(f"a commit permit covers CREATE or UPDATE, not {action!r}")
    permit = CommitPermit(
        permit_id=uuid.uuid4().hex + secrets.token_hex(8),
        action=action,
        company_key=company_key,
        owner_id=owner_id,
        event_id=event_id,
        proposal_digest=proposal_digest,
        content_digest=content_digest(content),
        namespace=namespace,
        write_set=tuple((str(b), str(v)) for b, v in write_set),
    )
    _ISSUED[permit.permit_id] = permit
    return permit


def abandon_permit(permit: Any) -> None:
    """Drop an unspent permit — a refused commit leaves no live authority."""
    _ISSUED.pop(getattr(permit, "permit_id", ""), None)


def spend_permit(permit: CommitPermit) -> None:
    _ISSUED.pop(permit.permit_id, None)
    if len(_SPENT) >= _SPENT_TRACKED:
        _SPENT.clear()  # the live registry is the real guard; this bounds memory
    _SPENT.add(permit.permit_id)


def check_permit(
    permit: Any,
    *,
    action: str,
    owner_id: str,
    content: str,
    namespace: str,
    target: Optional[Tuple[str, str]] = None,
) -> CommitPermit:
    """Every reason a semantic write may not proceed, checked in one place."""
    if not isinstance(permit, CommitPermit):
        raise PermitError("a semantic memory write requires a commit permit")
    if permit.permit_id in _SPENT:
        raise PermitError("this commit permit was already spent")
    if _ISSUED.get(permit.permit_id) is not permit:
        raise PermitError("this process never issued that commit permit")
    if permit.action != action:
        raise PermitError(f"permit authorizes {permit.action}, not {action}")
    if permit.company_key != require_company_key():
        raise PermitError("permit belongs to another company memory")
    if permit.owner_id != owner_id:
        raise PermitError("permit belongs to another account")
    if permit.content_digest != content_digest(content):
        raise PermitError("the content differs from what the permit authorized")
    if permit.namespace != namespace:
        raise PermitError("the namespace differs from what the permit authorized")
    if action == CREATE:
        if permit.write_set:
            raise PermitError("a CREATE permit names no existing blob")
    else:
        if target not in permit.write_set:
            raise PermitError("the target/version pair is not in the permit's write set")
    return permit


__all__ = [
    "CREATE",
    "UPDATE",
    "CommitPermit",
    "ConflictError",
    "PermitError",
    "abandon_permit",
    "check_permit",
    "content_digest",
    "issue_commit_permit",
    "spend_permit",
]
