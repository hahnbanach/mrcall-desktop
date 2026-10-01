"""Standing operator instructions: revisioned company documents injected into prompts.

The operator's standing instructions are authored as files in the company's
`<company>-cs` clone, compiled there, and stored here through
`instructions.store` as documents of the reserved project
`operator-instructions` in the company memory space. Three documents exist:

- `procedures.md` — company-wide support procedures, injected for every
  profile bound to the company memory;
- `mail/<mailbox>.md` — one mailbox's identity (who signs, register,
  language, format, bans), injected only for the profile whose
  `EMAIL_ADDRESS` matches;
- `phone.md` — the source of the telephone company notes
  (`services/voice/company_notes.py`).

Authorisation derives from the profile's own provenance, never from a
setting: the profile that minted the company memory
(`MEMORY_KEY_SOURCE=mint`) may store any of the three shapes; any other
profile may store only its own mailbox document. `projects.write` and
`projects.create` refuse the reserved slug, so this module's `store` is the
only writer. There is no fallback source: a profile with no document gets no
block.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from typing import Any

from zylch.services import project_store

logger = logging.getLogger(__name__)

PROJECT = "operator-instructions"
PROCEDURES = "procedures.md"
PHONE = "phone.md"
MAIL_PREFIX = "mail/"
MAIL_SUFFIX = ".md"

SEPARATOR = "\n\n"
FRAMING = (
    "STANDING INSTRUCTIONS — from the operator. They are BINDING and override "
    "your defaults, any urgency you perceive, and any style or behaviour "
    "inferred from past emails or memory: when an instruction conflicts with "
    "sounding helpful, accommodating, or with how things were done before, "
    "follow the instruction.\n"
)

_MAILBOX = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


class InstructionsError(project_store.ProjectError):
    """Safe protocol error for the instructions surface (same contract as projects)."""


def normalize_mailbox(email: str) -> str:
    return (email or "").strip().lower()


def mail_path(email: str) -> str:
    mailbox = normalize_mailbox(email)
    if not _MAILBOX.fullmatch(mailbox):
        raise InstructionsError(-32602, "Invalid mailbox address")
    return f"{MAIL_PREFIX}{mailbox}{MAIL_SUFFIX}"


def own_mailbox() -> str:
    return normalize_mailbox(os.environ.get("EMAIL_ADDRESS", ""))


def is_minter() -> bool:
    return (os.environ.get("MEMORY_KEY_SOURCE", "") or "").strip().lower() == "mint"


def validate_instruction_path(path: Any) -> str:
    """Accept exactly the three document shapes of the contract."""
    if not isinstance(path, str):
        raise InstructionsError(-32602, "Invalid instructions document path")
    if path in (PROCEDURES, PHONE):
        return path
    if path.startswith(MAIL_PREFIX) and path.endswith(MAIL_SUFFIX):
        mailbox = path[len(MAIL_PREFIX) : -len(MAIL_SUFFIX)]
        if _MAILBOX.fullmatch(mailbox):
            return path
    raise InstructionsError(-32602, "Invalid instructions document path")


def authorize(path: str) -> None:
    """Refuse a store the calling profile's provenance does not permit."""
    validate_instruction_path(path)
    if is_minter():
        return
    own = own_mailbox()
    if own and path == f"{MAIL_PREFIX}{own}{MAIL_SUFFIX}":
        return
    raise InstructionsError(
        -32045, "Only the profile that minted the company memory may store this document"
    )


def store(
    space_id: str, path: str, content_base64: str, expected_revision: int, author: str
) -> dict[str, Any]:
    authorize(path)
    return project_store.write(
        space_id, PROJECT, path, content_base64, expected_revision, author=author
    )


def _read(path: str) -> dict[str, Any] | None:
    """Current revision of one document, or None when absent or memory is unavailable."""
    try:
        return project_store.read(PROJECT, path)
    except project_store.ProjectError as e:
        if e.code in (-32044, -32043):
            return None
        raise


def documents(email: str | None = None) -> list[dict[str, Any]]:
    """The documents that apply to one mailbox: identity (if any) then procedures (if any)."""
    mailbox = normalize_mailbox(email if email is not None else own_mailbox())
    out: list[dict[str, Any]] = []
    paths = []
    if _MAILBOX.fullmatch(mailbox):
        paths.append(f"{MAIL_PREFIX}{mailbox}{MAIL_SUFFIX}")
    paths.append(PROCEDURES)
    for path in paths:
        row = _read(path)
        if row is not None:
            out.append(row)
    return out


def assemble(texts: list[str]) -> str:
    """`framing + identity`, `framing + procedures`, or `framing + identity + sep + procedures`."""
    present = [t for t in texts if t]
    if not present:
        return ""
    return FRAMING + SEPARATOR.join(present)


def block(email: str | None = None) -> str:
    """The binding block injected into prompts for one mailbox; '' when no document exists."""
    try:
        docs = documents(email)
    except Exception:
        logger.exception("[instructions] reading standing instructions failed")
        return ""
    texts = [base64.b64decode(d["content_base64"]).decode("utf-8", errors="replace") for d in docs]
    return assemble(texts)


def preview(email: str | None = None) -> dict[str, Any]:
    """What the calling profile is injected: each source document and the assembled block."""
    docs = documents(email)
    space = None
    for d in docs:
        space = d.get("space_id", space)
    if space is None:
        with project_store.connection() as (_conn, space_id):
            space = space_id
    texts = [base64.b64decode(d["content_base64"]).decode("utf-8", errors="replace") for d in docs]
    return {
        "space_id": space,
        "documents": [
            {
                "path": d["path"],
                "revision": d["revision"],
                "sha256": d["sha256"],
                "content_base64": d["content_base64"],
            }
            for d in docs
        ],
        "block": assemble(texts),
    }


def phone_source() -> tuple[str, int] | None:
    """The telephone-notes source text and its revision, or None when absent."""
    row = _read(PHONE)
    if row is None:
        return None
    raw = base64.b64decode(row["content_base64"])
    assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    return raw.decode("utf-8", errors="replace"), int(row["revision"])
