"""Auto-reply and automatic email detection utilities.

Detects automatic email messages such as:
- Out-of-office (OOF) replies
- Auto-responders
- Mailer-daemon bounces
- Mailing list auto-responses
- Vacation responders
"""

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def detect_auto_reply(headers: Dict[str, Optional[str]], from_email: Optional[str] = None) -> bool:
    """Detect if an email is an automatic reply/response.

    Checks standard email headers used to indicate automatic messages:
    - Auto-Submitted: auto-generated, auto-replied, auto-notified
    - X-Auto-Response-Suppress: All, OOF, DR, RN, NRN
    - Precedence: bulk, junk, list, auto_reply
    - X-Autoreply: yes
    - X-Autorespond: (any value)
    - Return-Path: <> (empty = bounce)
    - X-Failed-Recipients: (bounce indicator)

    Args:
        headers: Dict of email headers (case-insensitive keys recommended)
        from_email: Optional sender email for additional heuristics

    Returns:
        True if the email appears to be an automatic message
    """
    # Check from_email first (works even with empty/None headers)
    if from_email and is_auto_reply_sender(from_email):
        logger.debug(f"Auto-reply detected: from_email pattern match ({from_email})")
        return True

    if not headers:
        return False

    # Normalize header keys to handle case variations
    normalized = {k.lower() if k else '': v for k, v in headers.items()}

    # 1. Auto-Submitted header (RFC 3834)
    # Values: auto-generated, auto-replied, auto-notified
    auto_submitted = normalized.get('auto-submitted', '')
    if auto_submitted:
        auto_submitted_lower = auto_submitted.lower()
        if auto_submitted_lower.startswith('auto-'):
            logger.debug(f"Auto-reply detected: Auto-Submitted={auto_submitted}")
            return True

    # 2. X-Auto-Response-Suppress header (Microsoft)
    # Values: All, OOF, DR, RN, NRN, AutoReply
    x_auto_suppress = normalized.get('x-auto-response-suppress', '')
    if x_auto_suppress:
        logger.debug(f"Auto-reply detected: X-Auto-Response-Suppress={x_auto_suppress}")
        return True

    # 3. Precedence header
    # Values indicating auto: bulk, junk, list, auto_reply
    precedence = normalized.get('precedence', '')
    if precedence:
        precedence_lower = precedence.lower()
        auto_precedence_values = ['bulk', 'junk', 'list', 'auto_reply', 'auto-reply']
        if precedence_lower in auto_precedence_values:
            logger.debug(f"Auto-reply detected: Precedence={precedence}")
            return True

    # 4. X-Autoreply header
    x_autoreply = normalized.get('x-autoreply', '')
    if x_autoreply:
        if x_autoreply.lower() in ['yes', 'true', '1']:
            logger.debug(f"Auto-reply detected: X-Autoreply={x_autoreply}")
            return True

    # 5. X-Autorespond header (any value indicates auto-response)
    x_autorespond = normalized.get('x-autorespond', '')
    if x_autorespond:
        logger.debug(f"Auto-reply detected: X-Autorespond={x_autorespond}")
        return True

    # 6. Return-Path empty (bounce indicator)
    return_path = normalized.get('return-path', '')
    if return_path == '<>' or return_path == '':
        # Only if explicitly set to empty (not just missing)
        if 'return-path' in normalized:
            logger.debug("Auto-reply detected: Return-Path is empty (bounce)")
            return True

    # 7. X-Failed-Recipients header (bounce indicator)
    x_failed = normalized.get('x-failed-recipients', '')
    if x_failed:
        logger.debug(f"Auto-reply detected: X-Failed-Recipients={x_failed}")
        return True

    # 8. Content-Type multipart/report (delivery status notification)
    content_type = normalized.get('content-type', '')
    if content_type:
        if 'multipart/report' in content_type.lower():
            logger.debug("Auto-reply detected: Content-Type=multipart/report")
            return True
        if 'delivery-status' in content_type.lower():
            logger.debug("Auto-reply detected: Content-Type contains delivery-status")
            return True

    # 9. X-MS-Exchange-Generated-Message-Source (Exchange auto-messages)
    x_ms_generated = normalized.get('x-ms-exchange-generated-message-source', '')
    if x_ms_generated:
        logger.debug(f"Auto-reply detected: X-MS-Exchange-Generated-Message-Source={x_ms_generated}")
        return True

    return False


def is_auto_reply_sender(email: str) -> bool:
    """Check if sender email matches common auto-reply patterns.

    Args:
        email: Sender email address

    Returns:
        True if email appears to be from an automated sender
    """
    if not email:
        return False

    email_lower = email.lower()

    # Extract local part (before @)
    local_part = email_lower.split('@')[0] if '@' in email_lower else email_lower

    # Patterns that indicate auto-reply sender
    auto_patterns = [
        'mailer-daemon',
        'postmaster',
        'noreply',
        'no-reply',
        'no_reply',
        'donotreply',
        'do-not-reply',
        'do_not_reply',
        'auto-reply',
        'autoreply',
        'auto_reply',
        'bounce',
        'daemon',
        'automated',
    ]

    for pattern in auto_patterns:
        if pattern in local_part:
            return True

    # Check domain part for system addresses
    if '@' in email_lower:
        domain = email_lower.split('@')[1]
        system_domains = [
            'mailer-daemon',
            'bounce.',
            'notifications.',
        ]
        for sys_domain in system_domains:
            if domain.startswith(sys_domain):
                return True

    return False


def detect_vacation_responder(subject: str, body: str) -> bool:
    """Detect vacation/out-of-office auto-responders by content.

    This is a fallback for when headers don't indicate auto-reply
    but the content clearly shows it's an OOF message.

    Args:
        subject: Email subject line
        body: Email body text

    Returns:
        True if content indicates vacation/OOF auto-responder
    """
    if not subject and not body:
        return False

    text = f"{subject or ''} {body or ''}".lower()

    # Common vacation responder phrases (multilingual)
    vacation_phrases = [
        # English
        'out of office',
        'out of the office',
        'away from office',
        'automatic reply',
        'auto reply',
        'auto-reply',
        'vacation reply',
        'i am currently out',
        'i will be out',
        'i am away',
        'i will be away',
        'limited access to email',
        'away from my desk',
        'on vacation',
        'on holiday',
        'on leave',
        'maternity leave',
        'paternity leave',
        # Italian
        'fuori ufficio',
        'risposta automatica',
        'sono in ferie',
        'sono assente',
        # German
        'abwesenheitsnotiz',
        'automatische antwort',
        'bin nicht im büro',
        # French
        'absence du bureau',
        'réponse automatique',
        'je suis absent',
        # Spanish
        'fuera de la oficina',
        'respuesta automática',
        'estoy de vacaciones',
    ]

    for phrase in vacation_phrases:
        if phrase in text:
            return True

    return False
