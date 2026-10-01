"""Free model discovery respects payment choice and never reads private keys."""

import json
from pathlib import Path

import pytest
from zylch.rpc import usage_queries

ROLES = Path(__file__).resolve().parents[2] / "zylch" / "llm" / "roles"


def table_models(provider, key):
    """Picks and Anthropic fallbacks of resolved.json plus the allowlist rows of the transport."""
    resolved = json.loads((ROLES / "resolved.json").read_text())
    allowlist = json.loads((ROLES / "requirements.json").read_text())["allowlist"]
    transport = "direct" if provider == "anthropic" else "openrouter"
    picks = {
        row[key]
        for preset in resolved["presets"].values()
        for record in preset["roles"].values()
        for row in (record, record["anthropic_fallback"])
        if row.get(key)
    }
    return picks | {m for m, row in allowlist.items() if row["transport"] == transport}


@pytest.mark.asyncio
async def test_personal_catalog_contains_verified_models_without_credit_connection(monkeypatch):
    monkeypatch.setattr(
        usage_queries, "_credit_client", lambda: pytest.fail("credit lookup for BYOK")
    )
    result = await usage_queries.llm_models({"provider": "openrouter"}, None)
    assert result["available"]
    ids = {m["id"] for m in result["models"]}
    assert ids >= {
        "z-ai/glm-5.2",
        "moonshotai/kimi-k3",
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "anthropic/claude-haiku-4.5",
    }
    assert ids == table_models("openrouter", "catalogue_id")


@pytest.mark.asyncio
async def test_personal_anthropic_catalog_is_the_table_and_the_allowlist(monkeypatch):
    monkeypatch.setattr(
        usage_queries, "_credit_client", lambda: pytest.fail("credit lookup for BYOK")
    )
    result = await usage_queries.llm_models({"provider": "anthropic"}, None)
    assert result["available"]
    assert {m["provider"] for m in result["models"]} == {"anthropic"}
    assert {m["id"] for m in result["models"]} == table_models("anthropic", "direct_id")


@pytest.mark.asyncio
async def test_credit_catalog_from_server_not_personal_key(monkeypatch):
    class Server:
        def capabilities(self):
            return {
                "models": [
                    {"id": "moonshotai/kimi-k3", "label": "Kimi K3", "provider": "openrouter"}
                ]
            }

    monkeypatch.setattr(usage_queries, "_credit_client", Server)
    result = await usage_queries.llm_models({"provider": "mrcall"}, None)
    assert result["models"][0]["id"] == "moonshotai/kimi-k3"


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog", [{}, {"models": [{"id": "unsafe"}]}, {"models": []}])
async def test_old_or_invalid_server_never_invents_models(monkeypatch, catalog):
    class Server:
        def capabilities(self):
            return catalog

    monkeypatch.setattr(usage_queries, "_credit_client", Server)
    result = await usage_queries.llm_models({"provider": "mrcall"}, None)
    assert not result["available"]
    assert result["models"] == []
