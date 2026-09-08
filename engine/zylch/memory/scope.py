"""The one predicate that decides which memory rows an account may see.

Every read, write, update, delete and list on the memory tables used to
filter on ``owner_id`` alone. That wall is gone: company families are
visible to every account holding the key, rule families only to their
owner. Rather than teach each of the ~30 call sites the family rule, they
all apply one of the predicates below and the rule lives here once.

    Blob.company_key == key AND (
        namespace is a company family   -- anyone with the key
        OR owner_id == owner            -- rule families: mine only
    )

``owner_id`` on a company-family row is provenance and takes no part in
visibility — which is exactly why an unfiltered "owner == me" read of
those rows would leak another account's rules, and why nothing here is
ever scoped by owner alone.
"""

from __future__ import annotations

from sqlalchemy import and_, or_

from zylch.memory.company_key import RULE_FAMILIES
from zylch.storage.models import (
    Blob,
    BlobSentence,
    CalendarBlob,
    EmailBlob,
    PersonIdentifier,
    WhatsAppBlob,
)


def _is_rule_namespace(column):
    return or_(*[column.like(f"{fam}:%") for fam in RULE_FAMILIES])


def blob_visible(owner_id: str, company_key: str):
    """Rows of ``blobs`` this (owner, key) may read, update, delete or list."""
    return and_(
        Blob.company_key == company_key,
        or_(~_is_rule_namespace(Blob.namespace), Blob.owner_id == owner_id),
    )


def blob_owned_rules(owner_id: str, company_key: str):
    """This account's own rule rows — what a per-account reset removes."""
    return and_(
        Blob.company_key == company_key,
        Blob.owner_id == owner_id,
        _is_rule_namespace(Blob.namespace),
    )


def blob_contributed(owner_id: str, company_key: str):
    """Every row this account wrote, company families included (provenance)."""
    return and_(Blob.company_key == company_key, Blob.owner_id == owner_id)


def sentences_in_scope(company_key: str):
    """Sentences are reached through a blob id already checked by ``blob_visible``."""
    return BlobSentence.company_key == company_key


def links_in_scope(model, company_key: str):
    """Association and identifier rows belong to the company, not to an owner."""
    assert model in (EmailBlob, CalendarBlob, WhatsAppBlob, PersonIdentifier)
    return model.company_key == company_key
