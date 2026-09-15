"""Tests for the channel-aware memory trainer (whatsapp-pipeline-parity Phase 2b).

These tests lock the contract of MESSAGE_AGENT_META_PROMPT — a regression
to email-only language would silently break cross-channel identity, since
the GENERATED extraction prompt would stop instructing the LLM to emit
`Phone:` lines for WhatsApp messages, which is the load-bearing signal
the Phase 1 person_identifiers index keys on.

The actual GENERATED prompt is produced by an LLM call to the meta-prompt
and varies; we only test the meta-prompt's structure here, not the
output of the live training run.
"""

from zylch.agents.trainers import (
    EmailMemoryAgentTrainer,
    MessageMemoryAgentTrainer,
)
from zylch.agents.trainers.memory_message import (
    EMAIL_AGENT_META_PROMPT,
    MESSAGE_AGENT_META_PROMPT,
)


# ---------------------------------------------------------------------
# Class / module backward-compat aliases
# ---------------------------------------------------------------------


def test_email_trainer_is_alias_for_message_trainer():
    """The legacy `EmailMemoryAgentTrainer` import path must keep working."""
    assert EmailMemoryAgentTrainer is MessageMemoryAgentTrainer


def test_meta_prompt_constants_are_same_object():
    """`EMAIL_AGENT_META_PROMPT` is preserved as alias for the new constant."""
    assert EMAIL_AGENT_META_PROMPT is MESSAGE_AGENT_META_PROMPT


def test_legacy_module_path_still_imports():
    """memory_email.py is a thin re-export for backward compat."""
    from zylch.agents.trainers import memory_email

    assert memory_email.MessageMemoryAgentTrainer is MessageMemoryAgentTrainer
    assert memory_email.EmailMemoryAgentTrainer is MessageMemoryAgentTrainer


def test_method_alias_keeps_old_name_callable():
    """`build_memory_email_prompt` aliases the new `build_memory_message_prompt`."""
    assert hasattr(MessageMemoryAgentTrainer, "build_memory_message_prompt")
    assert hasattr(MessageMemoryAgentTrainer, "build_memory_email_prompt")


# ---------------------------------------------------------------------
# Meta-prompt content — channel-awareness contract
# ---------------------------------------------------------------------


def test_meta_prompt_mentions_whatsapp_explicitly():
    """The meta-prompt must tell the LLM the generated prompt also runs
    on WhatsApp messages — not just emails."""
    assert "WhatsApp" in MESSAGE_AGENT_META_PROMPT


def test_meta_prompt_includes_cross_channel_identity_section():
    """Phase 2b CRITICAL invariant — Phone in #IDENTIFIERS must propagate
    to WhatsApp blobs, otherwise the Phase 1 cross-channel match fails."""
    assert "CROSS-CHANNEL IDENTITY" in MESSAGE_AGENT_META_PROMPT


def test_meta_prompt_instructs_to_emit_phone_in_identifiers():
    """The structured `#IDENTIFIERS` block must include a `Phone:` line."""
    text = MESSAGE_AGENT_META_PROMPT
    # Both the per-channel rule and the IDENTIFIERS template need it.
    assert "Phone:" in text
    # Phase 1 keys on email/phone/lid; the meta-prompt should mention all
    # three so the generated prompt knows which structured fields matter.
    for kind in ("Email:", "Phone:", "LID:"):
        assert kind in text, f"missing {kind!r} in meta-prompt"


def test_meta_prompt_describes_both_envelope_shapes():
    """The meta-prompt should specify the EMAIL and WHATSAPP envelope
    formats so the generated prompt knows how to parse the user message."""
    text = MESSAGE_AGENT_META_PROMPT
    assert "EMAIL envelope" in text
    assert "WHATSAPP envelope" in text


def test_meta_prompt_warns_against_format_placeholders():
    """The new prompt is sent as a cached system prompt; the LLM must NOT
    use Python format-string placeholders (`{from_email}` etc.). Old
    prompts with placeholders still work via the worker's compat path,
    but new training should not produce them."""
    text = MESSAGE_AGENT_META_PROMPT
    # The instruction at the bottom must explicitly forbid placeholders
    # so the generated prompt is system-cache compatible from day one.
    assert "Do NOT use Python `.format()` placeholders" in text


def test_meta_prompt_keeps_three_user_template_variables_for_meta_call():
    """The meta-prompt itself uses `.format()` with `user_profile` and
    `email_samples`. Removing these would break the trainer's own
    formatting step."""
    text = MESSAGE_AGENT_META_PROMPT
    assert "{user_profile}" in text
    assert "{email_samples}" in text


def test_trainer_fact_example_passes_real_extraction_parser():
    """The illustrative FACT must obey the same parser as real extraction."""
    from zylch.memory.response_validation import complete_memory_text
    from zylch.workers.memory import MemoryWorker, _entity_type
    from zylch.services.facts_store import parse_category, parse_key, parse_value
    from types import SimpleNamespace

    marker = '#IDENTIFIERS\nEntity type: FACT\n'
    example = marker + MESSAGE_AGENT_META_PROMPT.split(marker, 1)[1].split('```', 1)[0].strip()
    response = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text=example)])
    entities = MemoryWorker._parse_entities(None, complete_memory_text(response))
    assert len(entities) == 1
    assert _entity_type(entities[0]) == 'FACT'
    assert parse_category(entities[0]) == 'white-label'
    assert parse_key(entities[0]) == 'Minimum order quantity'
    assert parse_value(entities[0]) == '500 units; lead time 6 weeks'


def test_shared_suffix_has_no_fabricated_example_evidence_or_flat_fact_instruction():
    trainer = MessageMemoryAgentTrainer.__new__(MessageMemoryAgentTrainer)
    suffix = trainer._get_entity_format_suffix()
    assert 'Illustrative examples' in suffix
    assert 'never evidence' in suffix
    assert 'john@acme.com' not in suffix
    assert 'IT Consulting Offer' not in suffix
    assert '800 EUR/day' not in suffix
    assert 'no sections' not in suffix
    assert 'FLAT format' not in MESSAGE_AGENT_META_PROMPT
    assert '3 entity types' not in MESSAGE_AGENT_META_PROMPT
