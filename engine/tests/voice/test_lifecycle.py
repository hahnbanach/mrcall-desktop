"""Regression scenarios from the rejected M1 review, without paid transports."""

import asyncio
import json

import pytest

from zylch.services.voice.smoke_runtime import SmokeRuntime
from zylch.storage.voice_smoke import SmokeLedger

from .helpers import Socket, Transport, delegation, finished, incoming, setup


def test_lost_accept_response_retains_reservation_and_never_reaccepts(tmp_path):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path)
        transport.accept_error = TimeoutError("simulated lost response after paid dispatch")
        transport.hangup_ok = False
        runtime.incoming(incoming())
        await finished(runtime)
        runtime.incoming(incoming(event_id="another-delivery-id"))
        runtime.incoming(incoming("sess_other"))
        await finished(runtime)
        assert transport.accept_calls == ["sess_test"]
        assert transport.controls[0][1] == "hangup"
        assert ledger.rows()[0]["state"] == "uncertain"
        assert ledger.rows()[0]["reserved_microusd"] == 800_000
        assert ledger.rows()[1]["state"] == "rejected"
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("end", [None, RuntimeError("broken socket")])
def test_sideband_end_without_final_event_attempts_hangup(tmp_path, end):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path)
        transport.socket.events.put_nowait(end)
        runtime.incoming(incoming())
        await finished(runtime)
        assert transport.controls == [("sess_test", "hangup", None)]
        assert ledger.rows()[0]["state"] == "stopped"
        assert json.loads(ledger.rows()[0]["evidence"])["finalization"] == "incomplete"
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked_stage", ["accept", "attach", "receive"])
def test_watchdog_includes_accept_and_handshake(tmp_path, blocked_stage):
    async def scenario():
        config, ledger, transport, runtime = setup(tmp_path)
        # Test-only short deadline; production profile validation permits integer seconds only.
        runtime.config = config.model_copy(update={"duration_seconds": 0.03})
        if blocked_stage == "accept":
            transport.accept_block = asyncio.Event()
        if blocked_stage == "attach":
            transport.attach_block = asyncio.Event()
        transport.hangup_ok = False
        runtime.incoming(incoming())
        await finished(runtime)
        assert transport.controls == [("sess_test", "hangup", None)]
        row = ledger.rows()[0]
        assert row["state"] == "uncertain"
        assert json.loads(row["evidence"])["closure_trigger"] == "duration_limit"
        ledger.close()

    asyncio.run(scenario())


def test_delayed_result_does_not_block_transcript_or_hangup(tmp_path):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path, result_delay_seconds=1)
        for event in [
            delegation(),
            {"type": "session.input_transcript.delta", "delta": "private test utterance"},
            {"type": "session.closed", "usage": {"seconds": 1.5}},
        ]:
            transport.socket.events.put_nowait(event)
        runtime.incoming(incoming())
        await finished(runtime)
        assert transport.socket.sent == []
        assert transport.controls == []
        row = ledger.rows()[0]
        evidence = json.loads(row["evidence"])
        assert row["state"] == "closed"
        assert evidence["events"]["session.input_transcript.delta"] == 1
        assert evidence["voice_seconds"] == 1.5
        assert "private test utterance" not in row["evidence"]
        ledger.close()

    asyncio.run(scenario())


def test_delegation_once_and_next_call_has_no_prior_events(tmp_path):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path, result_delay_seconds=0)
        runtime.incoming(incoming())
        transport.socket.events.put_nowait(delegation())
        transport.socket.events.put_nowait(delegation())
        await asyncio.wait_for(transport.socket.result_sent.wait(), 1)
        result = transport.socket.sent[0]
        assert result["delegation_id"] == "delegation_test"
        assert result["event_id"].startswith("smoke_")
        transport.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 1}})
        await finished(runtime)
        assert len(transport.socket.sent) == 1
        transport.socket = Socket()
        transport.socket.events.put_nowait({"type": "session.closed"})
        runtime.incoming(incoming("sess_second"))
        await finished(runtime)
        assert json.loads(ledger.rows()[1]["evidence"])["events"] == {"session.closed": 1}
        ledger.close()

    asyncio.run(scenario())


def test_shutdown_hangs_up_drains_final_usage_and_cancels_work(tmp_path):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path)
        transport.close_on_hangup = True
        runtime.incoming(incoming())
        await transport.entered.wait()
        transport.socket.events.put_nowait(delegation())
        await runtime.shutdown()
        assert not runtime.tasks
        assert transport.socket.sent == []
        assert ledger.rows()[0]["state"] == "closed"
        assert json.loads(ledger.rows()[0]["evidence"])["voice_seconds"] == 2.0
        with pytest.raises(RuntimeError):
            runtime.incoming(incoming("sess_new"))
        ledger.close()

    asyncio.run(scenario())


