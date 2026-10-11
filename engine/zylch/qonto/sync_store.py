"""Guarded source page persistence and durable bounded window planning."""

import hashlib
import json
import time
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy import func, or_

from zylch.qonto import guard, repository
from zylch.qonto.amounts import instant, utc
from zylch.qonto.errors import QontoError
from zylch.qonto.models import QontoAccount, QontoSyncWindow, QontoTransaction


def balances(session, binding, org):
    for account in org.accounts:
        if account.id not in binding.account_ids:
            continue
        row = session.get(QontoAccount, (binding.dataset_id, account.id))
        if row is None or row.currency != account.currency:
            raise QontoError("binding_changed")
        for prefix, value in (
            ("balance", account.balance),
            ("authorized_balance", account.authorized_balance),
        ):
            if value is not None:
                setattr(row, prefix + "_minor", value.minor)
                setattr(row, prefix + "_scale", value.scale)
                setattr(row, prefix + "_decimal", value.decimal)
        row.balance_provider_at = account.updated_at
        row.balance_retrieved_at = account.retrieved_at or time.time()


def window_id(binding, account, basis, start, end, purpose):
    return hashlib.sha256(
        json.dumps([binding.dataset_id, account, basis, start, end, purpose]).encode()
    ).hexdigest()


def add_window(session, binding, account, basis, start, end, purpose):
    key = window_id(binding, account, basis, start, end, purpose)
    row = session.get(QontoSyncWindow, key)
    if row is None:
        row = QontoSyncWindow(
            id=key,
            dataset_id=binding.dataset_id,
            uid=binding.uid,
            account_id=account,
            generation=binding.generation,
            date_basis=basis,
            window_from=start,
            window_to=end,
            purpose=purpose,
        )
        session.add(row)
    return row


def daily_windows(start, end):
    cursor = instant(start)
    limit = instant(end)
    while cursor < limit:
        following = min(cursor + timedelta(days=1), limit)
        yield utc(cursor), utc(following)
        cursor = following


def plan(authority, binding, started, *, initial):
    with guard.commit_guard(authority, binding) as session:
        for account_id in binding.account_ids:
            account = session.get(QontoAccount, (binding.dataset_id, account_id))
            fresh = account.initial_from is None
            if account.initial_from is None:
                account.initial_from = utc(started - timedelta(days=30))
                account.initial_to = utc(started)
            for start, end in daily_windows(account.initial_from, account.initial_to):
                add_window(session, binding, account_id, "emitted_at", start, end, "initial")
            if not initial or not fresh:
                start = instant(account.updated_watermark or account.initial_from) - timedelta(
                    hours=48
                )
                incremental = add_window(
                    session,
                    binding,
                    account_id,
                    "updated_at",
                    utc(start),
                    utc(started),
                    "incremental",
                )
                if incremental.status == "completed":
                    incremental.status = "pending"
                for start, end in daily_windows(utc(started - timedelta(hours=48)), utc(started)):
                    recent = add_window(
                        session, binding, account_id, "emitted_at", start, end, "recent"
                    )
                    if recent.status == "completed":
                        recent.status = "pending"
                pending = (
                    session.query(QontoTransaction.emitted_at)
                    .filter(
                        QontoTransaction.dataset_id == binding.dataset_id,
                        QontoTransaction.account_id == account_id,
                        QontoTransaction.status == "pending",
                        QontoTransaction.emitted_at.isnot(None),
                    )
                    .order_by(QontoTransaction.emitted_at)
                    .all()
                )
                dates = sorted(
                    {
                        instant(value).replace(hour=0, minute=0, second=0, microsecond=0)
                        for (value,) in pending
                    }
                )
                cursor = account.pending_repair_cursor or ""
                dates = [day for day in dates if utc(day) > cursor] + [
                    day for day in dates if utc(day) <= cursor
                ]
                for day in dates[:8]:
                    row = add_window(
                        session,
                        binding,
                        account_id,
                        "emitted_at",
                        utc(day),
                        utc(min(day + timedelta(days=1), started)),
                        "pending",
                    )
                    if row.status == "completed":
                        row.status = "pending"
                    account.pending_repair_cursor = utc(day)
        session.flush()
        rows = (
            session.query(QontoSyncWindow)
            .filter(
                QontoSyncWindow.dataset_id == binding.dataset_id,
                QontoSyncWindow.account_id.in_(binding.account_ids),
                QontoSyncWindow.status != "completed",
                or_(QontoSyncWindow.retry_at.is_(None), QontoSyncWindow.retry_at <= time.time()),
            )
            .all()
        )
        return fair_order(session, binding, rows)


