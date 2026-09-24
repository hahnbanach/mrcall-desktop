"""Semantic tests for behavioral-rule routing (2026-05-22).

Locks the fix for the "general feedback written into a contact blob" bug:
- behavioral rules route to the always-injected `template:<owner>` bucket,
- entity facts can't land in a rule namespace,
- a behavioral rule can NEVER overwrite a `user:` contact blob,
- `_get_learned_preferences` injects both `template:` and legacy `prefs:`.

The routing is structural — the model-declared `entry_type` and the family of
the model-declared `namespace`, never the content — and it runs before the
mnemonic role is asked anything. A rule declared as one (`behavioral_rule`, or
a rule-family namespace with no `entry_type`) goes through the rule store's
door: its shape and exact-duplicate defences are unpaid, and the write itself
is the role's decision with the candidate pinned. Entity facts reach the role
directly — including one whose named `blob_id` is a rule row, which the role
may answer with an account STYLE proposal. Every case that writes runs the
real semantic path with the role's answer scripted (`decided`), against a real
temp SQLite store.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest

OWNER = "owner-rules-test"

ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\n#ABOUT\nPrefers email over phone."
)
LUIGI = "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luigi Bianchi\nPhone: 111"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "rules_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """The semantic path with a real store: company key, stubbed embedder, a turn."""
    from tests.memory.mnemonic_env import (
        COMPANY_A,
        BagOfWordsEmbedder,
        boot,
        clear_process_state,
        stub_embedder,
    )
    from zylch.assistant.turn_context import set_turn_observation
    from zylch.storage import database as db_mod

    embedder = BagOfWordsEmbedder()
    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER, COMPANY_A)
    set_turn_observation("Acme Srl preferisce essere contattata via email.")
    yield embedder
    db_mod.dispose_engine()
    clear_process_state()


def decided(monkeypatch, *decisions):
    """Script the role's answers; everything else — validator, journal, commit — is real."""
    from tests.memory.mnemonic_env import client, with_client

    with_client(monkeypatch, client(*decisions))


def style_create(content):
    return json.dumps(
        {
            "action": "CREATE",
            "entity_type": "STYLE",
            "scope": "account",
            "content": "#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\n" + content,
            "reason": "this account's own operating rule",
        }
    )


def style_update(blob_id, content):
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session

    from tests.memory.mnemonic_env import BagOfWordsEmbedder

    version = BlobStorage(get_session, BagOfWordsEmbedder()).get_blob(blob_id, OWNER)["updated_at"]
    return json.dumps(
        {
            "action": "UPDATE",
            "entity_type": "STYLE",
            "scope": "account",
            "content": "#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\n" + content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the rule, refined",
        }
    )


def create_decision(content=ACME, entity_type="COMPANY"):
    return json.dumps(
        {
            "action": "CREATE",
            "entity_type": entity_type,
            "scope": "entity",
            "content": content,
            "reason": "no visible candidate describes this entity",
        }
    )


def seed_entity(embedder, content):
    """A contact written the way ingestion writes one; returns (id, version)."""
    from zylch.memory.blob_storage import BlobStorage
    from zylch.memory.company_key import current_company_key, entity_namespace
    from zylch.storage.database import get_session

    storage = BlobStorage(get_session, embedder)
    blob = storage.store_blob(OWNER, entity_namespace(current_company_key()), content, "seed")
    return blob["id"], storage.get_blob(blob["id"], OWNER)["updated_at"]


def _blob(blob_id):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    with get_session() as s:
        b = s.query(Blob).filter_by(id=blob_id, owner_id=OWNER).one()
        return b.namespace, b.content


# ── create_memory routing ──────────────────────────────────────────────


def test_behavioral_rule_routes_to_template(harness, monkeypatch):
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

    decided(monkeypatch, style_create("RULE: never invent MrCall settings.\nWhy: incident 2026-05-22."))
    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(
        t.execute(
            content="RULE: never invent MrCall settings.\nWhy: incident 2026-05-22.",
            entry_type="behavioral_rule",
        )
    )
    assert res.status == ToolStatus.SUCCESS, res.error
    ns, _ = _blob(res.data["blob_id"])
    assert ns == f"template:{OWNER}"


