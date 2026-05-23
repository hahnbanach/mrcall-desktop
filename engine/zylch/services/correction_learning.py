"""Learn durable rules from the user's corrections to drafted messages.

When the user edits an approval-gated send (e.g. deletes "we'll happily
call you back" from a drafted reply), the diff between what the model
proposed and what the user actually sent is a supervision signal. A cheap
LLM judges whether the edit reflects a DURABLE policy worth remembering —
as opposed to a one-off, contact-specific tweak, a typo fix, or a personal
detail — and, if so, writes it to the always-on `prefs:` store with a
`Why:` provenance line so it can be audited and, if wrong, deleted.

No regex / hardcoded classification: the model decides what is durable.
See memory/feedback_no_hardcoded_rules.md for the principle.

This runs AFTER the message has already been sent, so it never blocks the
user. Failures are swallowed — a missed rule is cheaper than a crash in
the send path.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Approval-gated tools whose payload is a human-authored message. Only
# these carry a meaningful "policy" diff; editing a run_python arg or a
# memory blob is not a writing-style/policy correction.
_MESSAGE_TOOLS = {"send_email", "send_whatsapp", "send_sms"}

# Fields, per tool, that hold the message text the user may have edited.
_TEXT_FIELDS = ("body", "message", "text")

_JUDGE_MODEL = "claude-haiku-4-5-20251001"

_RECORD_RULE_TOOL = {
    "name": "record_rule",
    "description": (
        "Record your judgment about whether the user's edit reveals a "
        "durable policy worth remembering for all future messages."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_durable_rule": {
                "type": "boolean",
                "description": (
                    "True only if the edit reflects a general policy that "
                    "should apply to FUTURE messages too (e.g. removing an "
                    "offer to phone customers because the business never "
                    "phones for support). False for one-off, recipient-"
                    "specific tweaks, typo/grammar fixes, added personal "
                    "details, or anything already covered by an existing "
                    "rule below."
                ),
            },
            "rule": {
                "type": "string",
                "description": (
                    "If durable: a single imperative sentence stating the "
                    "policy, phrased positively where possible (prefer "
                    "'For support, direct customers to email' over 'do not "
                    "offer calls'). Empty otherwise."
                ),
            },
            "why": {
                "type": "string",
                "description": (
                    "If durable: one short clause explaining what edit "
                    "this was inferred from. Empty otherwise."
                ),
            },
        },
        "required": ["is_durable_rule", "rule", "why"],
    },
}

_JUDGE_SYSTEM = (
    "You maintain a small set of operating rules for an assistant that "
    "drafts business messages on behalf of a user. You are shown what the "
    "assistant DRAFTED and what the user actually SENT after editing. Your "
    "job is to decide whether the user's change reveals a DURABLE policy "
    "worth applying to every future message, and to avoid duplicating "
    "rules that already exist. Be conservative: only record a rule when the "
    "edit clearly generalises. Recording a wrong rule is worse than "
    "missing one."
)

# A SECOND, independent judgment on the same diff: did the user correct a
# concrete BUSINESS VALUE (a price, rate, lead time, minimum order,
# opening hours, deliverable) that future offers of the same kind should
# reuse? This is distinct from a policy rule — it updates the structured
# facts store, not the always-on rules. Kept separate so a tone edit and
# a price edit on the same message can both be captured.
_RECORD_FACT_TOOL = {
    "name": "record_fact",
    "description": (
        "Record whether the user's edit corrected a concrete, reusable "
        "business value that future offers/replies should use."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_fact_change": {
                "type": "boolean",
                "description": (
                    "True ONLY if the edit changed a STANDARD business value "
                    "(price, rate, lead time, minimum order, hours, "
                    "deliverable) that should be reused in FUTURE offers of "
                    "the same kind. False for a discount or figure specific to "
                    "this one recipient, for typo/grammar fixes, for tone "
                    "changes, or when no concrete value changed."
                ),
            },
            "category": {
                "type": "string",
                "description": (
                    "The kind of offer/topic the value belongs to. Reuse an "
                    "existing category name from the list when one fits; keep "
                    "names stable (e.g. 'white-label'). Empty if not a fact "
                    "change."
                ),
            },
            "key": {
                "type": "string",
                "description": (
                    "A short stable name for the value (e.g. 'Day rate', "
                    "'Minimum order quantity'). Empty if not a fact change."
                ),
            },
            "value": {
                "type": "string",
                "description": (
                    "The corrected value WITH units (e.g. '800 EUR/day'). "
                    "Empty if not a fact change."
                ),
            },
        },
        "required": ["is_fact_change", "category", "key", "value"],
    },
}

_FACT_JUDGE_SYSTEM = (
    "You maintain a store of an organisation's standard business facts "
    "(prices, rates, lead times, minimum orders, hours, deliverables), "
    "grouped by category. You are shown what an assistant DRAFTED and what "
    "the user actually SENT after editing. Decide whether the user's edit "
    "corrected a STANDARD value worth reusing in future offers of the same "
    "kind. Be conservative: a one-off discount for a single customer is NOT "
    "a standard fact. Reuse an existing category when one fits. Recording a "
    "wrong fact is worse than missing one."
)


def _message_text(tool_input: Dict[str, Any]) -> str:
    for field in _TEXT_FIELDS:
        val = tool_input.get(field)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _existing_rules(owner_id: str) -> List[str]:
    """Return existing rule blob contents for `prefs:<owner_id>`."""
    try:
        from zylch.services.solve_constants import _get_learned_preferences

        joined = _get_learned_preferences(owner_id)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[learn] cannot read existing rules: {e}")
        return []
    return [chunk.strip() for chunk in joined.split("\n\n") if chunk.strip()]


def _build_judge_prompt(
    proposed: str,
    edited: str,
    existing_rules: List[str],
) -> str:
    rules_text = "\n".join(f"- {r}" for r in existing_rules) or "(none yet)"
    return (
        "EXISTING RULES:\n"
        f"{rules_text}\n\n"
        "ASSISTANT DRAFTED:\n"
        f"{proposed}\n\n"
        "USER ACTUALLY SENT:\n"
        f"{edited}\n\n"
        "Call record_rule with your judgment."
    )


def extract_rule(
    proposed: str,
    edited: str,
    existing_rules: List[str],
    client,
) -> Optional[str]:
    """Ask the LLM whether the diff yields a durable rule.

    Returns the formatted blob content ("<rule>\\nWhy: <why>") or None.
    """
    if not proposed.strip() or not edited.strip() or proposed.strip() == edited.strip():
        return None
    prompt = _build_judge_prompt(proposed, edited, existing_rules)
    try:
        response = client.create_message_sync(
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[_RECORD_RULE_TOOL],
            tool_choice={"type": "tool", "name": "record_rule"},
            max_tokens=300,
        )
    except Exception as e:
        logger.warning(f"[learn] judge call failed: {e}")
        return None

    for block in getattr(response, "content", []) or []:
        data = getattr(block, "input", None)
        if not isinstance(data, dict):
            continue
        if not data.get("is_durable_rule"):
            return None
        rule = (data.get("rule") or "").strip()
        if not rule:
            return None
        why = (data.get("why") or "").strip()
        return f"{rule}\nWhy: {why}" if why else rule
    return None


def _existing_fact_categories(owner_id: str) -> List[str]:
    """Return the user's current fact category names (for reuse)."""
    try:
        from zylch.services.facts_store import list_categories

        return [c["category"] for c in list_categories(owner_id)]
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[learn] cannot read fact categories: {e}")
        return []


