"""Invalid spending policy must never reach the settings writer."""
import asyncio
from unittest.mock import Mock

import pytest

from zylch.rpc.methods import settings_update
from zylch.services import settings_io


@pytest.mark.parametrize("key,value", [
    ("LLM_PROVIDER", "auto"), ("LLM_MODEL_PRESET", "premium_fallback"),
    ("PREPARATION_BATCH_SIZE", "0"), ("PREPARATION_BATCH_SIZE", "101"),
    ("PREPARATION_BATCH_SIZE", "2.5"), ("PREPARATION_BATCH_SIZE", "²"),
])
def test_invalid_policy_does_not_write(monkeypatch, key, value):
    write = Mock()
    monkeypatch.setattr(settings_io, "update_env", write)
    with pytest.raises(ValueError):
        asyncio.run(settings_update({"updates": {key: value}}, lambda *a: None))
    write.assert_not_called()


def test_explicit_billing_does_not_clear_other_credentials(monkeypatch):
    write = Mock(return_value=["LLM_PROVIDER"])
    monkeypatch.setattr(settings_io, "update_env", write)
    result = asyncio.run(settings_update({"updates": {"LLM_PROVIDER": "mrcall"}}, lambda *a: None))
    assert result["ok"]
    write.assert_called_once_with({"LLM_PROVIDER": "mrcall"})


def test_credit_model_and_personal_key_save_are_independent(monkeypatch):
    write = Mock(return_value=['MRCALL_CREDITS_MODEL', 'OPENROUTER_API_KEY'])
    monkeypatch.setattr(settings_io, 'update_env', write)
    changes = {'MRCALL_CREDITS_MODEL': 'moonshotai/kimi-k3', 'OPENROUTER_API_KEY': 'synthetic-key'}
    result = asyncio.run(settings_update({'updates': changes}, lambda *a: None))
    assert result['ok']
    write.assert_called_once_with(changes)


def test_real_profile_save_preserves_other_payment_key_and_role(tmp_path, monkeypatch):
    from dotenv import dotenv_values
    from zylch.llm.model_policy import resolve_model
    path = tmp_path / '.env'
    path.write_text('OWNER_ID=test-uid\nANTHROPIC_API_KEY=synthetic-existing\nMODEL_MEMORY_MERGE=claude-opus-5\n')
    monkeypatch.setattr(settings_io, '_env_path', lambda: str(path))
    monkeypatch.setattr(settings_io, 'get_active_profile', lambda: 'test-uid')
    changes = {'LLM_PROVIDER': 'openrouter', 'OPENROUTER_API_KEY': 'synthetic-new',
               'OPENROUTER_MODEL': 'moonshotai/kimi-k3', 'LLM_MODEL_PRESET': 'custom'}
    assert asyncio.run(settings_update({'updates': changes}, lambda *a: None))['ok']
    saved = dotenv_values(path)
    assert saved['ANTHROPIC_API_KEY'] == 'synthetic-existing'
    assert saved['OPENROUTER_API_KEY'] == 'synthetic-new'
    assert saved['MODEL_MEMORY_MERGE'] == 'claude-opus-5'
    assert resolve_model(values=saved) == 'moonshotai/kimi-k3'
    assert path.stat().st_mode & 0o777 == 0o600
