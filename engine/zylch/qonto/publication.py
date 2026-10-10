"""Explicit consent and bounded mnemonic publication of a minimal bank fact."""

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import replace

from zylch.memory.company_key import current_company_key
from zylch.memory.mnemonic import commit, journal
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    FACT,
    MemoryEvent,
    SubjectHint,
)
from zylch.memory.mnemonic.wiring import default_context
from zylch.qonto import guard, reads
from zylch.qonto.errors import QontoError
from zylch.qonto.logging import private_scope
from zylch.qonto.models import QontoAccount, QontoPublicationIntent
from zylch.qonto.publication_guard import PublicationGuard, scope
from zylch.qonto.repository import profile_transaction
from zylch.services.preparation import bounded_item, preparation_run
from zylch.storage.models import Blob, MemoryOperation

RULE = "minimal-company-fact-v1"
TTL = 900
DISCLOSURE = (
    "This fact is shared with all current and future holders of this company's memory key. "
    "The fact may be processed by the selected LLM service. It remains historical company "
    "knowledge after disconnect or imported-data deletion; its bank source then becomes unavailable."
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _projection(authority, binding):
    with profile_transaction() as session:
        rows = (
            session.query(QontoAccount.account_id, QontoAccount.currency)
            .filter(
                QontoAccount.uid == authority.uid,
                QontoAccount.dataset_id == binding.dataset_id,
                QontoAccount.account_id.in_(binding.account_ids),
                QontoAccount.selected.is_(True),
            )
            .all()
        )
    if set(a for a, _ in rows) != set(binding.account_ids):
        raise QontoError("accounts_invalid")
    currencies = sorted(set(c for _, c in rows))
    if any(
        not isinstance(c, str) or len(c) != 3 or not c.isascii() or not c.isupper()
        for c in currencies
    ):
        raise QontoError("accounts_invalid")
    source = _digest(
        [binding.dataset_id, binding.organization_id, sorted((a, c) for a, c in rows), RULE]
    )
    fact = (
        "Category: finance\nKey: qonto\nValue: The company uses Qonto. Selected business-account currencies: "
        + ", ".join(currencies)
        + "."
    )
    return fact, source


def _target():
    from zylch.memory.join_import import parse_fact

    with journal.company_transaction() as session:
        matches = [
            (str(row.id), row.updated_at.isoformat())
            for row in session.query(Blob)
            .filter(Blob.namespace == "facts:" + current_company_key())
            .all()
            if parse_fact(row.content) == ("finance", "qonto")
        ]
    if len(matches) > 1:
        raise QontoError("operation_failed")
    return matches[0] if matches else None


async def preview(params=None):
    if params not in (None, {}):
        raise QontoError("operation_failed")
    with private_scope():
        authority, binding = await reads.authorize()
        fact, revision = _projection(authority, binding)
        target = _target()
        data = dict(
            fact_text=fact,
            disclosure=DISCLOSURE,
            expires_at=time.time() + TTL,
            host_id=authority.host_id,
            organization_id=binding.organization_id,
            account_ids=list(binding.account_ids),
            target=target,
        )
        intent_id = uuid.uuid4().hex
        with guard.commit_guard(authority, binding) as session:
            session.add(
                QontoPublicationIntent(
                    id=intent_id,
                    uid=authority.uid,
                    dataset_id=binding.dataset_id,
                    company_scope=authority.company_scope,
                    generation=binding.generation,
                    source_revision=revision,
                    state="pending",
                    created_at=time.time(),
                    preview=data,
                    event_id=_digest(
                        [authority.uid, binding.dataset_id, binding.generation, revision, RULE]
                    ),
                )
            )
        return dict(
            preview_id=intent_id,
            fact_text=fact,
            disclosure=DISCLOSURE,
            generation=binding.generation,
            expires_at=data["expires_at"],
        )


def _event(authority, binding, intent):
    target = intent.preview.get("target")
    return MemoryEvent(
        owner_id=authority.uid,
        company_key=current_company_key(),
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="qonto",
        source_id=_digest([binding.dataset_id, RULE, intent.source_revision]),
        source_revision=intent.source_revision,
        observation=intent.preview["fact_text"],
        event_id=intent.event_id,
        subject_hint=SubjectHint(entity_type=FACT, target_blob_id=target[0] if target else None),
        stage="memory:qonto",
    )


def _checkpoint(authority, binding, intent_id, result):
    with guard.commit_guard(authority, binding) as session:
        row = session.get(QontoPublicationIntent, intent_id)
        if row is None or row.state == "cancelled":
            raise QontoError("generation_changed")
        row.state = (
            result.outcome
            if result.advances_checkpoint or result.outcome == "review_needed"
            else "confirmed"
        )
        row.committed_ids = [list(pair) for pair in result.committed_ids]


class Publisher:
    def __init__(self, authority, binding, intent, event):
        self.owner_id = authority.uid
        self.authority, self.binding, self.intent, self.event = authority, binding, intent, event
        self.result = None

    @bounded_item("memory:qonto")
    async def run(self, data):
        target = self.intent.preview.get("target")
        publication = PublicationGuard(
            self.authority,
            self.binding,
            self.intent.id,
            self.event,
            tuple(target) if target else None,
        )
        with scope(publication):
            base = default_context(self.owner_id, retrieval=False)

            def projection_target(blob_id):
                value = base.get_blob(blob_id)
                if value is None or not target or blob_id != target[0]:
                    return None
                return {**value, "content": self.event.observation}

            context = replace(
                base,
                get_blob=projection_target,
                commit_guard=publication.commit,
                commit_check=publication.check,
                proposal_validator=publication.validate,
            )
            try:
                self.result = await asyncio.to_thread(commit.submit, self.event, context=context)
            except asyncio.CancelledError:
                self.event.cancellation.cancel("Publication cancelled by caller.")
                raise
            publication.check()
            if self.result.refusal is not None:
                raise self.result.refusal
            _checkpoint(self.authority, self.binding, self.intent.id, self.result)
        return self.result.advances_checkpoint


async def publish(params):
    if (
        not isinstance(params, dict)
        or set(params) - {"preview_id", "confirmed", "resume"}
        or params.get("confirmed") is not True
        or not isinstance(params.get("preview_id"), str)
        or ("resume" in params and type(params["resume"]) is not bool)
    ):
        return {
            "status": "refused",
            "reason": "Confirm the exact engine-issued publication preview.",
        }
    with private_scope():
        authority, binding = await reads.authorize()
        fact, revision = _projection(authority, binding)
        with guard.commit_guard(authority, binding) as session:
            intent = session.get(QontoPublicationIntent, params["preview_id"])
            if (
                intent is None
                or intent.uid != authority.uid
                or intent.dataset_id != binding.dataset_id
                or intent.company_scope != authority.company_scope
                or intent.generation != binding.generation
                or intent.source_revision != revision
                or intent.preview.get("fact_text") != fact
                or intent.preview.get("host_id") != authority.host_id
                or intent.preview.get("organization_id") != binding.organization_id
                or intent.preview.get("account_ids") != list(binding.account_ids)
                or intent.state == "cancelled"
                or (intent.preview["expires_at"] < time.time() and intent.consent_at is None)
            ):
                return {
                    "status": "refused",
                    "reason": "Publication preview is unavailable or changed. Preview again.",
                }
            intent.consent_at = intent.consent_at or time.time()
            intent.state = "confirmed"
        event = _event(authority, binding, intent)
        publication = PublicationGuard(
            authority,
            binding,
            intent.id,
            event,
            tuple(intent.preview["target"]) if intent.preview.get("target") else None,
        )
        with scope(publication):
            with journal.company_transaction() as session:
                recorded = session.get(MemoryOperation, event.event_id)
                terminal = recorded is not None and recorded.state in journal.TERMINAL
            replay = journal.open_operation(event).replay if terminal else None
            if replay is not None:
                _checkpoint(authority, binding, intent.id, replay)
                publication.check()
                return {"status": replay.outcome, "reason": "Recorded publication outcome."}
            worker = Publisher(authority, binding, intent, event)
            with preparation_run(authority.uid, explicit=params.get("resume") is True):
                await worker.run({"id": event.source_id})
            publication.check()
            if worker.result is None:
                return {
                    "status": "refused",
                    "reason": "Preparation retry or batch limit refused this item.",
                }
            return {
                "status": (
                    worker.result.outcome
                    if worker.result.outcome != "retryable_failure"
                    else "refused"
                ),
                "reason": (
                    "Minimal fact committed."
                    if worker.result.mutated
                    else "Publication requires review or retry."
                ),
            }
