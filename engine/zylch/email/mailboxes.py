"""Mailbox rows of a profile: loading, the primary row, and IMAP clients.

A profile holds N IMAP mailboxes in the ``mailboxes`` table (model
:class:`zylch.storage.models.Mailbox`). The primary one is the sign-up
mailbox: its address is the profile's ``owner_id``, its password stays in
the ``.env`` ``EMAIL_PASSWORD`` and its hosts mirror ``IMAP_HOST`` /
``IMAP_PORT`` / ``SMTP_HOST`` / ``SMTP_PORT``, refreshed from the
environment at every boot by :func:`ensure_primary_mailbox`. Additional
mailboxes carry their own hosts and an encrypted password
(:mod:`zylch.email.mailbox_secrets`).

Every ``emails`` row and every sync cursor names its mailbox. The sync
always does; the send mirrors and a row built without one get
:func:`resolve_default_mailbox_id`: the owner's primary row when it
exists or can be materialised from ``EMAIL_ADDRESS``, otherwise an active
row keyed by the owner itself, which is also how the migration treats a
profile whose owner is ``local-user``.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Connection, Engine

from zylch.email.mailbox_secrets import MailboxSecretError, decrypt_secret, encrypt_secret

if TYPE_CHECKING:
    from zylch.email.imap_client import IMAPClient

logger = logging.getLogger(__name__)

LOCAL_OWNER = "local-user"


@dataclass(frozen=True)
class MailboxInfo:
    """A mailbox row without its secret; ``has_secret`` says whether one is stored."""

    id: str
    owner_id: str
    address: str
    imap_host: str | None
    imap_port: int | None
    smtp_host: str | None
    smtp_port: int | None
    preset: str | None
    is_primary: bool
    has_secret: bool
    created_at: datetime | None
    last_sync_at: datetime | None
    last_error: str | None
    removed_at: datetime | None

    @property
    def removed(self) -> bool:
        return self.removed_at is not None


def _info(row) -> MailboxInfo:
    return MailboxInfo(
        id=row.id,
        owner_id=row.owner_id,
        address=row.address,
        imap_host=row.imap_host,
        imap_port=row.imap_port,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        preset=row.preset,
        is_primary=bool(row.is_primary),
        has_secret=bool(row.secret),
        created_at=row.created_at,
        last_sync_at=row.last_sync_at,
        last_error=row.last_error,
        removed_at=row.removed_at,
    )


def _env_int(name: str) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"[mailboxes] {name}={raw!r} is not an integer; ignored")
        return None


def env_primary_address() -> str | None:
    """``EMAIL_ADDRESS`` exactly as the runtime owner reads it; ``None`` when absent.

    Raw on purpose: ``zylch.cli.utils.get_owner_id`` keys every row by the
    unmodified value (whitespace and an empty string included), so the
    primary row must carry that same value or the user's own mail would
    land in a different mailbox than the runtime writes to.
    """
    return os.environ.get("EMAIL_ADDRESS")


def runtime_owner_id() -> str:
    """The owner the running engine keys rows by (``get_owner_id``)."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


def env_hosts() -> dict:
    """The primary mailbox's hosts and ports as the profile ``.env`` states them."""
    return {
        "imap_host": (os.environ.get("IMAP_HOST") or "").strip() or None,
        "imap_port": _env_int("IMAP_PORT"),
        "smtp_host": (os.environ.get("SMTP_HOST") or "").strip() or None,
        "smtp_port": _env_int("SMTP_PORT"),
    }


def _now() -> str:
    # Naive UTC in the format the ORM's SQLite DateTime type reads back.
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")


# ─── Reading ───────────────────────────────────────────────────


def for_owner(owner_id: str, include_removed: bool = False) -> list[MailboxInfo]:
    """The owner's mailboxes, primary first; removed rows only on request."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    with get_session() as session:
        q = session.query(Mailbox).filter(Mailbox.owner_id == owner_id)
        if not include_removed:
            q = q.filter(Mailbox.removed_at.is_(None))
        rows = q.order_by(Mailbox.is_primary.desc(), Mailbox.created_at, Mailbox.address).all()
        return [_info(r) for r in rows]


def primary(owner_id: str) -> MailboxInfo | None:
    """The owner's active primary mailbox, or ``None`` (no ``EMAIL_ADDRESS``)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    with get_session() as session:
        row = (
            session.query(Mailbox)
            .filter(
                Mailbox.owner_id == owner_id,
                Mailbox.is_primary.is_(True),
                Mailbox.removed_at.is_(None),
            )
            .first()
        )
        return _info(row) if row else None


