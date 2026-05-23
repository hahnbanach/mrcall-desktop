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
    """Turn captured (proposed, edited) diffs into durable rule blobs.

    Returns the blob_ids of rules created. Safe to call with an empty
    list. Never raises.
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
    created: List[str] = []
    for corr in corrections:
        if corr.get("tool_name") not in _MESSAGE_TOOLS:
            continue
        proposed = _message_text(corr.get("proposed") or {})
        edited = _message_text(corr.get("edited") or {})
        content = extract_rule(proposed, edited, existing, client)
        if not content:
            continue
        blob_id = _write_rule(owner_id, content)
        if blob_id:
            created.append(blob_id)
            # Feed the new rule back in so a second correction in the
            # same batch doesn't create a near-duplicate.
            existing.append(content)
    if created:
        logger.info(f"[learn] created {len(created)} rule(s) from corrections")
    return created