def _build_fact_judge_prompt(
    proposed: str,
    edited: str,
    existing_categories: List[str],
) -> str:
    cats_text = ", ".join(existing_categories) or "(none yet)"
    return (
        "EXISTING CATEGORIES:\n"
        f"{cats_text}\n\n"
        "ASSISTANT DRAFTED:\n"
        f"{proposed}\n\n"
        "USER ACTUALLY SENT:\n"
        f"{edited}\n\n"
        "Call record_fact with your judgment."
    )


def extract_fact(
    proposed: str,
    edited: str,
    existing_categories: List[str],
    client,
) -> Optional[tuple]:
    """Ask the LLM whether the diff corrected a standard business value.

    Returns (category, key, value) or None.
    """
    if not proposed.strip() or not edited.strip() or proposed.strip() == edited.strip():
        return None
    prompt = _build_fact_judge_prompt(proposed, edited, existing_categories)
    try:
        response = client.create_message_sync(
            system=_FACT_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[_RECORD_FACT_TOOL],
            tool_choice={"type": "tool", "name": "record_fact"},
            max_tokens=300,
        )
    except Exception as e:
        logger.warning(f"[learn] fact judge call failed: {e}")
        return None

    for block in getattr(response, "content", []) or []:
        data = getattr(block, "input", None)
        if not isinstance(data, dict):
            continue
        if not data.get("is_fact_change"):
            return None
        category = (data.get("category") or "").strip()
        key = (data.get("key") or "").strip()
        value = (data.get("value") or "").strip()
        if not (category and key and value):
            return None
        return (category, key, value)
    return None


