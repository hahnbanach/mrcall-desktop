"""Pattern detection for exact-match search queries."""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class DetectedPattern:
    """A detected pattern in a search query."""

    type: str  # "email", "phone", "url"
    value: str  # The matched pattern


EMAIL_REGEX = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
PHONE_REGEX = r'[\+]?[0-9]{7,15}'  # International format, 7-15 digits
URL_REGEX = r'https?://[^\s]+'


def detect_pattern(query: str) -> Optional[DetectedPattern]:
    """Detect if query is an exact-match pattern (email, phone, URL).

    Args:
        query: The search query string

    Returns:
        DetectedPattern if a pattern is found, None otherwise
    """
    query = query.strip()

    # Check for email pattern
    if re.fullmatch(EMAIL_REGEX, query, re.IGNORECASE):
        return DetectedPattern(type="email", value=query)

    # Check for phone pattern (clean first)
    clean_phone = re.sub(r'[\s\-\(\)]', '', query)
    if re.fullmatch(PHONE_REGEX, clean_phone):
        return DetectedPattern(type="phone", value=clean_phone)

    # Check for URL pattern
    if re.fullmatch(URL_REGEX, query, re.IGNORECASE):
        return DetectedPattern(type="url", value=query)

    return None
