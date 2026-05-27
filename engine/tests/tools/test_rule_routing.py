"""Semantic tests for behavioral-rule routing (2026-05-22).

Locks the fix for the "general feedback written into a contact blob" bug:
- behavioral rules route to the always-injected `template:<owner>` bucket,
- entity facts can't land in a rule namespace,
- a behavioral rule can NEVER overwrite a `user:` contact blob,
- `_get_learned_preferences` injects both `template:` and legacy `prefs:`.

Runs against a real temp SQLite DB (embeddings included) — no mocks.
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

OWNER = "owner-rules-test"


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


def _blob(blob_id):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    with get_session() as s:
        b = s.query(Blob).filter_by(id=blob_id, owner_id=OWNER).one()
        return b.namespace, b.content


# ── create_memory routing ──────────────────────────────────────────────


def test_behavioral_rule_routes_to_template(fresh_db):
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

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


def test_behavioral_rule_overrides_wrong_user_namespace(fresh_db):
    # Even if the model wrongly passes namespace="user", entry_type wins.
    from zylch.tools.create_memory_tool import CreateMemoryTool

    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="RULE: x", namespace="user", entry_type="behavioral_rule"))
    ns, _ = _blob(res.data["blob_id"])
    assert ns == f"template:{OWNER}"


def test_entity_fact_rejected_in_rule_namespace(fresh_db):
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool

    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="Acme Srl", namespace="template", entry_type="entity_fact"))
    assert res.status == ToolStatus.ERROR
    assert "entity_fact" in (res.error or "")


def test_entity_fact_defaults_to_user(fresh_db):
    from zylch.tools.create_memory_tool import CreateMemoryTool

    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="Acme prefers email", entry_type="entity_fact"))
    ns, _ = _blob(res.data["blob_id"])
    assert ns == f"user:{OWNER}"


def test_no_entry_type_keeps_legacy_default(fresh_db):
    # Backward compat: no entry_type → default user: (unchanged behaviour).
    from zylch.tools.create_memory_tool import CreateMemoryTool

    t = CreateMemoryTool(owner_id=OWNER)
    res = _run(t.execute(content="some contact note"))
    ns, _ = _blob(res.data["blob_id"])
    assert ns == f"user:{OWNER}"


# ── update_memory guard ────────────────────────────────────────────────


def test_rule_cannot_overwrite_contact_blob(fresh_db):
    # THE Pautasso bug: a behavioral rule must never land on a contact.
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    contact = _run(
        CreateMemoryTool(owner_id=OWNER).execute(
            content="#IDENTIFIERS\nEntity type: PERSON\nName: Simona Pautasso",
            entry_type="entity_fact",
        )
    )
    contact_id = contact.data["blob_id"]

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


def test_refining_an_existing_rule_is_allowed(fresh_db):
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    rule = _run(
        CreateMemoryTool(owner_id=OWNER).execute(content="RULE: v1", entry_type="behavioral_rule")
    )
    rid = rule.data["blob_id"]
    res = _run(
        UpdateMemoryTool(owner_id=OWNER).execute(
            blob_id=rid, new_content="RULE: v2 refined", entry_type="behavioral_rule"
        )
    )
    assert res.status == ToolStatus.SUCCESS, res.error
    _, content = _blob(rid)
    assert "v2 refined" in content


def test_entity_fact_update_on_contact_still_works(fresh_db):
    # Normal use of update_memory (an entity fact on a contact) is unaffected.
    from zylch.tools.base import ToolStatus
    from zylch.tools.create_memory_tool import CreateMemoryTool
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    contact = _run(
        CreateMemoryTool(owner_id=OWNER).execute(
            content="#IDENTIFIERS\nEntity type: PERSON\nName: Luigi\nPhone: 111",
            entry_type="entity_fact",
        )
    )
    cid = contact.data["blob_id"]
    res = _run(
        UpdateMemoryTool(owner_id=OWNER).execute(
            blob_id=cid,
            new_content="#IDENTIFIERS\nEntity type: PERSON\nName: Luigi\nPhone: 222",
            entry_type="entity_fact",
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
    assert "Rules — always apply" in section
    assert "RULE A (template)" in section