def by_id(owner_id: str, mailbox_id: str) -> MailboxInfo | None:
    """One mailbox by id, removed or not; ``None`` when the owner has no such row."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    with get_session() as session:
        row = (
            session.query(Mailbox)
            .filter(Mailbox.owner_id == owner_id, Mailbox.id == mailbox_id)
            .first()
        )
        return _info(row) if row else None


def by_address(owner_id: str, address: str, include_removed: bool = False) -> MailboxInfo | None:
    """One mailbox by address, case-insensitively; removed rows only on request.

    Addresses are compared lower-cased and trimmed: ``Owner@Company.test``
    and ``owner@company.test`` are one account.
    """
    from sqlalchemy import func

    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    wanted = (address or "").strip().lower()
    with get_session() as session:
        q = session.query(Mailbox).filter(
            Mailbox.owner_id == owner_id, func.lower(Mailbox.address) == wanted
        )
        if not include_removed:
            q = q.filter(Mailbox.removed_at.is_(None))
        row = q.first()
        return _info(row) if row else None


def active_mailbox_ids(owner_id: str) -> list[str]:
    """Ids of the owner's non-removed mailboxes (the filter list queries apply)."""
    return [m.id for m in for_owner(owner_id)]


# ─── The default mailbox for writers that pass none ───────────


def _insert_row(conn: Connection, owner_id: str, address: str, *, is_primary: bool) -> str:
    hosts = env_hosts() if is_primary else {}
    mailbox_id = str(uuid.uuid4())
    conn.exec_driver_sql(
        "INSERT INTO mailboxes (id, owner_id, address, imap_host, imap_port, smtp_host, "
        "smtp_port, preset, is_primary, secret, created_at, last_sync_at, last_error, removed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, NULL, NULL, NULL)",
        (
            mailbox_id,
            owner_id,
            address,
            hosts.get("imap_host"),
            hosts.get("imap_port"),
            hosts.get("smtp_host"),
            hosts.get("smtp_port"),
            1 if is_primary else 0,
            _now(),
        ),
    )
    return mailbox_id


def resolve_default_mailbox_id(conn: Connection, owner_id: str) -> str:
    """The mailbox a row of ``owner_id`` belongs to when the writer named none.

    Runs on the caller's connection so it works inside a column default
    and inside the migration runner's transaction. Order: the active
    primary row; else, when ``EMAIL_ADDRESS`` is this owner, the primary
    row materialised from the environment (an owner-keyed row that already
    exists is promoted); else the row keyed by the owner itself, revived
    when hidden, created on first need. ``(owner_id, address)`` is unique,
    so an owner never ends up with two rows for one address.
    """
    row = conn.exec_driver_sql(
        "SELECT id FROM mailboxes WHERE owner_id = ? AND is_primary = 1 "
        "AND removed_at IS NULL LIMIT 1",
        (owner_id,),
    ).fetchone()
    if row:
        return row[0]

    current = env_primary_address()
    if current is not None and current == owner_id:
        existing = conn.exec_driver_sql(
            "SELECT id FROM mailboxes WHERE owner_id = ? AND address = ? LIMIT 1",
            (owner_id, owner_id),
        ).fetchone()
        if existing:
            conn.exec_driver_sql(
                "UPDATE mailboxes SET is_primary = 1, removed_at = NULL WHERE id = ?",
                (existing[0],),
            )
            logger.info(f"[mailboxes] promoted the owner-keyed row to primary for {owner_id}")
            return existing[0]
        mailbox_id = _insert_row(conn, owner_id, owner_id, is_primary=True)
        logger.info(f"[mailboxes] materialised the primary mailbox row for {owner_id}")
        return mailbox_id

    row = conn.exec_driver_sql(
        "SELECT id, removed_at FROM mailboxes WHERE owner_id = ? AND address = ? LIMIT 1",
        (owner_id, owner_id),
    ).fetchone()
    if row:
        if row[1] is not None:
            conn.exec_driver_sql("UPDATE mailboxes SET removed_at = NULL WHERE id = ?", (row[0],))
            logger.info(f"[mailboxes] revived the owner-keyed mailbox row for {owner_id}")
        return row[0]
    mailbox_id = _insert_row(conn, owner_id, owner_id, is_primary=False)
    logger.info(f"[mailboxes] materialised an owner-keyed mailbox row for {owner_id}")
    return mailbox_id