def test_crash_recovery_does_cleanup_only_and_preserves_uncertainty(tmp_path):
    async def scenario():
        config, ledger, _, _ = setup(tmp_path)
        ledger.admit("sess_crashed", allowed=True)
        ledger.close()
        restarted = SmokeLedger(config.profile / "voice-smoke.db", config.policy_id, 800_000, 6)
        transport = Transport()
        transport.hangup_ok = False
        transport.ledger = restarted
        runtime = SmokeRuntime(config, restarted, transport)
        await runtime.recover()
        runtime.incoming(incoming("sess_new"))
        await finished(runtime)
        assert not transport.accept_calls
        assert transport.controls[0] == ("sess_crashed", "hangup", None)
        assert restarted.rows()[0]["reserved_microusd"] == 800_000
        assert restarted.rows()[0]["state"] == "uncertain"
        restarted.close()

    asyncio.run(scenario())


def test_wrong_destination_and_concurrent_call_never_accept(tmp_path):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path)
        runtime.incoming(incoming("sess_wrong", to="sip:production@elsewhere.test"))
        await finished(runtime)

        # Remove the fake boundary's first-row convenience assertion for this ordering.
        async def accept(session):
            transport.accept_calls.append(session)
            return True

        transport.accept = accept
        runtime.incoming(incoming())
        runtime.incoming(incoming("sess_second"))
        await transport.entered.wait()
        await runtime.shutdown()
        assert transport.accept_calls == ["sess_test"]
        assert ledger.rows()[0]["reserved_microusd"] == 0
        assert ledger.rows()[2]["reserved_microusd"] == 0
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failed_state", ["active", "uncertain", "stopped", "closed"])
def test_ledger_failure_cannot_prevent_provider_cleanup(tmp_path, failed_state):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path)
        real_finish = ledger.finish

        def fail_write(session, state, evidence=None):
            if state == failed_state:
                raise OSError("simulated disk full")
            real_finish(session, state, evidence)

        ledger.finish = fail_write
        if failed_state == "closed":
            transport.socket.events.put_nowait({"type": "session.closed"})
        else:
            transport.socket.events.put_nowait(None)
        runtime.incoming(incoming())
        await finished(runtime)
        assert runtime.stopping
        assert runtime.call is None
        if failed_state != "closed":
            assert transport.controls == [("sess_test", "hangup", None)]
        with pytest.raises(RuntimeError):
            runtime.incoming(incoming("sess_later"))
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["accept", "attach"])
@pytest.mark.parametrize("late_success", [False, True])
def test_shutdown_interrupts_setup_and_never_proceeds_after_late_completion(
    tmp_path, stage, late_success
):
    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path)
        entered = asyncio.Event()

        async def block():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if not late_success:
                    raise

        if stage == "accept":

            async def accept(session):
                transport.accept_calls.append(session)
                await block()
                return True

            transport.accept = accept
        else:
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def attach(session):
                await block()
                yield transport.socket

            transport.attach = attach
        runtime.incoming(incoming())
        await entered.wait()
        await asyncio.wait_for(runtime.shutdown(), 0.5)
        assert transport.controls == [("sess_test", "hangup", None)]
        assert not transport.entered.is_set()
        assert transport.socket.sent == []
        assert runtime.call is None
        assert ledger.rows()[0]["reserved_microusd"] == 800_000
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["hangup", "socket_close"])
def test_repeated_shutdown_does_not_cancel_finalizer(tmp_path, stage):
    from contextlib import asynccontextmanager

    async def scenario():
        _, ledger, transport, runtime = setup(tmp_path)
        entered = asyncio.Event()
        release = asyncio.Event()
        socket_closed = asyncio.Event()
        cancelled = []
        real_control = transport.control

        async def block():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(stage)
                raise

        async def control(session, action, payload=None):
            if stage == "hangup" and action == "hangup":
                await block()
            return await real_control(session, action, payload)

        @asynccontextmanager
        async def attach(session):
            try:
                yield transport.socket
            finally:
                if stage == "socket_close":
                    await block()
                socket_closed.set()

        transport.control = control
        transport.attach = attach
        transport.socket.events.put_nowait(None)
        runtime.incoming(incoming())
        await asyncio.wait_for(entered.wait(), 0.5)
        stops = [asyncio.create_task(runtime.shutdown()) for _ in range(2)]
        await asyncio.sleep(0)
        assert not any(task.done() for task in stops)
        release.set()
        await asyncio.wait_for(asyncio.gather(*stops), 0.5)
        assert cancelled == []
        assert socket_closed.is_set()
        assert runtime.call is None
        assert not runtime.tasks
        assert ledger.rows()[0]["state"] == "stopped"
        assert transport.controls == [("sess_test", "hangup", None)]
        ledger.close()

    asyncio.run(scenario())
