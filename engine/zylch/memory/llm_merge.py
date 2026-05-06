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


async def reconsolidate_now(owner_id: str) -> Dict[str, Any]:
    """Walk all blobs in ``user:<owner_id>``, merge same-name groups.

    Algorithm:
      1. Fetch every blob in the namespace.
      2. Group by canonical Name (extracted from the structured
         #IDENTIFIERS block).
      3. For each group of size >= 2, treat the longest blob as the
         keeper, then pairwise merge each other blob into it. If the
         LLM returns "INSERT" / "SKIP" (different entity), preserve
         both. Otherwise: update keeper.content with the merged text
         and delete the other blob.
      4. Return summary counts.

    Returns:
        {
          "groups_examined": int,
          "blobs_examined": int,
          "blobs_merged": int,    # successful merges (other deleted)
          "blobs_kept_distinct": int,  # LLM said different, both kept
          "pair_cap_hit": bool,
          "no_llm": bool,
        }
    """
    from zylch.memory import EmbeddingEngine, MemoryConfig
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    namespace = f"user:{owner_id}"

    if try_make_llm_client() is None:
        logger.warning(
            "[reconsolidate] no LLM transport configured — sweep skipped"
        )
        return {
            "groups_examined": 0,
            "blobs_examined": 0,
            "blobs_merged": 0,
            "blobs_kept_distinct": 0,
            "pair_cap_hit": False,
            "no_llm": True,
        }

    # Pull every blob in the namespace. We do not use BlobStorage.list_blobs
    # because that limits to N most-recent; reconsolidation needs the full
    # set so a forgotten old duplicate still surfaces.
    with get_session() as sess:
        rows = (
            sess.query(Blob.id, Blob.content)
            .filter(Blob.owner_id == owner_id, Blob.namespace == namespace)
            .all()
        )
        blobs: List[Dict[str, Any]] = [
            {"id": str(r[0]), "content": r[1] or ""} for r in rows
        ]

    blobs_examined = len(blobs)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for b in blobs:
        name = _extract_canonical_name(b["content"])
        if not name:
            continue
        groups.setdefault(name, []).append(b)

    # Filter to groups with potential duplicates.
    dup_groups = {n: bs for n, bs in groups.items() if len(bs) >= 2}
    if not dup_groups:
        return {
            "groups_examined": 0,
            "blobs_examined": blobs_examined,
            "blobs_merged": 0,
            "blobs_kept_distinct": 0,
            "pair_cap_hit": False,
            "no_llm": False,
        }

    # Need an embedding engine + BlobStorage instance for the
    # update/delete calls (they handle sentence re-embedding +
    # mutation hooks).
    config = MemoryConfig()
    embedding = EmbeddingEngine(config)
    storage = BlobStorage(get_session, embedding)

    merge_service = LLMMergeService()

    blobs_merged = 0
    blobs_kept_distinct = 0
    pair_cap_hit = False
    aborted_overload = False
    pairs_done = 0
    consecutive_overload = 0

    for name, group in dup_groups.items():
        # Keep the longest (most informative) blob as the keeper.
        group.sort(key=lambda b: len(b["content"]), reverse=True)
        keeper = group[0]
        for other in group[1:]:
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
                logger.exception(
                    f"[reconsolidate] merge failed for keeper={keeper['id'][:12]} "
                    f"other={other['id'][:12]} name={name!r}: {e}"
                )
                # Persistent provider overload: stop hammering. The
                # blobs that didn't get merged THIS run remain
                # untouched; next manual click retries.
                if "529" in err_str or "overloaded" in err_str.lower():
                    consecutive_overload += 1
                    if consecutive_overload >= 2:
                        aborted_overload = True
                        logger.warning(
                            "[reconsolidate] sweep aborted — provider overloaded "
                            f"after {consecutive_overload} consecutive 529s. "
                            "Re-run when capacity recovers."
                        )
                        break
                continue
            if not merged:
                continue
            up = merged.strip().upper()
            if up == "INSERT" or up == "SKIP" or (len(merged) < 10 and "INSERT" in up):
                blobs_kept_distinct += 1
                logger.debug(
                    f"[reconsolidate] kept distinct: keeper={keeper['id'][:12]} "
                    f"other={other['id'][:12]} name={name!r}"
                )
                continue
            # Successful merge — write merged content into keeper,
            # delete other.
            try:
                storage.update_blob(
                    blob_id=keeper["id"],
                    owner_id=owner_id,
                    content=merged,
                    event_description=(
                        f"Reconsolidated with {other['id'][:8]}… via "
                        "manual sweep"
                    ),
                )
                deleted = storage.delete_blob(other["id"], owner_id)
                if deleted:
                    keeper["content"] = merged  # so next pair sees the merged text
                    blobs_merged += 1
                    logger.info(
                        f"[reconsolidate] merged keeper={keeper['id'][:12]} "
                        f"absorbed={other['id'][:12]} name={name!r}"
                    )
            except Exception as e:
                logger.exception(
                    f"[reconsolidate] storage write failed for keeper={keeper['id'][:12]}: {e}"
                )
                continue
        if pair_cap_hit or aborted_overload:
            break

    summary = {
        "groups_examined": len(dup_groups),
        "blobs_examined": blobs_examined,
        "blobs_merged": blobs_merged,
        "blobs_kept_distinct": blobs_kept_distinct,
        "pair_cap_hit": pair_cap_hit,
        "aborted_overload": aborted_overload,
        "no_llm": False,
    }
    logger.info(f"[reconsolidate] sweep complete: {summary}")
    return summary
