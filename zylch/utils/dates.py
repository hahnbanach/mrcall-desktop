"""Date parsing utilities.

Zylch stores all datetimes as naive UTC (convention: naive == UTC). The
`emails.date` column and every other `DateTime` column in the model is naive;
`_utcnow()` in `storage/models.py` produces naive UTC. Dates coming from
external sources (RFC 2822 `Date:` headers, ISO 8601 strings) MUST be
converted through this helper before being compared, sorted, or stored.

The historical bug: `dt.replace(tzinfo=None)` was used to "make the datetime
naive", which keeps the wall-clock of the sender's timezone. For a header
like `Date: Fri, 27 Feb 2026 07:42:27 -0600` this stored `07:42:27` instead
of the correct UTC `13:42:27`, a 6-hour shift that silently corrupted thread
chronology and task detection reasoning.
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_email_date_to_utc_naive(raw: str) -> datetime:
    """Parse an RFC 2822 or ISO 8601 date string to a naive UTC datetime.

    Args:
        raw: Date string. Typical forms:
            - RFC 2822: `Fri, 27 Feb 2026 07:42:27 -0600`
            - ISO 8601: `2026-02-27T13:42:27+00:00` or `2026-02-27T13:42:27Z`

    Returns:
        Naive `datetime` in UTC (tzinfo stripped after offset is applied).

    Raises:
        ValueError: if `raw` is empty or cannot be parsed as RFC 2822 or
            ISO 8601.
    """
    if not raw:
        raise ValueError("Empty date string — cannot parse")

    dt: datetime | None = None
    rfc_err: Exception | None = None
    iso_err: Exception | None = None

    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError) as exc:
        rfc_err = exc

    if dt is None:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            iso_err = exc
            raise ValueError(
                f"Failed to parse date {raw!r}: RFC2822 error: {rfc_err}, " f"ISO error: {iso_err}"
            )

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)
