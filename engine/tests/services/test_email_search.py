"""Tests for the Gmail-style email search parser + matcher.

Covers tokenisation, operator dispatch, negation, OR-of-same-op,
quoted phrases, date predicates, and the empty-query short-circuit.
The matcher is fed plain dataclass-shaped rows so the tests don't
need a real SQLAlchemy session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from zylch.services.email_search import (
    ParsedQuery,
    Predicate,
    email_matches,
    parse_query,
)


@dataclass
class _Row:
    from_email: str = ""
    from_name: str = ""
    to_email: str = ""
    cc_email: str = ""
    subject: str = ""
    body_plain: str = ""
    snippet: str = ""
    has_attachments: bool = False
    attachment_filenames: Optional[List[str]] = None
    pinned_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    is_auto_reply: bool = False
    date: Optional[datetime] = None


# --------------------------------------------------------------- parser


def _ops(q: ParsedQuery) -> list[tuple[str, str, bool]]:
    return [(p.op, p.value, p.negate) for p in q.predicates]


def test_parse_empty():
    assert parse_query("").is_empty
    assert parse_query("   ").is_empty


def test_parse_free_terms():
    assert _ops(parse_query("invoice april")) == [
        ("", "invoice", False),
        ("", "april", False),
    ]


def test_parse_known_ops():
    q = parse_query("from:alice to:bob subject:invoice")
    assert _ops(q) == [
        ("from", "alice", False),
        ("to", "bob", False),
        ("subject", "invoice", False),
    ]


def test_parse_quoted_phrase_as_value():
    q = parse_query('subject:"q3 plan" body:"important note"')
    assert _ops(q) == [
        ("subject", "q3 plan", False),
        ("body", "important note", False),
    ]


def test_parse_quoted_bare_term():
    q = parse_query('"hello world"')
    # A bare quoted string is a single free term.
    assert _ops(q) == [("", "hello world", False)]


def test_parse_negation():
    q = parse_query("-from:spam -is:read")
    assert _ops(q) == [
        ("from", "spam", True),
        ("is", "read", True),
    ]


def test_parse_unknown_op_falls_back_to_free_term():
    q = parse_query("label:work foo:bar")
    # Unknown ops kept as free-text predicates with the colon intact —
    # treated as opaque substrings to match (so they degrade silently).
    assert _ops(q) == [
        ("", "label:work", False),
        ("", "foo:bar", False),
    ]


def test_parse_dash_in_value_is_not_negation():
    # Quoted negation is a literal.
    q = parse_query('"-not-negated"')
    assert _ops(q) == [("", "-not-negated", False)]


# -------------------------------------------------------------- matcher


def test_match_empty_query_matches_anything():
    row = _Row(subject="anything")
    assert email_matches(row, ParsedQuery()) is True


def test_match_free_term_searches_multiple_columns():
    row = _Row(
        subject="Q3 plan",
        body_plain="",
        snippet="",
        from_email="alice@example.com",
        from_name="Alice",
    )
    assert email_matches(row, parse_query("plan")) is True
    assert email_matches(row, parse_query("alice")) is True
    assert email_matches(row, parse_query("nope")) is False


def test_match_from_op_searches_email_and_name():
    row = _Row(from_email="alice@example.com", from_name="Alice Wonderland")
    assert email_matches(row, parse_query("from:alice")) is True
    assert email_matches(row, parse_query("from:wonder")) is True
    assert email_matches(row, parse_query("from:bob")) is False


def test_match_to_and_cc_are_distinct():
    row = _Row(to_email="primary@example.com", cc_email="copy@example.com")
    assert email_matches(row, parse_query("to:primary")) is True
    assert email_matches(row, parse_query("to:copy")) is False  # cc is separate
    assert email_matches(row, parse_query("cc:copy")) is True


def test_match_subject_and_body_separate():
    row = _Row(subject="Lunch", body_plain="contract attached")
    assert email_matches(row, parse_query("subject:lunch")) is True
    assert email_matches(row, parse_query("subject:contract")) is False
    assert email_matches(row, parse_query("body:contract")) is True


def test_match_has_attachment():
    row_yes = _Row(has_attachments=True)
    row_no = _Row(has_attachments=False)
    assert email_matches(row_yes, parse_query("has:attachment")) is True
    assert email_matches(row_yes, parse_query("has:attach")) is True
    assert email_matches(row_no, parse_query("has:attachment")) is False


def test_match_filename():
    row = _Row(
        has_attachments=True,
        attachment_filenames=["Report Q3.pdf", "image.png"],
    )
    assert email_matches(row, parse_query("filename:report")) is True
    assert email_matches(row, parse_query("filename:.pdf")) is True
    assert email_matches(row, parse_query("filename:invoice")) is False


def test_match_is_unread_excludes_user_sent():
    row_other = _Row(from_email="alice@example.com", read_at=None)
    row_user = _Row(from_email="me@me.com", read_at=None)
    row_read = _Row(
        from_email="alice@example.com",
        read_at=datetime.now(timezone.utc),
    )
    q = parse_query("is:unread")
    assert email_matches(row_other, q, user_email="me@me.com") is True
    assert email_matches(row_user, q, user_email="me@me.com") is False
    assert email_matches(row_read, q, user_email="me@me.com") is False


def test_match_is_pinned_and_is_auto():
    row = _Row(pinned_at=datetime.now(timezone.utc), is_auto_reply=True)
    assert email_matches(row, parse_query("is:pinned")) is True
    assert email_matches(row, parse_query("is:auto")) is True
    assert email_matches(_Row(), parse_query("is:pinned")) is False


def test_match_date_absolute():
    apr = datetime(2026, 4, 15, tzinfo=timezone.utc)
    row = _Row(date=apr)
    assert email_matches(row, parse_query("after:2026-04-01")) is True
    assert email_matches(row, parse_query("after:2026-05-01")) is False
    assert email_matches(row, parse_query("before:2026-05-01")) is True
    assert email_matches(row, parse_query("before:2026-04-01")) is False


def test_match_date_relative():
    now = datetime(2026, 5, 5, tzinfo=timezone.utc)
    row_recent = _Row(date=now - timedelta(days=3))
    row_old = _Row(date=now - timedelta(days=30))
    assert email_matches(row_recent, parse_query("newer_than:7d"), now=now) is True
    assert email_matches(row_old, parse_query("newer_than:7d"), now=now) is False
    assert email_matches(row_old, parse_query("older_than:14d"), now=now) is True
    assert email_matches(row_recent, parse_query("older_than:14d"), now=now) is False


def test_match_negation():
    row = _Row(from_email="spam@spam.com", subject="Cheap deals")
    assert email_matches(row, parse_query("-from:spam")) is False
    assert email_matches(row, parse_query("-from:nobody")) is True


def test_match_or_within_same_op():
    # Same-op predicates OR; matches alice OR bob.
    row = _Row(from_email="alice@example.com")
    q = parse_query("from:alice from:bob")
    assert email_matches(row, q) is True
    row2 = _Row(from_email="carol@example.com")
    assert email_matches(row2, q) is False


def test_match_and_across_ops():
    row = _Row(from_email="alice@example.com", subject="Q3 plan")
    assert email_matches(row, parse_query("from:alice subject:q3")) is True
    assert email_matches(row, parse_query("from:alice subject:nope")) is False


def test_match_quoted_subject():
    row = _Row(subject="The Q3 plan is ready")
    assert email_matches(row, parse_query('subject:"q3 plan"')) is True
    assert email_matches(row, parse_query('subject:"q4 plan"')) is False


def test_match_naive_date_treated_as_utc():
    # ``Email.date`` is stored naive in the engine. The matcher must
    # treat naive datetimes as UTC; a sloppy implementation that compares
    # an aware ``after:`` target with a naive row date would raise.
    naive = datetime(2026, 4, 15)
    assert email_matches(_Row(date=naive), parse_query("after:2026-01-01")) is True
