"""The door on the learned-rules store, and how the read side truncates.

Measured on support@ (2026-08-01): the rule namespaces held 82 blobs /
66,842 chars against an 8,000-char soft cap, so every detection call
logged ``[prefs] learned preferences size 67004 chars exceeds soft cap
8000`` and ran on a truncated view. There were ZERO exact duplicates —
81 of the 82 blobs were memory ENTITIES (``Entity type: STYLE``), which
belong in ``user:`` where they are fetched by relevance rather than
pinned into every prompt.

So the bound is a door, not a bigger cap: entity-shaped content is
refused, an identical rule is stored once, and a rule that extends an
existing one updates it in place. Read-side truncation stays as the
emergency valve but now selects by priority and recency.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from zylch.services.prefs_store import (
    is_entity_shaped,
    normalise,
    select_within_cap,
    store_rule,
)

from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, BagOfWordsEmbedder, boot, clear_process_state, client, stub_embedder, with_client

ENTITY = (
    "#IDENTIFIERS\nEntity type: STYLE\nName: Win-back email\n\n"
    "#ABOUT\nTrigger: a churned customer. Tone: warm.\n\n#HISTORY\n- 2026-07-01\n"
)
RULE = (
    "Never promise a specific callback time to a customer; say the team will get "
    "back to them and ask for the details needed to proceed."
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "prefs_store.db"))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield
    db_mod.dispose_engine()


OWNER = "owner-prefs-store"
STYLE_HEADER = "#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\n"


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A real profile on real files: the semantic writes need the harness."""
    from zylch.storage import database as db_mod

    stub_embedder(monkeypatch, BagOfWordsEmbedder())
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    yield OWNER_A
    db_mod.dispose_engine()
    clear_process_state()


def _create(content):
    return json.dumps({"action": "CREATE", "entity_type": "STYLE", "scope": "account", "content": STYLE_HEADER + content, "reason": "new rule"})


def _update(blob_id, content):
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session

    version = BlobStorage(get_session, BagOfWordsEmbedder()).get_blob(blob_id, OWNER_A)["updated_at"]
    return json.dumps(
        {
            "action": "UPDATE",
            "entity_type": "STYLE",
            "scope": "account",
            "content": STYLE_HEADER + content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "extends the rule",
        }
    )


def _rows(*specs):
    """(content, age_days) tuples -> the row shape select_within_cap takes."""
    now = datetime.now(timezone.utc)
    return [
        {
            "id": f"blob-{i}",
            "namespace": f"template:{OWNER}",
            "content": content,
            "created_at": now - timedelta(days=age),
        }
        for i, (content, age) in enumerate(specs)
    ]


# ── shape guard ────────────────────────────────────────────────────


def test_entity_blobs_are_recognised():
    assert is_entity_shaped(ENTITY) is True
    assert is_entity_shaped("Entity type: FACT\nCategory: pricing\nKey: setup\n") is True
    assert is_entity_shaped(RULE) is False
    assert is_entity_shaped("") is False


def test_entity_content_is_refused(fresh_db):
    from zylch.services.prefs_store import load_rules

    outcome = store_rule(OWNER, ENTITY, "test", writer="unit")
    assert outcome["action"] == "refused"
    assert load_rules(OWNER) == []


# ── dedup + supersession ───────────────────────────────────────────


def test_identical_rule_is_stored_once(profile, monkeypatch):
    """A new rule is the role's decision; the exact duplicate is refused unpaid."""
    from zylch.services.prefs_store import load_rules

    with_client(monkeypatch, client(_create(RULE)))
    assert store_rule(OWNER_A, RULE, "test", writer="unit")["action"] == "created"
    second = store_rule(OWNER_A, f"  {RULE.upper()}  ", "test", writer="unit")
    assert second["action"] == "duplicate"
    assert len(load_rules(OWNER_A)) == 1


