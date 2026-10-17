"""Test, consented save, status and revocation without paid processing."""

from __future__ import annotations

import time

from zylch.qonto import challenges, guard, repository
from zylch.qonto.credentials import request_credentials
from zylch.qonto.errors import QontoError
from zylch.qonto.identity import current_authority, profile_identity, require_same
from zylch.qonto.models import (
    QontoAccount,
    QontoCheckpoint,
    QontoPublicationIntent,
    QontoSyncWindow,
    QontoTransaction,
)
from zylch.qonto.provider import probe
from zylch.qonto.secrets import decrypt_credentials, encrypt_credentials

CONSENT_VERSION = 1


def selected_accounts(
    values, available: tuple[str, ...], *, default_all: bool = False
) -> tuple[str, ...]:
    if values is None and default_all:
        return tuple(sorted(available))
    if not isinstance(values, list) or not values or len(values) > 100:
        raise QontoError("accounts_invalid")
    if any(
        not isinstance(value, str) or not value or value not in available for value in values
    ) or len(values) != len(set(values)):
        raise QontoError("accounts_invalid")
    return tuple(sorted(values))


async def test(params: dict) -> dict:
    authority = current_authority()
    binding = guard.state(authority)
    value = request_credentials(params)
    try:
        org = await probe(value)
    except QontoError as exc:
        if exc.outcome == "auth" and binding.status == "connected":
            _revoke_rejected_credentials(authority, binding, value)
        raise
    require_same(authority)
    with guard.state_guard(authority.profile_dir):
        from zylch.qonto.consent import company_name

        consent_company = company_name(authority)
        with repository.profile_transaction() as session:
            row = repository.connection(session, authority.uid)
            if row.generation != binding.generation:
                raise QontoError("generation_changed")
            accounts = selected_accounts(
                params.get("account_ids"),
                tuple(account.id for account in org.accounts),
                default_all=True,
            )
            token, expiry = challenges.issue(authority, row.generation, value, org, accounts)
    return {
        "ok": True,
        "organization": org.public(),
        "challenge_id": token,
        "expires_at": expiry,
        "account_ids": list(accounts),
        "engine_location": "hosted" if authority.host_id.startswith("hosted:") else "local",
        "consent_version": CONSENT_VERSION,
        "company_name": consent_company,
    }


async def connect(params: dict) -> dict:
    if (
        params.get("authority_confirmed") is not True
        or params.get("consent_version") != CONSENT_VERSION
        or isinstance(params.get("consent_version"), bool)
    ):
        raise QontoError("authority_required")
    authority = current_authority()
    binding = guard.state(authority)
    value = request_credentials(params)
    item = challenges.consume(params.get("challenge_id"), authority, binding.generation, value)
    accounts = selected_accounts(params.get("account_ids"), item.account_ids)
    if binding.encrypted_credentials:
        decrypt_credentials(binding.encrypted_credentials, authority.profile_dir)
    try:
        org = await probe(value)
    except QontoError as exc:
        if exc.outcome == "auth" and binding.status == "connected":
            _revoke_rejected_credentials(authority, binding, value)
        raise
    if org.id != item.organization_id or org.fingerprint() != item.organization_fingerprint:
        raise QontoError("binding_changed")
    selected_accounts(list(accounts), tuple(account.id for account in org.accounts))
    require_same(authority)
    with guard.state_guard(authority.profile_dir):
        require_same(authority)
        with repository.profile_transaction() as session:
            row = repository.connection(session, authority.uid)
            if row.generation != item.generation:
                raise QontoError("generation_changed")
            token = encrypt_credentials(
                value, authority.profile_dir, allow_create=not bool(row.encrypted_credentials)
            )
            row.host_id = authority.host_id
            row.company_scope = authority.company_scope
            row.organization_id = org.id
            row.dataset_id = repository.dataset_id(authority, org.id)
            row.selected_account_ids = list(accounts)
            row.encrypted_credentials = token
            row.generation += 1
            row.status = "connected"
            row.last_error = None
            row.sync_token = None
            row.sync_expires_at = None
            row.consent_at = time.time()
            row.consent_version = CONSENT_VERSION
            row.changed_at = time.time()
            guard.cancel_intents(session, authority.uid)
            session.query(QontoAccount).filter(QontoAccount.uid == authority.uid).update(
                {"selected": False}, synchronize_session=False
            )
            for account in org.accounts:
                if account.id not in accounts:
                    continue
                saved = session.get(QontoAccount, (row.dataset_id, account.id))
                if saved is None:
                    saved = QontoAccount(
                        dataset_id=row.dataset_id,
                        account_id=account.id,
                        uid=authority.uid,
                        organization_id=org.id,
                        host_id=authority.host_id,
                        company_scope=authority.company_scope,
                    )
                    session.add(saved)
                saved.name = account.name
                saved.currency = account.currency
                saved.selected = True
            generation = row.generation
            from zylch.qonto.sync_store import balances

            balances(session, repository.snapshot(row), org)
            require_same(authority)
    from zylch.qonto.sync import run

    try:
        initial_sync = await run(initial=True)
    except QontoError as exc:
        initial_sync = {"status": "partial", "error": exc.outcome}
        current = repository.read_binding(authority.uid)
        if current is None or current.generation != generation or current.status != "connected":
            return {
                "ok": False,
                "status": current.status if current else "disconnected",
                "generation": current.generation if current else generation,
                "initial_sync": initial_sync,
            }
    return {
        "ok": True,
        "status": "connected",
        "generation": generation,
        "account_count": len(accounts),
        "initial_sync": initial_sync,
    }


