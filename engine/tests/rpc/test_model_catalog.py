"""Free model discovery respects payment choice and never reads private keys.

Since milestone 10 S6 (brief D9, AC 8) `llm.models` proposes the rankings of
the table in force — here the fixture table the root conftest puts in force —
on a personal key, and on MrCall credits the billing server's v2
capabilities; never an excluded family; a model the profile saved that can run
on the provider stays listed after them. The 10a allowlist rows are gone.
"""

import pytest
from zylch.llm.bounded_proxy import PROTOCOL
from zylch.rpc import usage_queries

from tests.llm import model_table_fixture as fixture

TABLE = fixture.doc("table.json")


def table_models(key):
    """Every entry of both rankings of the fixture table, by `key` (`id` or `direct_id`)."""
    return {
        entry[key]
        for preset in TABLE["presets"].values()
        for record in preset["roles"].values()
        for column in ("ranking", "anthropic_ranking")
        for entry in record[column]
        if entry.get(key)
    }


def profile(tmp_path, monkeypatch, text):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text(text)


class Server:
    """A billing server answering `answer` to every capabilities read."""

    reads = 0

    def __init__(self, answer):
        self.answer = answer

    def capabilities(self):
        Server.reads += 1
        return self.answer


def serving(monkeypatch, answer):
    Server.reads = 0
    monkeypatch.setattr(usage_queries, "_credit_client", lambda: Server(answer))


@pytest.mark.asyncio
async def test_personal_catalog_contains_verified_models_without_credit_connection(monkeypatch):
    monkeypatch.setattr(
        usage_queries, "_credit_client", lambda: pytest.fail("credit lookup for BYOK")
    )
    result = await usage_queries.llm_models({"provider": "openrouter"}, None)
    assert result["available"]
    ids = {m["id"] for m in result["models"]}
    assert ids >= {fixture.FLASH, fixture.K3, fixture.OPUS, fixture.SONNET, fixture.SONNET5}
    assert ids == table_models("id")
    assert fixture.HAIKU not in ids  # an excluded family is never offered


@pytest.mark.asyncio
async def test_personal_anthropic_catalog_is_the_table_s_direct_ids(monkeypatch):
    monkeypatch.setattr(
        usage_queries, "_credit_client", lambda: pytest.fail("credit lookup for BYOK")
    )
    result = await usage_queries.llm_models({"provider": "anthropic"}, None)
    assert result["available"]
    assert {m["provider"] for m in result["models"]} == {"anthropic"}
    assert {m["id"] for m in result["models"]} == table_models("direct_id")


@pytest.mark.asyncio
async def test_a_saved_model_that_runs_on_the_provider_stays_listed(tmp_path, monkeypatch):
    profile(
        tmp_path,
        monkeypatch,
        "LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=k\n"
        f"OPENROUTER_MODEL={fixture.OPUS5}\nMODEL_DEDUP={fixture.HAIKU}\n"
        "MODEL_REANALYZE=claude-sonnet-5\nMODEL_TRAIN=vendor/unpriced-model\n",
    )
    result = await usage_queries.llm_models({}, None)
    ids = [m["id"] for m in result["models"]]
    ranked = table_models("id")
    assert set(ids[: len(ranked)]) == ranked  # the rankings first
    # Saved and priced on OpenRouter: listed after them, Haiku included (saved, not offered).
    assert ids[len(ranked) :] == [fixture.OPUS5, fixture.HAIKU]
    # A direct id cannot run on OpenRouter; an unpriced id cannot run anywhere.
    assert "claude-sonnet-5" not in ids and "vendor/unpriced-model" not in ids
    saved = {m["id"]: m for m in result["models"]}[fixture.OPUS5]
    assert saved["provider"] == "openrouter" and "/" not in saved["label"]


@pytest.mark.asyncio
async def test_credit_catalog_from_server_not_personal_key(monkeypatch):
    k3 = fixture.served_entry(fixture.K3, "openrouter")
    serving(monkeypatch, fixture.capabilities([k3]))
    result = await usage_queries.llm_models({"provider": "mrcall"}, None)
    assert result["available"]
    assert result["models"] == [{"id": fixture.K3, "label": k3["label"], "provider": "openrouter"}]


@pytest.mark.asyncio
async def test_the_credit_catalog_offers_no_excluded_family_but_keeps_a_saved_one(
    tmp_path, monkeypatch
):
    profile(tmp_path, monkeypatch, "LLM_PROVIDER=mrcall\nMRCALL_CREDITS_MODEL=claude-haiku-4-5\n")
    listed = [
        fixture.served_entry("claude-sonnet-5", "anthropic"),
        fixture.served_entry("claude-haiku-4-5", "anthropic"),
        fixture.served_entry(fixture.HAIKU, "openrouter"),
    ]
    serving(monkeypatch, fixture.capabilities(listed))
    result = await usage_queries.llm_models({}, None)
    assert [(m["id"], m["provider"]) for m in result["models"]] == [
        ("claude-sonnet-5", "anthropic"),
        ("claude-haiku-4-5", "anthropic"),  # the saved explicit choice, listed after
    ]


@pytest.mark.asyncio
async def test_the_served_set_is_read_once_an_hour(monkeypatch):
    serving(monkeypatch, fixture.capabilities(fixture.everything()))
    first = await usage_queries.llm_models({"provider": "mrcall"}, None)
    second = await usage_queries.llm_models({"provider": "mrcall"}, None)
    assert first == second and first["available"] and Server.reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "catalog, says",
    [
        ({}, "update the billing server"),
        ({"models": [{"id": "unsafe"}]}, "update the billing server"),
        ({"models": []}, "update the billing server"),
        (fixture.capabilities([], protocol="mrcall-bounded-v1"), "update the billing server"),
        (fixture.capabilities([{"id": "unsafe"}]), "malformed model catalogue"),
        ({**fixture.capabilities([]), "currency": "EUR"}, "malformed model catalogue"),
        (fixture.capabilities([]), "serves no model"),
    ],
)
async def test_old_or_invalid_server_never_invents_models(monkeypatch, catalog, says):
    serving(monkeypatch, catalog)
    result = await usage_queries.llm_models({"provider": "mrcall"}, None)
    assert not result["available"]
    assert result["models"] == []
    assert says in result["reason"]
    assert PROTOCOL == "mrcall-bounded-v2"
