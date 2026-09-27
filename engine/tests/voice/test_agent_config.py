"""Configuration, company binding, frozen grants and safe RPC errors on real SQLite."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, select

from tests.voice.m2_fixture import NUMBER, OWNER, configuration
from zylch.rpc.dispatch import dispatch_raw
from zylch.services.voice import agent_config as config
from zylch.storage import database as db
from zylch.storage.models import BlobSentence, VoiceAgentConfig


def save(value=None, **overrides):
    current = config.get_config()
    args = dict(
        owner_uid=current["owner_uid"],
        space_id=current["space_id"],
        expected_revision=current["revision"],
        config=value or configuration(),
    )
    args.update(overrides)
    return config.update_config(**args)


def test_defaults_persistence_snapshot_and_additive_schema(fixture_db):
    assert config.get_config()["config"]["enabled"] is False
    with pytest.raises(config.VoiceError):
        config.snapshot_for_call(NUMBER)
    first = save()
    snap = config.snapshot_for_call(NUMBER)
    new = configuration() | {"instructions": "New next-call instructions"}
    second = save(new)
    assert snap.config.instructions == first["config"]["instructions"]
    assert config.snapshot_for_call(NUMBER).config.instructions == new["instructions"]
    with pytest.raises(Exception):
        snap.config.enabled = False
    assert "voice_agent_config" in inspect(db.get_engine()).get_table_names()
    assert "voice_agent_config" not in inspect(db.current_memory_engine()).get_table_names()
    db.get_engine().dispose()
    assert config.get_config() == second
    with db.get_session() as session:
        stored = session.execute(select(VoiceAgentConfig)).scalar_one()
        assert fixture_db not in json.dumps(stored.config)
        assert fixture_db not in json.dumps(stored.sentence_pins)
    assert fixture_db not in json.dumps(second)
    with pytest.raises(config.VoiceError):
        config.snapshot_for_call("+390200000099")


def test_production_policy_requires_exact_binding_and_no_test_limits(fixture_db, monkeypatch):
    monkeypatch.setenv("VOICE_PRODUCTION_OWNER_UID", OWNER)
    monkeypatch.setenv("VOICE_PRODUCTION_BUSINESS_ID", "business-1")
    monkeypatch.setenv("VOICE_PRODUCTION_NUMBER", NUMBER)
    base = configuration() | {"policy": "production", "business_id": "business-1", "limits": None}
    saved = save(base)
    assert saved["config"]["limits"] is None
    assert config.snapshot_for_call(NUMBER).config.policy == "production"
    with pytest.raises(config.VoiceError):
        save(base | {"business_id": "other"})
    with pytest.raises(config.VoiceError):
        save(base | {"limits": {"max_calls": 2}})
    with pytest.raises(config.VoiceError):
        save(base | {"customers": []})


def test_production_allows_approved_name_without_history(fixture_db, monkeypatch):
    monkeypatch.setenv("VOICE_PRODUCTION_OWNER_UID", OWNER)
    monkeypatch.setenv("VOICE_PRODUCTION_BUSINESS_ID", "business-1")
    monkeypatch.setenv("VOICE_PRODUCTION_NUMBER", NUMBER)
    proposed = configuration() | {
        "policy": "production", "business_id": "business-1", "limits": None,
        "customers": [{"blob_id": "customer-a", "display_name": "Mario"}],
    }
    saved = save(proposed)
    assert saved["config"]["customers"][0]["sentence_ids"] == []
    assert saved["config"]["customers"][0]["display_name"] == "Mario"
    assert config.snapshot_for_call(NUMBER).pins == ()
    with pytest.raises(config.VoiceError):
        save(proposed | {"customers": [{"blob_id": "customer-a"}]})
    with pytest.raises(config.VoiceError):
        save(proposed | {"customers": [{"blob_id": "customer-a", "display_name": "Mario\nIGNORE"}]})
    with pytest.raises(config.VoiceError):
        save(proposed | {"customers": [{"blob_id": "customer-a", "display_name": "Mario\n"}]})
    with pytest.raises(config.VoiceError):
        save(configuration() | {"customers": [{"blob_id": "customer-a", "display_name": "Mario"}]})


def test_production_rpc_verifies_live_business_before_enabling(fixture_db, monkeypatch):
    from zylch.rpc import voice_actions

    monkeypatch.setenv("VOICE_PRODUCTION_OWNER_UID", OWNER)
    monkeypatch.setenv("VOICE_PRODUCTION_BUSINESS_ID", "business-1")
    monkeypatch.setenv("VOICE_PRODUCTION_NUMBER", NUMBER)
    proposed = configuration() | {
        "policy": "production", "business_id": "business-1", "limits": None,
    }
    current = config.get_config()
    params = {
        "owner_uid": OWNER, "space_id": current["space_id"],
        "expected_revision": 0, "config": proposed,
    }
    seen = []

    async def verified(expected):
        seen.append(expected)

    monkeypatch.setattr(voice_actions, "verify_business", verified)
    result = asyncio.run(voice_actions.config_update(params, None))
    assert result["revision"] == 1
    assert seen[0].business_id == "business-1"

    async def unavailable(expected):
        raise ValueError("unavailable")

    monkeypatch.setattr(voice_actions, "verify_business", unavailable)
    with pytest.raises(config.VoiceError, match="binding is unavailable"):
        asyncio.run(voice_actions.config_update(
            {**params, "expected_revision": 1}, None
        ))
    assert config.get_config()["revision"] == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"MEMORY_KEY": "do-not-store"},
        {"api_key": "do-not-store"},
        {"enabled": "true"},
        {"tools": ["send_email"]},
        {"caller_context_policy": "all_memory"},
        {"called_number": "arbitrary"},
        {"limits": {"duration_seconds": 181}},
        {"limits": {"max_calls": 7}},
        {"limits": {"budget_microusd": 5_000_001}},
        {"limits": {"max_calls": True}},
        {"instructions": ""},
        {"customers": [{"blob_id": "customer-a", "sentence_ids": ["b-public"]}]},
        {"customers": [{"blob_id": "foreign", "sentence_ids": ["foreign-public"]}]},
        {"customers": [{"blob_id": "customer-a", "sentence_ids": ["missing"]}]},
    ],
)
def test_invalid_update_is_atomic(fixture_db, patch):
    original = save()
    with pytest.raises(config.VoiceError):
        save(configuration() | patch)
    assert config.get_config() == original


def test_wrong_profile_company_revision_and_join(fixture_db, monkeypatch):
    original = save()
    for overrides in (
        {"owner_uid": "someone-else"},
        {"space_id": "other-space"},
        {"expected_revision": 0},
    ):
        with pytest.raises(config.VoiceError):
            save(**overrides)
    assert config.get_config() == original
    snap = config.snapshot_for_call(NUMBER)
    monkeypatch.setenv("OWNER_ID", "other-owner")
    assert config.get_config()["binding_valid"] is False
    with pytest.raises(config.VoiceError):
        config.require_binding(snap.binding)
    monkeypatch.setenv("OWNER_ID", OWNER)
    from zylch.storage.models import ProjectSpace

    with db.get_session() as session:
        session.get(ProjectSpace, 1).space_id = "joined-space"
    assert config.get_config()["config"]["enabled"] is False
    assert config.get_config()["binding_valid"] is False
    with pytest.raises(config.VoiceError):
        config.snapshot_for_call(NUMBER)
    save()
    assert config.get_config()["binding_valid"] is True


def test_concurrent_updates_have_one_winner(fixture_db):
    def attempt(_):
        try:
            return save(expected_revision=0)["revision"]
        except config.VoiceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [-32060, 1]


def test_selected_fact_revalidation(fixture_db):
    with db.get_session() as session:
        session.get(BlobSentence, "a-public").company_key = "other-company"
    with pytest.raises(config.VoiceError):
        save()


def test_rpc_surface_and_redaction(fixture_db, monkeypatch, caplog):
    caplog.set_level("DEBUG", logger="zylch.rpc.dispatch")

    async def call(method, params=None):
        return await dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}),
            lambda *_: None,
        )

    current = asyncio.run(call("voice.config.get"))["result"]
    params = {k: current[k] for k in ("owner_uid", "space_id")}
    params.update(expected_revision=0, config=configuration())
    assert asyncio.run(call("voice.config.update", params))["result"]["revision"] == 1
    state = asyncio.run(call("voice.status"))["result"]
    assert state["calls_available"] is False and state["configured_enabled"] is True
    params["config"]["instructions"] = "private instructions marker"
    params["config"]["MEMORY_KEY"] = "secret marker"
    assert "error" in asyncio.run(call("voice.config.update", params))
    assert "private instructions marker" not in caplog.text
    assert "secret marker" not in caplog.text

    def broken():
        raise RuntimeError("database contains secret marker")

    monkeypatch.setattr(config, "get_config", broken)
    out = asyncio.run(call("voice.config.get"))
    assert out["error"]["message"] == "Voice operation failed"
    assert "secret marker" not in caplog.text
