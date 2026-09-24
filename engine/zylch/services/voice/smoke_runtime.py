"""M1 lifecycle: durable admission, one reader, delayed fixed result, bounded close."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from zylch.storage.voice_smoke import SmokeLedger

from .smoke_config import SmokeConfig
from .smoke_transport import carrier_token_hash, command, incoming_session

logger = logging.getLogger(__name__)
FIXED_FACT = "The isolated test case is ready for the demonstration."
OBSERVED_EVENTS = {
    "session.started",
    "session.commentary.appended",
    "session.thinking.appended",
    "session.instructions.appended",
    "session.input_transcript.delta",
    "session.output_transcript.delta",
    "session.delegation.created",
    "session.closed",
    "session.output_audio.delta",
    "session.input_audio.append",
    "error",
}


@dataclass
class Call:
    session_id: str
    started: float = field(default_factory=time.monotonic)
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    finalized: bool = False
    allow_results: bool = True
    interruptible: bool = False
    task: asyncio.Task | None = None
    worker: asyncio.Task | None = None
    conversation: object | None = None
    trace: object | None = None
    prepared: object | None = None
    duration_seconds: int | None = None
    seen_delegations: set[str] = field(default_factory=set)
    evidence: dict = field(
        default_factory=lambda: {
            "events": {},
            "results_sent": 0,
            "finalization": "incomplete",
            "voice_seconds": None,
            "carrier_cost": "unverified",
            "engine_cost_microusd": 0,
        }
    )


class SmokeRuntime:
    def __init__(self, config: SmokeConfig, ledger: SmokeLedger, transport) -> None:
        self.config, self.ledger, self.transport = config, ledger, transport
        self.stopping = False
        self.tasks: set[asyncio.Task] = set()
        self.call: Call | None = None
        self.finalization_timeout = 5.0

    def incoming(self, event: dict) -> None:
        """No await between reserving and scheduling: shutdown cannot miss a call."""
        parsed = incoming_session(event, self.config.sip_to_uri)
        if parsed is None:
            return
        session_id, route_matches = parsed
        if self.stopping:
            raise RuntimeError("smoke is stopping")
        allowed = route_matches and self.call is None
        if self.config.vonage_application_id:
            decision = self.ledger.bind_carrier(
                session_id, carrier_token_hash(event), allowed=allowed
            )
        else:
            decision = self.ledger.admit(session_id, allowed=allowed)
        logger.debug("[voice-smoke] admission=%s", decision)
        if decision == "duplicate":
            return
        if decision == "accept":
            self.call = self.new_call(session_id, event)
            task = asyncio.create_task(self._run(self.call))
            self.call.task = task
        else:
            task = asyncio.create_task(self._reject(session_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def new_call(self, session_id: str, event: dict) -> Call:
        return Call(session_id)

    async def accept_call(self, call: Call) -> bool:
        return await self.transport.accept(call.session_id)

    def attached(self, call: Call, ws) -> None:
        pass

    def event(self, call: Call, event: dict) -> bool:
        return False

    def _record(self, session_id: str, state: str, evidence: dict | None = None) -> None:
        """Fail closed on disk errors, but never let them prevent provider cleanup."""
        try:
            self.ledger.finish(session_id, state, evidence)
        except Exception:
            self.stopping = True
            logger.error("[voice-smoke] ledger write failed; new admissions disabled")

    async def _control(self, session_id: str, action: str, payload: dict | None = None) -> bool:
        try:
            async with asyncio.timeout(8):
                return await self.transport.control(session_id, action, payload)
        except Exception:
            # Exceptions from transports can contain headers, URLs, and bodies.
            logger.warning("[voice-smoke] control outcome uncertain action=%s", action)
            return False

    async def _reject(self, session_id: str) -> None:
        confirmed = await self._control(session_id, "reject", {"status_code": 486})
        self._record(
            session_id,
            "rejected" if confirmed else "uncertain",
            {
                "rejection_confirmed": confirmed,
                "finalization": "not_started",
            },
        )

    async def recover(self) -> None:
        """Restart never re-accepts; attempt cleanup only, retaining every reservation."""
        for session_id in self.ledger.unresolved():
            if session_id.startswith("vonage:"):
                # No OpenAI session exists to hang up. Keep the carrier hold and
                # require supervised reconciliation; never accept after restart.
                self.ledger.finish(session_id, "uncertain")
                continue
            confirmed = await self._control(session_id, "hangup")
            self.ledger.finish(
                session_id,
                "stopped" if confirmed else "uncertain",
                {
                    "hangup_confirmed": confirmed,
                    "finalization": "incomplete",
                    "recovered_after_restart": True,
                },
            )

    async def _run(self, call: Call) -> None:
        call.interruptible = True
        reader = stop_waiter = None
        stack = AsyncExitStack()
        reason = "sideband_eof"
        try:
            # Deadline starts before accept, not after the sideband handshake.
            async with asyncio.timeout(
                None
                if self.config.unlimited
                else (call.duration_seconds or self.config.duration_seconds)
            ):
                if call.stopped.is_set():
                    reason = "shutdown"
                    return
                if not await self.accept_call(call):
                    reason = "accept_unconfirmed"
                    return
                self._record(call.session_id, "active")
                if call.stopped.is_set() or self.stopping:
                    reason = "shutdown"
                    return
                ws = await stack.enter_async_context(self.transport.attach(call.session_id))
                if call.stopped.is_set() or self.stopping:
                    reason = "shutdown"
                    return
                self.attached(call, ws)
                reader = asyncio.create_task(self._read(ws, call))
                stop_waiter = asyncio.create_task(call.stopped.wait())
                done, _ = await asyncio.wait(
                    [reader, stop_waiter], return_when=asyncio.FIRST_COMPLETED
                )
                if reader in done:
                    await reader
                else:
                    reason = "shutdown"
        except TimeoutError:
            reason = "duration_limit"
        except asyncio.CancelledError:
            reason = "cancelled"
        except Exception:
            reason = "transport_error"
        finally:
            # Shutdown may interrupt setup/active work, never bounded cleanup.
            call.interruptible = False
            call.allow_results = False
            if call.conversation:
                await call.conversation.close()
            if call.worker:
                call.worker.cancel()
                await asyncio.gather(call.worker, return_exceptions=True)
            confirmed = False
            if not call.finalized:
                self._record(call.session_id, "uncertain")
                confirmed = await self._control(call.session_id, "hangup")
                # Keep the receiver attached for final usage after hangup.
                if reader and not reader.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(reader), self.finalization_timeout)
                    except (Exception, asyncio.CancelledError):
                        pass
            for task in (reader, stop_waiter):
                if task:
                    task.cancel()
            await asyncio.gather(*(t for t in (reader, stop_waiter) if t), return_exceptions=True)
            try:
                async with asyncio.timeout(3):
                    await stack.aclose()
            except Exception:
                pass
            state = "closed" if call.finalized else ("stopped" if confirmed else "uncertain")
            call.evidence.update(
                {
                    "closure_trigger": reason,
                    "hangup_confirmed": confirmed,
                    "observed_elapsed_ms": round((time.monotonic() - call.started) * 1000),
                }
            )
            if call.trace:
                try:
                    call.trace.record("call_finished", state=state, evidence=call.evidence)
                    call.trace.close()
                except Exception:
                    call.evidence["diagnostics"] = "incomplete"
                    logger.warning("[voice] diagnostic finalization incomplete")
            self._record(call.session_id, state, call.evidence)
            logger.info("[voice-smoke] call finished state=%s", state)
            if self.call is call:
                self.call = None

    async def _read(self, ws, call: Call) -> None:
        try:
            await self._events(ws, call)
        finally:
            call.allow_results = False

    async def _events(self, ws, call: Call) -> None:
        async for raw in ws:
            event = json.loads(raw)
            kind = event.get("type")
            if kind not in OBSERVED_EVENTS:
                continue
            counts = call.evidence["events"]
            counts[kind] = counts.get(kind, 0) + 1
            # Observe before closure disables conversation; audio metadata only.
            handled = self.event(call, event)
            if kind == "session.output_audio.delta":
                call.evidence.setdefault(
                    "first_audio_ms", round((time.monotonic() - call.started) * 1000)
                )
            elif kind == "session.closed":
                call.finalized = True
                call.allow_results = False
                if call.conversation:
                    await call.conversation.close()
                call.evidence["finalization"] = "confirmed"
                usage = event.get("usage")
                seconds = usage.get("seconds") if isinstance(usage, dict) else None
                if type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0:
                    call.evidence["voice_seconds"] = seconds
                    call.evidence["voice_cost_estimate_microusd"] = math.ceil(
                        seconds * self.config.voice_per_minute_microusd / 60
                    )
                return
            elif kind == "error":
                raise RuntimeError("Live session error")
            elif handled:
                continue
            elif kind == "session.delegation.created" and call.allow_results:
                delegation = event.get("delegation", {})
                identifier = delegation.get("id")
                if delegation.get("target") != "client" or not isinstance(identifier, str):
                    continue
                if identifier in call.seen_delegations:
                    continue
                if not self.config.unlimited and len(call.seen_delegations) >= 16:
                    raise RuntimeError("smoke delegation limit exceeded")
                call.seen_delegations.add(identifier)
                # M1 needs one demonstrated delegation. Multiple requests while
                # it waits are coalesced; there is no general agent scheduler yet.
                if call.worker is None or call.worker.done():
                    call.worker = asyncio.create_task(self._result(ws, call, identifier))
        call.allow_results = False

    async def _result(self, ws, call: Call, identifier: str) -> None:
        await asyncio.sleep(self.config.result_delay_seconds)
        if not call.allow_results or call.stopped.is_set():
            return
        try:
            await ws.send(command("session.commentary.append", FIXED_FACT, identifier))
            call.evidence["results_sent"] += 1
        except Exception:
            call.stopped.set()

    async def shutdown(self) -> None:
        self.stopping = True
        if self.call:
            self.call.allow_results = False
            self.call.stopped.set()
            # Cancel an in-progress accept/attach as well as an attached call.
            # If its coroutine hasn't started, let it observe stopped first so
            # its finally still performs cleanup of the committed reservation.
            if self.call.interruptible and self.call.task:
                # Repeated/concurrent shutdown must not inject a second cancel
                # after the first has transferred execution into the finalizer.
                self.call.interruptible = False
                self.call.task.cancel()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
