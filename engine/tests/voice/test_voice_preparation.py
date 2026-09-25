"""Telephone admission validates membership without starting an LLM client."""

import asyncio
from unittest.mock import Mock

import pytest

from tests.voice.m2_fixture import NUMBER
from tests.voice.test_agent_config import save
from zylch.services.voice import preparation
from zylch.services.voice.agent_config import snapshot_for_call


def test_prepare_call_checks_binding_only(fixture_db, monkeypatch):
    save()
    snapshot = snapshot_for_call(NUMBER)
    binding = Mock()
    monkeypatch.setattr(preparation, "require_binding", binding)
    assert asyncio.run(preparation.prepare_call(snapshot)) is None
    binding.assert_called_once_with(snapshot.binding)


def test_prepare_call_fails_closed(fixture_db, monkeypatch):
    save()
    snapshot = snapshot_for_call(NUMBER)
    monkeypatch.setattr(preparation, "require_binding", Mock(side_effect=ValueError("secret")))
    with pytest.raises(ValueError, match="Voice call preparation unavailable") as error:
        asyncio.run(preparation.prepare_call(snapshot))
    assert "secret" not in str(error.value)
