"""Read-only selected facts for a server-bound caller, never owner's chat context."""

import asyncio
import logging
import re

import phonenumbers
from sqlalchemy import select

from zylch.memory.scope import blob_visible, sentences_in_scope
from zylch.services.voice.agent_config import (
    Snapshot,
    fingerprint,
    require_binding,
    selected_rows,
)
from zylch.storage import database
from zylch.storage.models import Blob, BlobSentence
from zylch.storage.storage import Storage
from zylch.tools.base import Tool, ToolResult, ToolStatus
from zylch.workers.memory import _normalise_phone

logger = logging.getLogger(__name__)
MAX_REVIEW_ROWS = 24
MAX_REVIEW_BYTES = 12_000
PRIVATE_MARKER = re.compile(
    r"\b(?:internal|confidential|riservat[oaie]|privat[oaie]|"
    r"segreto|secret|password|token|api[_ -]?key|memory[_ -]?key|"
    r"do not share|non condivid\w*)\b",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|whsec_[A-Za-z0-9_-]{8,}|"
    r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|"
    r"sk_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|\b[A-Za-z0-9_-]{48,}\b)"
)
CONTACT_DETAIL = re.compile(r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\+\d{9,15}\b)")
BROAD_PERSONAL_QUESTION = re.compile(
    r"\b(?:"
    r"(?:cosa|quali|che)\b.{0,40}\b(?:sai|sapete|hai|avete|conosci|conoscete|informazioni)"
    r"\b.{0,40}\b(?:di|su di) me|"
    r"chi sono|mio ruolo|mia posizione|(?:che|quale) ruolo|"
    r"what do you know about me|who am i|my role|my information"
    r")\b",
    re.IGNORECASE,
)


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
        on_demand = self.snapshot.config.caller_context_policy == "on_demand_review"
        if self.trace:
            self.trace.record(
                "memory_started",
                **(
                    {"query_present": bool(kwargs.get("query"))}
                    if on_demand
                    else {"query": kwargs.get("query", "")}
                ),
            )
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
                self.trace.record(
                    "memory_result",
                    **(
                        {
                            "recognition": (found.data or {}).get("recognition"),
                            "candidate_count": len((found.data or {}).get("facts") or []),
                            "error": found.error,
                        }
                        if on_demand
                        else {"result": found.data, "error": found.error}
                    ),
                )
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
        raw_phone = self.caller_number or ""
        # Vonage sends E.164 digits; fixtures and other adapters may include
        # harmless separators or a 00 prefix. Reject text before normalizing,
        # since the memory index normalizer intentionally clips narrative tails.
        if not re.fullmatch(r"(?:\+[1-9]|00[1-9])[0-9\s()./\-]*", raw_phone):
            return result("unknown", missing="Caller number is unavailable or invalid")
        phone = _normalise_phone(raw_phone)
        if not phone or not phone.startswith("+"):
            return result("unknown", missing="Caller number is unavailable or invalid")
        try:
            if not phonenumbers.is_valid_number(phonenumbers.parse(phone, None)):
                return result("unknown", missing="Caller number is unavailable or invalid")
        except phonenumbers.NumberParseException:
            return result("unknown", missing="Caller number is unavailable or invalid")
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
        if self.snapshot.config.caller_context_policy == "on_demand_review":
            return self._on_demand(bound, customer, query)
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
        if customer.display_name:
            found.data["display_name"] = customer.display_name
        if fallback:
            found.data["retrieval"] = "selected_facts_fallback_no_lexical_match"
        return found

    def _on_demand(self, bound, customer, query: str) -> ToolResult:
        found = result("matched")
        found.data["display_name"] = customer.display_name
        if not query.strip():
            return found
        with database.get_session() as session:
            rows = session.execute(
                select(BlobSentence.id, BlobSentence.sentence_text)
                .join(Blob, Blob.id == BlobSentence.blob_id)
                .where(
                    blob_visible(bound.owner_uid, bound.company_key),
                    Blob.namespace == f"user:{bound.company_key}",
                    Blob.id == customer.blob_id,
                    sentences_in_scope(bound.company_key),
                )
                .order_by(BlobSentence.id)
                .limit(MAX_REVIEW_ROWS + 1)
            ).all()
        require_binding(bound)
        if len(rows) > MAX_REVIEW_ROWS:
            found.data["missing"] = ["Caller history exceeds review size"]
            return found
        broad = bool(BROAD_PERSONAL_QUESTION.search(query))
        query_words = set(re.findall(r"\w+", query.casefold()))
        eligible = []
        for row in rows:
            source = row.sentence_text
            if PRIVATE_MARKER.search(source) or SECRET_VALUE.search(source):
                continue
            if not broad and not (query_words & set(re.findall(r"\w+", source.casefold()))):
                continue
            eligible.append((row.id, CONTACT_DETAIL.sub("[contact detail omitted]", source)))
        if sum(len(text.encode()) for _, text in eligible) > MAX_REVIEW_BYTES:
            found.data["missing"] = ["Caller history exceeds review size"]
            return found
        found.data["facts"] = [
            {
                "text": text,
                "source": {"blob_id": customer.blob_id, "sentence_id": sentence_id},
                "knowledge": "unreviewed_stored_history",
            }
            for sentence_id, text in eligible
        ]
        if not eligible:
            found.data["missing"] = ["No relevant caller history available for review"]
        return found
