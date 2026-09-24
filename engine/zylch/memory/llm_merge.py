"""The merge-routed client consolidation decides pairs with, and the merge-gate canary.

:class:`LLMMergeService` holds the ``MODEL_MEMORY_MERGE``-routed client.
Consolidation (:mod:`zylch.memory.consolidation`) submits every pair it
clusters through :meth:`LLMMergeService.decide_pair` into the mnemonic
harness, where the role decides, the validator checks and the commit writes;
nothing here writes memory. :func:`merge_gate_selfcheck` is the canary that
asks the same routed model whether it still refuses to fold two unrelated
memories together.

Every mnemonic import here is deferred into the function that needs it:
``zylch.memory`` loads this module, and the mnemonic package loads
``zylch.workers``, whose memory module imports :class:`LLMMergeService`.
"""

import logging
from typing import Any, Dict, Optional

from zylch.memory.response_validation import complete_memory_text
from zylch.llm import LLMClient, make_llm_client, routed_model
from zylch.llm.usage import call_site

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
    """The merge-routed LLM client, and consolidation's pair decision through it.

    :meth:`decide_pair` is how a consolidation pair reaches the mnemonic
    harness; :meth:`merge` is the legacy two-entity prompt the canary still
    asks.
    """

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
        from zylch.llm.usage import call_site, current_call_site

        site = current_call_site()
        with call_site("memory.merge" if site == "untagged" else site):
            response = self.client.create_message_sync(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=[
                    {"role": "user", "content": user_content},
                ],
            )
        result = complete_memory_text(response)
        # Log the DECISION at INFO so the INSERT rate is visible at a glance
        # in the logs — a sustained 0% INSERT rate is the fingerprint of a
        # broken-open gate (the 2026-06 silent regression).
        decision = "INSERT" if is_no_merge_response(result) else "MERGE"
        logger.info(f"[merge] decision={decision} model={self.model}")
        logger.debug("[merge] existing=%r\nnew=%r\nresult=%r", existing, new, result)
        return result

    def decide_pair(self, pair: Dict[str, Any]) -> Any:
        """Submit one consolidation pair to the mnemonic harness with this client.

        The role proposes, the validator checks the identity evidence and the
        commit writes, inside the admitted preparation item the caller runs
        this in: MERGE is the one mutation a pair admits
        (:func:`zylch.memory.mnemonic.pairs.decide`). Returns the
        :class:`~zylch.memory.mnemonic.proposals.MnemonicResult`.
        """
        from zylch.memory.mnemonic.pairs import decide

        return decide(pair, client=self.client)


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
        # MODEL_MEMORY_MERGE per-worker knob (empty → engine default). The
        # canary must exercise the SAME model the live merge gate uses.
        svc = merge_service or LLMMergeService(model=routed_model("MODEL_MEMORY_MERGE"))
        with call_site("canary"):
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
