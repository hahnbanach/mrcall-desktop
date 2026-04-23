"""
Auto-Reply Detection Utility

Detects auto-reply emails based on RFC 3834 headers and common patterns.
"""

from typing import Dict, Optional
import re


def detect_auto_reply(headers: Dict[str, str], from_email: str = None) -> bool:
    """
    Detect if email is an auto-reply based on headers and sender patterns.

    Checks multiple indicators following RFC 3834 and common auto-reply patterns:
    - Auto-Submitted header with auto-* values
    - X-Autoreply header
    - Precedence header (bulk, auto_reply, list, junk)
    - X-Auto-Response-Suppress header
    - From/Reply-To email patterns (noreply@, no-reply@, mailer-daemon@)

    Args:
        headers: Dictionary of email headers (case-insensitive keys)
        from_email: Optional sender email address

    Returns:
        True if auto-reply detected, False otherwise

    Examples:
        >>> detect_auto_reply({'Auto-Submitted': 'auto-replied'})
        True
        >>> detect_auto_reply({}, 'noreply@example.com')
        True
        >>> detect_auto_reply({'Subject': 'Hello'}, 'user@example.com')
        False
    """
    # Normalize headers to lowercase for case-insensitive matching
    normalized_headers = {k.lower(): v for k, v in headers.items()}

    # Check Auto-Submitted header (RFC 3834)
    auto_submitted = normalized_headers.get('auto-submitted', '')
    if auto_submitted and auto_submitted.lower() != 'no':
        # Any value except "no" indicates auto-reply
        if auto_submitted.lower().startswith('auto-'):
            return True

    # Check X-Autoreply header
    x_autoreply = normalized_headers.get('x-autoreply', '')
    if x_autoreply and x_autoreply.lower() in ('yes', 'true', '1'):
        return True

    # Check Precedence header
    precedence = normalized_headers.get('precedence', '')
    auto_precedence_values = {'bulk', 'auto_reply', 'list', 'junk'}
    if precedence.lower() in auto_precedence_values:
        return True

    # Check X-Auto-Response-Suppress header
    # Any non-empty value indicates suppression request
    x_auto_suppress = normalized_headers.get('x-auto-response-suppress', '')
    if x_auto_suppress and x_auto_suppress.strip():
        return True

    # Check From email patterns
    if from_email:
        from_email_lower = from_email.lower()
        auto_reply_patterns = [
            r'^noreply@',
            r'^no-reply@',
            r'^no_reply@',
            r'^mailer-daemon@',
            r'^postmaster@',
            r'^daemon@',
            r'^bounce@',
            r'^do-not-reply@',
            r'^donotreply@'
        ]

        for pattern in auto_reply_patterns:
            if re.match(pattern, from_email_lower):
                return True

    # Check Reply-To header for similar patterns
    reply_to = normalized_headers.get('reply-to', '')
    if reply_to:
        reply_to_lower = reply_to.lower()
        auto_reply_patterns = [
            r'noreply@',
            r'no-reply@',
            r'no_reply@',
            r'mailer-daemon@',
            r'donotreply@'
        ]

        for pattern in auto_reply_patterns:
            if re.search(pattern, reply_to_lower):
                return True

    return False


def get_auto_reply_reason(headers: Dict[str, str], from_email: str = None) -> Optional[str]:
    """
    Get the reason why an email was classified as auto-reply.

    Args:
        headers: Dictionary of email headers (case-insensitive keys)
        from_email: Optional sender email address

    Returns:
        Reason string if auto-reply detected, None otherwise

    Examples:
        >>> get_auto_reply_reason({'Auto-Submitted': 'auto-replied'})
        "Auto-Submitted header: 'auto-replied'"
        >>> get_auto_reply_reason({}, 'noreply@example.com')
        "From address matches no-reply pattern: 'noreply@example.com'"
        >>> get_auto_reply_reason({'Subject': 'Hello'})
        None
    """
    # Normalize headers to lowercase
    normalized_headers = {k.lower(): v for k, v in headers.items()}

    # Check Auto-Submitted header (RFC 3834)
    auto_submitted = normalized_headers.get('auto-submitted', '')
    if auto_submitted and auto_submitted.lower() != 'no':
        if auto_submitted.lower().startswith('auto-'):
            return f"Auto-Submitted header: '{auto_submitted}'"

    # Check X-Autoreply header
    x_autoreply = normalized_headers.get('x-autoreply', '')
    if x_autoreply and x_autoreply.lower() in ('yes', 'true', '1'):
        return f"X-Autoreply header: '{x_autoreply}'"

    # Check Precedence header
    precedence = normalized_headers.get('precedence', '')
    auto_precedence_values = {'bulk', 'auto_reply', 'list', 'junk'}
    if precedence.lower() in auto_precedence_values:
        return f"Precedence header: '{precedence}'"

    # Check X-Auto-Response-Suppress header
    x_auto_suppress = normalized_headers.get('x-auto-response-suppress', '')
    if x_auto_suppress and x_auto_suppress.strip():
        return f"X-Auto-Response-Suppress header: '{x_auto_suppress}'"

    # Check From email patterns
    if from_email:
        from_email_lower = from_email.lower()
        pattern_names = {
            r'^noreply@': 'noreply@',
            r'^no-reply@': 'no-reply@',
            r'^no_reply@': 'no_reply@',
            r'^mailer-daemon@': 'mailer-daemon@',
            r'^postmaster@': 'postmaster@',
            r'^daemon@': 'daemon@',
            r'^bounce@': 'bounce@',
            r'^do-not-reply@': 'do-not-reply@',
            r'^donotreply@': 'donotreply@'
        }

        for pattern, name in pattern_names.items():
            if re.match(pattern, from_email_lower):
                return f"From address matches no-reply pattern: '{from_email}'"

    # Check Reply-To header
    reply_to = normalized_headers.get('reply-to', '')
    if reply_to:
        reply_to_lower = reply_to.lower()
        patterns = [r'noreply@', r'no-reply@', r'no_reply@',
                   r'mailer-daemon@', r'donotreply@']

        for pattern in patterns:
            if re.search(pattern, reply_to_lower):
                return f"Reply-To address matches no-reply pattern: '{reply_to}'"

    return None
