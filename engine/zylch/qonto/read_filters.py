"""Strict bounded filters for private financial reads."""

from datetime import datetime, timedelta

from zylch.qonto.amounts import timestamp
from zylch.qonto.errors import QontoError
from zylch.qonto.source import STATUSES

MAX_DAYS = 31
MAX_PAGE_SIZE = 50
MAX_SUMMARY_ROWS = 500
STALE_SECONDS = 86400


def refuse(outcome):
    error = QontoError("operation_failed")
    error.outcome = outcome
    error.args = (outcome + ": Narrow the Qonto request or sync its coverage first.",)
    raise error


def bounded_int(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        refuse("filters_invalid")
    return value


def accounts(params, binding):
    ids = params.get("account_ids", list(binding.account_ids))
    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) > 100
        or any(not isinstance(item, str) or item not in binding.account_ids for item in ids)
        or len(set(ids)) != len(ids)
    ):
        raise QontoError("accounts_invalid")
    return sorted(ids)


def filters(params, binding, *, paged=False):
    allowed = {"account_ids", "date_basis", "date_from", "date_to", "statuses", "currency", "side"}
    if paged:
        allowed |= {"page", "page_size"}
    if set(params) - allowed:
        refuse("filters_invalid")
    basis = params.get("date_basis")
    if basis not in ("emitted_at", "updated_at", "settled_at"):
        refuse("filters_invalid")
    statuses = params.get("statuses")
    if (
        not isinstance(statuses, list)
        or not statuses
        or any(not isinstance(item, str) or item not in STATUSES for item in statuses)
        or len(set(statuses)) != len(statuses)
    ):
        refuse("filters_invalid")
    try:
        if not all(isinstance(params.get(key), str) for key in ("date_from", "date_to")):
            raise ValueError
        start, end = timestamp(params["date_from"]), timestamp(params["date_to"])
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        if not timedelta(0) < delta <= timedelta(days=MAX_DAYS):
            raise ValueError
    except (ValueError, TypeError, QontoError):
        refuse("filters_invalid")
    currency = params.get("currency")
    if currency is not None and (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isupper()
    ):
        refuse("filters_invalid")
    side = params.get("side")
    if side is not None and side not in ("debit", "credit"):
        refuse("filters_invalid")
    result = dict(
        account_ids=accounts(params, binding),
        date_basis=basis,
        date_from=start,
        date_to=end,
        statuses=statuses,
        currency=currency,
        side=side,
    )
    if paged:
        result.update(
            page=bounded_int(params.get("page", 1), 1, 1000),
            page_size=bounded_int(params.get("page_size", 25), 1, MAX_PAGE_SIZE),
        )
    return result
