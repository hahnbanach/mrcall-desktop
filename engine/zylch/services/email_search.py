"""Gmail-style query parser and matcher for the desktop email search.

Translates strings like

    from:alice subject:"q3 plan" has:attachment newer_than:7d -is:read

into a structured :class:`ParsedQuery`, and exposes
:func:`email_matches` to test a single :class:`zylch.storage.models.Email`
row against it. Pure functions — no DB access here, the storage layer
threads the parser into its existing in-RAM scan.

Operators supported:

    from:        substring of from_email or from_name
    to:          substring of to_email
    cc:          substring of cc_email
    subject:     substring of subject
    body:        substring of body_plain
    has:         attachment / attachments / attach / file
    is:          unread | read | pinned | auto
    before:      YYYY-MM-DD (UTC), strict less-than
    after:       YYYY-MM-DD (UTC), >=
    older_than:  Nd | Nw | Nm | Ny — relative cutoff
    newer_than:  same units, >= cutoff
    filename:    substring inside any attachment_filenames entry

Bare terms (no ``key:``) match in subject / body_plain / snippet /
from_email / from_name. A leading ``-`` negates a predicate. Multiple
predicates of the same operator OR together (Gmail-style); different
operators AND.

Unknown ``key:value`` pairs degrade silently to free-text — the search
should not fail just because the user typed an operator we haven't
implemented.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

_KNOWN_OPS = {
    "from",
    "to",
    "cc",
    "subject",
    "body",
    "has",
    "is",
    "before",
    "after",
    "older_than",
    "newer_than",
    "filename",
}


@dataclass
class Predicate:
    op: str  # one of _KNOWN_OPS, or "" for free-text
    value: str
    negate: bool = False


@dataclass
class ParsedQuery:
    predicates: List[Predicate] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.predicates


def _tokens(text: str) -> List[Tuple[str, bool]]:
    """Split *text* into ``(raw_token, was_pure_quoted)`` pairs.

    Whitespace inside a quoted region does not split a token, so
    ``subject:"q3 plan"`` is one token whose content is
    ``subject:q3 plan``. The second tuple element is ``True`` only when
    the *entire* token was a single quoted phrase with no unquoted
    prefix or suffix — that is the case the caller treats as a free
    term (not an operator+value).
    """
    out: List[Tuple[str, bool]] = []
    buf: List[str] = []
    quote: Optional[str] = None
    started_with_quote = False
    has_unquoted_chars = False
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        else:
            if ch in ('"', "'"):
                if not buf:
                    started_with_quote = True
                quote = ch
            elif ch.isspace():
                if buf:
                    out.append(
                        (
                            "".join(buf),
                            started_with_quote and not has_unquoted_chars,
                        )
                    )
                    buf = []
                    started_with_quote = False
                    has_unquoted_chars = False
            else:
                has_unquoted_chars = True
                buf.append(ch)
    if buf:
        out.append(
            (
                "".join(buf),
                started_with_quote and not has_unquoted_chars,
            )
        )
    return out


def parse_query(text: str) -> ParsedQuery:
    """Parse a Gmail-like search string into a :class:`ParsedQuery`."""
    text = (text or "").strip()
    if not text:
        return ParsedQuery()

    preds: List[Predicate] = []
    for raw, was_quoted in _tokens(text):
        if not raw:
            continue
        negate = False
        s = raw
        if not was_quoted and s.startswith("-") and len(s) > 1:
            negate = True
            s = s[1:]

        op = ""
        value = s
        if not was_quoted:
            colon = s.find(":")
            if colon > 0:
                head = s[:colon].lower()
                if head in _KNOWN_OPS:
                    op = head
                    value = s[colon + 1 :]
                    if (
                        len(value) >= 2
                        and value[0] in ('"', "'")
                        and value[-1] == value[0]
                    ):
                        value = value[1:-1]
        preds.append(Predicate(op=op, value=value, negate=negate))
    return ParsedQuery(predicates=preds)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REL_RE = re.compile(r"^(\d+)([dwmy])$", re.IGNORECASE)


def _parse_abs_date(value: str) -> Optional[datetime]:
    if not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_rel_offset(value: str) -> Optional[timedelta]:
    m = _REL_RE.match(value)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "d":
        return timedelta(days=n)
    if unit == "w":
        return timedelta(weeks=n)
    if unit == "m":
        return timedelta(days=n * 30)
    if unit == "y":
        return timedelta(days=n * 365)
    return None


def _icontains(haystack: Optional[str], needle: str) -> bool:
    if not haystack or not needle:
        return False
    return needle.lower() in haystack.lower()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _match_one(
    row: Any,
    p: Predicate,
    *,
    user_email: str,
    now: datetime,
) -> bool:
    op = p.op
    value = p.value
    if value == "":
        return True

    if op == "":
        return (
            _icontains(getattr(row, "subject", None), value)
            or _icontains(getattr(row, "body_plain", None), value)
            or _icontains(getattr(row, "snippet", None), value)
            or _icontains(getattr(row, "from_email", None), value)
            or _icontains(getattr(row, "from_name", None), value)
        )
    if op == "from":
        return _icontains(
            getattr(row, "from_email", None), value
        ) or _icontains(getattr(row, "from_name", None), value)
    if op == "to":
        return _icontains(getattr(row, "to_email", None), value)
    if op == "cc":
        return _icontains(getattr(row, "cc_email", None), value)
    if op == "subject":
        return _icontains(getattr(row, "subject", None), value)
    if op == "body":
        return _icontains(getattr(row, "body_plain", None), value)
    if op == "filename":
        names = getattr(row, "attachment_filenames", None) or []
        return any(_icontains(n, value) for n in names)
    if op == "has":
        v = value.lower()
        if v in ("attachment", "attachments", "attach", "file"):
            return bool(getattr(row, "has_attachments", False))
        return False
    if op == "is":
        v = value.lower()
        if v == "pinned":
            return getattr(row, "pinned_at", None) is not None
        if v == "unread":
            sender = (getattr(row, "from_email", "") or "").lower()
            from_user = bool(user_email) and sender == user_email
            return (
                not from_user
                and getattr(row, "read_at", None) is None
            )
        if v == "read":
            return getattr(row, "read_at", None) is not None
        if v == "auto":
            return bool(getattr(row, "is_auto_reply", False))
        return False
    if op in ("before", "after"):
        target = _parse_abs_date(value)
        date_val = getattr(row, "date", None)
        if target is None or date_val is None:
            return False
        row_dt = _aware(date_val)
        if op == "before":
            return row_dt < target
        return row_dt >= target
    if op in ("older_than", "newer_than"):
        delta = _parse_rel_offset(value)
        date_val = getattr(row, "date", None)
        if delta is None or date_val is None:
            return False
        row_dt = _aware(date_val)
        cutoff = now - delta
        if op == "older_than":
            return row_dt < cutoff
        return row_dt >= cutoff
    return False


def email_matches(
    row: Any,
    query: ParsedQuery,
    *,
    user_email: str = "",
    now: Optional[datetime] = None,
) -> bool:
    """Return True if a single email row satisfies *query*.

    Multiple predicates with the same operator OR together; different
    operators AND. Negated predicates AND-NOT.
    """
    if query.is_empty:
        return True

    me = (user_email or "").lower()
    now_dt = now or datetime.now(timezone.utc)

    positive: dict[str, list[Predicate]] = {}
    negative: list[Predicate] = []
    for p in query.predicates:
        if p.negate:
            negative.append(p)
        else:
            positive.setdefault(p.op, []).append(p)

    for _op, preds in positive.items():
        if not any(_match_one(row, p, user_email=me, now=now_dt) for p in preds):
            return False
    for p in negative:
        if _match_one(row, p, user_email=me, now=now_dt):
            return False
    return True
