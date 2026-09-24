"""Incident regressions: bounded comparisons, pending retries, nothing marked on failure.

The candidate-set cases are pure. The worker-path cases run the real worker on
the ingestion bench (``tests/workers/ingestion_env.py``): a real store, the real
clients with a scripted transport, a real admitted preparation run — because
what they hold is that a source is never marked processed unless the harness
settled it, and a mocked store cannot fail that assertion.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from zylch.llm.budget import BudgetError
from zylch.memory.blob_storage import BlobStorage
from zylch.services.preparation import preparation_run
from zylch.storage.database import get_session
from zylch.workers.memory import MemoryWorker, _parse_identifiers_block
from zylch.workers.memory_candidates import merge_shortlist

from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, BagOfWordsEmbedder, text_response
from tests.workers.ingestion_env import (
    LUCA,
    blobs,
    booted,
    create_decision,
    extraction,
    make_worker,
    run,
    scripted,
    seed_calendar,
    seed_email,
    seed_mrcall,
    seed_whatsapp,
)


def entity(email, phone=""):
    return f"#IDENTIFIERS\nEntity type: PERSON\nName: Example\nEmail: {email}\nPhone: {phone}\n#ABOUT\nContext"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


def processed(model, source_id) -> bool:
    with get_session() as session:
        return session.get(model, source_id).memory_processed_at is not None


CHANNELS = {
    "email": ("process_email", seed_email, "zylch.storage.models.Email"),
    "whatsapp": ("process_whatsapp_message", seed_whatsapp, "zylch.storage.models.WhatsAppMessage"),
    "calendar": ("process_calendar_event", seed_calendar, "zylch.storage.models.CalendarEvent"),
    "mrcall": ("process_mrcall_conversation", seed_mrcall, "zylch.storage.models.MrcallConversation"),
}


def model_of(path: str):
    module, name = path.rsplit(".", 1)
    return getattr(__import__(module, fromlist=[name]), name)


# ─── The candidate set stays bounded and corroborated ─────────────────


def test_polluted_index_does_not_create_paid_candidates():
    blobs_ = {str(i): {"content": entity(f"unrelated{i}@example.com")} for i in range(300)}
    blobs_["correct"] = {"content": entity("person@example.com")}
    candidates = merge_shortlist(
        [("email", "person@example.com")], list(blobs_), [], blobs_.get, _parse_identifiers_block
    )
    assert [c["blob_id"] for c in candidates] == ["correct"]


def test_all_sources_share_limit_and_multiple_identifiers_rank_first():
    blobs_ = {str(i): {"content": entity("shared@example.com")} for i in range(300)}
    blobs_["best"] = {"content": entity("shared@example.com", "+393331234567")}
    cosine = [SimpleNamespace(blob_id=str(i), hybrid_score=0.9 - i / 100) for i in range(3)]
    candidates = merge_shortlist(
        [("email", "shared@example.com"), ("phone", "+393331234567")],
        list(reversed(blobs_)),
        cosine,
        blobs_.get,
        _parse_identifiers_block,
    )
    assert [c["blob_id"] for c in candidates] == ["best", "0", "1"]


# ─── Nothing is marked unless the harness settled the source ──────────


@pytest.mark.parametrize("channel", list(CHANNELS))
def test_provider_failure_never_marks_processed(profile, channel):
    method, seeder, model = CHANNELS[channel]
    item = seeder()
    worker = make_worker([RuntimeError("credit balance is too low")], [])
    assert run(worker, method, item) is False
    assert not processed(model_of(model), item["id"])
    assert blobs() == {}


def test_valid_semantic_skip_marks_email_processed(profile):
    mail = seed_email()
    worker = make_worker(["SKIP"], [])
    assert run(worker, "process_email", mail) is True
    assert processed(model_of(CHANNELS["email"][2]), "mail-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["email", "whatsapp"])
async def test_budget_stops_queued_batch_and_propagates(channel):
    w = MemoryWorker.__new__(MemoryWorker)
    w.owner_id = "owner"
    method = "process_email" if channel == "email" else "process_whatsapp_message"
    setattr(w, method, AsyncMock(side_effect=BudgetError("budget unavailable")))
    batch = w.process_batch if channel == "email" else w.process_whatsapp_batch
    with pytest.raises(BudgetError):
        await batch([{"id": str(i)} for i in range(1000)], concurrency=1)
    assert getattr(w, method).call_count == 1


def test_credit_errors_stop_after_three_without_checkpoint(profile):
    mails = [seed_email(f"mail-{i}") for i in range(1000)]
    worker = make_worker([RuntimeError("credit balance is too low")] * 3, [])
    with preparation_run(OWNER_A):
        assert asyncio.run(worker.process_batch(mails, concurrency=1)) == 0
    assert worker.client._client.messages.create.call_count == 3
    assert not any(processed(model_of(CHANNELS["email"][2]), m["id"]) for m in mails[:3])


@pytest.mark.parametrize(
    "output",
    [
        "",
        "I cannot analyze this message",
        "#IDENTIFIERS\nEmail: a@example.com\n---ENTITY---\nInvalid second entity",
    ],
)
def test_invalid_extraction_does_not_silently_complete(profile, output):
    mail = seed_email()
    worker = make_worker([output], [])
    assert run(worker, "process_email", mail) is False
    assert not processed(model_of(CHANNELS["email"][2]), "mail-1")


@pytest.mark.parametrize("channel", list(CHANNELS))
def test_truncated_valid_identity_never_writes_or_completes(profile, channel):
    method, seeder, model = CHANNELS[channel]
    item = seeder()
    worker = make_worker([text_response(entity("person@example.com"), "max_tokens")], [])
    assert run(worker, method, item) is False
    assert not processed(model_of(model), item["id"])
    assert blobs() == {}


def test_a_truncated_decision_never_writes_or_marks_the_source(profile):
    """The old merge could be cut off mid-blob; now the role's decision can be.
    A truncated decision is no proposal at all, and after the bounded rounds
    the source is in review: the existing memory untouched, nothing marked."""
    existing = BlobStorage(get_session, profile.embedder).store_blob(OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    mail = seed_email()
    worker = make_worker(
        [extraction(LUCA)],
        [text_response(create_decision(LUCA, "PERSON"), "max_tokens")] * 3,
    )
    assert run(worker, "process_email", mail) is False
    assert blobs() == {existing["id"]: LUCA}
    assert not processed(model_of(CHANNELS["email"][2]), "mail-1")


@pytest.mark.parametrize("reason", ["max_tokens", "tool_use", "stop_sequence", None])
def test_unfinished_or_unexpected_response_rejected(reason):
    from zylch.memory.response_validation import MemoryResponseError, complete_memory_text

    with pytest.raises(MemoryResponseError):
        complete_memory_text(
            SimpleNamespace(stop_reason=reason, content=[SimpleNamespace(type="text", text="SKIP")])
        )


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("stop_reason", ["end_turn", "max_tokens"])
def test_email_capacity_keeps_complete_entities_and_rejects_truncation(profile, legacy, stop_reason):
    mail = seed_email(body="Message")
    # More output tokens than the historical 1024 ceiling, within the extraction
    # bound and within the harness's per-entity bound (MAX_CONTENT_CHARS).
    output = entity("person@example.com") + "\n" + "Documented detail. " * 300
    worker = make_worker([text_response(output, stop_reason)], [create_decision(output, "PERSON")])
    if legacy:
        worker._custom_prompt = "Extract the email: {body}"
    ok = run(worker, "process_email", mail)
    kwargs = worker.client._client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 4096
    # The modern path sends the trained prompt as a cached system block and the
    # mail as the user turn; the legacy path interpolates the mail into the
    # prompt and sends it as the user turn, with no cached block.
    cached = [b for b in kwargs["system"] if isinstance(b, dict) and b.get("cache_control")]
    user_turn = kwargs["messages"][0]["content"]
    if legacy:
        assert cached == []
        assert user_turn.startswith("Extract the email: ")
    else:
        assert len(cached) == 1 and cached[0]["text"].startswith(worker._custom_prompt)
        assert user_turn.startswith("Analyze this email:")
    if stop_reason == "end_turn":
        assert ok is True
        assert processed(model_of(CHANNELS["email"][2]), "mail-1")
        assert len(blobs()) == 1
    else:
        assert ok is False
        assert not processed(model_of(CHANNELS["email"][2]), "mail-1")
        assert blobs() == {}


def test_saved_flat_fact_prompt_gets_format_contract_without_retraining(monkeypatch):
    from zylch.memory.extraction_format import SERIALIZATION_CONTRACT
    from zylch.services.facts_store import parse_category, parse_key, parse_value

    w = MemoryWorker.__new__(MemoryWorker)
    w.owner_id = "owner"
    w.storage = MagicMock()
    original = "Only extract supported facts. Skip internal contacts. FACT: Category/Key/Value"
    w.storage.get_agent_prompt.return_value = original
    w._custom_prompt_loaded = False
    monkeypatch.setattr("zylch.workers.memory._shared_self_notion", lambda: "Our company")
    prompt = w._get_extraction_prompt()
    assert prompt.startswith(original)
    assert "DO NOT extract its people as external contacts" in prompt
    assert prompt.endswith(SERIALIZATION_CONTRACT)
    assert w._get_extraction_prompt() == prompt
    w.storage.set_agent_prompt.assert_not_called()
    fact = "#IDENTIFIERS\nEntity type: FACT\nCategory: pricing\nKey: sample\n#ABOUT\nValue: EUR 12\n#HISTORY\nSource: email"
    assert w._parse_entities(fact) == [fact]
    assert (parse_category(fact), parse_key(fact), parse_value(fact)) == ("pricing", "sample", "EUR 12")