def _write_rule(owner_id: str, content: str) -> Optional[str]:
    try:
        from zylch.memory import EmbeddingEngine, MemoryConfig
        from zylch.memory.blob_storage import BlobStorage
        from zylch.storage.database import get_session

        blob_store = BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))
        blob = blob_store.store_blob(
            owner_id=owner_id,
            namespace=f"prefs:{owner_id}",
            content=content,
            event_description="Learned from a message correction",
        )
        blob_id = str(blob["id"])
        logger.debug(f"[learn] wrote rule blob_id={blob_id}: {content!r}")
        return blob_id
    except Exception as e:
        logger.warning(f"[learn] failed to write rule: {e}")
        return None


def learn_from_corrections(
    corrections: List[Dict[str, Any]],
    owner_id: str,
    client=None,
) -> List[str]:
    """Turn captured (proposed, edited) diffs into durable knowledge.

    Each diff is judged twice, independently: as a possible DURABLE RULE
    (tone/policy -> `prefs:`) and as a possible BUSINESS FACT correction
    (price/term -> `facts:`). A single edit can yield a rule, a fact,
    both, or neither.

    Returns the blob_ids written (rules + facts). Safe to call with an
    empty list. Never raises.
    """
    if not corrections or not owner_id:
        return []

    if client is None:
        try:
            from zylch.llm import try_make_llm_client

            client = try_make_llm_client(model=_JUDGE_MODEL)
        except Exception as e:
            logger.warning(f"[learn] cannot make judge client: {e}")
            client = None
    if client is None:
        logger.debug("[learn] no LLM client available; skipping")
        return []

    existing = _existing_rules(owner_id)
    existing_cats = _existing_fact_categories(owner_id)
    created: List[str] = []
    n_rules = 0
    n_facts = 0
    for corr in corrections:
        if corr.get("tool_name") not in _MESSAGE_TOOLS:
            continue
        proposed = _message_text(corr.get("proposed") or {})
        edited = _message_text(corr.get("edited") or {})

        # Path 1: durable rule (tone / policy).
        content = extract_rule(proposed, edited, existing, client)
        if content:
            blob_id = _write_rule(owner_id, content)
            if blob_id:
                created.append(blob_id)
                n_rules += 1
                # Feed the new rule back in so a second correction in the
                # same batch doesn't create a near-duplicate.
                existing.append(content)

        # Path 2: corrected business fact (price / term).
        fact = extract_fact(proposed, edited, existing_cats, client)
        if fact:
            category, key, value = fact
            from zylch.services.facts_store import upsert_fact

            blob_id = upsert_fact(
                owner_id,
                category,
                key,
                value,
                event_description="Learned from a message correction",
            )
            if blob_id:
                created.append(blob_id)
                n_facts += 1
                if category not in existing_cats:
                    existing_cats.append(category)
    if created:
        logger.info(f"[learn] wrote {n_rules} rule(s) and {n_facts} fact(s) from corrections")
    return created
