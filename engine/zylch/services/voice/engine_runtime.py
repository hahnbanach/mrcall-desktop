"""Memory-backed calls on the M1 admission/closure ledger; no operator dependency."""

import asyncio
import logging
import re
from dataclasses import dataclass

from .agent_config import snapshot_for_call
from .caller_memory import CallerMemory
from .conversation import Conversation, VOICE_RULES
from .preparation import prepare_client
from .smoke_runtime import Call, SmokeRuntime
from .smoke_transport import carrier_token_hash

logger = logging.getLogger(__name__)


@dataclass(repr=False)
class PreparedCall:
    snapshot: object
    client: object
    caller: str | None


class EngineVoiceRuntime(SmokeRuntime):
    """Only the signed carrier ingress can prepare/bind a customer-service call."""

    def __init__(self, config, ledger, transport):
        super().__init__(config, ledger, transport)
        if not config.vonage_application_id:
            raise ValueError("Voice requires the isolated signed carrier route")
        self.pending = {}
        self.ready = False
        self.preparation_lock = asyncio.Lock()

    def _within_limits(self, snapshot):
        if self.config.unlimited:
            return not self.ledger.unresolved()
        rows = self.ledger.rows()
        held = sum(row["reserved_microusd"] for row in rows)
        count = sum(row["reserved_microusd"] > 0 for row in rows)
        limits = snapshot.config.limits
        return (
            count < min(limits.max_calls, self.config.max_calls)
            and held + self.config.reservation_microusd <= limits.budget_microusd
            and not self.ledger.unresolved()
        )

    async def available(self):
        if not self.ready or self.stopping or self.call or self.pending:
            return False
        try:
            from zylch.llm.budget import budget_snapshot

            snapshot = await asyncio.to_thread(snapshot_for_call, self.config.test_number)
            budget = await asyncio.to_thread(budget_snapshot, snapshot.binding.owner_uid)
            return self._within_limits(snapshot) and not budget["paused"]
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
                client = await prepare_client(snapshot)
                if self.stopping:
                    return None
                self.ready = True
                return snapshot, client
            except Exception:
                logger.debug("[voice] admission unavailable during preparation")
                return None

    def carrier_reserved(self, token_hash, payload, prepared):
        snapshot, client = prepared
        # The verified carrier callback, never an unbound SIP From or model
        # argument, supplies recognition metadata. It is not proof of identity.
        caller = payload.get("from")
        if not isinstance(caller, str) or len(caller) > 32:
            caller = None
        elif re.fullmatch(r"[1-9][0-9]{7,14}", caller):
            # Vonage answer callbacks use international digits without '+'.
            # Canonicalize this carrier representation at its trusted boundary.
            caller = "+" + caller
        self.pending[token_hash] = PreparedCall(snapshot, client, caller)

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
        call.duration_seconds = min(
            self.config.duration_seconds, prepared.snapshot.config.limits.duration_seconds
        )
        call.evidence.update(
            config_revision=prepared.snapshot.revision,
            engine_cost_microusd=None,
            engine_accounting="profile durable LLM ledger; dispatched holds survive closure",
        )
        return call

    async def accept_call(self, call):
        return await self.transport.accept(
            call.session_id, VOICE_RULES + "\n" + call.prepared.snapshot.config.instructions
        )

    def attached(self, call, ws):
        prepared = call.prepared
        memory = CallerMemory(prepared.snapshot, prepared.caller)

        async def send(raw):
            if call.allow_results and not call.stopped.is_set():
                await ws.send(raw)

        call.conversation = Conversation(
            prepared.snapshot,
            memory,
            prepared.client,
            send,
            call.evidence,
            unlimited=self.config.unlimited,
        )
        call.conversation.start()

    def event(self, call, event):
        if call.conversation and call.allow_results:
            call.conversation.event(event)
        return True

    async def shutdown(self):
        self.ready = False
        await super().shutdown()
        self.pending.clear()
