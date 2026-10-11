"""Exact cents, normalized UTC and source revision contracts."""

from decimal import Decimal

import pytest

from zylch.qonto.amounts import money, timestamp
from zylch.qonto.errors import QontoError
from zylch.qonto.source import transaction


@pytest.mark.parametrize(
    "value,cents,expected",
    [
        (Decimal("0.43"), 43, "0.43"),
        ("-1.20", -120, "-1.20"),
        (0, 0, "0.00"),
        ("1234567890123.45", 123456789012345, "1234567890123.45"),
    ],
)
def test_exact_money(value, cents, expected):
    result = money(value, cents)
    assert result.decimal == expected and result.minor == cents and result.scale == 2


@pytest.mark.parametrize(
    "value,cents",
    [
        (0.43, 43),
        (True, 100),
        ("NaN", None),
        ("Infinity", None),
        ("0.001", None),
        ("1.00", 99),
        ("1", True),
        ("92233720368547759", None),
    ],
)
def test_invalid_money(value, cents):
    with pytest.raises(QontoError, match="invalid_response"):
        money(value, cents)


def test_utc_and_nullable_timestamp():
    assert timestamp(None) is None
    assert timestamp("2026-10-04T02:00:00+02:00") == "2026-10-04T00:00:00.000000Z"
    with pytest.raises(QontoError):
        timestamp("2026-10-04T02:00:00")


def test_original_currency_and_revision():
    raw = dict(
        transaction_id="source",
        amount="12.10",
        amount_cents=1210,
        currency="EUR",
        local_amount="10.20",
        local_amount_cents=1020,
        local_currency="GBP",
        status="pending",
        side="debit",
    )
    one = transaction(raw)
    assert one["original_currency"] == "GBP" and one["original_amount_minor"] == 1020
    assert one["emitted_at"] is None and one["settled_at"] is None
    assert transaction({**raw, "attachment_ids": ["not-saved"]}) == one
    assert transaction({**raw, "status": "reversed"})["source_revision"] != one["source_revision"]


def test_excess_precision_cannot_round_into_valid_cents():
    with pytest.raises(QontoError, match="invalid_response"):
        money("0.43000000000000000000000000000000001", 43)
    assert money("-0.00", 0).decimal == "0.00"


def test_observed_live_retrieval_time_is_formatted_without_model_conversion():
    from zylch.qonto.amounts import retrieved_time

    assert retrieved_time(1791182991.28412) == {
        "retrieved_at": 1791182991.28412,
        "retrieved_at_utc": "2026-10-05T06:49:51.284120Z",
    }
    assert retrieved_time(None) == {"retrieved_at": None, "retrieved_at_utc": None}
