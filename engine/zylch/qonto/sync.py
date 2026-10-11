"""Single-flight source-only sync with bounded network work and guarded commits."""

import asyncio
import time
import uuid
from datetime import datetime, timezone

from zylch.qonto import guard, repository, sync_store
from zylch.qonto.errors import QontoError
from zylch.qonto.provider import get_provider, probe
from zylch.qonto.secrets import decrypt_credentials

RUN_SECONDS = 120
MAX_REQUESTS = 160
MAX_WINDOWS = 96
SCAN_ATTEMPTS = 2


def now():
    return datetime.now(timezone.utc)


def acquire(authority, binding):
    token = uuid.uuid4().hex
    with guard.commit_guard(authority, binding) as session:
        row = repository.connection(session, binding.uid)
        if row.sync_token and row.sync_expires_at and row.sync_expires_at > time.time():
            raise QontoError("busy")
        row.sync_token = token
        row.sync_expires_at = time.time() + RUN_SECONDS + 35
    return token


def release(authority, binding, token):
    with guard.state_guard(authority.profile_dir):
        with repository.profile_transaction() as session:
            row = repository.connection(session, binding.uid)
            if row and row.generation == binding.generation and row.sync_token == token:
                row.sync_token = None
                row.sync_expires_at = None
                row.last_sync_at = time.time()


async def run(*, initial=False):
    authority, binding = guard.active_binding()
    value = decrypt_credentials(binding.encrypted_credentials, authority.profile_dir)
    token = acquire(authority, binding)
    started = now()
    deadline = time.monotonic() + RUN_SECONDS
    requests = 0
    outcome = None
    try:
        try:
            with guard.commit_guard(authority, binding) as session:
                row = repository.connection(session, binding.uid)
                throttled = row.provider_retry_at and row.provider_retry_at > time.time()
            if throttled:
                return {
                    "ok": True,
                    "generation": binding.generation,
                    "requests": 0,
                    **sync_store.coverage(binding),
                    "status": "partial",
                    "error": "rate_limited",
                }
            org = await probe(value)
            if org.id != binding.organization_id or not set(binding.account_ids) <= {
                account.id for account in org.accounts
            }:
                raise QontoError("binding_changed")
            with guard.commit_guard(authority, binding) as session:
                sync_store.balances(session, binding, org)
            keys = sync_store.plan(authority, binding, started, initial=initial)
            for key in keys[:MAX_WINDOWS]:
                if requests >= MAX_REQUESTS or time.monotonic() >= deadline:
                    outcome = "sync_limit"
                    break
                for attempt in range(SCAN_ATTEMPTS):
                    window = sync_store.begin(authority, binding, key)
                    if window is None:
                        break
                    account, basis, start, end = window
                    number = 1
                    seen = set()
                    try:
                        while True:
                            if requests >= MAX_REQUESTS or time.monotonic() >= deadline:
                                raise QontoError("sync_limit")
                            requests += 1
                            async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                                result = await get_provider().transactions(
                                    value, account, basis, start, end, number
                                )
                            sync_store.page(authority, binding, key, number, result, seen)
                            if result.next_page is None:
                                break
                            number = result.next_page
                        break
                    except TimeoutError:
                        error = QontoError("network")
                    except QontoError as exc:
                        error = exc
                    except Exception:
                        error = QontoError("invalid_response")
                    if error.outcome in (
                        "generation_changed",
                        "not_connected",
                        "binding_changed",
                        "identity_required",
                        "session_expired",
                        "company_joining",
                        "company_unavailable",
                    ):
                        raise error
                    if error.outcome == "auth":
                        guard.auth_failed(authority, binding)
                        raise error
                    if error.outcome == "pagination_changed" and attempt + 1 < SCAN_ATTEMPTS:
                        sync_store.failure(authority, binding, key, error.outcome, delay=0)
                        continue
                    sync_store.failure(
                        authority,
                        binding,
                        key,
                        error.outcome,
                        delay=getattr(error, "retry_after", 30),
                    )
                    outcome = error.outcome
                    break
                if outcome in ("rate_limited", "network", "tls", "sync_limit"):
                    break
            with guard.commit_guard(authority, binding) as session:
                row = repository.connection(session, binding.uid)
                row.last_error = outcome
                if outcome != "rate_limited":
                    row.provider_retry_at = None
            result = sync_store.coverage(binding)
            if outcome:
                result["status"] = "partial"
                result["error"] = outcome
            return {"ok": True, "generation": binding.generation, "requests": requests, **result}
        except QontoError as exc:
            if exc.outcome == "auth":
                guard.auth_failed(authority, binding)
            if exc.outcome in ("network", "tls", "rate_limited", "invalid_response"):
                with guard.commit_guard(authority, binding) as session:
                    row = repository.connection(session, binding.uid)
                    row.last_error = exc.outcome
                    if exc.outcome == "rate_limited":
                        row.provider_retry_at = time.time() + getattr(exc, "retry_after", 30)
                return {
                    "ok": True,
                    "generation": binding.generation,
                    "requests": requests,
                    **sync_store.coverage(binding),
                    "status": "partial",
                    "error": exc.outcome,
                }
            raise
    finally:
        release(authority, binding, token)
