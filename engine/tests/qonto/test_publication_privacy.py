"""Publication outcome text stays outside durable company storage."""

import json
import pytest

from .test_publication import publishing as publishing_fixture, issue, confirm, records
from .test_reads import bank as bank_fixture

publishing = publishing_fixture
bank = bank_fixture


@pytest.mark.parametrize("kind", ["SKIP", "REVIEW", "CREATE", "UPDATE", "invalid", "expanded"])
def test_model_free_text_never_persists_even_temporarily_in_company_journal(publishing, kind):
    env, api, wire = publishing
    from tests.memory.join_env import file_bytes
    from zylch.memory.company_key import current_company_key

    private = "PRIVATE-NARRATIVE-REASON-DE89370400440532013000"
    preview = issue(env)
    payload = dict(action=kind if kind not in ("invalid", "expanded") else "CREATE", reason=private)
    if kind in ("CREATE", "UPDATE", "invalid", "expanded"):
        payload.update(entity_type="FACT", scope="company", content=preview["fact_text"])
    if kind == "UPDATE":
        payload["write_set"] = [dict(blob_id="unapproved", expected_version="v1")]
    if kind == "invalid":
        payload["action"] = private
    if kind == "expanded":
        payload["content"] += private
    for _ in range(3):
        wire.answer(json.dumps(payload))
    result = confirm(env, preview)
    assert result["result"]["status"] == "review_needed", result
    blobs, operations = records()
    assert blobs == [] and operations[0]["state"] == "review"
    assert operations[0]["result"]["reason"] == "Publication requires review."
    assert private not in json.dumps(operations)
    assert private.encode() not in file_bytes(current_company_key())


@pytest.mark.parametrize(
    "action,reason,status",
    [
        ("SKIP", "Minimal fact already recorded.", "skipped"),
        ("REVIEW", "Publication requires review.", "review_needed"),
    ],
)
def test_sanctioned_non_mutating_outcomes_use_only_engine_reason(
    publishing, action, reason, status
):
    env, api, wire = publishing
    preview = issue(env)
    wire.answer(json.dumps(dict(action=action, reason=reason)))
    assert confirm(env, preview)["result"]["status"] == status
    assert records()[0] == []
    assert records()[1][0]["result"]["reason"] == reason


def test_paid_target_candidate_contains_only_confirmed_projection(publishing):
    env, api, wire = publishing
    from zylch.memory.blob_storage import BlobStorage
    from zylch.memory.company_key import current_company_key
    from zylch.storage.database import get_session
    from tests.memory.mnemonic_env import BagOfWordsEmbedder
    from tests.memory import seeding
    from .conftest import UID

    secret = "PRIVATE-PRIOR-TARGET-BANKTEXT-948352 DE89370400440532013000 100.43"
    existing = seeding.store_blob(
        BlobStorage(get_session, BagOfWordsEmbedder()),
        UID,
        "facts:" + current_company_key(),
        "Category: finance\nKey: qonto\nValue: " + secret,
    )
    preview = issue(env)
    wire.answer(
        json.dumps(
            dict(
                action="UPDATE",
                entity_type="FACT",
                scope="company",
                content=preview["fact_text"],
                reason="Confirmed minimal company projection.",
                write_set=[
                    dict(
                        blob_id=existing["id"],
                        expected_version=existing["updated_at"],
                        role="target",
                    )
                ],
            )
        )
    )
    assert confirm(env, preview)["result"]["status"] == "committed"
    assert secret not in json.dumps(wire.calls)
    assert current_company_key() not in json.dumps(wire.calls)
    assert records()[0][0]["content"] == preview["fact_text"]


@pytest.mark.parametrize(
    "extra",
    [
        dict(entity_type="PERSON"),
        dict(scope="account"),
        dict(declared_effects=["delete:unapproved"]),
        dict(content="expanded nonmutating content"),
    ],
)
def test_non_mutating_proposals_cannot_expand_family_type_scope_or_effects(publishing, extra):
    env, api, wire = publishing
    preview = issue(env)
    wire.answer(json.dumps(dict(action="SKIP", reason="Minimal fact already recorded.", **extra)))
    assert confirm(env, preview)["result"]["status"] == "review_needed"
    assert records()[0] == []
    assert records()[1][0]["target_family"] is None