def status() -> dict:
    from zylch.auth import get_session

    uid, _ = profile_identity()
    session = get_session()
    if session is None or session.uid != uid:
        raise QontoError("identity_required")
    if session.is_expired():
        raise QontoError("session_expired")
    guard.recover()
    binding = repository.read_binding(uid)
    result = {
        "status": binding.status if binding else "disconnected",
        "generation": binding.generation if binding else 0,
        "credential_stored": bool(binding and binding.encrypted_credentials),
        "account_count": 0,
        "source_access": False,
    }
    if binding and binding.status == "connected":
        try:
            authority = current_authority()
            decrypt_credentials(binding.encrypted_credentials, authority.profile_dir)
            result["account_count"] = len(binding.account_ids)
            from zylch.qonto.sync_store import coverage

            result["sync"] = coverage(binding)
        except QontoError as exc:
            result["status"] = "unavailable"
            result["error"] = exc.outcome
    return result


def disconnect() -> dict:
    from zylch.auth import get_session

    uid, directory = profile_identity()
    session = get_session()
    if session is None or session.uid != uid:
        raise QontoError("identity_required")
    if session.is_expired():
        raise QontoError("session_expired")
    with guard.state_guard(directory):
        with repository.profile_transaction() as session:
            row = repository.connection(session, uid, create=True)
            guard.revoke(row, status="disconnected", reason="not_connected", erase=True)
            row.selected_account_ids = []
            session.query(QontoAccount).filter(QontoAccount.uid == uid).update(
                {"selected": False}, synchronize_session=False
            )
            guard.cancel_intents(session, uid)
            generation = row.generation
    return {
        "ok": True,
        "status": "disconnected",
        "generation": generation,
    }


def delete_imported_data(params: dict) -> dict:
    if params.get("confirmed") is not True:
        raise QontoError("confirmation_required")
    result = disconnect()
    uid, directory = profile_identity()
    with guard.state_guard(directory):
        with repository.profile_transaction() as session:
            row = repository.connection(session, uid)
            if row.generation != result["generation"] or row.status != "disconnected":
                raise QontoError("generation_changed")
            from zylch.qonto.task_records import delete_sources

            delete_sources(session, uid)
            removed = 0
            for model in (
                QontoTransaction,
                QontoAccount,
                QontoSyncWindow,
                QontoCheckpoint,
                QontoPublicationIntent,
            ):
                removed += (
                    session.query(model).filter(model.uid == uid).delete(synchronize_session=False)
                )
            row.dataset_id = None
            row.organization_id = None
            row.company_scope = None
            row.host_id = None
    return {**result, "deleted": True, "removed_rows": removed, "published_facts_retained": True}


def _revoke_rejected_credentials(authority, binding, value):
    if binding.encrypted_credentials:
        try:
            saved = decrypt_credentials(binding.encrypted_credentials, authority.profile_dir)
        except QontoError:
            return
        if saved == value:
            guard.auth_failed(authority, binding)
