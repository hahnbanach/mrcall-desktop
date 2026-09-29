"""Re-encrypt a profile's stored credentials from one Fernet key to another.

Plan M2.6 (docs/execution-plans/2026-09-29-toward-sandbox.md): on the host
every ``OAuthToken`` row was written under the shared ``/etc/mrcalld/env``
key; each profile gets its own. This module builds two ``Fernet`` instances
directly — it never touches the module-level cache in ``zylch.utils.encryption``
— and rewrites rows by ORM, while the daemon is stopped.

Rules, each with a test:

- **Idempotent.** A row that already decrypts under the *new* key is left
  alone (``decrypt`` fails open, so "try old first" would double-encrypt).
- **Nested fields.** A row's outer blob is a JSON object whose provider
  entries carry ``encrypted:<fernet>`` fields (``save_provider_credentials``);
  inner fields are re-encrypted too, then the outer.
- **Plaintext rows.** Hosts that ran without a key stored JSON in clear;
  those are encrypted with the new key and counted separately.
- **Verify.** ``verify(new)`` decrypts every row (outer and inner) and
  fails loudly on any miss; the runbook runs it before the unit starts.
- **Reverse.** ``rekey(old=new_key, new=old_key)`` is the rollback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken

from zylch.storage.database import get_session
from zylch.storage.models import OAuthToken

logger = logging.getLogger(__name__)

INNER_PREFIX = "encrypted:"


@dataclass
class RekeyReport:
    rewritten: int = 0
    already: int = 0
    plaintext: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _try(fernet: Fernet, token: str) -> str | None:
    try:
        return fernet.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None


def _looks_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith("gAAA") and len(value) > 80


def _rekey_inner(obj, old: Fernet, new: Fernet, report: RekeyReport, provider: str):
    """Walk the decrypted outer JSON; re-encrypt every ``encrypted:`` field."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith(INNER_PREFIX):
                token = v[len(INNER_PREFIX) :]
                if _try(new, token) is not None:
                    out[k] = v
                    continue
                plain = _try(old, token)
                if plain is None:
                    report.failed.append(f"{provider}: inner field {k}")
                    out[k] = v
                    continue
                out[k] = INNER_PREFIX + new.encrypt(plain.encode()).decode()
            else:
                out[k] = _rekey_inner(v, old, new, report, provider)
        return out
    if isinstance(obj, list):
        return [_rekey_inner(v, old, new, report, provider) for v in obj]
    return obj


def rekey(old_key: str, new_key: str) -> RekeyReport:
    """Rewrite every ``oauth_tokens.credentials`` from ``old_key`` to ``new_key``."""
    old = Fernet(old_key.encode())
    new = Fernet(new_key.encode())
    report = RekeyReport()
    with get_session() as session:
        for row in session.query(OAuthToken).all():
            blob = row.credentials
            if not blob or not isinstance(blob, str):
                continue
            if _looks_encrypted(blob):
                if _try(new, blob) is not None:
                    # Already under the new key — but inner fields might not be
                    # (a partial earlier run); walk them with old→new anyway.
                    outer_plain = _try(new, blob)
                    inner_before = report.failed[:]
                    walked = _rekey_inner(_load(outer_plain), old, new, report, row.provider)
                    if report.failed != inner_before:
                        continue
                    row.credentials = new.encrypt(json.dumps(walked).encode()).decode()
                    report.already += 1
                    continue
                outer_plain = _try(old, blob)
                if outer_plain is None:
                    report.failed.append(f"{row.provider}: outer blob decrypts under neither key")
                    continue
            else:
                outer_plain = blob
                report.plaintext += 1
            walked = _rekey_inner(_load(outer_plain), old, new, report, row.provider)
            row.credentials = new.encrypt(json.dumps(walked).encode()).decode()
            report.rewritten += 1
    logger.info(
        f"[rekey] rewritten={report.rewritten} already={report.already} "
        f"plaintext={report.plaintext} failed={len(report.failed)}"
    )
    return report


def verify(new_key: str) -> RekeyReport:
    """Every row, outer and inner, decrypts under ``new_key``; nothing is written."""
    new = Fernet(new_key.encode())
    report = RekeyReport()
    with get_session() as session:
        for row in session.query(OAuthToken).all():
            blob = row.credentials
            if not blob or not isinstance(blob, str):
                continue
            if not _looks_encrypted(blob):
                report.failed.append(f"{row.provider}: outer blob is plaintext")
                continue
            outer_plain = _try(new, blob)
            if outer_plain is None:
                report.failed.append(f"{row.provider}: outer blob does not decrypt")
                continue
            _verify_inner(_load(outer_plain), new, report, row.provider)
            report.rewritten += 1
    return report


def _verify_inner(obj, new: Fernet, report: RekeyReport, provider: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith(INNER_PREFIX):
                if _try(new, v[len(INNER_PREFIX) :]) is None:
                    report.failed.append(f"{provider}: inner field {k} does not decrypt")
            else:
                _verify_inner(v, new, report, provider)
    elif isinstance(obj, list):
        for v in obj:
            _verify_inner(v, new, report, provider)


def _load(text: str):
    """The outer plaintext is JSON in every writer; tolerate a bare string."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text
