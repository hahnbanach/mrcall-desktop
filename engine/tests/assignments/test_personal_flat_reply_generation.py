"""Personal MCP uses the production formatter and persists only outgoing content."""

import asyncio
import json
from base64 import b64decode

import pytest

from mail_fixture import ROOT
from test_mailbox_caller_journey import NativeMailbox, journey, parsed
from test_scheduled_reply_generation import paid_attempts, scheduled, text_block
from zylch.storage import database as db


BODY = "Thank you for the supplied details."
EXPLANATION = "Private explanation of why the supplied facts permit this draft."


@pytest.fixture(autouse=True)
def current_published_instructions(journey, scheduled, monkeypatch):
    from zylch.services import operator_instructions
    async def instructions(grant):
        documents = [{key: row[key] for key in ("path", "revision", "sha256")}
                     | {"text": b64decode(row["content_base64"]).decode()}
                     for row in operator_instructions.documents("alice@example.test")]
        return {"status": "available", "documents": documents, "missing_paths": []}
    monkeypatch.setattr(journey.effects.port, "instructions", instructions)


def prepare_person(journey):
    docs = asyncio.run(journey.effects.port.instructions(None))["documents"]
    versions = [{key: row[key] for key in ("path", "revision", "sha256")} for row in docs]
    return asyncio.run(journey.effects.prepare(
        "token", "personal-flat-request-0001", ROOT, journey.mail.root_id, versions,
        "Acknowledge the exact supplied details."))


@pytest.mark.parametrize("reason", ["", EXPLANATION])
def test_personal_mcp_discards_explanation_and_replays_one_draft(
        env, journey, scheduled, reason):
    decision = {"decision": "draft", "body": BODY, "reason": reason, "missing_facts": []}
    scheduled.payload["content"] = [text_block(decision)]
    first = prepare_person(journey)
    assert first["state"] == "completed", first
    assert first["current_draft"]["exists"] is True
    assert len(scheduled.calls) == NativeMailbox.creates == 1
    assert NativeMailbox.transmissions == NativeMailbox.updates == 0
    native = next(iter(NativeMailbox.drafts.values()))
    assert parsed(native["raw"]).get_content().strip() == BODY
    assert EXPLANATION.encode() not in native["raw"]
    with db.get_engine().connect() as conn:
        saved = conn.exec_driver_sql("SELECT result FROM operator_reply_operations").scalar_one()
        assert EXPLANATION not in saved
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM mailbox_operation_receipts").scalar_one() == 1
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM drafts").scalar_one() == 0
    assert EXPLANATION not in json.dumps(first)
    attempt = paid_attempts()
    assert attempt == [(first["reservation_ids"][0], True)]
    env.select("alice")
    again = prepare_person(journey)
    recovered = asyncio.run(journey.effects.recover(
        "token", request_key="personal-flat-request-0001"))
    for result in (again, recovered):
        assert result["operation_id"] == first["operation_id"]
        assert result["result"]["draft_id"] == first["result"]["draft_id"]
        assert result["current_draft"]["exists"] is True
    assert paid_attempts() == attempt
    assert len(scheduled.calls) == NativeMailbox.creates == 1
    assert NativeMailbox.transmissions == 0


@pytest.mark.parametrize("facts", [[], ["A required current condition is unavailable."]])
def test_personal_mcp_retains_real_review_without_mailbox_effects(
        env, journey, scheduled, facts):
    review = {"reason": "Published instructions require internal review.", "missing_facts": facts}
    scheduled.payload["content"] = [text_block({"decision": "needs_review", "body": "", **review})]
    first = prepare_person(journey)
    assert first["state"] == "needs_review" and first["review"] == review
    assert "draft_id" not in (first.get("result") or {})
    with db.get_engine().connect() as conn:
        assert json.loads(conn.exec_driver_sql("SELECT result FROM operator_reply_operations").scalar_one()) == review
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM mailbox_operation_receipts").scalar_one() == 0
    env.select("alice")
    again = prepare_person(journey)
    assert again == first
    assert len(scheduled.calls) == 1 and paid_attempts() == [(first["reservation_ids"][0], True)]
    assert NativeMailbox.creates == NativeMailbox.transmissions == NativeMailbox.updates == 0
    assert not NativeMailbox.drafts and not NativeMailbox.trash


@pytest.mark.parametrize("decision", [
    {"decision": "draft", "body": BODY, "reason": EXPLANATION, "missing_facts": ["Unresolved fact"]},
    {"decision": "needs_review", "body": "Must never be sent.", "reason": EXPLANATION, "missing_facts": []},
    {"reply": {"decision": "draft", "body": BODY}},
])
def test_personal_mcp_reopens_contradictory_output_without_recomposing(
        env, journey, scheduled, decision):
    scheduled.payload["content"] = [text_block(decision)]
    first = prepare_person(journey)
    assert first["state"] == "failed_before_dispatch"
    assert first["result"]["effect_certainty"] == "not-dispatched"
    env.select("alice")
    again = prepare_person(journey)
    recovered = asyncio.run(journey.effects.recover(
        "token", request_key="personal-flat-request-0001"))
    assert again == recovered == first
    assert len(scheduled.calls) == 1 and paid_attempts() == [(first["reservation_ids"][0], True)]
    with db.get_engine().connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM mailbox_operation_receipts").scalar_one() == 0
    assert NativeMailbox.creates == NativeMailbox.transmissions == NativeMailbox.updates == 0
    assert not NativeMailbox.drafts and not NativeMailbox.trash
