"""Free model discovery respects payment choice and never reads private keys."""
import pytest
from zylch.rpc import usage_queries


@pytest.mark.asyncio
async def test_personal_catalog_contains_verified_models_without_credit_connection(monkeypatch):
    monkeypatch.setattr(usage_queries, '_credit_client', lambda: pytest.fail('credit lookup for BYOK'))
    result = await usage_queries.llm_models({'provider': 'openrouter'}, None)
    assert result['available']
    assert {m['id'] for m in result['models']} == {
        'z-ai/glm-5.2', 'moonshotai/kimi-k3', 'anthropic/claude-opus-5',
        'anthropic/claude-sonnet-5', 'anthropic/claude-haiku-4.5'}


@pytest.mark.asyncio
async def test_credit_catalog_from_server_not_personal_key(monkeypatch):
    class Server:
        def capabilities(self):
            return {'models': [{'id': 'moonshotai/kimi-k3', 'label': 'Kimi K3', 'provider': 'openrouter'}]}
    monkeypatch.setattr(usage_queries, '_credit_client', Server)
    result = await usage_queries.llm_models({'provider': 'mrcall'}, None)
    assert result['models'][0]['id'] == 'moonshotai/kimi-k3'


@pytest.mark.asyncio
@pytest.mark.parametrize('catalog', [{}, {'models': [{'id': 'unsafe'}]}, {'models': []}])
async def test_old_or_invalid_server_never_invents_models(monkeypatch, catalog):
    class Server:
        def capabilities(self):
            return catalog
    monkeypatch.setattr(usage_queries, '_credit_client', Server)
    result = await usage_queries.llm_models({'provider': 'mrcall'}, None)
    assert not result['available']
    assert result['models'] == []
