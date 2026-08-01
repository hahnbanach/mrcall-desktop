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

from datetime import datetime, timedelta, timezone

import pytest

from zylch.services.prefs_store import (
    is_entity_shaped,
    normalise,
    select_within_cap,
    store_rule,
)

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


def test_identical_rule_is_stored_once(fresh_db):
    from zylch.services.prefs_store import load_rules

    assert store_rule(OWNER, RULE, "test", writer="unit")["action"] == "created"
    second = store_rule(OWNER, f"  {RULE.upper()}  ", "test", writer="unit")
    assert second["action"] == "duplicate"
    assert len(load_rules(OWNER)) == 1


def test_an_extended_rule_supersedes_in_place(fresh_db):
    from zylch.services.prefs_store import load_rules

    store_rule(OWNER, RULE, "test", writer="unit")
    extended = RULE + " Always sign as the team, never with an invented first name."
    outcome = store_rule(OWNER, extended, "test", writer="unit")
    assert outcome["action"] == "superseded"

    rules = load_rules(OWNER)
    assert len(rules) == 1
    assert rules[0]["content"] == extended


def test_a_rule_contained_in_an_existing_one_is_not_stored(fresh_db):
    from zylch.services.prefs_store import load_rules

    extended = RULE + " Always sign as the team."
    store_rule(OWNER, extended, "test", writer="unit")
    assert store_rule(OWNER, RULE, "test", writer="unit")["action"] == "duplicate"
    assert len(load_rules(OWNER)) == 1


def test_normalise_ignores_whitespace_and_case():
    assert normalise("  A  RULE\n\nhere ") == normalise("a rule here")


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
