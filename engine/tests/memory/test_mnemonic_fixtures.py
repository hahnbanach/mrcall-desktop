"""Milestone 0 semantic corpus and current SQLite behavior fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.company_key import (
    current_company_key,
    entity_namespace,
    facts_namespace,
    rule_namespaces,
)
from zylch.memory.store import memory_db_path
from zylch.services.facts_store import get_facts_by_category
from zylch.storage.database import get_session
from zylch.storage.models import Email
from zylch.storage.storage import Storage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mnemonic"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_incident_corpus_is_bounded_and_preserves_original_observations():
    corpus = _load("incidents.json")
    cases = corpus["cases"]
    expected_ids = {
        "unrelated_same_name_people",
        "shared_switchboard",
        "corroborated_same_person",
        "customer_forwarding_number_correction",
        "customer_price_correction",
        "global_opening_hours",
        "account_feedback",
        "planned_not_completed",
        "contradictory_legacy_fact_rule",
        "malformed_output",
        "multi_entity_source",
    }

    assert corpus["schema_version"] == 1
    assert {case["id"] for case in cases} == expected_ids
    assert len(cases) == len(expected_ids)
    for case in cases:
        assert case["original_observation"].strip()
        assert case["caller_class"] in {
            "automatic_observation",
            "verified_human_correction",
        }
        assert case["expected"]
        assert len(case.get("candidates", [])) <= 3

    multi = next(case for case in cases if case["id"] == "multi_entity_source")
    children = multi["expected"]["children"]
    assert len(children) == 2
    assert len({child["stable_key"] for child in children}) == len(children)


def test_current_visibility_and_legacy_fact_exposure_use_real_company_store(company_db, embedder):
    fixture = _load("current_behavior.json")
    owner_a, owner_b = fixture["owners"]
    key = current_company_key()
    namespaces = {
        "user": entity_namespace(key),
        "facts": facts_namespace(key),
        "template": rule_namespaces(owner_a)[0],
    }
    store = BlobStorage(get_session, embedder)
    ids: dict[str, str] = {}

    for row in fixture["blobs"]:
        saved = store.store_blob(
            row["owner"],
            namespaces[row["family"]],
            row["content"],
            "mnemonic M0 fixture",
        )
        ids[row["fixture_id"]] = saved["id"]

    for owner in (owner_a, owner_b):
        visible = {blob["id"] for blob in store.list_blobs(owner, limit=50)}
        expected = {
            ids[row["fixture_id"]] for row in fixture["blobs"] if owner in row["visible_to"]
        }
        assert visible == expected

    # This deliberately freezes the pre-M5 behavior: a known customer-shaped
    # FACT is still returned by ordinary category reads.  M5 must change this
    # expectation only when it adds the shared eligibility predicate.
    facts = get_facts_by_category(owner_b, "pricing")
    assert [fact["blob_id"] for fact in facts] == [ids["legacy-customer-fact"]]
    assert "Acme pays 74 euro" in facts[0]["content"]

    profile_path = Path(company_db)
    assert profile_path.is_file()
    company_path = Path(memory_db_path(key))
    assert company_path.is_file()
    assert company_path != profile_path


def test_current_email_checkpoint_is_owner_scoped_and_source_grained(company_db):
    fixture = _load("current_behavior.json")["checkpoint"]
    source_id = fixture["source_id"]
    owner = fixture["owner"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with get_session() as session:
        session.add(
            Email(
                id=source_id,
                owner_id=owner,
                gmail_id=source_id,
                thread_id="thread-multi-entity-1",
                from_email="marta@acme.example",
                subject="Two updates",
                body_plain="Marta joined Acme; Acme plans a forwarding change.",
                date=now,
            )
        )

    storage = Storage.__new__(Storage)
    assert [row["id"] for row in storage.get_unprocessed_emails(owner)] == [source_id]

    storage.mark_email_processed("owner-b", source_id)
    assert [row["id"] for row in storage.get_unprocessed_emails(owner)] == [source_id]

    storage.mark_email_processed(owner, source_id)
    assert storage.get_unprocessed_emails(owner) == []
    with get_session() as session:
        assert session.get(Email, source_id).memory_processed_at is not None