def default_mailbox_id(owner_id: str, engine: Engine | None = None) -> str:
    """:func:`resolve_default_mailbox_id` in its own short transaction."""
    from zylch.storage.database import get_engine

    with (engine or get_engine()).begin() as conn:
        return resolve_default_mailbox_id(conn, owner_id)


def ensure_primary_mailbox(engine: Engine | None = None) -> str | None:
    """Boot pass: the primary row exists when ``EMAIL_ADDRESS`` is set.

    Creates it when missing and mirrors the environment's hosts and ports
    onto it, so a Settings edit of ``IMAP_HOST`` is reflected after the
    restart the app performs. Returns the primary id, or ``None`` when the
    profile has no address (no primary, sync stays gated as it is).
    """
    address = env_primary_address()
    if address is None:
        return None
    from zylch.storage.database import get_engine

    hosts = env_hosts()
    with (engine or get_engine()).begin() as conn:
        mailbox_id = resolve_default_mailbox_id(conn, address)
        conn.exec_driver_sql(
            "UPDATE mailboxes SET imap_host = ?, imap_port = ?, smtp_host = ?, smtp_port = ? "
            "WHERE id = ?",
            (
                hosts["imap_host"],
                hosts["imap_port"],
                hosts["smtp_host"],
                hosts["smtp_port"],
                mailbox_id,
            ),
        )
    return mailbox_id


def record_sync_result(owner_id: str, mailbox_id: str, error: str | None) -> None:
    """Write the outcome of one mailbox's sync on its row.

    Success stamps ``last_sync_at`` and clears ``last_error``; a failure
    keeps the last successful time and records the message. Never
    raises: bookkeeping must not undo a sync that already happened.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    try:
        with get_session() as session:
            row = (
                session.query(Mailbox)
                .filter(Mailbox.owner_id == owner_id, Mailbox.id == mailbox_id)
                .first()
            )
            if row is None:
                return
            if error is None:
                row.last_sync_at = datetime.now(UTC).replace(tzinfo=None)
                row.last_error = None
            else:
                row.last_error = error[:1000]
    except Exception as e:
        logger.error(f"[mailboxes] record_sync_result(mailbox_id={mailbox_id}) failed: {e}")


# ─── Writing an additional mailbox ────────────────────────────


def add_mailbox(
    owner_id: str,
    address: str,
    password: str,
    *,
    imap_host: str | None = None,
    imap_port: int | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    preset: str | None = None,
) -> MailboxInfo:
    """Store an additional mailbox with its password encrypted.

    The secret key is generated and persisted before the row is written,
    so a daemon that restarts between the two never holds a row it cannot
    read. An active row with the same address is refused; a removed one
    is revived with its id (its rows and cursors come back with it).
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    from sqlalchemy import func
    from sqlalchemy.exc import IntegrityError

    # Stored and compared lower-cased: one account, whatever its casing.
    address = (address or "").strip().lower()
    if not address:
        raise ValueError("a mailbox needs an address")
    token = encrypt_secret(password)
    with get_session() as session:
        rows = session.query(Mailbox).filter(
            Mailbox.owner_id == owner_id, func.lower(Mailbox.address) == address
        )
        active = rows.filter(Mailbox.removed_at.is_(None)).first()
        if active is not None:
            raise ValueError(f"mailbox {address} is already configured")
        row = rows.first()
        if row is None:
            row = Mailbox(owner_id=owner_id, address=address, is_primary=False)
            session.add(row)
        row.removed_at = None
        row.imap_host = imap_host
        row.imap_port = imap_port
        row.smtp_host = smtp_host
        row.smtp_port = smtp_port
        row.preset = preset
        row.secret = token
        row.last_error = None
        try:
            session.flush()
        except IntegrityError as e:
            # Another process stored the same address meanwhile. Never let
            # the driver's text out: its parameters include the ciphertext.
            session.rollback()
            logger.info(f"[mailboxes] {address}: stored concurrently ({type(e).__name__})")
            raise ValueError(f"mailbox {address} is already configured") from None
        info = _info(row)
    logger.info(f"[mailboxes] stored mailbox {address} for {owner_id} (secret present)")
    return info


