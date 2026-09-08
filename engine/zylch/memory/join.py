"""Joining a company memory — the only write path for ``MEMORY_KEY`` after M2.

Entering an existing key from a profile that already holds a memory merges
two memories. The merge is deterministic and lossless:

- **facts** with the same (category, key) converge to one row — the store
  being joined wins, it is the company's — and the value that does not
  win is kept in ``fact_history`` with the losing row's ``owner_id``, so
  the rollback can still return it to the profile it came from;
- **entities** from both memories are all kept; duplicates are united by
  the reconsolidation sweep, which under a shared store runs once per
  company;
- **rules** travel with their owner (``template:<owner>`` is personal);
- sentences, links and identifiers follow their blob.

Then the key is written to the profile ``.env`` with
``MEMORY_KEY_SOURCE=join``, the session factory is rebound to the joined
store in-process (a restart is not available to a headless daemon), and
the vector index is invalidated. The old store is left on disk: it is the
only copy of the pre-join state.

``settings.update`` refuses ``MEMORY_KEY`` — a key written there would boot
the engine on a new store with no merge and orphan the old one.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import Engine, text

from zylch.memory.company_key import COMPANY_FAMILIES, RULE_FAMILIES, well_formed
from zylch.memory.store import (
    MemoryUnavailable,
    memory_db_path,
    open_memory_engine,
    prepare_store,
    store_exists,
    store_summary,
)
from zylch.storage.migrations import db_file_lock

logger = logging.getLogger(__name__)

_LOCK_SUFFIX = ".join.lock"


def preview(key: str) -> Dict[str, Any]:
    """What joining ``key`` would join — echoed to the user before they commit.

    Never creates anything; an unknown key is ``{"exists": False}``.
    """
    ok, reason = well_formed(key)
    if not ok:
        return {"well_formed": False, "reason": reason, "exists": False}
    key = key.strip()
    if not store_exists(key):
        return {
            "well_formed": True,
            "exists": False,
            "reason": "no company memory exists for this key",
        }
    engine = open_memory_engine(key, create=False)
    try:
        return {"well_formed": True, "exists": True, "reason": "", **store_summary(engine)}
    finally:
        engine.dispose()


def _parse_fact(content: str):
    from zylch.services.facts_store import parse_category, parse_key

    return parse_category(content or "").lower(), parse_key(content or "").lower()


def _fact_value(content: str) -> str:
    """The value of a ``Category:/Key:/<value>`` fact blob — what history keeps."""
    lines = [ln for ln in (content or "").splitlines()]
    body = [ln for ln in lines if not ln.strip().lower().startswith(("category:", "key:"))]
    value = "\n".join(body).strip()
    if value.lower().startswith("value:"):
        value = value.split(":", 1)[1].strip()
    return value or content


def _rewrite_namespace(namespace: str, src_key: Optional[str], dst_key: str) -> str:
    family = namespace.split(":", 1)[0] if ":" in namespace else ""
    if family in COMPANY_FAMILIES:
        return f"{family}:{dst_key}"
    if family in RULE_FAMILIES:
        return namespace
    return namespace


def merge_store_into(
    src: Engine, dst: Engine, src_key: Optional[str], dst_key: str
) -> Dict[str, int]:
    """Copy ``src``'s memory into ``dst`` under ``dst_key``. Returns counts."""
    counts = {
        "blobs": 0,
        "facts_converged": 0,
        "blob_sentences": 0,
        "links": 0,
        "identifiers": 0,
        "aliases": 0,
    }
    with src.begin() as s, dst.begin() as d:
        # existing facts in the destination, by (category, key)
        dst_facts = {}
        for bid, content in d.exec_driver_sql(
            "SELECT id, content FROM blobs WHERE namespace LIKE 'facts:%'"
        ).fetchall():
            dst_facts[_parse_fact(content)] = bid

        skipped_blob_ids = set()
        rows = s.exec_driver_sql(
            "SELECT id, owner_id, namespace, content, embedding, events, created_at, updated_at "
            "FROM blobs"
        ).fetchall()
        for bid, owner, ns, content, emb, events, created, updated in rows:
            new_ns = _rewrite_namespace(ns, src_key, dst_key)
            if new_ns.startswith("facts:"):
                fact_key = _parse_fact(content)
                winner = dst_facts.get(fact_key)
                if winner and winner != bid:
                    d.exec_driver_sql(
                        "INSERT INTO fact_history (id, company_key, category, fact_key, losing_value, "
                        "losing_owner_id, losing_blob_id, winning_blob_id, reason) "
                        "VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?, ?, ?, 'join')",
                        (
                            dst_key,
                            fact_key[0],
                            fact_key[1],
                            _fact_value(content),
                            owner,
                            bid,
                            winner,
                        ),
                    )
                    counts["facts_converged"] += 1
                    skipped_blob_ids.add(bid)
                    continue
                dst_facts[fact_key] = bid
            res = d.exec_driver_sql(
                "INSERT OR IGNORE INTO blobs (id, owner_id, namespace, content, embedding, events, "
                "created_at, updated_at, company_key) VALUES (?,?,?,?,?,?,?,?,?)",
                (bid, owner, new_ns, content, emb, events, created, updated, dst_key),
            )
            counts["blobs"] += res.rowcount or 0

        def _copy(table, cols, key_col="company_key"):
            n = 0
            col_list = ", ".join(cols)
            sel = s.exec_driver_sql(f"SELECT {col_list} FROM {table}").fetchall()
            for row in sel:
                row = dict(zip(cols, row))
                if row.get("blob_id") in skipped_blob_ids:
                    continue
                row[key_col] = dst_key
                names = list(row.keys())
                r = d.exec_driver_sql(
                    f"INSERT OR IGNORE INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                    tuple(row[k] for k in names),
                )
                n += r.rowcount or 0
            return n

        counts["blob_sentences"] += _copy(
            "blob_sentences",
            [
                "id",
                "blob_id",
                "owner_id",
                "sentence_text",
                "embedding",
                "created_at",
                "company_key",
            ],
        )
        counts["links"] += _copy(
            "email_blobs", ["email_id", "blob_id", "owner_id", "created_at", "company_key"]
        )
        counts["links"] += _copy(
            "calendar_blobs", ["event_id", "blob_id", "owner_id", "created_at", "company_key"]
        )
        counts["links"] += _copy(
            "whatsapp_blobs",
            ["whatsapp_message_id", "blob_id", "owner_id", "created_at", "company_key"],
        )
        counts["identifiers"] += _copy(
            "person_identifiers",
            ["id", "owner_id", "blob_id", "kind", "value", "created_at", "company_key"],
        )
        counts["aliases"] += _copy(
            "blob_aliases", ["merged_id", "keeper_id", "created_at", "company_key"]
        )
        d.exec_driver_sql("UPDATE memory_meta SET mutation_seq = mutation_seq + 1 WHERE id = 1")
    return counts


