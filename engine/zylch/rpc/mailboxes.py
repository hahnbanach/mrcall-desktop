"""RPC handlers for the profile's mailboxes (``mailboxes.*``).

The primary mailbox is the sign-up address configured in Settings
(``EMAIL_ADDRESS`` / ``EMAIL_PASSWORD`` / hosts in ``.env``); this surface
only reads it. Additional mailboxes are added, tested, changed and removed
here; their passwords are encrypted under the profile's
``MAILBOX_SECRET_KEY`` (``zylch.email.mailbox_secrets``) and never leave the
engine: no result carries a password or a secret, and no message echoes
one.

Refusals are answers (``{ok: false, status, message}``), not errors, so a
renderer can show them inline: a failed test, a duplicate address, an
unknown or primary row. Errors are reserved for a missing required
parameter.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.exc import IntegrityError

from zylch.email import mailboxes as mailbox_rows
from zylch.email.mailbox_probe import probe_mailbox
from zylch.email.mailbox_secrets import MailboxSecretError, ensure_secret_key

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


def _int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    return int(value)


def _state(row: mailbox_rows.MailboxInfo) -> str:
    if row.last_error:
        return "error"
    if row.last_sync_at is not None:
        return "ok"
    return "never"


def _configured(row: mailbox_rows.MailboxInfo) -> bool:
    if row.is_primary:
        return bool(row.address) and bool(os.environ.get("EMAIL_PASSWORD"))
    return bool(row.address) and row.has_secret


def _row_dict(row: mailbox_rows.MailboxInfo) -> Dict[str, Any]:
    """A mailbox row as the app sees it: no secret, ever."""
    return {
        "id": row.id,
        "address": row.address,
        "imap_host": row.imap_host,
        "imap_port": row.imap_port,
        "smtp_host": row.smtp_host,
        "smtp_port": row.smtp_port,
        "preset": row.preset,
        "is_primary": row.is_primary,
        "configured": _configured(row),
        "state": _state(row),
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _refuse(status: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "status": status, "message": message}


def _probe_client(address: str, password: str, hosts: Dict[str, Any]):
    from zylch.email.imap_client import IMAPClient

    return IMAPClient(
        email_addr=address,
        password=password,
        imap_host=hosts.get("imap_host") or None,
        imap_port=_int(hosts.get("imap_port")),
        smtp_host=hosts.get("smtp_host") or None,
        smtp_port=_int(hosts.get("smtp_port")),
    )


async def _run_probe(address: str, password: str, hosts: Dict[str, Any]) -> Dict[str, Any]:
    if "@" not in address:
        return _refuse("invalid", f"{address!r} is not an email address")
    try:
        client = _probe_client(address, password, hosts)
    except (TypeError, ValueError) as e:
        return _refuse("invalid", f"mailbox settings are not valid: {e}")
    result = await asyncio.to_thread(probe_mailbox, client)
    return result.to_dict()


async def mailboxes_list(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mailboxes.list() -> {mailboxes: [{id, address, imap_host, imap_port, smtp_host, smtp_port, preset, is_primary, configured, state, last_sync_at, last_error, created_at}]}.

    Every active mailbox of the profile, the primary first, without
    secrets. ``configured`` is false for a primary whose address or
    ``EMAIL_PASSWORD`` is empty and for an additional mailbox without a
    stored password. ``state`` is ``ok`` (last sync succeeded), ``error``
    (``last_error`` set) or ``never`` (not synced yet).
    """
    owner_id = _owner_id()
    rows = [_row_dict(r) for r in mailbox_rows.for_owner(owner_id)]
    logger.debug(f"[rpc] mailboxes.list owner_id={owner_id} -> {len(rows)} mailbox(es)")
    return {"mailboxes": rows}


