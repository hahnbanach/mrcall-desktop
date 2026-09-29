"""Host-side names derived from a profile uid and a company key.

On a shared host every profile runs as its own Unix user and every
company's store sits in its own group-owned directory. Neither the
Firebase uid nor the ``MEMORY_KEY`` may appear in ``/etc/passwd``,
``/etc/group``, ``ps`` or ``ls``: the key is a capability and the uid is
28 mixed-case characters, too long and the wrong alphabet for ``useradd``.
So each name is a short, lowercase, one-way derivation.

Brief: docs/briefs/2026-09-29-toward-sandbox.md; plan M2.2.
"""

import hashlib

USER_PREFIX = "mc-"
GROUP_PREFIX = "mc-c-"
NAME_DIGEST_CHARS = 12
STORE_DIGEST_CHARS = 32


def _digest(value: str, chars: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:chars]


def unix_user(uid: str) -> str:
    """The Unix user a profile's daemon runs as: ``mc-<12 hex>``."""
    return USER_PREFIX + _digest(uid, NAME_DIGEST_CHARS)


def company_group(key: str) -> str:
    """The Unix group that owns a company's store: ``mc-c-<12 hex>``."""
    return GROUP_PREFIX + _digest(key, NAME_DIGEST_CHARS)


def store_basename(key: str) -> str:
    """The company store's file name, ``<32 hex>.db``, never the key."""
    return _digest(key, STORE_DIGEST_CHARS) + ".db"
