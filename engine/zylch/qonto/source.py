"""Allow-listed normalized transaction source content and revision hashes."""

import hashlib
import json

from zylch.qonto.amounts import currency, money, timestamp
from zylch.qonto.errors import QontoError

STATUSES = ("pending", "completed", "declined", "reversed")


def text(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > 4096 or (required and not value):
        raise QontoError("invalid_response")
    return value


def transaction(item):
    if not isinstance(item, dict):
        raise QontoError("invalid_response")
    result = {
        "transaction_id": text(item.get("transaction_id"), required=True),
        "provider_id": text(item.get("id")),
        "status": item.get("status"),
        "side": item.get("side"),
        "currency": currency(item.get("currency")),
        **{key: timestamp(item.get(key)) for key in ("emitted_at", "settled_at", "updated_at")},
        **{key: text(item.get(key)) for key in ("label", "reference", "note")},
        "counterparty_name": text(item.get("counterparty_name")),
    }
    if result["status"] not in STATUSES or result["side"] not in ("debit", "credit"):
        raise QontoError("invalid_response")
    amount = money(item.get("amount"), item.get("amount_cents"))
    result.update(
        amount_minor=amount.minor, amount_scale=amount.scale, amount_decimal=amount.decimal
    )
    original = item.get("local_amount")
    if original is not None:
        original_money = money(original, item.get("local_amount_cents"))
        result.update(
            original_currency=currency(item.get("local_currency")),
            original_amount_minor=original_money.minor,
            original_amount_scale=original_money.scale,
            original_amount_decimal=original_money.decimal,
        )
    else:
        if item.get("local_amount_cents") is not None:
            raise QontoError("invalid_response")
        result.update(
            original_currency=(
                currency(item["local_currency"]) if item.get("local_currency") else None
            ),
            original_amount_minor=None,
            original_amount_scale=None,
            original_amount_decimal=None,
        )
    result["source_revision"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result