def test_behavioral_rule_overrides_wrong_user_namespace(harness, monkeypatch):
    # Even if the model wrongly passes namespace="user", entry_type wins.
    from zylch.tools.create_memory_tool import CreateMemoryTool

    decided(monkeypatch, style_create("RULE: x"))
    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="RULE: x", namespace="user", entry_type="behavioral_rule"))
    ns, _ = _blob(res.data["blob_id"])
    assert ns == f"template:{OWNER}"


def test_entity_fact_rejected_in_rule_namespace(fresh_db):
    """Declared kind beats declared family, before anything is decided or paid."""
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="Acme Srl", namespace="template", entry_type="entity_fact"))
    assert res.status == ToolStatus.ERROR
    assert "entity_fact" in (res.error or "")


def test_an_unknown_family_is_refused_not_stored(fresh_db):
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

    res = _run(CreateMemoryTool(owner_id=OWNER).execute(content="x", namespace="attic:whatever"))
    assert res.status == ToolStatus.ERROR
    assert "unknown memory namespace family" in (res.error or "")


def test_entity_fact_defaults_to_user(harness, monkeypatch):
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

    decided(monkeypatch, create_decision())
    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="Acme prefers email", entry_type="entity_fact"))
    assert res.status == ToolStatus.SUCCESS, res.error
    ns, _ = _blob(res.data["blob_id"])
    from zylch.memory.company_key import current_company_key, entity_namespace

    assert ns == entity_namespace(current_company_key())  # company family: keyed, not owner


def test_no_entry_type_means_an_entity_fact(harness, monkeypatch):
    # No entry_type → the default family is still `user`; since 2026-09 that
    # namespace is the company's, not the owner's.
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

    decided(monkeypatch, create_decision())
    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="some contact note"))
    assert res.status == ToolStatus.SUCCESS, res.error
    ns, _ = _blob(res.data["blob_id"])
    from zylch.memory.company_key import current_company_key, entity_namespace

    assert ns == entity_namespace(current_company_key())  # company family: keyed, not owner


def test_a_rule_family_hint_without_an_entry_type_is_still_a_rule(harness, monkeypatch):
    """The model names a family, never a namespace: `template:anyone` is this
    owner's rule bucket, and the rule store's door — with the role deciding the
    STYLE — takes it."""
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

    decided(monkeypatch, style_create("be terse in every reply"))
    res = _run(
        CreateMemoryTool(owner_id=OWNER).execute(
            content="be terse in every reply", namespace="template:someone-else"
        )
    )
    assert res.status == ToolStatus.SUCCESS, res.error
    ns, _ = _blob(res.data["blob_id"])
    assert ns == f"template:{OWNER}"


# ── update_memory guard ────────────────────────────────────────────────


def test_rule_cannot_overwrite_contact_blob(harness, monkeypatch):
    # THE Pautasso bug: a behavioral rule must never land on a contact. The
    # refusal is structural — the target row's own family — and happens before
    # the role is asked anything: no decision is scripted here, and none is needed.
    from zylch.tools.base import ToolStatus
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    contact_id, _ = seed_entity(
        harness, "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Simona Pautasso"
    )
    res = _run(
        UpdateMemoryTool(owner_id=OWNER).execute(
            blob_id=contact_id,
            new_content="RULE: never contradict the user about phone support",
            entry_type="behavioral_rule",
        )
    )
    assert res.status == ToolStatus.ERROR
    assert "contact" in (res.error or "").lower()
    # Contact blob is untouched.
    _, content = _blob(contact_id)
    assert "Simona Pautasso" in content
    assert "never contradict" not in content


def test_refining_an_existing_rule_is_allowed(harness, monkeypatch):
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    decided(monkeypatch, style_create("RULE: v1"))
    rule = _run(
        CreateMemoryTool(owner_id=OWNER).execute(content="RULE: v1", entry_type="behavioral_rule")
    )
    rid = rule.data["blob_id"]
    decided(monkeypatch, style_update(rid, "RULE: v2 refined"))
    res = _run(
        UpdateMemoryTool(owner_id=OWNER).execute(
            blob_id=rid, new_content="RULE: v2 refined", entry_type="behavioral_rule"
        )
    )
    assert res.status == ToolStatus.SUCCESS, res.error
    ns, content = _blob(rid)
    assert ns == f"template:{OWNER}"
    assert "v2 refined" in content


