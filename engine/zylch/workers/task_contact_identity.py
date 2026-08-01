"""Who is the real correspondent behind a task?

Two questions live here, both answered from the same notion of
identity:

1. **At creation time** (:func:`resolve_contact_identity`) — the
   envelope ``From`` is not always the correspondent. When the mail
   arrives through a notifier relay (see
   :mod:`zylch.utils.notifier_senders`) the real person is described in
   the body, and the detection LLM — which is already reading that
   body — reports them on its decision tool. This function prefers the
   reported identity over the envelope and, when the LLM could not
   resolve one, keeps the envelope address but records the relay in
   ``sources`` so the substitution is never silent.

2. **At dedup time** (:func:`task_identity_key`) — before two tasks may
   be merged, they must be shown to belong to the SAME party. A
   notifier address is not an identity: 28 call-back tasks all carrying
   ``notification@transactional.mrcall.ai`` are 28 different people.
   The key is therefore phone-first, and a task whose only identifier
   is a notifier address reports ``None`` (unknown), which the sweeps
   treat as "cannot prove same party" rather than as consent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from zylch.utils.notifier_senders import is_notifier_sender, match_notifier

logger = logging.getLogger(__name__)


@dataclass
class ContactIdentity:
    """Resolved correspondent for a task about to be created."""

    email: str
    phone: Optional[str]
    name: str
    #: Envelope address when the mail came through a relay, else None.
    notifier_email: Optional[str] = None
    #: True when the identity comes from the LLM's reading of the body.
    resolved_from_body: bool = False

    def apply_to_sources(self, sources: Dict[str, Any]) -> Dict[str, Any]:
        """Record the relay provenance on a task's ``sources`` dict.

        Mutates and returns ``sources``. Only writes when a notifier was
        involved, so ordinary email tasks keep their existing shape.
        """
        if self.notifier_email:
            sources["notifier_email"] = self.notifier_email
            sources["contact_identity"] = (
                "extracted_from_body" if self.resolved_from_body else "notifier_envelope_fallback"
            )
        return sources


def _clean(value: Any) -> str:
    return str(value or "").strip()


def resolve_contact_identity(
    from_email: str,
    from_name: str,
    decision: Optional[Dict[str, Any]] = None,
) -> ContactIdentity:
    """Pick the correspondent for a task built from an email event.

    ``decision`` is the detection LLM's ``task_decision`` output, which
    may carry ``contact_email`` / ``contact_phone`` / ``contact_name``
    read out of the body. Those fields are honoured ONLY when the
    envelope sender is a notifier relay — for an ordinary correspondent
    the envelope is authoritative and the model must not be able to
    re-point a task at somebody else.

    Returns a :class:`ContactIdentity`. When the sender is a notifier
    but nothing usable came back, the envelope address is kept (so the
    task still has a handle) and ``notifier_email`` is set — callers
    log a WARNING and stamp ``sources`` via :meth:`apply_to_sources`.
    """
    envelope = _clean(from_email).lower()
    spec = match_notifier(envelope)
    if spec is None:
        return ContactIdentity(email=envelope, phone=None, name=_clean(from_name))

    d = decision or {}
    body_email = _clean(d.get("contact_email")).lower()
    body_phone = _clean(d.get("contact_phone"))
    body_name = _clean(d.get("contact_name"))

    # Guard against the model echoing the relay back at us.
    if body_email and is_notifier_sender(body_email):
        logger.warning(
            f"[identity] detector returned the notifier address itself "
            f"as contact_email (notifier={spec.name}) — discarding"
        )
        body_email = ""

    if body_email or body_phone:
        return ContactIdentity(
            email=body_email,
            phone=body_phone or None,
            name=body_name or _clean(from_name),
            notifier_email=envelope,
            resolved_from_body=True,
        )

    logger.warning(
        f"[identity] notifier mail from {envelope} (notifier={spec.name}) "
        f"but the detector reported no contact_email/contact_phone — "
        f"keeping the envelope address as the task handle and recording "
        f"the notifier in sources"
    )
    return ContactIdentity(
        email=envelope,
        phone=None,
        name=body_name or _clean(from_name),
        notifier_email=envelope,
        resolved_from_body=False,
    )


def task_identity_key(task: Dict[str, Any]) -> Optional[str]:
    """Stable party key for a stored task, or ``None`` when unknown.

    Priority:

    1. ``contact_phone`` — the strongest identifier the pipeline has,
       and the one phone-lead tasks carry after the notifier fix.
    2. ``contact_email``, unless it is a notifier relay address (which
       identifies the platform, not the party).
    3. ``sources.whatsapp_chat_jid`` — a WA task whose phone never
       resolved still has a chat that IS one party.

    ``None`` means "cannot tell who this is". Callers must treat that
    as a refusal to merge, not as a match.
    """
    phone = _clean(task.get("contact_phone"))
    if phone:
        return f"phone:{phone.lower()}"

    email = _clean(task.get("contact_email")).lower()
    if email and not is_notifier_sender(email):
        return f"email:{email}"

    sources = task.get("sources") or {}
    if isinstance(sources, dict):
        jid = _clean(sources.get("whatsapp_chat_jid"))
        if jid:
            return f"wa:{jid.lower()}"

    return None


def describe_identity(task: Dict[str, Any]) -> str:
    """Human-readable identity for log lines (never truncated)."""
    key = task_identity_key(task)
    if key:
        return key
    return f"unknown(contact_email={task.get('contact_email') or '-'})"
