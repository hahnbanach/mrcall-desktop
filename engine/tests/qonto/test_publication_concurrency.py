"""Real concurrent RPC revocation during blocking publication model work."""

import asyncio
import threading

import pytest

from .chat_fixture import reservations
from .test_publication import publishing as publishing_fixture, issue, decision, records
from .test_reads import bank as bank_fixture

publishing = publishing_fixture
bank = bank_fixture


@pytest.mark.parametrize("action", ["disconnect", "cancel", "pause"])
def test_waiting_publication_keeps_rpc_loop_responsive_and_cancel_authority(
    publishing, monkeypatch, action
):
    env, api, wire = publishing
    from zylch.memory.mnemonic import commit
    from zylch.memory.mnemonic.authorization import active_grant
    from zylch.qonto.publication_guard import _scope
    from zylch.services.preparation import current_item, current_run
    from zylch.storage.database import get_engine

    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    started, release, completed = threading.Event(), threading.Event(), threading.Event()
    observed = {}
    real_submit = commit.submit

    def tracked_submit(event, **kwargs):
        observed["event"] = event
        try:
            return real_submit(event, **kwargs)
        finally:
            completed.set()

    def provider_wait(_):
        observed["grant"] = active_grant()
        observed["publication"] = _scope.get()
        observed["item"] = current_item()
        observed["run"] = current_run()
        started.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(commit, "submit", tracked_submit)
    wire.callback = provider_wait

    async def scenario():
        task = asyncio.create_task(
            env.arpc("qonto.publish", preview_id=preview["preview_id"], confirmed=True)
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            if action == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert observed["event"].cancellation.cancelled
            else:
                method = "qonto.disconnect" if action == "disconnect" else "preparation.pause"
                response = await asyncio.wait_for(env.arpc(method), timeout=1)
                assert "result" in response, response
                if action == "pause":
                    assert response["result"]["paused"] is True
        finally:
            release.set()
            if not task.done():
                await task
            assert await asyncio.to_thread(completed.wait, 3)
        return None if task.cancelled() else task.result()

    result = asyncio.run(scenario())
    event = observed["event"]
    assert observed["grant"].cancellation is event.cancellation
    assert observed["publication"].event is event
    assert observed["item"][1:3] == ("memory:qonto", event.source_id)
    assert observed["item"][3] == observed["run"][1]
    assert len(wire.calls) == reservations() == 1
    with get_engine().connect() as conn:
        assert conn.exec_driver_sql("SELECT settled_at FROM llm_reservations").scalar() is not None
    assert result is None or "error" in result or result["result"]["status"] != "committed"
    assert records()[0] == []
    assert records()[1][0]["state"] != "committed"
    if action == "pause":
        from zylch.qonto.models import QontoPublicationIntent
        from zylch.qonto.repository import profile_transaction

        with profile_transaction() as session:
            intent = session.get(QontoPublicationIntent, preview["preview_id"])
            assert intent.state == "confirmed" and not intent.committed_ids