def fair_order(session, binding, rows):
    progress = (
        session.query(
            QontoSyncWindow.purpose,
            QontoSyncWindow.account_id,
            func.max(QontoSyncWindow.completed_at),
        )
        .filter(
            QontoSyncWindow.dataset_id == binding.dataset_id,
            QontoSyncWindow.account_id.in_(binding.account_ids),
        )
        .group_by(QontoSyncWindow.purpose, QontoSyncWindow.account_id)
        .all()
    )
    last = {(purpose, account): completed or 0 for purpose, account, completed in progress}
    queues = defaultdict(lambda: defaultdict(deque))
    for row in sorted(rows, key=lambda item: (item.attempts or 0, item.window_from, item.id)):
        queues[row.purpose][row.account_id].append(row.id)
    purposes = sorted(
        queues,
        key=lambda purpose: (
            max(last.get((purpose, account), 0) for account in binding.account_ids),
            purpose,
        ),
    )
    accounts = {
        purpose: deque(
            sorted(queues[purpose], key=lambda account: (last.get((purpose, account), 0), account))
        )
        for purpose in purposes
    }
    result = []
    while any(accounts.values()):
        for purpose in purposes:
            if not accounts[purpose]:
                continue
            account = accounts[purpose].popleft()
            result.append(queues[purpose][account].popleft())
            if queues[purpose][account]:
                accounts[purpose].append(account)
    return result


def begin(authority, binding, key):
    with guard.commit_guard(authority, binding) as session:
        row = session.get(QontoSyncWindow, key)
        if row.retry_at and row.retry_at > time.time():
            return None
        row.status = "running"
        row.generation = binding.generation
        row.next_page = 1
        row.observed_count = 0
        row.total_count = None
        row.total_pages = None
        row.attempts += 1
        row.last_error = None
        row.retry_at = None
        return row.account_id, row.date_basis, row.window_from, row.window_to


def upsert(session, binding, account, item, retrieved):
    key = repository.source_id(
        binding.dataset_id, binding.organization_id, account, item["transaction_id"]
    )
    row = session.get(QontoTransaction, key)
    if row is not None:
        previous, incoming = row.updated_at, item["updated_at"]
        if previous and (incoming is None or incoming < previous):
            return
        if row.source_revision == item["source_revision"]:
            return
    else:
        row = QontoTransaction(
            source_id=key,
            dataset_id=binding.dataset_id,
            uid=binding.uid,
            organization_id=binding.organization_id,
            account_id=account,
            host_id=binding.host_id,
            company_scope=binding.company_scope,
        )
        session.add(row)
    for name, value in item.items():
        setattr(row, name, value)
    row.retrieved_at = retrieved


