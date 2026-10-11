"""Engine-issued authority for one consented minimal company projection."""

import contextvars
import json
from contextlib import contextmanager
from dataclasses import dataclass

from zylch.qonto import guard
from zylch.qonto.errors import QontoError
from zylch.qonto.identity import require_same
from zylch.qonto.models import QontoPublicationIntent
from zylch.qonto.repository import read_binding, profile_transaction

_scope = contextvars.ContextVar("qonto_publication", default=None)


@dataclass(frozen=True)
class PublicationGuard:
    authority: object
    binding: object
    intent_id: str
    event: object
    target: tuple | None = None

    def check(self):
        if self.event.cancellation.cancelled:
            raise QontoError("operation_failed")
        from zylch.services.preparation import current_run, check_dispatch

        if current_run() is not None:
            check_dispatch(count_auxiliary=False)
        require_same(self.authority)
        if read_binding(self.authority.uid) != self.binding:
            raise QontoError("generation_changed")
        from zylch.qonto.publication import _projection

        fact, revision = _projection(self.authority, self.binding)
        if fact != self.event.observation or revision != self.event.source_revision:
            raise QontoError("binding_changed")
        with profile_transaction() as session:
            row = session.get(QontoPublicationIntent, self.intent_id)
            if (
                row is None
                or row.consent_at is None
                or row.state
                not in ("confirmed", "running", "committed", "skipped", "review_needed")
                or row.uid != self.authority.uid
                or row.dataset_id != self.binding.dataset_id
                or row.company_scope != self.authority.company_scope
                or row.generation != self.binding.generation
                or row.event_id != self.event.event_id
                or row.source_revision != self.event.source_revision
                or row.preview.get("fact_text") != self.event.observation
            ):
                raise QontoError("binding_changed")

    @contextmanager
    def commit(self):
        with guard.state_guard(self.authority.profile_dir):
            self.check()
            yield
            self.check()

    def validate(self, event, proposal):
        if event is not self.event:
            return "Publication authority does not match this event."
        if proposal is None:
            return ""
        safe_reasons = {
            "Confirmed minimal company projection.",
            "Minimal fact already recorded.",
            "Publication requires review.",
        }
        if proposal.reason not in safe_reasons:
            return "Publication decision exceeds the confirmed projection."
        if proposal.action in ("SKIP", "REVIEW"):
            no_op = proposal.no_op_target
            if no_op is not None and (
                self.target is None or (no_op.blob_id, no_op.expected_version) != self.target
            ):
                return "Publication decision exceeds the confirmed projection."
            if (
                proposal.content
                or proposal.ineligible
                or proposal.write_set
                or proposal.entity_type not in (None, "FACT")
                or proposal.scope not in (None, "company")
                or proposal.declared_effects
                or proposal.reclassification is not None
            ):
                return "Publication decision exceeds the confirmed projection."
            return ""
        expected = () if self.target is None else ((self.target[0], self.target[1], "target"),)
        actual = tuple((t.blob_id, t.expected_version, t.role) for t in proposal.write_set)
        if (
            proposal.action != ("CREATE" if self.target is None else "UPDATE")
            or proposal.entity_type != "FACT"
            or proposal.scope != "company"
            or proposal.family != "facts"
            or proposal.content != self.event.observation
            or actual != expected
            or proposal.reclassification is not None
            or proposal.declared_effects
            or proposal.ineligible
            or proposal.no_op_target is not None
        ):
            return "Publication decision exceeds the confirmed projection."
        return ""


@contextmanager
def scope(value):
    token = _scope.set(value)
    try:
        value.check()
        yield
    finally:
        _scope.reset(token)


def authorizes(event):
    current = _scope.get()
    if current is None or current.event is not event:
        return False
    current.check()
    return True


def check_before_disclosure():
    current = _scope.get()
    if current is not None:
        current.check()


def constrain_request(request):
    current = _scope.get()
    if current is None:
        return
    current.check()
    contract = {
        "action": "CREATE" if current.target is None else "UPDATE",
        "entity_type": "FACT",
        "scope": "company",
        "content": current.event.observation,
        "reason": "Confirmed minimal company projection.",
        "write_set": (
            []
            if current.target is None
            else [
                {
                    "blob_id": current.target[0],
                    "expected_version": current.target[1],
                    "role": "target",
                }
            ]
        ),
    }
    text = (
        "This engine-authorized Qonto publication is limited to the exact confirmed projection below. "
        "Its complete flat fact format is intentional; do not add or rewrite headers, history, values, "
        "or other content. Existing target content shown is the permitted projection, not a live bank source. "
        "Return this exact mutation envelope if appropriate: "
        + json.dumps(contract)
        + '. You may instead return SKIP with reason "Minimal fact already recorded." or REVIEW with reason '
        '"Publication requires review." and empty content. No other targets, effects or facts are authorized.'
    )
    system = request.get("system")
    if isinstance(system, str):
        request["system"] = system + "\n\n" + text
    else:
        request["system"] = list(system or []) + [{"type": "text", "text": text}]


def sanitize_outcome(event, result, proposal):
    from dataclasses import replace

    current = _scope.get()
    if current is None:
        return result, proposal
    if current.event is not event:
        raise QontoError("binding_changed")
    current.check()
    reason = {
        "skipped": "Minimal fact already recorded.",
        "review_needed": "Publication requires review.",
        "retryable_failure": "Publication unavailable. Retry authorized preparation.",
    }.get(result.outcome, "")
    return replace(result, reason=reason, proposal=None, departure=None), proposal
