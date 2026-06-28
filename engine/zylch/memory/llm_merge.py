"""LLM-assisted memory reconsolidation."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from zylch.llm import LLMClient, make_llm_client, try_make_llm_client

logger = logging.getLogger(__name__)


# ─── Merge-gate sentinel ─────────────────────────────────────────────
#
# The merge model answers a TWO-part question: are EXISTING and NEW the
# same real-world entity, and — only if so — what is the merged blob? When
# they are NOT the same entity it must emit a short sentinel ("INSERT", or
# the legacy "SKIP") instead of a blob. Every caller MUST treat that
# sentinel as "do not merge"; writing it into a blob — or, worse, the model
# never emitting it at all — silently destroys contact data.
#
# That second failure is the 2026-06 regression: the prompt-cache refactor
# in 58f392a put only the one-line preamble ("Merge these entities into a
# SINGLE ENTITY:") into the cached system prompt — `MERGE_PROMPT.split(
# "EXISTING_ENTITY:")[0]` — and dropped the ENTIRE rule set, including the
# INSERT rule, on the floor. The model was never told it could refuse, so
# across 859 merges it refused 0 times: the first PERSON blob ("John Doe")
# became a universal sink that absorbed 400+ unrelated contacts, each one's
# specifics discarded by the one-sentence #ABOUT constraint, and nobody
# could notice. merge_gate_selfcheck() below is the canary that now makes
# that failure loud and non-destructive.

_NO_MERGE_TOKENS = ("INSERT", "SKIP")


def is_no_merge_response(merged: Optional[str]) -> bool:
    """True when :meth:`LLMMergeService.merge` declined to merge.

    Tolerant of trailing punctuation / whitespace / case ("INSERT.",
    "insert\\n") but length-bounded, so a genuinely merged blob that merely
    contains the word "insert" somewhere in its prose is NOT misread as a
    refusal. Single source of truth for every merge-gate call site (the
    upsert paths historically checked only "INSERT", so a bare "SKIP" would
    have been written into a blob as its new content).
    """
    if not merged:
        return False
    up = merged.strip().upper()
    if up in _NO_MERGE_TOKENS:
        return True
    return len(up) < 12 and any(tok in up for tok in _NO_MERGE_TOKENS)


# The complete merge instructions. The ENTIRE rule set lives here and ships
# as the cached system prompt; ONLY the two entities go in the per-call
# user message. Do NOT fold the existing/new data into this string —
# keeping data out of the cached block is what 58f392a was reaching for,
# but it sliced the template and lost the rules. Data and instructions stay
# physically separate now.
MERGE_INSTRUCTIONS = """You compare two entity memories and decide whether they describe the SAME real-world entity, then merge them ONLY if they do.

You receive EXISTING_ENTITY and NEW_ENTITY in the user message.

STEP 1 — Decide identity. They are the SAME entity ONLY if their identifiers point to the same real-world person / company / project: the same email address, the same phone number, or unmistakably the same name together with the same company. A similar topic, a shared subject line, or both parties writing to the same support inbox is NOT enough. Two parties that merely interacted with each other (e.g. a customer and your company) are DIFFERENT entities.

If they are NOT the same entity, output EXACTLY this one word and nothing else:
INSERT

STEP 2 — Only if they ARE the same entity, merge them into ONE entity, in this exact format:

#IDENTIFIERS
Entity type: [person/company/project]
Name: [name]
[other identifiers as available: Email, Phone, Company, Website, etc.]

#ABOUT
[One sentence describing who/what this single entity is]

#HISTORY
[Chronological narrative of events and interactions; append new events, keep concise]

Rules when merging:
1. The result describes EXACTLY ONE entity — never combine two different people or companies into a single blob.
2. #IDENTIFIERS: add identifiers from NEW_ENTITY only when they belong to that same one entity.
3. #ABOUT: keep it to ONE sentence; update it only if NEW_ENTITY adds information.
4. #HISTORY: append new events chronologically, keep it concise.

