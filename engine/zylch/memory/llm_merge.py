"""The merge-routed client consolidation decides pairs with, and the merge-gate canary.

:class:`LLMMergeService` holds the ``MODEL_MEMORY_MERGE``-routed client.
Consolidation (:mod:`zylch.memory.consolidation`) submits every pair it
clusters through :meth:`LLMMergeService.decide_pair` into the mnemonic
harness, where the role decides, the validator checks and the commit writes;
nothing here writes memory. :func:`merge_gate_selfcheck` is the canary that
asks the same routed model, through the same role and the same rule set,
whether it still refuses to fold two unrelated memories together.

Every mnemonic import here is deferred into the function that needs it:
``zylch.memory`` loads this module, and the mnemonic package loads
``zylch.workers``, whose memory module imports :class:`LLMMergeService`.
"""

import logging
from typing import Any, Dict, Optional

from zylch.llm import LLMClient, make_llm_client, routed_model
from zylch.llm.usage import call_site

logger = logging.getLogger(__name__)


class LLMMergeService:
    """The merge-routed LLM client, and consolidation's pair decision through it.

    :meth:`decide_pair` is how a consolidation pair reaches the mnemonic
    harness; :func:`merge_gate_selfcheck` asks the same client whether the
    role still refuses to fold two unrelated memories together.
    """

    def __init__(self, model: str = None):
        self.client: LLMClient = make_llm_client(model=model)
        self.model = self.client.model

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


# ─── Merge-gate canary ────────────────────────────────────────────────
#
# Two fixtures that are UNMISTAKABLY different subjects — an individual and an
# unrelated company, sharing no identifier — shown to the mnemonic role as one
# consolidation pair. A healthy role does not propose to fold them together.
# If it proposes a MERGE, or a write that absorbs the other memory, the gate is
# broken open: consolidation would fold strangers and ingestion would absorb
# new contacts into existing memories, their specifics discarded. The canary
# makes that loud and, through the merge gate it sets, non-destructive: an
# unhealthy verdict shows ingestion's role no candidate and suspends every
# consolidation pair.
_CANARY_OWNER = "merge-gate-canary"
_CANARY_COMPANY = "merge-gate-canary"
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


def _canary_memory(blob_id: str, content: str) -> Dict[str, Any]:
    """A canary fixture in the shape ``get_blob`` returns a memory."""
    return {
        "id": blob_id,
        "content": content,
        "updated_at": "canary",
        "namespace": f"user:{_CANARY_COMPANY}",
    }


def merge_gate_selfcheck(merge_service: Optional["LLMMergeService"] = None) -> Dict[str, Any]:
    """Semantic canary for the merge gate: does the role still refuse to fold strangers?

    The two canary memories are built into a consolidation pair
    (:func:`~zylch.memory.mnemonic.pairs.pair_event`, pinned candidates) and
    shown to the LIVE merge-routed model with the mnemonic role's own cached
    rule set and data turn (``prompts.system_blocks``, ``prompts.user_message``):
    one call, tagged ``canary``, an auxiliary preparation dispatch. It asks for
    a decision and writes nothing — no grant, no journal row. This is the
    detector for the 'broken-open gate' failure mode (2026-06), in which the
    model folds unrelated contacts together and their data is lost.

    Returns ``{"healthy": bool|None, "verdict": str, "raw": str, "validator": str}``:

    - ``refused`` (``healthy`` True) when the role does not propose to fold the
      two together;
    - ``merged`` (``healthy`` False, logged at ERROR) when it answers MERGE or
      a proposal that absorbs the other memory, whatever the validator then
      says: the gate guards the model's judgment, and a model that folds
      strangers is broken open even where the validator refuses this pair;
    - ``error`` (``healthy`` None) when the check could not run or the answer
      was unusable — treat as 'unknown', NOT 'broken', so a flaky API call
      never disables merging.

    ``validator`` is whether the validator would have accepted the proposal
    (``accepted`` / ``refused``), recorded for the log; it decides nothing.
    """
    from zylch.memory.mnemonic import prompts
    from zylch.memory.mnemonic.agent import adapt_response
    from zylch.memory.mnemonic.candidates import pinned
    from zylch.memory.mnemonic.contracts import MERGE, MNEMONIC_MAX_TOKENS
    from zylch.memory.mnemonic.pairs import pair_event
    from zylch.memory.mnemonic.validator import validate
    from zylch.memory.response_validation import complete_memory_text

    try:
        # MODEL_MEMORY_MERGE per-worker knob (empty → engine default). The
        # canary must exercise the SAME model the live merge gate uses.
        svc = merge_service or LLMMergeService(model=routed_model("MODEL_MEMORY_MERGE"))
        members = {
            "canary-person": _canary_memory("canary-person", _CANARY_EXISTING),
            "canary-company": _canary_memory("canary-company", _CANARY_NEW),
        }
        event = pair_event(_CANARY_OWNER, _CANARY_COMPANY, *members.values())
        candidates = pinned(event, members.get, list(members))
        with call_site("canary"):
            response = svc.client.create_message_sync(
                system=prompts.system_blocks(),
                messages=[{"role": "user", "content": prompts.user_message(event, candidates)}],
                max_tokens=MNEMONIC_MAX_TOKENS,
            )
        raw = complete_memory_text(response)
        proposal = adapt_response(response)
    except Exception as e:
        logger.warning(f"[merge-gate] self-check could not run: {e}")
        return {"healthy": None, "verdict": "error", "raw": str(e), "validator": ""}

    healthy = proposal.action != MERGE and not proposal.absorbs_another_memory
    try:
        judged = "accepted" if validate(event, proposal, candidates).ok else "refused"
    except Exception as e:  # noqa: BLE001 - the verdict stands; only the log detail is lost
        judged = f"unavailable ({e})"
    if healthy:
        logger.info(
            f"[merge-gate] self-check OK — the role answered {proposal.action} "
            "for two unrelated memories"
        )
    else:
        logger.error(
            "[merge-gate] BROKEN-OPEN: the role proposed to fold two unrelated "
            "memories together (action=%s, validator %s). Consolidation would "
            "fold strangers and ingestion would absorb new contacts; memory "
            "merging is being DISABLED to prevent corruption. raw=%r",
            proposal.action,
            judged,
            raw,
        )
    return {
        "healthy": healthy,
        "verdict": "refused" if healthy else "merged",
        "raw": raw,
        "validator": judged,
    }
