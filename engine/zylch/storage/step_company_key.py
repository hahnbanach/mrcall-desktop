"""Migration step ``0001_company_key`` — every memory row gets the key.

Forward (run once by the M0 runner, under the file lock, backed up first
because it rewrites rows):

1. mint and persist the profile's ``MEMORY_KEY`` if it has none — this
   happens *inside* the step, so the mint provably precedes the rewrite
   in the same boot and no boot can record the step with no key;
2. stamp ``company_key`` on every existing row of the six memory tables
   — rule families included, or their rows would be invisible once the
   rule predicate is key AND owner;
3. rewrite the company-family namespaces: ``user:<anything>`` and
   ``facts:<anything>`` become ``user:<key>`` / ``facts:<key>``. Facts are
   retrieved by exact namespace equality, so rewriting rows without the
   constructors — or the reverse — re-splits the store on the next write;
   both halves ship in one commit.

Idempotent over a partially-reverted database: every UPDATE is guarded so
a re-run touches nothing it already did.

Reverse (a rollback, never run by the runner): namespaces go back to
``<family>:<owner_id>`` — exact, because ``owner_id`` was never overwritten
— and the step is un-recorded so a later forward re-applies it. The
``company_key`` column is nullable and stays; reverted code ignores it.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, Engine

from zylch.memory.company_key import COMPANY_FAMILIES, ensure_company_key
from zylch.storage.migrations import MigrationStep, unrecord_step

logger = logging.getLogger(__name__)

STEP_ID = "0001_company_key"

MEMORY_TABLES = (
    "blobs",
    "blob_sentences",
    "email_blobs",
    "calendar_blobs",
    "whatsapp_blobs",
    "person_identifiers",
)


def apply(conn: Connection) -> None:
    key = ensure_company_key()
    stamped = 0
    for table in MEMORY_TABLES:
        res = conn.exec_driver_sql(
            f"UPDATE {table} SET company_key = ? WHERE company_key IS NULL", (key,)
        )
        stamped += res.rowcount or 0
    rewritten = 0
    for fam in COMPANY_FAMILIES:
        target = f"{fam}:{key}"
        res = conn.exec_driver_sql(
            "UPDATE blobs SET namespace = ? WHERE namespace LIKE ? AND namespace != ?",
            (target, f"{fam}:%", target),
        )
        rewritten += res.rowcount or 0
    logger.info(
        f"[migrate] {STEP_ID}: stamped company_key on {stamped} row(s), "
        f"rewrote {rewritten} company-family namespace(s)"
    )


def reverse(engine: Engine) -> None:
    """Undo the namespace rewrite and forget the step. Lossless."""
    with engine.begin() as conn:
        for fam in COMPANY_FAMILIES:
            conn.exec_driver_sql(
                "UPDATE blobs SET namespace = ? || ':' || owner_id WHERE namespace LIKE ?",
                (fam, f"{fam}:%"),
            )
    unrecord_step(engine, STEP_ID)
    logger.info(f"[migrate] {STEP_ID}: reversed and un-recorded")


STEP = MigrationStep(
    id=STEP_ID,
    apply=apply,
    destructive=True,
    description="company_key on every memory row; company-family namespaces keyed",
)