def test_an_extended_rule_supersedes_in_place(profile, monkeypatch):
    """The superseding candidate is pinned and the role updates it in place."""
    from zylch.services.prefs_store import load_rules

    with_client(monkeypatch, client(_create(RULE)))
    first = store_rule(OWNER_A, RULE, "test", writer="unit")
    extended = RULE + " Always sign as the team, never with an invented first name."
    with_client(monkeypatch, client(_update(first["blob_id"], extended)))
    outcome = store_rule(OWNER_A, extended, "test", writer="unit")
    assert outcome["action"] == "superseded"

    rules = load_rules(OWNER_A)
    assert len(rules) == 1
    assert rules[0]["content"] == STYLE_HEADER + extended


def test_a_rule_contained_in_an_existing_one_is_not_stored(profile, monkeypatch):
    from zylch.services.prefs_store import load_rules

    extended = RULE + " Always sign as the team."
    with_client(monkeypatch, client(_create(extended)))
    store_rule(OWNER_A, extended, "test", writer="unit")
    assert store_rule(OWNER_A, RULE, "test", writer="unit")["action"] == "duplicate"
    assert len(load_rules(OWNER_A)) == 1


def test_normalise_ignores_whitespace_and_case():
    assert normalise("  A  RULE\n\nhere ") == normalise("a rule here")


def test_a_rule_written_under_its_control_header_renders_and_compares_as_its_text():
    """The harness writes every memory under the minimal header; for a rule the
    header is control metadata. Rendering strips it, duplicate detection
    compares the text, and the rule is not ranked as an entity stray."""
    from zylch.services.prefs_store import render, rule_body

    headed = STYLE_HEADER + RULE + "\n#HISTORY\nRequested by this account."
    assert rule_body(headed) == RULE + "\nRequested by this account."
    assert normalise(STYLE_HEADER + RULE) == normalise(RULE)
    assert rule_body(RULE) == RULE
    assert rule_body(ENTITY) == ENTITY.strip()  # a STYLE stray with a Name keeps its header: the guard sees it
    assert render([{"content": headed}]) == RULE + "\nRequested by this account."
    kept, dropped = select_within_cap([{"id": "h", "content": headed, "created_at": None}, {"id": "e", "content": ENTITY, "created_at": None}], cap=10000)
    assert [r["id"] for r in kept] == ["e", "h"] or [r["id"] for r in kept] == ["h", "e"]
    assert dropped == []


# ── read-side selection ────────────────────────────────────────────


def test_a_big_stray_does_not_hide_the_rules_behind_it():
    """The old loop `break`-ed on the first oversized chunk."""
    big_entity = ENTITY + "x" * 500
    rows = _rows((big_entity, 1), ("rule one " * 5, 2), ("rule two " * 5, 3))
    kept, dropped = select_within_cap(rows, cap=200)
    kept_contents = [r["content"] for r in kept]
    assert "rule one " * 5 in kept_contents
    assert "rule two " * 5 in kept_contents
    assert dropped and dropped[0]["content"] == big_entity


def test_newest_rules_win_when_the_cap_bites():
    rows = _rows(("old " * 20, 30), ("new " * 20, 1))
    kept, dropped = select_within_cap(rows, cap=85)
    assert [r["content"] for r in kept] == ["new " * 20]
    assert [r["content"] for r in dropped] == ["old " * 20]


def test_kept_order_is_stable_for_the_prompt_cache():
    rows = _rows(("alpha " * 5, 10), ("beta " * 5, 1), ("gamma " * 5, 5))
    kept, _ = select_within_cap(rows, cap=10000)
    assert [r["created_at"] for r in kept] == sorted(r["created_at"] for r in kept)


def test_cap_is_read_live_from_the_environment(monkeypatch):
    from zylch.services.prefs_store import learned_prefs_max_chars

    monkeypatch.setenv("LEARNED_PREFS_MAX_CHARS", "1234")
    assert learned_prefs_max_chars() == 1234
    monkeypatch.setenv("LEARNED_PREFS_MAX_CHARS", "nonsense")
    assert learned_prefs_max_chars() == 8000
