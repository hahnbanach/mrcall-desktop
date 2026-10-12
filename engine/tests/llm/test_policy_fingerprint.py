"""`policy_fingerprint` follows the models a profile resolves to, not the table (brief D9; AC 8).

A client keeps the fingerprint of the policy it was built under and refuses
to run ("AI settings changed") once it differs. Since milestone 10 S6 the
fingerprint covers the model each role resolves to, role by role, with no
network (credits from the cached served set): a table refresh or a change of
the served set that moves a model this profile runs reads as a settings
change; a price refresh, a reorder that moves none of its models, or a new
table version alone does not, so runs in progress are not aborted for nothing.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from zylch.llm import model_policy
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.model_policy import policy_fingerprint
from zylch.llm.roles import catalogue, gates, served, table

from . import model_table_fixture as fixture

TABLE = fixture.doc("table.json")


def saved(provider, preset="economy", **extra):
    return {"LLM_PROVIDER": provider, "LLM_MODEL_PRESET": preset, **extra}


def refreshed(edit) -> dict:
    """The fixture table after `edit(record)`, restamped: a new table version."""
    record = copy.deepcopy(TABLE)
    edit(record)
    return gates.stamped(record)


def tail_reversed(record):
    """Every ranking keeps its first entry; the rest is reordered."""
    for body in record["presets"].values():
        for rankings in body["roles"].values():
            for column in ("ranking", "anthropic_ranking"):
                rankings[column][1:] = reversed(rankings[column][1:])


def dedup_pick_moved(record):
    """DEDUP's first two entries under economy swap: FLASH gives way to QWEN."""
    ranking = record["presets"]["economy"]["roles"]["DEDUP"]["ranking"]
    ranking[0], ranking[1] = ranking[1], ranking[0]


@pytest.mark.parametrize("provider", ["anthropic", "openrouter"])
def test_a_reorder_that_moves_no_resolved_model_keeps_the_fingerprint(provider):
    values = saved(provider)
    before = policy_fingerprint(values)
    table.set_table(refreshed(tail_reversed))
    assert table.document()["version"] != TABLE["version"]
    assert policy_fingerprint(values) == before


def test_a_price_refresh_keeps_the_fingerprint():
    values = saved("openrouter")
    before = policy_fingerprint(values)
    snapshot = fixture.doc("snapshot.json")
    snapshot["models"][fixture.FLASH]["pricing"]["output"] = "0.7"
    catalogue.set_layers(gates.stamped(snapshot))
    assert catalogue.rates(fixture.FLASH, "openrouter")[1] == Decimal("0.7")
    assert policy_fingerprint(values) == before


def test_a_refresh_that_moves_a_model_the_profile_runs_changes_it():
    openrouter, anthropic = saved("openrouter"), saved("anthropic")
    before = {
        "openrouter": policy_fingerprint(openrouter),
        "anthropic": policy_fingerprint(anthropic),
    }
    table.set_table(refreshed(dedup_pick_moved))
    assert model_policy.resolve_model("MODEL_DEDUP", values=openrouter) == fixture.QWEN
    assert policy_fingerprint(openrouter) != before["openrouter"]
    # A personal Anthropic key runs DEDUP's Anthropic ranking, which did not move.
    assert policy_fingerprint(anthropic) == before["anthropic"]


def test_an_explicit_choice_shields_its_role_from_a_refresh():
    values = saved("openrouter", MODEL_DEDUP=fixture.FLASH)
    before = policy_fingerprint(values)
    table.set_table(refreshed(dedup_pick_moved))
    assert policy_fingerprint(values) == before


def test_on_credits_the_fingerprint_reads_the_cached_served_set_and_never_the_network(
    monkeypatch,
):
    monkeypatch.setattr(served, "_reader", lambda url: pytest.fail("network in the fingerprint"))
    values = saved("mrcall", "balanced")
    unread = policy_fingerprint(values)  # nothing read yet: every credits role unresolved
    assert set(model_policy.resolved_models(values).values()) == {None}
    fixture.serve(fixture.everything())
    every = policy_fingerprint(values)
    assert every != unread
    # A served set that changes no pick of this profile keeps it...
    fixture.serve(
        fixture.everything() + [fixture.served_entry("anthropic/claude-opus-5", "openrouter")]
    )
    assert policy_fingerprint(values) == every
    # ...one that moves a pick changes it (Opus 5.5 no longer served: CHAT runs Sonnet 5.5).
    fewer = [e for e in fixture.everything() if e["id"] not in ("claude-opus-5-5", fixture.OPUS)]
    fixture.serve(fewer)
    assert model_policy.resolved_models(values)["MODEL_CHAT"] == "claude-sonnet-5-5"
    assert policy_fingerprint(values) != every


def test_a_built_client_refuses_after_a_refresh_moves_its_model_and_not_after_a_reorder(
    tmp_path, monkeypatch
):
    from zylch.llm.client import make_llm_client

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text(
        "LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=k\nLLM_MODEL_PRESET=economy\n"
    )
    client = make_llm_client(model=model_policy.resolve_model("MODEL_DEDUP"))
    table.set_table(refreshed(tail_reversed))
    assert policy_fingerprint() == client._saved_policy_fingerprint
    table.set_table(refreshed(dedup_pick_moved))
    with pytest.raises(BudgetError, match="AI settings changed"):
        client.create_message_sync(messages=[{"role": "user", "content": "x"}], max_tokens=8)


def test_a_credits_client_reads_the_served_set_before_keeping_its_fingerprint(
    tmp_path, monkeypatch
):
    """Built with an explicit model, it still primes the served set its other
    roles resolve from, so the first read afterwards changes nothing."""
    from zylch import auth
    from zylch.llm.client import make_llm_client

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("LLM_PROVIDER=mrcall\nLLM_MODEL_PRESET=economy\n")
    monkeypatch.setattr(auth, "get_session", lambda: type("S", (), {"id_token": "t"})())
    reads = []

    class Reader:
        def capabilities(self):
            reads.append(1)
            return fixture.capabilities(fixture.everything())

    monkeypatch.setattr(served, "_reader", lambda url: Reader())
    client = make_llm_client(model="claude-sonnet-5")
    assert reads == [1] and served.cached(model_policy.PROXY_URL) is not None
    assert policy_fingerprint() == client._saved_policy_fingerprint
    # Every role saved explicitly: nothing to read.
    served._cache.clear()
    keys = "".join(f"{role}=claude-sonnet-5\n" for role in model_policy.ROLES)
    (tmp_path / ".env").write_text("LLM_PROVIDER=mrcall\nLLM_MODEL_PRESET=economy\n" + keys)
    make_llm_client(model="claude-sonnet-5")
    assert reads == [1]
