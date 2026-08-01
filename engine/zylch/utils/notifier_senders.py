"""Notifier senders — addresses that RELAY somebody else's message.

A *notifier* is a system address that delivers a THIRD PARTY's message:
the envelope ``From`` is the platform, while the real correspondent —
their name, phone number, email address — is inside the body. The
canonical case is a missed-call alert: the mail arrives from
``notification@transactional.mrcall.ai`` but the person who needs a
call back is the caller described in the text.

Two engine behaviours depend on recognising these senders:

1. **Channel inference** (``storage._infer_task_channel``): a task born
   from a call notification belongs to the ``phone`` channel, not
   ``email``.
2. **Contact identity** (``workers.task_contact_identity``): the task
   must be keyed to the CALLER, never to the notifier address. Keying
   every call-back task to the same relay address collapses N distinct
   people into one identity, which in turn lets the dedup sweeps merge
   unrelated leads.

The recognised notifiers live in :data:`NOTIFIER_SENDERS`, a table of
address shapes. This module is deliberately engine-generic: calling
code asks "is this sender a notifier?" and never branches on a company
name. Integrating a new platform means adding a row here — nothing
else in the engine changes.

Leaf module: imports nothing from ``zylch``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotifierSpec:
    """One recognised relay sender.

    A sender matches when its local part starts with any entry of
    ``local_prefixes`` AND its domain satisfies at least one of
    ``domain_suffixes`` / ``domain_contains``. Both address halves are
    compared lower-cased.

    ``channel`` is the semantic surface a task built from this sender
    belongs to (``phone`` for call notifications). ``identity_hint``
    is free text handed to the detection LLM so it knows WHERE in the
    body the real correspondent is described.
    """

    name: str
    local_prefixes: Tuple[str, ...]
    channel: str
    domain_suffixes: Tuple[str, ...] = field(default=())
    domain_contains: Tuple[str, ...] = field(default=())
    identity_hint: str = ""


# The notifier table. Add a row per integrated platform; never add an
# `if company == …` to calling code.
NOTIFIER_SENDERS: Tuple[NotifierSpec, ...] = (
    NotifierSpec(
        name="mrcall-call-notification",
        local_prefixes=("notification", "notifications"),
        domain_suffixes=("mrcall.ai",),
        domain_contains=("transactional.mrcall",),
        channel="phone",
        identity_hint=(
            "This mail is a MrCall phone-call notification. The sender "
            "address is the notification relay, NOT the person to call "
            "back. The caller's phone number, name and email (when the "
            "assistant captured them) are inside the body."
        ),
    ),
)


def match_notifier(from_email: Optional[str]) -> Optional[NotifierSpec]:
    """Return the :class:`NotifierSpec` matching ``from_email``, else None.

    Pure function — no I/O, no logging of the address (it is not a
    secret, but this runs in hot loops and must stay cheap).
    """
    addr = (from_email or "").strip().lower()
    if not addr or "@" not in addr:
        return None
    local, domain = addr.split("@", 1)
    for spec in NOTIFIER_SENDERS:
        if not any(local.startswith(p) for p in spec.local_prefixes):
            continue
        if any(domain.endswith(s) for s in spec.domain_suffixes):
            return spec
        if any(c in domain for c in spec.domain_contains):
            return spec
    return None


def is_notifier_sender(from_email: Optional[str]) -> bool:
    """True when ``from_email`` relays a third party's message."""
    return match_notifier(from_email) is not None


def notifier_channel(from_email: Optional[str]) -> Optional[str]:
    """Semantic channel for a notifier sender, or None when not one."""
    spec = match_notifier(from_email)
    return spec.channel if spec else None


def notifier_identity_hint(from_email: Optional[str]) -> str:
    """Prompt fragment telling the detector where the real contact is.

    Empty string when the sender is not a notifier, so callers can
    concatenate unconditionally.
    """
    spec = match_notifier(from_email)
    return spec.identity_hint if spec else ""