Output ONLY the single word INSERT, or ONLY the merged entity in the exact format above — nothing else."""


class LLMMergeService:
    """LLM-assisted memory merge for reconsolidation."""

    def __init__(self, model: str = None):
        self.client: LLMClient = make_llm_client(model=model)
        self.model = self.client.model
        # Backward-compat alias; the rule set now lives module-level.
        self.MERGE_PROMPT = MERGE_INSTRUCTIONS

    def merge(self, existing: str, new: str) -> str:
        """Merge two memory contents using the LLM.

        The cached system prompt carries the COMPLETE instruction set
        (identity decision + INSERT refusal + output format); the user
        message carries ONLY the two entities. Returns either the
        ``INSERT`` sentinel (distinct entities — test with
        :func:`is_no_merge_response`) or the merged blob.

        Args:
            existing: Current blob content.
            new: New information to merge.

        Returns:
            Merged content string, or the ``INSERT`` sentinel.
        """
        system = [
            {
                "type": "text",
                "text": MERGE_INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            },
        ]
        user_content = f"EXISTING_ENTITY:\n{existing}\n\nNEW_ENTITY:\n{new}"
        response = self.client.create_message_sync(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[
                {"role": "user", "content": user_content},
            ],
        )
        result = response.content[0].text.strip()
        # Log the DECISION at INFO so the INSERT rate is visible at a glance
        # in the logs — a sustained 0% INSERT rate is the fingerprint of a
        # broken-open gate (the 2026-06 silent regression).
        decision = "INSERT" if is_no_merge_response(result) else "MERGE"
        logger.info(f"[merge] decision={decision} model={self.model}")
        logger.debug("[merge] existing=%r\nnew=%r\nresult=%r", existing, new, result)
        return result


# ─── Merge-gate canary (closes the 2026-06 silent regression) ────────
#
# Two fixtures that are UNMISTAKABLY different entities — an individual and
# an unrelated company, sharing no identifier. A healthy gate must refuse
# to merge them (emit the INSERT sentinel). If it returns a merged blob the
# gate is "broken-open": every new contact is being absorbed into an
# existing blob and its specifics discarded. The memory build runs this
# once per pass so that condition is loud and, via the worker's
# merge_enabled guard, non-destructive — never again silent.
_CANARY_EXISTING = (
    "#IDENTIFIERS\n"
    "Entity type: PERSON\n"
    "Name: Aldo Bianchi\n"
    "Email: aldo.bianchi@canary-person.example\n"
    "Phone: +39 02 1110001\n\n"
    "#ABOUT\n"
    "Aldo Bianchi is an individual customer asking about a refund.\n\n"
    "#HISTORY\n"
    "2026-01-10: emailed support asking for a refund on order 8842."
)
_CANARY_NEW = (
    "#IDENTIFIERS\n"
    "Entity type: COMPANY\n"
    "Name: Zeta Logistics SRL\n"
    "Email: info@canary-company.example\n"
    "Phone: +39 06 9990002\n\n"
    "#ABOUT\n"
    "Zeta Logistics SRL is a freight-forwarding company.\n\n"
    "#HISTORY\n"
    "2026-02-03: wrote to propose a logistics partnership."
)


def merge_gate_selfcheck(merge_service: Optional["LLMMergeService"] = None) -> Dict[str, Any]:
    """Semantic canary for the merge gate.

    Feeds two unmistakably-distinct entities to the LIVE merge model and
    asserts it refuses to merge them. This is the detector for the
    'broken-open gate' failure mode (2026-06) in which the model is never
    told it may refuse, silently collapses every contact into one blob, and
    discards their data.

    Returns ``{"healthy": bool|None, "verdict": str, "raw": str}``.
    ``healthy is None`` means the check could not run (no LLM / transient
    error) — treat as 'unknown', NOT 'broken', so a flaky API call never
    disables merging. ``healthy is False`` is a data-destroying condition
    and is logged at ERROR.
    """
    try:
        svc = merge_service or LLMMergeService()
        raw = svc.merge(_CANARY_EXISTING, _CANARY_NEW)
    except Exception as e:
        logger.warning(f"[merge-gate] self-check could not run: {e}")
        return {"healthy": None, "verdict": "error", "raw": str(e)}

    healthy = is_no_merge_response(raw)
    if healthy:
        logger.info("[merge-gate] self-check OK — distinct entities correctly refused (INSERT)")
    else:
        logger.error(
            "[merge-gate] BROKEN-OPEN: the merge model MERGED two unrelated "
            "entities instead of refusing. New contacts would be absorbed "
            "into existing blobs and their data discarded; memory merging is "
            "being DISABLED for this build to prevent corruption. raw=%r",
            raw,
        )
    return {
        "healthy": healthy,
        "verdict": "refused" if healthy else "merged",
        "raw": raw,
    }


# ─── Manual reconsolidation sweep ────────────────────────────────────


# Cap the number of merge pairs we attempt per /reconsolidate_now call.
# Each pair is one LLM call, so a profile with many duplicate-name
# blobs (the Smith case had 8 PERSON blobs collapsing into 1) burns
# 7 calls. We cap to bound user-perceived latency on the button.
RECONSOLIDATION_PAIR_CAP = 50


def _extract_canonical_name(content: str) -> Optional[str]:
    """Pull a canonical entity name from a blob's structured-format body.

    The merge prompt mandates an `#IDENTIFIERS\\nEntity type: ...\\nName: ...`
    layout, so we can rely on a "Name:" line being present in any
    well-formed blob. Falls back to None when the line is missing or
    empty (e.g. legacy blobs with free-form content).

    The line format is structured by us, not free-form prose, so a
    line-prefix check is allowed under the engine's parsing rules.
    """
    if not content:
        return None
    for line in content.splitlines():
        s = line.strip()
        if s.lower().startswith("name:"):
            value = s[5:].strip()
            if value and value.lower() not in ("[name]", "(unknown)", "n/a"):
                return value.lower()
    return None


def _build_dedup_clusters(
    blobs: List[Dict[str, Any]],
    blob_identifiers: Dict[str, set],
) -> List[List[Dict[str, Any]]]:
    """Cluster blobs that share at least one identity key.

    Identity keys come from two sources, OR-merged via union-find:
      * structured identifiers from the ``person_identifiers`` index —
        ``("id", kind, value)`` tuples (Phase 1a/1b);
      * canonical Name from the blob's ``#IDENTIFIERS`` block —
        ``("name", lowercased name)`` tuple (legacy reconsolidation
        path, kept as a fallback for blobs without structured email /
        phone / lid).

    A chain like "A and B share email; B and C share phone" yields one
    cluster {A, B, C}. Returns clusters with ≥ 2 blobs each; singletons
    are dropped.
    """
    parent: Dict[str, str] = {b["id"]: b["id"] for b in blobs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Build key → [blob_id] index from BOTH identifier table AND name.
    key_to_blobs: Dict[tuple, List[str]] = {}
    for b in blobs:
        bid = b["id"]
        # Name key (legacy fallback for blobs without structured ids)
        name = _extract_canonical_name(b["content"])
        if name:
            key_to_blobs.setdefault(("name", name), []).append(bid)
        # Identifier keys (Phase 1a/1b)
        for kind, value in blob_identifiers.get(bid, set()):
            key_to_blobs.setdefault(("id", kind, value), []).append(bid)

    # Union every blob set sharing a key
    for bids in key_to_blobs.values():
        if len(bids) < 2:
            continue
        for i in range(1, len(bids)):
            union(bids[0], bids[i])

    # Group by root
    clusters_by_root: Dict[str, List[Dict[str, Any]]] = {}
    for b in blobs:
        root = find(b["id"])
        clusters_by_root.setdefault(root, []).append(b)

    return [c for c in clusters_by_root.values() if len(c) >= 2]


async def reconsolidate_now(owner_id: str) -> Dict[str, Any]:
    """Walk all blobs in ``user:<owner_id>``, merge identity-equivalent groups.

    Algorithm (Phase 1c, whatsapp-pipeline-parity, 2026-05-08):
      1. Fetch every blob in the namespace plus its rows in
         ``person_identifiers``.
      2. Cluster blobs that share at least one identity key. Identity
         keys are the structured ``(kind, value)`` tuples from the
         identifier index (email / phone / lid) OR the canonical
         ``Name:`` line from the blob's ``#IDENTIFIERS`` block. Both
         sources are OR-merged via union-find.
      3. For each cluster of size ≥ 2, treat the longest blob as the
         keeper. For each other blob:
           a. Run an LLM merge.
           b. If the LLM returns ``INSERT`` / ``SKIP`` (entities are
              different), keep both blobs and continue. The shared
              identifier is then a true cross-entity collision (e.g.
              switchboard phone) and the index correctly retains both.
           c. Otherwise, BEFORE deleting the other blob, migrate its
              cross-references — ``person_identifiers``,
              ``email_blobs``, ``calendar_blobs``, and the JSON
              ``task_items.sources.blobs`` lists — onto the keeper
              via ``Storage.migrate_blob_references``. Then
              ``update_blob`` with the merged content and
              ``delete_blob`` on the other.

    Returns summary counts including the migration totals so a caller
    can quantify the dedup impact across all four reference tables.
    """
    from zylch.memory import EmbeddingEngine, MemoryConfig
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage import Storage as MainStorage
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, PersonIdentifier

    namespace = f"user:{owner_id}"

    if try_make_llm_client() is None:
        logger.warning("[reconsolidate] no LLM transport configured — sweep skipped")
        return {
            "groups_examined": 0,
            "blobs_examined": 0,
            "blobs_merged": 0,
            "blobs_kept_distinct": 0,
            "pair_cap_hit": False,
            "no_llm": True,
            "person_identifiers_migrated": 0,
            "email_blobs_migrated": 0,
            "calendar_blobs_migrated": 0,
            "task_items_updated": 0,
        }

    # Pull every blob + identifier rows in ONE round-trip.
    with get_session() as sess:
        rows = (
            sess.query(Blob.id, Blob.content)
            .filter(Blob.owner_id == owner_id, Blob.namespace == namespace)
            .all()
        )
        blobs: List[Dict[str, Any]] = [{"id": str(r[0]), "content": r[1] or ""} for r in rows]
        ident_rows = (
            sess.query(
                PersonIdentifier.blob_id,
                PersonIdentifier.kind,
                PersonIdentifier.value,
            )
            .filter(PersonIdentifier.owner_id == owner_id)
            .all()
        )

    blobs_examined = len(blobs)
    blob_identifiers: Dict[str, set] = {}
    for bid, kind, value in ident_rows:
        blob_identifiers.setdefault(str(bid), set()).add((str(kind), str(value)))

    dup_clusters = _build_dedup_clusters(blobs, blob_identifiers)
    if not dup_clusters:
        return {
            "groups_examined": 0,
            "blobs_examined": blobs_examined,
            "blobs_merged": 0,
            "blobs_kept_distinct": 0,
            "pair_cap_hit": False,
            "no_llm": False,
            "person_identifiers_migrated": 0,
            "email_blobs_migrated": 0,
            "calendar_blobs_migrated": 0,
            "task_items_updated": 0,
        }

    # BlobStorage handles sentence re-embedding + mutation hooks for
    # the update/delete calls. MainStorage owns migrate_blob_references.
    config = MemoryConfig()
    embedding = EmbeddingEngine(config)
    blob_storage = BlobStorage(get_session, embedding)
    main_storage = MainStorage.get_instance()

    merge_service = LLMMergeService()

    blobs_merged = 0
    blobs_kept_distinct = 0
    pair_cap_hit = False
    aborted_overload = False
    pairs_done = 0
    consecutive_overload = 0
    migrate_totals = {
        "person_identifiers_migrated": 0,
        "email_blobs_migrated": 0,
        "calendar_blobs_migrated": 0,
        "task_items_updated": 0,
    }

    for cluster in dup_clusters:
        # Keep the longest (most informative) blob as the keeper.
        cluster.sort(key=lambda b: len(b["content"]), reverse=True)
        keeper = cluster[0]
        for other in cluster[1:]:
            if pairs_done >= RECONSOLIDATION_PAIR_CAP:
                pair_cap_hit = True
                break
            if aborted_overload:
                break
            pairs_done += 1
            try:
                # Run the sync merge in a thread so we don't block
                # the async event loop.
                merged = await asyncio.to_thread(
                    merge_service.merge, keeper["content"], other["content"]
                )
                consecutive_overload = 0
            except Exception as e:
                err_str = str(e)
                if "529" in err_str or "overloaded" in err_str.lower():
                    logger.warning(
                        f"[reconsolidate] merge overloaded (529) "
                        f"keeper={keeper['id'][:12]} other={other['id'][:12]}"
                    )
                    consecutive_overload += 1
                    if consecutive_overload >= 2:
                        aborted_overload = True
                        logger.warning(
                            "[reconsolidate] sweep aborted — provider overloaded "
                            f"after {consecutive_overload} consecutive 529s. "
                            "Re-run when capacity recovers."
                        )
                        break
                else:
                    logger.exception(
                        f"[reconsolidate] merge failed for keeper={keeper['id'][:12]} "
                        f"other={other['id'][:12]}: {e}"
                    )
                continue
            if not merged:
                continue
            if is_no_merge_response(merged):
                blobs_kept_distinct += 1
                logger.debug(
                    f"[reconsolidate] kept distinct: keeper={keeper['id'][:12]} "
                    f"other={other['id'][:12]}"
                )
                continue
            # Successful merge — migrate cross-references FIRST so
            # CASCADE delete doesn't drop them, then write merged
            # content into keeper, then delete other.
            try:
                migrated = main_storage.migrate_blob_references(
                    owner_id=owner_id,
                    dup_blob_id=other["id"],
                    keeper_blob_id=keeper["id"],
                )
                for k, v in migrated.items():
                    if k in migrate_totals:
                        migrate_totals[k] += int(v)
                blob_storage.update_blob(
                    blob_id=keeper["id"],
                    owner_id=owner_id,
                    content=merged,
                    event_description=(f"Reconsolidated with {other['id'][:8]}… via manual sweep"),
                )
                deleted = blob_storage.delete_blob(other["id"], owner_id)
                if deleted:
                    keeper["content"] = merged  # so next pair sees the merged text
                    blobs_merged += 1
                    logger.info(
                        f"[reconsolidate] merged keeper={keeper['id'][:12]} "
                        f"absorbed={other['id'][:12]} migrated={migrated}"
                    )
            except Exception as e:
                logger.exception(
                    f"[reconsolidate] storage write failed for keeper={keeper['id'][:12]}: {e}"
                )
                continue
        if pair_cap_hit or aborted_overload:
            break

    summary = {
        "groups_examined": len(dup_clusters),
        "blobs_examined": blobs_examined,
        "blobs_merged": blobs_merged,
        "blobs_kept_distinct": blobs_kept_distinct,
        "pair_cap_hit": pair_cap_hit,
        "aborted_overload": aborted_overload,
        "no_llm": False,
        **migrate_totals,
    }
    logger.info(f"[reconsolidate] sweep complete: {summary}")
    return summary
