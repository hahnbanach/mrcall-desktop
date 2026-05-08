"""LLM-assisted memory reconsolidation."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from zylch.llm import LLMClient, make_llm_client, try_make_llm_client

logger = logging.getLogger(__name__)


class LLMMergeService:
    """LLM-assisted memory merge for reconsolidation."""

    def __init__(self, model: str = None):
        self.client: LLMClient = make_llm_client(model=model)
        self.model = self.client.model
        self.MERGE_PROMPT = """Merge these entities into a SINGLE ENTITY:

EXISTING_ENTITY:
{existing}

NEW ENTITY:
{new}

#FIRST RULE
If you think EXISTING_ENTITY and NEW_ENTITY are not about the same entity, JUST PRODUCE ONE WORD:

INSERT

#OTHER Rules:
1. There must be **1** entity in the resulting entity: the resulting #IDENTIFIERS section must describe **1** entity.
2. There must be **1** entity in the resulting entity: the resulting #ABOUT section must describe **1** entity
3. #IDENTIFIERS: if the NEW ENTITY adds new IDENTIFIERS, add them. **But they must be about the same entity (IF NOT JUST RETURN "SKIP")
5. #ABOUT: keep as ONE sentence and update it only if NEW_ENTITY adds more information
6. #HISTORY: append new events chronologically, keep concise

OUTPUT FORMAT (required):
#IDENTIFIERS
Entity type: [person/company/project]
Name: [name]
[other identifiers as available: Email, Phone, Company, Website, etc.]
**REMEMBER** These must be the identifiers of just **1** entity!!

#ABOUT
[One sentence describing what/who this entity is]
**REMEMBER** These must describe just **1** entity!!

#HISTORY
[Chronological narrative of events and interactions]

Output ONLY the merged entity in this exact format, nothing else."""

    def merge(self, existing: str, new: str) -> str:
        """Merge two memory contents using LLM.

        Uses prompt caching: merge instructions as cached system,
        entity data as user message.

        Args:
            existing: Current blob content
            new: New information to merge

        Returns:
            Merged content string
        """
        logging.info("MERGING CALLED")
        system = [
            {
                "type": "text",
                "text": self.MERGE_PROMPT.split("EXISTING_ENTITY:")[0].strip(),
                "cache_control": {"type": "ephemeral"},
            },
        ]
        user_content = f"EXISTING_ENTITY:\n{existing}\n\n" f"NEW ENTITY:\n{new}"
        response = self.client.create_message_sync(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[
                {"role": "user", "content": user_content},
            ],
        )
        result = response.content[0].text.strip()
        logging.info(
            f"MERGING ENTITIES:\n" f"existing: {existing}\n" f"new:{new}\n" f"result:{result}\n\n"
        )
        return result


# ─── Manual reconsolidation sweep ────────────────────────────────────


# Cap the number of merge pairs we attempt per /reconsolidate_now call.
# Each pair is one LLM call, so a profile with many duplicate-name
# blobs (the Salamone case had 8 PERSON blobs collapsing into 1) burns
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
            up = merged.strip().upper()
            if up == "INSERT" or up == "SKIP" or (len(merged) < 10 and "INSERT" in up):
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
