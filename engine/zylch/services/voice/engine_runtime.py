"""Memory-backed calls on the M1 admission/closure ledger; no operator dependency."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass

from .agent_config import snapshot_for_call
from .caller_memory import CallerMemory
from .conversation import Conversation, VOICE_RULES
from .preparation import prepare_call
from .diagnostics import CallTrace, DiagnosticOptions
from .smoke_runtime import Call, SmokeRuntime
from .smoke_transport import carrier_token_hash

logger = logging.getLogger(__name__)


@dataclass(repr=False)
class PreparedCall:
    snapshot: object
    caller: str | None
    business_version: int | None = None


class EngineVoiceRuntime(SmokeRuntime):
    """Only the signed carrier ingress can prepare/bind a customer-service call."""

    def __init__(self, config, ledger, transport):
        super().__init__(config, ledger, transport)
        if not config.vonage_application_id:
            raise ValueError("Voice requires the isolated signed carrier route")
        self.production = hasattr(config, "expected_business")
        self.diagnostics = (
            DiagnosticOptions.for_production(config)
            if self.production else DiagnosticOptions.load(config.profile)
        )
        self.pending = {}
        self.ready = False
        self.preparation_lock = asyncio.Lock()

    def _within_limits(self, snapshot):
        if self.production and (
            snapshot.config.policy != "production"
            or snapshot.config.business_id != self.config.business_id
            or snapshot.config.limits is not None
        ):
            return False
        if self.config.unlimited:
            return (
                self.ledger.admission_ready()
                if self.production else not self.ledger.unresolved()
            )
        rows = self.ledger.rows()
        held = sum(row["reserved_microusd"] for row in rows)
        count = sum(row["reserved_microusd"] > 0 for row in rows)
        limits = snapshot.config.limits
        return (
            count < min(limits.max_calls, self.config.max_calls)
            and held + self.config.reservation_microusd <= limits.budget_microusd
            and not self.ledger.unresolved()
        )

    async def _prepare(self, snapshot, previous_version=None):
        if self.production:
            return await prepare_call(
                snapshot, self.config.expected_business, previous_version
            )
        return await prepare_call(snapshot)

    async def available(self):
        if not self.ready or self.stopping or self.call or self.pending:
            return False
        try:
            snapshot = await asyncio.to_thread(snapshot_for_call, self.config.test_number)
            await self._prepare(snapshot)
            return self._within_limits(snapshot)
        except Exception:
            return False

    async def prepare_carrier(self):
        # Preparation must precede NCCO and paid admission. Serializing this
        # phase keeps refresh/DB initialization bounded under callback races.
        async with self.preparation_lock:
            if self.stopping or self.call or self.pending:
                return None
            self.ready = False
            try:
                snapshot = await asyncio.to_thread(snapshot_for_call, self.config.test_number)
                if not self._within_limits(snapshot):
                    return None
                verified = await self._prepare(snapshot)
                if self.stopping:
                    return None
                self.ready = True
                return (snapshot, verified)
            except Exception:
                logger.debug("[voice] admission unavailable during preparation")
                return None

    def carrier_reserved(self, token_hash, payload, prepared):
        snapshot = prepared[0]
        # The verified carrier callback, never an unbound SIP From or model
        # argument, supplies recognition metadata. It is not proof of identity.
        caller = payload.get("from")
        if not isinstance(caller, str) or len(caller) > 32:
            caller = None
        elif re.fullmatch(r"[1-9][0-9]{7,14}", caller):
            # Vonage answer callbacks use international digits without '+'.
            # Canonicalize this carrier representation at its trusted boundary.
            caller = "+" + caller
        verified = prepared[1]
        self.pending[token_hash] = PreparedCall(
            snapshot, caller, verified.version if verified is not None else None
        )

    def incoming(self, event):
        digest = carrier_token_hash(event)
        if digest not in self.pending:
            # Unknown/replayed ingress must still use M1 durable rejection,
            # deduplication and uncertain-closure handling.
            old = self.call
            if old is None:
                self.call = Call("unprepared")
            try:
                super().incoming(event)
            finally:
                self.call = old
            return
        super().incoming(event)

    def new_call(self, session_id, event):
        prepared = self.pending.pop(carrier_token_hash(event))
        call = Call(session_id, prepared=prepared)
        if not self.production:
            call.duration_seconds = min(
                self.config.duration_seconds, prepared.snapshot.config.limits.duration_seconds
            )
        call.evidence.update(
            config_revision=prepared.snapshot.revision,
            conversational_model="gpt-live-1",
            delegated_engine_model=None,
            engine_accounting="no telephone backend LLM dispatch",
        )
        return call

    async def accept_call(self, call):
        instructions = call.prepared.snapshot.config.instructions + "\n" + VOICE_RULES
        if self.production:
            await self._prepare(call.prepared.snapshot, call.prepared.business_version)
            # Resolve only the selected display name before Live's first turn.
            # A missing/ambiguous match gets the generic approved greeting.
            memory = CallerMemory(call.prepared.snapshot, call.prepared.caller)
            recognized = await memory.execute()
            # The lookup can outlive a remote business or local binding change.
            # Do not send even an approved name after that change.
            current = await asyncio.to_thread(snapshot_for_call, self.config.test_number)
            if current.revision != call.prepared.snapshot.revision:
                raise ValueError("Voice configuration changed during caller lookup")
            await self._prepare(call.prepared.snapshot, call.prepared.business_version)
            name = (recognized.data or {}).get("display_name") if not recognized.error else None
            salutation = f"Buongiorno {name}" if name else "Buongiorno"
            instructions += (
                "\nAt the start of this call, say in Italian: '"
                f"{salutation}, sono l'assistente di Café 124. Come posso aiutarla?' "
                "Then listen. The name, if present, comes from an approved phone match "
                "and is not proof of identity."
            )
            if call.prepared.snapshot.config.caller_context_policy == "on_demand_review":
                instructions += (
                    " Do not mention customer history in the greeting. When the caller "
                    "asks for information, first judge whether consulting their memory "
                    "is legitimate for this request. Delegate to the client only then. "
                    "For 'what information do you have about me', consult the matched "
                    "contact, then decide what is relevant and safe to say. A phone "
                    "match alone does not verify identity; never disclose secrets, "
                    "sensitive private details, internal notes, or another person's data."
                )
            else:
                instructions += " Do not mention other customer history."
        return await self.transport.accept(call.session_id, instructions)

    def attached(self, call, ws):
        prepared = call.prepared
        memory = CallerMemory(prepared.snapshot, prepared.caller)
        call.trace = CallTrace(
            self.config.profile,
            call.session_id,
            prepared.snapshot.revision,
            call.evidence,
            self.diagnostics,
        )
        memory.diagnostic_delay = self.diagnostics.lookup_delay
        memory.diagnostic_failure = self.diagnostics.fail_lookup

        async def send(raw):
            if call.allow_results and not call.stopped.is_set():
                if self.production:
                    try:
                        current = await asyncio.to_thread(
                            snapshot_for_call, self.config.test_number
                        )
                        if current.revision != prepared.snapshot.revision:
                            raise ValueError("Voice configuration changed during call")
                        await self._prepare(prepared.snapshot, prepared.business_version)
                    except Exception:
                        call.evidence["binding_invalidated"] = True
                        call.stopped.set()
                        raise ValueError("Voice binding unavailable during call") from None
                conversation = call.conversation
                if (
                    conversation
                    and conversation.send_guard_revision is not None
                    and conversation.send_guard_revision != conversation.revision
                ):
                    return False
                await ws.send(raw)
            else:
                raise RuntimeError("Call closed before append")

        call.conversation = Conversation(
            prepared.snapshot,
            memory,
            send,
            call.evidence,
            unlimited=self.config.unlimited,
            trace=call.trace,
            backend_delay=self.diagnostics.backend_delay,
        )
        call.conversation.start()
        if self.production:
            task = asyncio.create_task(self._meter(call))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            watcher = asyncio.create_task(self._watch_binding(call))
            self.tasks.add(watcher)
            watcher.add_done_callback(self.tasks.discard)

    async def _watch_binding(self, call):
        while call.allow_results and not call.stopped.is_set():
            await asyncio.sleep(5)
            if not call.allow_results or call.stopped.is_set():
                return
            try:
                current = await asyncio.to_thread(
                    snapshot_for_call, self.config.test_number
                )
                if current.revision != call.prepared.snapshot.revision:
                    raise ValueError("Voice configuration changed during call")
                await self._prepare(
                    call.prepared.snapshot, call.prepared.business_version
                )
            except Exception:
                call.evidence["binding_invalidated"] = True
                call.stopped.set()
                logger.warning("[voice] active call binding invalidated")
                return

    async def _meter(self, call):
        rate = (
            self.config.voice_per_minute_microusd
            + self.config.carrier_per_minute_microusd
        )
        while call.allow_results and not call.stopped.is_set():
            try:
                elapsed = time.monotonic() - call.started
                await asyncio.to_thread(self.ledger.accrue, call.session_id, elapsed, rate)
            except Exception:
                # End an unmetered call through the normal bounded hangup path.
                # Its hold stays uncertain and blocks further admission.
                self.stopping = True
                call.evidence["exposure"] = "uncertain"
                logger.error("[voice] production exposure accrual failed")
                call.stopped.set()
                return
            await asyncio.sleep(5)

    def _record(self, session_id, state, evidence=None):
        if self.production and evidence and evidence.get("exposure") == "uncertain":
            state = "uncertain"
        super()._record(session_id, state, evidence)

    def event(self, call, event):
        if self.production and event.get("type") == "session.closed":
            usage = event.get("usage")
            seconds = usage.get("seconds") if isinstance(usage, dict) else None
            if type(seconds) in (int, float):
                self.ledger.record_provider_usage(call.session_id, seconds=seconds)
        if call.conversation and call.allow_results:
            call.conversation.event(event)
        return True

    async def shutdown(self):
        self.ready = False
        await super().shutdown()
        self.pending.clear()
