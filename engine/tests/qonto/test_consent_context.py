"""The tested company label follows the actual company binding and hides its key."""

import asyncio

import pytest

from zylch.memory.company_key import current_company_key, mint_key
from zylch.memory.join import join
from zylch.memory.mnemonic.session import company_transaction
from zylch.memory.store import open_memory_engine, prepare_store
from zylch.storage.models import MemoryMeta


def label(value):
    with company_transaction(write=True) as session:
        session.get(MemoryMeta, 1).self_notion = value


def test_actual_join_retest_names_the_current_company_and_old_save_refuses(env):
    label("First company")
    before = env.rpc("qonto.test", **env.credentials)["result"]
    assert before["company_name"] == "First company"
    key = mint_key()
    destination = open_memory_engine(key, create=True)
    prepare_store(destination, key, created_by="mint")
    destination.dispose()
    assert join(key)["ok"]
    label("Other company")
    after = env.rpc("qonto.test", **env.credentials)["result"]
    assert after["company_name"] == "Other company"
    stale = env.rpc(
        "qonto.connect",
        **env.credentials,
        challenge_id=before["challenge_id"],
        account_ids=before["account_ids"],
        authority_confirmed=True,
        consent_version=before["consent_version"],
    )
    assert "error" in stale


def test_tested_label_is_bounded_and_never_returns_the_company_capability(env):
    key = current_company_key()
    label("Company " + key + "\n" + "X" * 300)
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    assert key not in str(tested)
    assert tested["company_name"].startswith("Company [redacted]")
    assert len(tested["company_name"]) == 200
    assert "\n" not in tested["company_name"]


def test_unnamed_company_has_an_explicit_null_label(env):
    label(None)
    assert env.rpc("qonto.test", **env.credentials)["result"]["company_name"] is None


@pytest.mark.asyncio
async def test_join_during_provider_probe_cannot_issue_old_company_consent(env, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    original = env.provider.organization

    async def delayed(value):
        entered.set()
        await release.wait()
        return await original(value)

    monkeypatch.setattr(env.provider, "organization", delayed)
    request = asyncio.create_task(env.arpc("qonto.test", **env.credentials))
    await asyncio.wait_for(entered.wait(), timeout=2)
    key = mint_key()
    destination = open_memory_engine(key, create=True)
    prepare_store(destination, key, created_by="mint")
    destination.dispose()
    assert (await env.arpc("memory.join", key=key))["result"]["ok"]
    release.set()
    result = await request
    assert "error" in result and "binding_changed" in result["error"]["message"]