def update_mailbox(
    owner_id: str,
    mailbox_id: str,
    *,
    imap_host: str | None = None,
    imap_port: int | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    password: str | None = None,
    preset: str | None = None,
) -> MailboxInfo | None:
    """Change an additional mailbox's hosts, ports, preset or password.

    ``None`` leaves a field as it is. A new password is encrypted under
    the profile's key. Returns the row, or ``None`` when the owner has no
    such active row. The primary is refused (its settings live in
    ``.env``): ``ValueError``.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    token = encrypt_secret(password) if password is not None else None
    with get_session() as session:
        row = (
            session.query(Mailbox)
            .filter(
                Mailbox.owner_id == owner_id,
                Mailbox.id == mailbox_id,
                Mailbox.removed_at.is_(None),
            )
            .first()
        )
        if row is None:
            return None
        if row.is_primary:
            raise ValueError("the primary mailbox is configured in Settings, not here")
        if imap_host is not None:
            row.imap_host = imap_host or None
        if imap_port is not None:
            row.imap_port = imap_port or None
        if smtp_host is not None:
            row.smtp_host = smtp_host or None
        if smtp_port is not None:
            row.smtp_port = smtp_port or None
        if preset is not None:
            row.preset = preset or None
        if token is not None:
            row.secret = token
            row.last_error = None
        session.flush()
        info = _info(row)
    logger.info(f"[mailboxes] updated mailbox {info.address} for {owner_id}")
    return info


def remove_mailbox(owner_id: str, mailbox_id: str) -> MailboxInfo | None:
    """Hide a mailbox: ``removed_at`` set, rows and cursors kept (D3).

    Sync skips it from the next run and every list, search and picker
    stops seeing its rows; re-adding the address revives the row with
    its id. Returns the row, ``None`` when there is no such active row.
    The primary is refused: ``ValueError``.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    with get_session() as session:
        row = (
            session.query(Mailbox)
            .filter(
                Mailbox.owner_id == owner_id,
                Mailbox.id == mailbox_id,
                Mailbox.removed_at.is_(None),
            )
            .first()
        )
        if row is None:
            return None
        if row.is_primary:
            raise ValueError("the primary mailbox cannot be removed")
        row.removed_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush()
        info = _info(row)
    logger.info(f"[mailboxes] removed mailbox {info.address} for {owner_id} (rows kept)")
    return info


# ─── Presets ──────────────────────────────────────────────────

PEC_NET_PRESET = {
    "id": "pec.net",
    "label": "PEC.net (Register.it)",
    "domains": ["pec.net"],
    "imap_host": "imap.pec-email.com",
    "imap_port": 993,
    "imap_security": "ssl",
    "smtp_host": "smtp.pec-email.com",
    "smtp_port": 465,
    "smtp_security": "ssl",
    "username": "full_address",
    "password_label": "PEC mailbox password",
}


def presets() -> list[dict]:
    """The provider presets an app can offer: the engine's tables plus PEC.net.

    One entry per provider (domains grouped), each with IMAP and SMTP
    host, port and security, the username rule and the label the
    password field should carry.
    """
    from zylch.email.imap_client import IMAP_PRESETS, SMTP_PRESETS

    by_host: dict[tuple, dict] = {}
    for domain, (imap_host, imap_port) in IMAP_PRESETS.items():
        smtp_host, smtp_port = SMTP_PRESETS.get(domain, (None, None))
        key = (imap_host, smtp_host)
        entry = by_host.get(key)
        if entry is None:
            entry = by_host[key] = {
                "id": domain,
                "label": domain,
                "domains": [],
                "imap_host": imap_host,
                "imap_port": imap_port,
                "imap_security": "ssl",
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "smtp_security": "starttls",
                "username": "full_address",
                "password_label": "App password",
            }
        entry["domains"].append(domain)
    out = list(by_host.values())
    out.append(dict(PEC_NET_PRESET))
    return out


