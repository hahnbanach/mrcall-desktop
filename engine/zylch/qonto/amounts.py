"""Exact provider money and UTC timestamps without binary floating point."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Context, Decimal, InvalidOperation
import re

from zylch.qonto.errors import QontoError


@dataclass(frozen=True)
class Money:
    minor: int
    scale: int
    decimal: str


def currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise QontoError("invalid_response")
    return value


def money(value, cents=None):
    try:
        if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
            raise ValueError
        number = Decimal(value)
        if not number.is_finite() or number.copy_abs() > Decimal("92233720368547758.07"):
            raise ValueError
        fixed = number.quantize(Decimal("0.01"), context=Context(prec=24))
        if number != fixed:
            raise ValueError
        minor = int(fixed * 100)
        if cents is not None and (type(cents) is not int or cents != minor):
            raise ValueError
        return Money(minor, 2, format(fixed if minor else Decimal(0), ".2f"))
    except (ValueError, InvalidOperation, OverflowError):
        raise QontoError("invalid_response") from None


def timestamp(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return utc(parsed)
    except (ValueError, OverflowError):
        raise QontoError("invalid_response") from None


def utc(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def retrieved_time(value):
    """Render stored retrieval instants for literal model citation."""
    return {
        "retrieved_at": value,
        "retrieved_at_utc": (
            None if value is None else utc(datetime.fromtimestamp(value, timezone.utc))
        ),
    }