def page(authority, binding, key, number, result, seen):
    with guard.commit_guard(authority, binding) as session:
        row = session.get(QontoSyncWindow, key)
        if row.total_count is not None and (
            row.total_count != result.total_count or row.total_pages != result.total_pages
        ):
            raise QontoError("pagination_changed")
        ids = [item["transaction_id"] for item in result.transactions]
        if len(ids) != len(set(ids)) or set(ids) & seen:
            raise QontoError("pagination_changed")
        retrieved = time.time()
        for item in result.transactions:
            basis = item[row.date_basis]
            if basis is not None and not row.window_from <= basis <= row.window_to:
                raise QontoError("invalid_response")
            upsert(session, binding, row.account_id, item, retrieved)
        row.total_count = result.total_count
        row.total_pages = result.total_pages
        row.observed_count += len(ids)
        row.next_page = result.next_page or number
        row.retrieved_at = retrieved
        if row.observed_count > result.total_count:
            raise QontoError("pagination_changed")
        if result.next_page is None:
            if row.observed_count != result.total_count:
                raise QontoError("pagination_changed")
            row.status = "completed"
            row.completed_at = retrieved
            row.last_error = None
            account = session.get(QontoAccount, (binding.dataset_id, row.account_id))
            if row.date_basis == "updated_at":
                account.updated_watermark = max(
                    account.updated_watermark or row.window_to, row.window_to
                )
            if row.purpose == "initial":
                session.flush()
                windows = (
                    session.query(QontoSyncWindow)
                    .filter_by(
                        dataset_id=binding.dataset_id, account_id=row.account_id, purpose="initial"
                    )
                    .order_by(QontoSyncWindow.window_from)
                    .all()
                )
                cursor = account.initial_from
                for window in windows:
                    if window.status != "completed" or window.window_from != cursor:
                        break
                    cursor = window.window_to
                account.emitted_watermark = cursor if cursor != account.initial_from else None
                if cursor == account.initial_to and account.updated_watermark is None:
                    account.updated_watermark = cursor
        seen.update(ids)


def failure(authority, binding, key, outcome, *, delay=30):
    with guard.commit_guard(authority, binding) as session:
        row = session.get(QontoSyncWindow, key)
        row.status = "partial"
        row.last_error = outcome
        row.retry_at = time.time() + delay
        row.completed_at = None
        repository.connection(session, binding.uid).last_error = outcome
        if outcome == "rate_limited":
            repository.connection(session, binding.uid).provider_retry_at = row.retry_at


def coverage(binding):
    with repository.profile_transaction() as session:
        rows = (
            session.query(QontoSyncWindow)
            .filter(
                QontoSyncWindow.dataset_id == binding.dataset_id,
                QontoSyncWindow.account_id.in_(binding.account_ids),
            )
            .all()
        )
        unfinished = [row for row in rows if row.status != "completed"]
        eligibility = [row.retry_at for row in unfinished if row.retry_at]
        accounts = (
            session.query(QontoAccount)
            .filter(
                QontoAccount.dataset_id == binding.dataset_id,
                QontoAccount.account_id.in_(binding.account_ids),
            )
            .all()
        )
        unplanned = (
            sum(row.initial_from is None for row in accounts)
            + len(binding.account_ids)
            - len(accounts)
        )
        connection = repository.connection(session, binding.uid)
        last_error = connection.last_error or next(
            (row.last_error for row in unfinished if row.last_error), None
        )
        if connection.provider_retry_at:
            eligibility.append(connection.provider_retry_at)
        pending_dates = (
            session.query(QontoTransaction.account_id, QontoTransaction.emitted_at)
            .filter(
                QontoTransaction.dataset_id == binding.dataset_id,
                QontoTransaction.account_id.in_(binding.account_ids),
                QontoTransaction.status == "pending",
            )
            .all()
        )
        return {
            "status": ("partial" if unfinished or unplanned or last_error else "completed"),
            "completed_windows": len(rows) - len(unfinished),
            "remaining_windows": len(unfinished) + unplanned * 30,
            "remaining_backfill_windows": sum(row.purpose == "initial" for row in unfinished)
            + unplanned * 30,
            "history_planned": not bool(unplanned),
            "error": last_error,
            "unresolved_pending_windows": len(
                {(account, value[:10] if value else None) for account, value in pending_dates}
            ),
            "retry_at": min(eligibility) if eligibility else None,
            "coverage_kind": "traversed_windows",
            "accounts": [
                {
                    "account_id": row.account_id,
                    "emitted_watermark": row.emitted_watermark,
                    "updated_watermark": row.updated_watermark,
                    "initial_from": row.initial_from,
                    "initial_to": row.initial_to,
                }
                for row in accounts
            ],
        }