# ─── IMAP client per mailbox ──────────────────────────────────


def credential_fingerprint(mailbox: MailboxInfo) -> str:
    """A hash of what logs this mailbox in, for cache keys. Never the plaintext.

    Covers the address, hosts, ports and the stored secret ciphertext
    (the primary's ``EMAIL_PASSWORD`` for the primary), so a password
    change yields a different key and a cached client is rebuilt.
    """
    import hashlib

    if mailbox.is_primary:
        secret_part = os.environ.get("EMAIL_PASSWORD", "")
    else:
        secret_part = _stored_secret(mailbox.owner_id, mailbox.id) or ""
    material = "|".join(
        str(x)
        for x in (
            mailbox.address,
            mailbox.imap_host,
            mailbox.imap_port,
            mailbox.smtp_host,
            mailbox.smtp_port,
            secret_part,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _stored_secret(owner_id: str, mailbox_id: str) -> str | None:
    from zylch.storage.database import get_session
    from zylch.storage.models import Mailbox

    with get_session() as session:
        row = (
            session.query(Mailbox.secret)
            .filter(Mailbox.owner_id == owner_id, Mailbox.id == mailbox_id)
            .first()
        )
        return row[0] if row else None


def client_for_row(owner_id: str, row: dict) -> IMAPClient:
    """The client of the mailbox an ``emails`` row belongs to.

    A row without a known mailbox (a legacy dict from a tool) falls back to
    the primary: the mail is the profile's own either way.
    """
    mailbox = None
    mailbox_id = (row or {}).get("mailbox_id")
    if mailbox_id:
        mailbox = by_id(owner_id, mailbox_id)
        if mailbox is not None and mailbox.removed:
            # `get_email_by_supabase_id` is not filtered by mailbox: a row of
            # a removed mailbox must never log into it.
            raise MailboxSecretError(f"mailbox {mailbox.address} was removed from this profile")
    if mailbox is None:
        mailbox = primary(owner_id)
    if mailbox is None:
        raise MailboxSecretError("no mailbox is configured for this profile")
    return build_imap_client(mailbox)


def build_imap_client(mailbox: MailboxInfo) -> IMAPClient:
    """An :class:`IMAPClient` for one mailbox; connects on first use.

    The primary's password is the ``.env`` ``EMAIL_PASSWORD`` and its hosts
    are the environment's when set (the row mirrors them); any other
    mailbox decrypts its stored secret and uses the row's hosts. Both
    paths fail closed with :class:`MailboxSecretError` when no password
    can be produced.
    """
    from zylch.email.imap_client import IMAPClient

    if mailbox.is_primary:
        password = os.environ.get("EMAIL_PASSWORD", "")
        if not password:
            raise MailboxSecretError("the primary mailbox has no EMAIL_PASSWORD in the profile")
        hosts = env_hosts()
        imap_host = hosts["imap_host"] or mailbox.imap_host
        imap_port = hosts["imap_port"] or mailbox.imap_port
        smtp_host = hosts["smtp_host"] or mailbox.smtp_host
        smtp_port = hosts["smtp_port"] or mailbox.smtp_port
    else:
        password = decrypt_secret(_stored_secret(mailbox.owner_id, mailbox.id))
        imap_host, imap_port = mailbox.imap_host, mailbox.imap_port
        smtp_host, smtp_port = mailbox.smtp_host, mailbox.smtp_port
    logger.debug(
        f"[mailboxes] build_imap_client(address={mailbox.address}, primary={mailbox.is_primary}, "
        f"imap_host={imap_host}, password=present)"
    )
    return IMAPClient(
        email_addr=mailbox.address,
        password=password,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
    )
