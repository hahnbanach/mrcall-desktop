"""Who the user is, across every address they write from.

The engine keys a profile by its primary address (``owner_id``), but the
user also writes from declared aliases (``EMAIL_ALIASES``) and from every
additional mailbox configured on the profile. Anything that decides
"is this message ours" — task detection, reply need, the Sent list,
``is_user_sent``, thread history, hygiene, the trainers — asks this
module, so the answer is the same everywhere.

Rules:

- an address is the user's only by exact match (lower-cased); a colleague
  on the same domain is never the user;
- the primary's domain is the user's domain (the trainers' domain rule);
  another mailbox's domain — a PEC provider's, say — never is, so a
  third party on that provider is a contact, not the user;
- a mailbox that was removed no longer identifies the user.

Never raises: whatever cannot be read (no profile, no database) simply
contributes nothing, and the answer degrades to the primary address.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def parse_user_aliases(raw: str | None) -> frozenset[str]:
    """Parse ``EMAIL_ALIASES``: comma-separated, trimmed, lower-cased, no empties."""
    if not raw:
        return frozenset()
    out: set[str] = set()
    for chunk in raw.split(","):
        s = chunk.strip().lower()
        if s and "@" in s:
            out.add(s)
    return frozenset(out)


def primary_address(owner_id: str) -> str:
    """The profile's primary address (lower-cased), or ``""``."""
    try:
        from zylch.api.token_storage import get_email

        found = (get_email(owner_id) or "").strip().lower()
    except Exception as e:
        logger.debug(f"[identity] primary address unavailable for {owner_id}: {e}")
        found = ""
    # The Settings object is built once at boot; the live environment is
    # what the profile's `.env` says now.
    return found or (os.environ.get("EMAIL_ADDRESS") or "").strip().lower()


def declared_aliases() -> frozenset[str]:
    """The ``EMAIL_ALIASES`` setting, from the environment or Settings."""
    try:
        raw = os.environ.get("EMAIL_ALIASES")
        if raw is None:
            from zylch.config import settings as _settings

            raw = getattr(_settings, "email_aliases", "") or ""
        return parse_user_aliases(raw)
    except Exception as e:
        logger.debug(f"[identity] EMAIL_ALIASES unavailable: {e}")
        return frozenset()


def mailbox_addresses(owner_id: str) -> frozenset[str]:
    """Addresses of the owner's non-removed mailboxes (lower-cased)."""
    try:
        from zylch.email.mailboxes import for_owner

        return frozenset(m.address.strip().lower() for m in for_owner(owner_id) if m.address)
    except Exception as e:
        logger.debug(f"[identity] mailbox addresses unavailable for {owner_id}: {e}")
        return frozenset()


def user_addresses(owner_id: str) -> frozenset[str]:
    """Every address the user writes from: primary, aliases, active mailboxes."""
    out: set[str] = set(declared_aliases()) | set(mailbox_addresses(owner_id))
    primary = primary_address(owner_id)
    if primary:
        out.add(primary)
    return frozenset(out)


def other_user_addresses(owner_id: str) -> frozenset[str]:
    """The user's addresses other than the primary."""
    primary = primary_address(owner_id)
    return frozenset(a for a in user_addresses(owner_id) if a != primary)


def is_user_address(owner_id: str, address: str | None) -> bool:
    """Exact-match test against :func:`user_addresses`."""
    if not address:
        return False
    return address.strip().lower() in user_addresses(owner_id)


def verified_user_addresses(owner_id: str) -> frozenset[str]:
    """The addresses a connection has verified: the primary and the active mailboxes.

    Declared aliases are NOT here. ``emails.needs_reply`` and
    ``is_user_sent`` read this set (D2): counting an alias as ours would
    mark more conversations answered, the direction that loses a
    customer; an answer sent from an alias leaves the conversation
    looking unanswered, which is the safe reading.
    """
    out: set[str] = set(mailbox_addresses(owner_id))
    primary = primary_address(owner_id)
    if primary:
        out.add(primary)
    return frozenset(out)


def is_user_sender(owner_id: str, address: str | None, user_email: str = "") -> bool:
    """The trainers' rule: the primary's domain, or an exact match on the user's addresses.

    ``user_email`` is the primary the caller was built with; its domain is
    the user's domain. The domain of any other address the user writes
    from — a PEC provider's, say — never is: those match exactly, so a
    third party on the same provider is a contact.
    """
    sender = (address or "").strip().lower()
    if not sender:
        return False
    primary = (user_email or "").strip().lower() or primary_address(owner_id)
    domain = primary.split("@", 1)[1] if "@" in primary else ""
    if domain and domain in sender:
        return True
    if primary and sender == primary:
        return True
    return sender in user_addresses(owner_id)


def user_domain(owner_id: str) -> str:
    """The primary address's domain (never another mailbox's), or ``""``."""
    primary = primary_address(owner_id)
    return primary.split("@", 1)[1] if "@" in primary else ""


def describe_user(owner_id: str) -> str:
    """The primary address, followed by the other addresses the user writes from.

    Meant for prompts that name the user by address (``{{user_email}}``):
    "primary@x.test (also writes from: a@y.test, b@z.test)".
    """
    primary = primary_address(owner_id)
    others = sorted(other_user_addresses(owner_id))
    if not others:
        return primary
    return f"{primary} (also writes from: {', '.join(others)})" if primary else ", ".join(others)