def join(key: str) -> Dict[str, Any]:
    """Join the company memory ``key`` names. Refuses an unknown or malformed key."""
    from zylch.memory.company_key import current_company_key, persist_company_key
    from zylch.storage import database as dbm

    ok, reason = well_formed(key)
    if not ok:
        return {"ok": False, "reason": reason}
    key = key.strip()
    if not store_exists(key):
        return {"ok": False, "reason": "no company memory exists for this key on this host"}
    current = current_company_key()
    if current == key:
        # Same key — but the store may not have existed when this profile
        # booted (a typed key, refused then; the colleague minted since).
        # A headless daemon has no restart to pick it up: attach now.
        if dbm.memory_unavailable_reason() is not None and store_exists(key):
            engine = open_memory_engine(key, create=False)
            prepare_store(engine, key, created_by=None)
            dbm.rebind_memory(engine)
            logger.info("[memory] attached the store for this profile's own key")
            return {
                "ok": True,
                "already": True,
                "attached": True,
                "merged": {},
                **store_summary(engine),
            }
        return {"ok": True, "already": True, "merged": {}}

    dst = open_memory_engine(key, create=False)
    with db_file_lock(memory_db_path(key), suffix=_LOCK_SUFFIX):
        prepare_store(dst, key, created_by=None)
        src_engine = dbm.current_memory_engine()
        merged: Dict[str, int] = {}
        if src_engine is not None and current and store_exists(current):
            merged = merge_store_into(src_engine, dst, current, key)
        # the key changes hands: .env first (durable), then the live process
        persist_company_key(key, source="join")
        dbm.rebind_memory(dst)
    logger.info(f"[memory] joined company memory (merged={merged})")
    return {"ok": True, "already": False, "merged": merged, **store_summary(dst)}


def status() -> Dict[str, Any]:
    """Is memory available for this profile, and if not, why. No paths."""
    from zylch.memory.company_key import current_company_key
    from zylch.storage import database as dbm

    key = current_company_key()
    reason = dbm.memory_unavailable_reason()
    out: Dict[str, Any] = {
        "has_key": key is not None,
        "available": reason is None,
        "reason": reason or "",
    }
    if reason is None:
        engine = dbm.current_memory_engine()
        if engine is not None:
            try:
                out.update(store_summary(engine))
            except MemoryUnavailable as e:
                out.update({"available": False, "reason": e.reason})
    _ = text  # imported for callers that extend this module
    return out
