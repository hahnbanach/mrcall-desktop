"""Read-only selected facts for a server-bound caller, never owner's chat context."""

import asyncio
import logging
import re

from zylch.services.voice.agent_config import (
    Snapshot,
    fingerprint,
    require_binding,
    selected_rows,
)
from zylch.storage import database
from zylch.storage.storage import Storage
from zylch.tools.base import Tool, ToolResult, ToolStatus
from zylch.workers.memory import _normalise_phone

logger = logging.getLogger(__name__)


def result(recognition: str, facts: list | None = None, missing: str | None = None) -> ToolResult:
    return ToolResult(
        ToolStatus.SUCCESS,
        {"recognition": recognition, "facts": facts or [], "missing": [missing] if missing else []},
    )


class CallerMemory(Tool):
    """The phone and snapshot come from the adapter, never from model arguments.

    Snapshot once at call start. This fixture permission is recognition only,
    not proof of the caller's identity. No full blob, embedding service or LLM
    participates in lookup/ranking. Every output is safe for model input.
    """

    def __init__(self, snapshot: Snapshot, caller_number: str | None, *, timeout: float = 3.0):
        super().__init__(
            "caller_memory",
            "Read the permitted stored facts for this caller. An empty query returns all "
            "selected facts. A query uses literal word overlap, not semantic or multilingual "
            "search. If no words match, returns all still-permitted selected facts "
            "with a fallback label. Those facts may not answer the query; never invent "
            "missing details.",
        )
        self.snapshot = snapshot
        self.caller_number = caller_number
        self.timeout = timeout
        self.trace = None
        self.diagnostic_delay = 0
        self.diagnostic_failure = False

    def get_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "maxLength": 500}},
                "additionalProperties": False,
            },
        }

    async def execute(self, validation_only: bool = False, **kwargs) -> ToolResult:
        if self.trace:
            self.trace.record("memory_started", query=kwargs.get("query", ""))
        try:
            if self.diagnostic_delay:
                await asyncio.sleep(self.diagnostic_delay)
            if self.diagnostic_failure:
                found = ToolResult(
                    ToolStatus.ERROR, {"facts": []}, error="Caller memory unavailable"
                )
            else:
                found = await self._execute(validation_only, **kwargs)
            if self.trace:
                self.trace.record("memory_result", result=found.data, error=found.error)
            return found
        except asyncio.CancelledError:
            if self.trace:
                self.trace.record("memory_cancelled")
            raise

    async def _execute(self, validation_only=False, **kwargs):
        query = kwargs.get("query", "")
        if set(kwargs) - {"query"} or not isinstance(query, str) or len(query) > 500:
            return ToolResult(ToolStatus.ERROR, {"facts": []}, error="Invalid memory query")
        if validation_only:
            return result("not_checked")
        if not self.snapshot.config.enabled or "caller_memory" not in self.snapshot.config.tools:
            return ToolResult(ToolStatus.ERROR, {"facts": []}, error="Caller memory is disabled")
        try:
            async with asyncio.timeout(self.timeout):
                found = await asyncio.to_thread(self._lookup, query)
                # Include final membership validation in the same read deadline.
                await asyncio.to_thread(require_binding, self.snapshot.binding)
            logger.debug("[voice] caller_memory recognition=%s", found.data["recognition"])
            return found
        except TimeoutError:
            logger.debug("[voice] caller_memory timeout")
            return ToolResult(ToolStatus.ERROR, {"facts": []}, error="Caller memory timed out")
        except Exception:
            # SQL exceptions can contain a capability or sentence: no repr/traceback.
            logger.debug("[voice] caller_memory unavailable")
            return ToolResult(ToolStatus.ERROR, {"facts": []}, error="Caller memory unavailable")

    def _lookup(self, query: str) -> ToolResult:
        bound = self.snapshot.binding
        require_binding(bound)
        phone = _normalise_phone(self.caller_number or "")
        if not phone:
            return result("unknown", missing="Caller number is unavailable")
        matches = Storage.find_blobs_by_identifiers(
            bound.owner_uid,
            [("phone", phone)],
            raise_errors=True,
        )
        # Count all company matches before consulting the selection. An allowed
        # customer sharing a number with an unselected one is still ambiguous.
        if len(matches) != 1:
            return result(
                "ambiguous" if matches else "unknown",
                missing="Ask the caller for clarification",
            )
        customer = next(
            (c for c in self.snapshot.config.customers if c.blob_id == matches[0]), None
        )
        if customer is None:
            return result("unselected", missing="No permitted facts for this caller")
        pins = {(b, s): digest for b, s, digest in self.snapshot.pins}
        facts = []
        words = set(re.findall(r"\w+", query.casefold()))
        with database.get_session() as session:
            for row in selected_rows(session, bound, customer):
                if pins.get((customer.blob_id, row.id)) != fingerprint(row):
                    continue
                score = len(words & set(re.findall(r"\w+", row.sentence_text.casefold())))
                facts.append(
                    (
                        score,
                        {
                            "text": row.sentence_text,
                            "source": {"blob_id": customer.blob_id, "sentence_id": row.id},
                            "knowledge": "stored_history",
                        },
                    )
                )
        require_binding(bound)
        facts.sort(key=lambda item: (-item[0], item[1]["source"]["sentence_id"]))
        matching = [item for item in facts if item[0]] if words else facts
        fallback = bool(words and facts and not matching)
        facts = matching or facts
        found = result(
            "matched", [fact for _, fact in facts], None if facts else "No permitted fact found"
        )
        if fallback:
            found.data["retrieval"] = "selected_facts_fallback_no_lexical_match"
        return found
