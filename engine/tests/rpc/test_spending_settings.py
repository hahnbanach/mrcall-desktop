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
