"""Regression test for email extraction prompt routing.

Bug (2026-06): MemoryWorker._extract_entities decided "does the trained
prompt have {placeholder} tokens?" by calling ``prompt_template.format(...)``
and treating "no exception" as "yes". But a prompt with NO placeholders
ALSO formats without error, so a modern cached-system prompt took the
legacy inline branch and was sent as a bare user message with the email
body NEVER interpolated. The model then saw only the instructions + its
few-shot examples, answered "no message content was included", and echoed
the example entity — which is how the bogus "John Doe / IT Consulting"
PERSON and ~440 duplicate TEMPLATE blobs were produced on support@ from
mail it never actually read.

These assert the email body reaches the model on BOTH prompt styles, with
no live LLM.
"""
from unittest.mock import MagicMock

from zylch.workers.memory import MemoryWorker


def _worker_with_prompt(prompt_text, returns="SKIP"):
    """A MemoryWorker with just enough wired up to drive _extract_entities."""
    w = MemoryWorker.__new__(MemoryWorker)
    w._custom_prompt = prompt_text
    w._custom_prompt_loaded = True
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.content = [MagicMock(text=returns)]
        return resp

    w.client = MagicMock()
    w.client.create_message_sync.side_effect = fake_create
    return w, captured


_EMAIL = {
    "from_email": "eva@fanimotors.it",
    "to_email": ["support@mrcall.ai"],
    "subject": "CREDITI MR CALL",
    "date": "2026-06-01",
    "body_plain": "Buongiorno, vorrei sapere come ricaricare i crediti del mio MrCall.",
}


def test_cached_system_prompt_sends_email_body_in_user_message():
    # A modern prompt with NO {placeholder} tokens must take the
    # cached-system path: instructions in the system block, the real email
    # (body included) in the user message.
    prompt = "You extract entities. Output #IDENTIFIERS/#ABOUT/#HISTORY. No placeholders here."
    w, captured = _worker_with_prompt(prompt)

    w._extract_entities(_EMAIL, _EMAIL["from_email"])

    assert captured.get("system"), "no-placeholder prompt must use the cached system block"
    assert captured["system"][0]["text"] == prompt
    user = captured["messages"][0]["content"]
    assert "ricaricare i crediti" in user, "the email BODY never reached the model"
    assert "eva@fanimotors.it" in user


def test_legacy_placeholder_prompt_interpolates_body_inline():
    # A legacy prompt WITH {body} must interpolate inline and send no system
    # block — the body still has to reach the model.
    prompt = "Analyze:\nFrom: {from_email}\nSubject: {subject}\n\n{body}"
    w, captured = _worker_with_prompt(prompt)

    w._extract_entities(_EMAIL, _EMAIL["from_email"])

    assert not captured.get("system"), "legacy inline prompt must not use a system block"
    user = captured["messages"][0]["content"]
    assert "ricaricare i crediti" in user, "the email BODY never reached the model"
    assert "eva@fanimotors.it" in user