async def mailboxes_presets(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mailboxes.presets() -> {presets: [{id, label, domains, imap_host, imap_port, imap_security, smtp_host, smtp_port, smtp_security, username, password_label}]}.

    The engine's provider table plus ``PEC.net (Register.it)``. ``username``
    is ``full_address`` for every preset; ``password_label`` is what the
    password field should be called for that provider.
    """
    return {"presets": mailbox_rows.presets()}


async def mailboxes_test(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mailboxes.test(address, password, imap_host?, imap_port?, smtp_host?, smtp_port?) -> {ok, status, message}.

    IMAP login, LIST, read-only SELECT of INBOX and of the Sent and
    archive folders discovery finds (absent ones count as absent).
    ``status`` is ``ok``, ``auth``, ``unreachable``, ``tls`` or ``folder``
    (a found folder cannot be selected); ``invalid`` when the address or
    a port is not usable. The message never echoes the password. Nothing
    is stored.
    """
    address = str(params.get("address") or "").strip()
    password = params.get("password")
    if not address:
        raise ValueError("address is required")
    if not password:
        raise ValueError("password is required")
    result = await _run_probe(address, str(password), params)
    logger.info(f"[rpc] mailboxes.test address={address} -> {result['status']}")
    return result


async def mailboxes_add(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mailboxes.add(address, password, imap_host?, imap_port?, smtp_host?, smtp_port?, preset?) -> {ok, status, message?, mailbox?}.

    Runs ``mailboxes.test`` first and refuses on its failure with the same
    ``status`` (``auth``, ``unreachable``, ``tls``, ``folder``,
    ``invalid``); refuses an active duplicate address, compared
    case-insensitively, and the primary's address (``duplicate``); answers
    ``secret`` when the profile's key cannot be written or the password
    cannot be stored; revives a removed row with its id, rows and cursors.
    The profile's ``MAILBOX_SECRET_KEY`` is written to ``.env`` before the
    row, so a restart in between never leaves an unreadable secret.
    """
    address = str(params.get("address") or "").strip()
    password = params.get("password")
    if not address:
        raise ValueError("address is required")
    if not password:
        raise ValueError("password is required")
    owner_id = _owner_id()
    existing = mailbox_rows.by_address(owner_id, address)
    if existing is not None:
        return _refuse("duplicate", f"{address} is already configured on this profile")

    probe = await _run_probe(address, str(password), params)
    if not probe["ok"]:
        return probe

    try:
        ensure_secret_key()  # the key precedes the row (M1 risk note)
        row = mailbox_rows.add_mailbox(
            owner_id,
            address,
            str(password),
            imap_host=params.get("imap_host") or None,
            imap_port=_int(params.get("imap_port")),
            smtp_host=params.get("smtp_host") or None,
            smtp_port=_int(params.get("smtp_port")),
            preset=params.get("preset") or None,
        )
    except MailboxSecretError as e:
        logger.error(f"[rpc] mailboxes.add {address}: secret store failed: {e}")
        return _refuse("secret", str(e))
    except ValueError as e:
        return _refuse("duplicate", str(e))
    except IntegrityError as e:
        # Another process stored the address between the check and the
        # write. The driver's text carries the statement parameters (the
        # ciphertext among them): only the classification leaves.
        logger.info(f"[rpc] mailboxes.add {address}: stored concurrently ({type(e).__name__})")
        return _refuse("duplicate", f"{address} is already configured on this profile")
    logger.info(f"[rpc] mailboxes.add {address} -> {row.id}")
    return {"ok": True, "status": "ok", "mailbox": _row_dict(row)}


async def mailboxes_update(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mailboxes.update(mailbox_id, imap_host?, imap_port?, smtp_host?, smtp_port?, password?, preset?) -> {ok, status, message?, mailbox?}.

    Changes an additional mailbox's hosts, ports, preset or password.
    When a host, port or password changes the mailbox is re-tested with
    the new values (and the stored password when none is given) and the
    change is refused on failure with the test's ``status`` (``auth``,
    ``unreachable``, ``tls``, ``folder``, ``invalid``); ``secret`` when the
    stored or new password cannot be handled; ``unknown`` for an id the
    profile has no active row for; ``primary`` for the primary, which is
    configured in Settings.
    """
    mailbox_id = str(params.get("mailbox_id") or "").strip()
    if not mailbox_id:
        raise ValueError("mailbox_id is required")
    owner_id = _owner_id()
    row = mailbox_rows.by_id(owner_id, mailbox_id)
    if row is None or row.removed:
        return _refuse("unknown", "no such mailbox on this profile")
    if row.is_primary:
        return _refuse("primary", "the primary mailbox is configured in Settings")

    changes = {
        k: params[k]
        for k in ("imap_host", "imap_port", "smtp_host", "smtp_port")
        if k in params and params[k] is not None
    }
    password = params.get("password")
    if changes or password:
        hosts = {
            "imap_host": changes.get("imap_host", row.imap_host),
            "imap_port": changes.get("imap_port", row.imap_port),
            "smtp_host": changes.get("smtp_host", row.smtp_host),
            "smtp_port": changes.get("smtp_port", row.smtp_port),
        }
        try:
            secret = (
                str(password)
                if password
                else mailbox_rows.decrypt_secret(mailbox_rows._stored_secret(owner_id, row.id))
            )
        except MailboxSecretError as e:
            return _refuse("secret", str(e))
        probe = await _run_probe(row.address, secret, hosts)
        if not probe["ok"]:
            return probe
    try:
        updated = mailbox_rows.update_mailbox(
            owner_id,
            mailbox_id,
            imap_host=changes.get("imap_host"),
            imap_port=_int(changes["imap_port"]) if "imap_port" in changes else None,
            smtp_host=changes.get("smtp_host"),
            smtp_port=_int(changes["smtp_port"]) if "smtp_port" in changes else None,
            password=str(password) if password else None,
            preset=params.get("preset"),
        )
    except MailboxSecretError as e:
        return _refuse("secret", str(e))
    except ValueError as e:
        return _refuse("primary", str(e))
    if updated is None:
        return _refuse("unknown", "no such mailbox on this profile")
    logger.info(f"[rpc] mailboxes.update {updated.address} -> ok")
    return {"ok": True, "status": "ok", "mailbox": _row_dict(updated)}


async def mailboxes_remove(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """mailboxes.remove(mailbox_id) -> {ok, status, message?, mailbox?}.

    Sets ``removed_at``: the sync stops covering the mailbox and its rows
    leave every list, search and processing query; rows, cursors and the
    memory already extracted are kept, and re-adding the address revives
    the same row. ``unknown`` for an id the profile has no active row for;
    ``primary`` for the primary, which cannot be removed.
    """
    mailbox_id = str(params.get("mailbox_id") or "").strip()
    if not mailbox_id:
        raise ValueError("mailbox_id is required")
    owner_id = _owner_id()
    try:
        removed = mailbox_rows.remove_mailbox(owner_id, mailbox_id)
    except ValueError as e:
        return _refuse("primary", str(e))
    if removed is None:
        return _refuse("unknown", "no such mailbox on this profile")
    logger.info(f"[rpc] mailboxes.remove {removed.address} -> hidden, rows kept")
    return {"ok": True, "status": "ok", "mailbox": _row_dict(removed)}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "mailboxes.list": mailboxes_list,
    "mailboxes.presets": mailboxes_presets,
    "mailboxes.test": mailboxes_test,
    "mailboxes.add": mailboxes_add,
    "mailboxes.update": mailboxes_update,
    "mailboxes.remove": mailboxes_remove,
}
