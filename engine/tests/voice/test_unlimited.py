"""Operator-authorized removal of isolated test caps preserves real accounting."""

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.voice.helpers import config_for, finished
from tests.voice.test_engine_runtime import setup_runtime, admit
from tests.voice.test_agent_config import save
from zylch.llm.budget import BudgetError, budget_snapshot, reserve
from zylch.llm.model_policy import isolated_voice_unlimited
from zylch.services.voice.live_sip_smoke import create_app
from zylch.storage.voice_smoke import SmokeLedger


def test_unlimited_retains_original_policy_and_all_holds_after_restart(tmp_path):
    config = config_for(tmp_path, max_calls=2, reservation_microusd=1_000_000)
    unlimited = config.model_copy(update={"unlimited": True})
    assert unlimited.policy_id == config.policy_id
    path = config.profile / "voice-smoke.db"
    ledger = SmokeLedger(path, config.policy_id, config.reservation_microusd, 2)
    for i in range(2):
        assert ledger.admit(str(i), allowed=True) == "accept"
        ledger.finish(str(i), "closed")
    original = ledger.rows()
    ledger.close()
    ledger = SmokeLedger(path, unlimited.policy_id, 1_000_000, 2, unlimited=True)
    for i in range(2, 9):
        assert ledger.admit(str(i), allowed=True) == "accept"
        ledger.finish(str(i), "closed")
    assert ledger.rows()[:2] == original
    assert sum(r["reserved_microusd"] for r in ledger.rows()) == 9_000_000
    assert ledger.admit("uncertain", allowed=True) == "accept"
    ledger.finish("uncertain", "uncertain")
    assert ledger.admit("blocked", allowed=True) == "reject"
    assert ledger.admit("0", allowed=True) == "duplicate"
    ledger.close()


@pytest.mark.parametrize("mode", ["unlimited", "wrong_marker", "ambient_only", "populated"])
def test_unlimited_engine_budget_is_file_scoped_and_keeps_reservations(
    fixture_db, tmp_path, monkeypatch, mode
):
    valid = mode == "unlimited"
    uid = tmp_path.name
    monkeypatch.setenv("OWNER_ID", uid)
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("VOICE_ENGINE_UNLIMITED", "1")
    (tmp_path / ".env").write_text(
        f"OWNER_ID={uid}\nVOICE_SMOKE_TEST_PROFILE={uid}\n"
        f"VOICE_ENGINE_ISOLATED_PROFILE={'wrong' if mode == 'wrong_marker' else uid}\n"
        f"VOICE_ENGINE_UNLIMITED={0 if mode == 'ambient_only' else 1}\n"
        "LLM_DAILY_BUDGET_USD=0\n"
    )
    if mode == "populated":
        (tmp_path / "zylch.db").touch()
    args = dict(
        model="claude-haiku-4-5",
        messages=[{"role": "user", "content": "synthetic"}],
        max_tokens=512,
    )
    assert isolated_voice_unlimited() == valid
    if not valid:
        with pytest.raises(BudgetError):
            reserve(args, "direct")
        return
    reserve(args, "direct")
    reserve(args, "direct")
    state = budget_snapshot(uid)
    assert state["budget_usd"] is None and state["remaining_usd"] is None
    assert not state["paused"] and state["reserved_usd"] > 0
    # Returning to bounded mode never deletes or refunds those reservations.
    (tmp_path / ".env").write_text("LLM_DAILY_BUDGET_USD=0\n")
    assert not isolated_voice_unlimited()
    assert budget_snapshot(uid)["reserved_usd"] == state["reserved_usd"]
    with pytest.raises(BudgetError):
        reserve(args, "direct")


def test_unlimited_removes_carrier_and_runtime_duration_caps(fixture_db, tmp_path, monkeypatch):
    save()
    config, ledger, transport, runtime, _ = setup_runtime(
        tmp_path,
        monkeypatch,
        unlimited=True,
        duration_seconds=1,
    )
    # Past the original configured count and selected-fact settings' budget.
    for i in range(7):
        assert ledger.admit(f"old-{i}", allowed=True) == "accept"
        ledger.finish(f"old-{i}", "closed")

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            ncco = await admit(http, config)
            assert "limit" not in ncco[0]
            await transport.entered.wait()
            call = runtime.call
            assert call.conversation.unlimited
            await asyncio.sleep(1.1)
            assert runtime.call is call and not call.stopped.is_set()
            transport.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 2}})
            await finished(runtime)
            assert ledger.rows()[-1]["state"] == "closed"
        ledger.close()

    asyncio.run(scenario())
