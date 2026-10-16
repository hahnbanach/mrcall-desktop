"""Expiring, single-use confirmation challenges contain no credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass

from zylch.qonto.bootstrap import Credentials
from zylch.qonto.errors import QontoError
from zylch.qonto.identity import Authority
from zylch.qonto.provider import Organization

_secret = secrets.token_bytes(32)
_lock = threading.Lock()
_challenges: dict[str, "Challenge"] = {}
TTL_SECONDS = 300


@dataclass(frozen=True)
class Challenge:
    authority: Authority
    generation: int
    credential_fingerprint: str
    organization_fingerprint: str
    organization_id: str
    account_ids: tuple[str, ...]
    expires_at: float


def fingerprint(value: Credentials) -> str:
    payload = json.dumps([value.login, value.key]).encode()
    return hmac.new(_secret, payload, hashlib.sha256).hexdigest()


def issue(
    authority: Authority,
    generation: int,
    value: Credentials,
    org: Organization,
    accounts: tuple[str, ...],
) -> tuple[str, float]:
    expires = time.time() + TTL_SECONDS
    token = secrets.token_urlsafe(32)
    with _lock:
        for key, item in list(_challenges.items()):
            if item.expires_at <= time.time():
                del _challenges[key]
        if len(_challenges) >= 128:
            _challenges.pop(next(iter(_challenges)))
        _challenges[token] = Challenge(
            authority, generation, fingerprint(value), org.fingerprint(), org.id, accounts, expires
        )
    return token, expires


def consume(token, authority: Authority, generation: int, value: Credentials) -> Challenge:
    if not isinstance(token, str):
        raise QontoError("challenge_invalid")
    with _lock:
        item = _challenges.pop(token, None)
    if (
        item is None
        or item.expires_at <= time.time()
        or item.authority != authority
        or item.generation != generation
        or not hmac.compare_digest(item.credential_fingerprint, fingerprint(value))
    ):
        raise QontoError("challenge_invalid")
    return item
