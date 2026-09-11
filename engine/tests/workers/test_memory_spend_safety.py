"""Incident regressions: sender provenance, bounded comparisons, pending retries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from zylch.llm.budget import BudgetError
from zylch.workers.memory import MemoryWorker, _parse_identifiers_block
from zylch.workers.memory_candidates import merge_shortlist


def entity(email, phone=""):
    return f"#IDENTIFIERS\nEntity type: PERSON\nName: Example\nEmail: {email}\nPhone: {phone}\n#ABOUT\nContext"


def worker():
    w = MemoryWorker.__new__(MemoryWorker)
    w.owner_id = "owner"
    w.namespace = "user:company"
    w.storage = MagicMock()
    w.blob_storage = MagicMock()
    w.blob_storage.store_blob.return_value = {"id": "new"}
    w.hybrid_search = MagicMock()
    w.hybrid_search.search.return_value = []
    w.hybrid_search.find_candidates_for_reconsolidation.return_value = []
    w.storage.find_blobs_by_identifiers.return_value = []
    w.merge_enabled = True
    w.llm_merge = MagicMock()
    w.client = MagicMock()
    w._get_extraction_prompt = MagicMock(
        return_value="Extract entity identities. Output SKIP if none."
    )
    w._get_mrcall_extraction_prompt = MagicMock(
        return_value="Extract identities from {conversation}"
    )
    return w


def test_polluted_index_does_not_create_paid_candidates():
    blobs = {str(i): {"content": entity(f"unrelated{i}@example.com")} for i in range(300)}
    blobs["correct"] = {"content": entity("person@example.com")}
    candidates = merge_shortlist(
        [("email", "person@example.com")], list(blobs), [], blobs.get, _parse_identifiers_block
    )
    assert [c["blob_id"] for c in candidates] == ["correct"]


def test_all_sources_share_limit_and_multiple_identifiers_rank_first():
    blobs = {str(i): {"content": entity("shared@example.com")} for i in range(300)}
    blobs["best"] = {"content": entity("shared@example.com", "+393331234567")}
    cosine = [SimpleNamespace(blob_id=str(i), hybrid_score=0.9 - i / 100) for i in range(3)]
    candidates = merge_shortlist(
        [("email", "shared@example.com"), ("phone", "+393331234567")],
        list(reversed(blobs)),
        cosine,
        blobs.get,
        _parse_identifiers_block,
    )
    assert [c["blob_id"] for c in candidates] == ["best", "0", "1"]


@pytest.mark.asyncio
async def test_sender_is_not_injected_into_another_entity():
    w = worker()
    await w._upsert_entity(
        entity("person@example.com"), "event", "mail", 1, 1, contact_identifier="sender@example.com"
    )
    assert w.storage.find_blobs_by_identifiers.call_args.kwargs["identifiers"] == [
        ("email", "person@example.com")
    ]
    assert w.storage.add_person_identifiers.call_args.kwargs["identifiers"] == [
        ("email", "person@example.com")
    ]


@pytest.mark.asyncio
async def test_merge_model_still_decides_shortlist_and_refuses_all():
    w = worker()
    ids = list(map(str, range(200)))
    w.storage.find_blobs_by_identifiers.return_value = ids
    w.blob_storage.get_blob.side_effect = lambda bid, owner: {
        "content": entity("shared@example.com")
    }
    w.llm_merge.merge.return_value = "INSERT"
    await w._upsert_entity(entity("shared@example.com"), "event", "mail", 1, 1)
    assert w.llm_merge.merge.call_count == 3
    w.blob_storage.store_blob.assert_called_once()
    w.blob_storage.update_blob.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["email", "whatsapp", "calendar", "mrcall"])
async def test_provider_failure_never_marks_processed(channel, monkeypatch):
    monkeypatch.setattr("zylch.storage.database.memory_unavailable_reason", lambda: None)
    w = worker()
    w.client.create_message_sync.side_effect = RuntimeError("credit balance is too low")
    methods = {
        "email": (
            w.process_email,
            {"id": "mail", "from_email": "sender@example.com"},
            "mark_email_processed",
        ),
        "whatsapp": (
            w.process_whatsapp_message,
            {
                "id": "wa",
                "text": "A business message long enough to extract",
                "sender_jid": "123@s.whatsapp.net",
            },
            "mark_whatsapp_memory_processed",
        ),
        "calendar": (w.process_calendar_event, {"id": "cal"}, "mark_calendar_event_processed"),
        "mrcall": (
            w.process_mrcall_conversation,
            {"id": "call", "body": "A business conversation"},
            "mark_mrcall_memory_processed",
        ),
    }
    method, item, mark = methods[channel]
    assert await method(item) is False
    getattr(w.storage, mark).assert_not_called()


@pytest.mark.asyncio
async def test_valid_semantic_skip_marks_email_processed(monkeypatch):
    monkeypatch.setattr("zylch.storage.database.memory_unavailable_reason", lambda: None)
    w = worker()
    w.client.create_message_sync.return_value = SimpleNamespace(
        content=[SimpleNamespace(text="SKIP")]
    )
    assert await w.process_email({"id": "mail", "from_email": "sender@example.com"}) is True
    w.storage.mark_email_processed.assert_called_once_with("owner", "mail")


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["email", "whatsapp"])
async def test_budget_stops_queued_batch_and_propagates(channel):
    w = worker()
    method = "process_email" if channel == "email" else "process_whatsapp_message"
    setattr(w, method, AsyncMock(side_effect=BudgetError("budget unavailable")))
    batch = w.process_batch if channel == "email" else w.process_whatsapp_batch
    with pytest.raises(BudgetError):
        await batch([{"id": str(i)} for i in range(1000)], concurrency=1)
    assert getattr(w, method).call_count == 1


@pytest.mark.asyncio
async def test_credit_errors_stop_after_three_without_checkpoint(monkeypatch):
    monkeypatch.setattr("zylch.storage.database.memory_unavailable_reason", lambda: None)
    w = worker()
    w.client.create_message_sync.side_effect = RuntimeError("credit balance is too low")
    assert (
        await w.process_batch(
            [{"id": str(i), "from_email": "sender@example.com"} for i in range(1000)], concurrency=1
        )
        == 0
    )
    assert w.client.create_message_sync.call_count == 3
    w.storage.mark_email_processed.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        "",
        "I cannot analyze this message",
        "#IDENTIFIERS\nEmail: a@example.com\n---ENTITY---\nInvalid second entity",
    ],
)
async def test_invalid_extraction_does_not_silently_complete(output, monkeypatch):
    monkeypatch.setattr("zylch.storage.database.memory_unavailable_reason", lambda: None)
    w = worker()
    w.client.create_message_sync.return_value = SimpleNamespace(
        content=[SimpleNamespace(text=output)]
    )
    assert await w.process_email({"id": "mail", "from_email": "sender@example.com"}) is False
    w.storage.mark_email_processed.assert_not_called()


@pytest.mark.asyncio
async def test_name_only_entity_does_not_inherit_sender_identity():
    w = worker()
    await w._upsert_entity(
        "#IDENTIFIERS\nEntity type: COMPANY\nName: Example Ltd\n#ABOUT\nContext",
        "event",
        "mail",
        1,
        1,
        contact_identifier="sender@example.com",
    )
    w.storage.find_blobs_by_identifiers.assert_not_called()
    w.storage.add_person_identifiers.assert_not_called()
    w.blob_storage.store_blob.assert_called_once()