def test_an_entity_cannot_be_written_over_a_rule(harness, monkeypatch):
    """The refinement door keeps the rule store's shape rule, unpaid."""
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    decided(monkeypatch, style_create("RULE: v1"))
    rid = _run(
        CreateMemoryTool(owner_id=OWNER).execute(content="RULE: v1", entry_type="behavioral_rule")
    ).data["blob_id"]
    res = _run(
        UpdateMemoryTool(owner_id=OWNER).execute(
            blob_id=rid, new_content=ACME, entry_type="behavioral_rule"
        )
    )
    assert res.status == ToolStatus.ERROR
    assert "entity-shaped" in (res.error or "")
    _, content = _blob(rid)
    assert content.endswith("RULE: v1")


def test_a_refinement_with_nothing_to_say_or_no_row_is_refused(fresh_db):
    from zylch.services.prefs_store import refine_rule
    from zylch.tools.base import ToolStatus
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    assert refine_rule(OWNER, "b1", "   ", writer="test")["action"] == "refused"
    res = _run(
        UpdateMemoryTool(owner_id=OWNER).execute(
            blob_id="no-such-blob", new_content="RULE: v2", entry_type="behavioral_rule"
        )
    )
    assert res.status == ToolStatus.ERROR
    assert "No blob with id" in (res.error or "")


def test_entity_fact_update_on_contact_still_works(harness, monkeypatch):
    # Normal use of update_memory (an entity fact on a contact) goes through
    # the role, with the named row pinned first among the candidates.
    from zylch.assistant.turn_context import set_turn_observation
    from zylch.tools.base import ToolStatus
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    cid, version = seed_entity(harness, LUIGI)
    set_turn_observation("Il numero di Luigi Bianchi ora è 222.")
    corrected = LUIGI.replace("Phone: 111", "Phone: 222")
    decided(
        monkeypatch,
        json.dumps(
            {
                "action": "UPDATE",
                "entity_type": "PERSON",
                "scope": "entity",
                "content": corrected,
                "write_set": [{"blob_id": cid, "expected_version": version, "role": "target"}],
                "reason": "the phone number replaces the old one",
            }
        ),
    )
    res = _run(
        UpdateMemoryTool(owner_id=OWNER).execute(
            blob_id=cid, new_content=corrected, entry_type="entity_fact"
        )
    )
    assert res.status == ToolStatus.SUCCESS, res.error
    _, content = _blob(cid)
    assert "222" in content


# ── always-on injection ────────────────────────────────────────────────


def test_get_learned_preferences_reads_template_and_prefs(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    with get_session() as s:
        s.add(
            Blob(
                id=str(uuid.uuid4()),
                owner_id=OWNER,
                namespace=f"template:{OWNER}",
                content="RULE A (template)",
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        )
        s.add(
            Blob(
                id=str(uuid.uuid4()),
                owner_id=OWNER,
                namespace=f"prefs:{OWNER}",
                content="RULE B (legacy prefs)",
                created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
            )
        )
        s.add(
            Blob(
                id=str(uuid.uuid4()),
                owner_id=OWNER,
                namespace=f"user:{OWNER}",
                content="a contact fact, must NOT be injected",
                created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
            )
        )

    from zylch.services.solve_constants import (
        _get_learned_preferences,
        get_personal_data_section,
    )

    out = _get_learned_preferences(OWNER)
    assert "RULE A (template)" in out
    assert "RULE B (legacy prefs)" in out
    assert "contact fact" not in out

    section = get_personal_data_section(owner_id=OWNER)
    # Learned rules reach the section via the framed OPERATING RULES block.
    # The old "## Rules — always apply" footer that re-embedded the same text
    # a second time was removed in support-llm-cost-fix P4 / FIX 2, so the
    # rule text must now appear EXACTLY ONCE.
    assert "OPERATING RULES" in section
    assert "RULE A (template)" in section
    assert section.count("RULE A (template)") == 1
