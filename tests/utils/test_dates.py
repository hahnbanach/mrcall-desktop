"""Regression tests for email date parsing.

Bug history: `dt.replace(tzinfo=None)` was being used in two places to "make
the datetime naive" for storage. That silently kept the sender-timezone
wall-clock, so a `Date: Fri, 27 Feb 2026 07:42:27 -0600` header was stored
as naive `2026-02-27 07:42:27` instead of the correct UTC `2026-02-27
13:42:27`. Thread chronology and task detection drew wrong conclusions.

These tests pin the corrected behaviour of
`zylch.utils.parse_email_date_to_utc_naive`.
"""

from datetime import datetime

import pytest

from zylch.utils import parse_email_date_to_utc_naive


def test_rfc2822_negative_offset_converted_to_utc():
    """Missive sends from US Central (-0600). Regression case for Tentacools bug."""
    result = parse_email_date_to_utc_naive("Fri, 27 Feb 2026 07:42:27 -0600")
    assert result == datetime(2026, 2, 27, 13, 42, 27)
    assert result.tzinfo is None


def test_rfc2822_positive_offset_converted_to_utc():
    """Italy in November is +0100 (CET). 10:30 CET == 09:30 UTC."""
    result = parse_email_date_to_utc_naive("Thu, 20 Nov 2025 10:30:59 +0100")
    assert result == datetime(2025, 11, 20, 9, 30, 59)
    assert result.tzinfo is None


def test_rfc2822_utc_offset_unchanged():
    result = parse_email_date_to_utc_naive("Wed, 01 Jan 2025 00:00:00 +0000")
    assert result == datetime(2025, 1, 1, 0, 0, 0)
    assert result.tzinfo is None


def test_iso_with_z_suffix():
    result = parse_email_date_to_utc_naive("2026-02-27T13:42:27Z")
    assert result == datetime(2026, 2, 27, 13, 42, 27)
    assert result.tzinfo is None


def test_iso_with_explicit_offset():
    result = parse_email_date_to_utc_naive("2026-02-27T07:42:27-06:00")
    assert result == datetime(2026, 2, 27, 13, 42, 27)
    assert result.tzinfo is None


def test_empty_string_raises():
    with pytest.raises(ValueError, match="Empty"):
        parse_email_date_to_utc_naive("")


def test_garbage_raises():
    with pytest.raises(ValueError):
        parse_email_date_to_utc_naive("not a date at all")
