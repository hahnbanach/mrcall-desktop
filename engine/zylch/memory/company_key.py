"""The company memory key — minting, shape, persistence, and namespaces.

One memory per company. The company is a random key — a capability: a
new key starts a new company memory, an existing one joins it. The key
lives in the profile ``.env`` as ``MEMORY_KEY`` and reaches the running
engine through ``os.environ`` like every other setting.

Memory has four namespace families. Two are company knowledge and are
scoped by the key alone (``owner_id`` stays on every row as provenance —
which account contributed — but decides nothing):

- ``user:<company_key>``  — entities (people, companies, styles)
- ``facts:<company_key>`` — category-tagged business facts

Two are operating rules injected verbatim into each agent's prompts and
stay personal — scoped by the key AND the owner:

- ``template:<owner_id>`` / ``prefs:<owner_id>``

Nothing in the store is scoped by owner alone any more. The predicate
that says which rows an (owner, key) pair may see lives in
:mod:`zylch.memory.scope`; this module stays free of ORM imports so the
models can use it for column defaults.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import secrets
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

SETTING = "MEMORY_KEY"
KEY_BYTES = 16  # 128 bits of randomness, the product brief's floor
KEY_LENGTH = 22  # token_urlsafe(16) is 22 chars, no padding

COMPANY_FAMILIES: Tuple[str, ...] = ("user", "facts")
RULE_FAMILIES: Tuple[str, ...] = ("template", "prefs")
FAMILIES: Tuple[str, ...] = COMPANY_FAMILIES + RULE_FAMILIES


def mint_key() -> str:
    """A fresh key: 128 random bits, URL-safe base64, 22 characters."""
    return secrets.token_urlsafe(KEY_BYTES)


def well_formed(key: Optional[str]) -> Tuple[bool, str]:
    """Shape check only — existence is the store's business, not this module's.

    Returns ``(ok, reason)``; ``reason`` is empty when ``ok``.
    """
    if not key or not isinstance(key, str):
        return False, "empty key"
    key = key.strip()
    if len(key) != KEY_LENGTH:
        return False, f"a memory key is {KEY_LENGTH} characters, got {len(key)}"
    try:
        # strict: a character outside the URL-safe alphabet is a refusal,
        # not something to discard (the lenient decoder would skip it)
        raw = base64.b64decode(key + "==", altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return False, "not URL-safe base64"
    if len(raw) != KEY_BYTES:
        return False, "wrong length after decoding"
    return True, ""


def current_company_key() -> Optional[str]:
    """The running profile's key, or ``None`` when unset."""
    value = os.environ.get(SETTING, "")
    value = value.strip() if value else ""
    return value or None


def _profile_dir() -> Optional[str]:
    from zylch.cli.profiles import get_active_profile_dir

    return get_active_profile_dir() or os.environ.get("ZYLCH_PROFILE_DIR") or None


def persist_company_key(key: str) -> None:
    """Write the key to the profile ``.env`` and the live environment.

    Raises when no profile directory can be resolved: an unpersisted key
    would be re-minted on the next boot and every row written under the
    old one would become invisible — that must fail loudly, never
    quietly succeed for one process.
    """
    if _profile_dir() is None:
        raise RuntimeError(
            "cannot persist MEMORY_KEY: no active profile directory "
            "(neither activate_profile() nor ZYLCH_PROFILE_DIR)"
        )
    from zylch.services.settings_io import update_env

    update_env({SETTING: key})  # also hot-loads os.environ
    logger.info("[memory] company key persisted to the profile .env")


def ensure_company_key() -> str:
    """The profile's key, minting and persisting one on first use.

    This is what the M1 migration step calls before it rewrites rows, so
    the mint provably precedes the migration inside the same boot.
    """
    key = current_company_key()
    if key:
        return key
    key = mint_key()
    persist_company_key(key)
    logger.info("[memory] minted a new company key for this profile")
    return key


def require_company_key() -> str:
    """The key, or a clear error — never a silently empty scope."""
    key = current_company_key()
    if not key:
        raise RuntimeError(
            "MEMORY_KEY is unset for this profile; the engine boot should have "
            "minted one (storage migration 0001_company_key)"
        )
    return key


# ─── Namespaces ───────────────────────────────────────────────


def family_of(namespace: str) -> str:
    """``'user:abc'`` → ``'user'``; empty when malformed."""
    if not namespace or ":" not in namespace:
        return ""
    return namespace.split(":", 1)[0].strip().lower()


def is_company_family(family: str) -> bool:
    return family in COMPANY_FAMILIES


def is_rule_family(family: str) -> bool:
    return family in RULE_FAMILIES


def entity_namespace(company_key: str) -> str:
    return f"user:{company_key}"


def facts_namespace(company_key: str) -> str:
    return f"facts:{company_key}"


def rule_namespaces(owner_id: str) -> Tuple[str, str]:
    return (f"template:{owner_id}", f"prefs:{owner_id}")


def scoped_namespace(family: str, owner_id: str, company_key: str) -> str:
    """The one correct namespace for ``family`` under this (owner, key).

    Company families take the key, rule families take the owner, and an
    unknown family is refused rather than stored — the namespace is
    something the engine decides, never something a caller (least of
    all a model) hands in verbatim.
    """
    fam = (family or "").strip().lower()
    if fam in COMPANY_FAMILIES:
        return f"{fam}:{company_key}"
    if fam in RULE_FAMILIES:
        return f"{fam}:{owner_id}"
    raise ValueError(f"unknown memory namespace family {family!r}; known: {', '.join(FAMILIES)}")
