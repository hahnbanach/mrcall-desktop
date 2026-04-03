"""Unified multi-channel conversation timeline.

Merges interactions across email, WhatsApp, and MrCall calls
for a single contact. Resolves contacts by email, phone, or name.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)


def get_unified_timeline(
    owner_id: str,
    contact_name: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    days_back: int = 90,
    limit: int = 50,
) -> Dict[str, Any]:
    """Get unified timeline of all interactions with a contact.

    Merges emails, WhatsApp messages, and MrCall calls into a
    single chronological timeline.

    Args:
        owner_id: User's owner ID
        contact_name: Contact name to search for
        contact_email: Contact email to filter by
        contact_phone: Contact phone to filter by
        days_back: How far back to look
        limit: Max interactions to return

    Returns:
        Dict with contact info, channel counts, and timeline.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import (
        Contact,
        Email,
        MrcallConversation,
        WhatsAppContact,
        WhatsAppMessage,
    )

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    timeline = []
    resolved_email = contact_email
    resolved_phone = contact_phone
    resolved_name = contact_name

    with get_session() as session:
        # -- Step 1: Resolve contact across channels -------

        # Try to find in contacts table (has both email + phone)
        if contact_name and not (contact_email and contact_phone):
            contact = (
                session.query(Contact)
                .filter(
                    Contact.owner_id == owner_id,
                    Contact.name.ilike(f"%{contact_name}%"),
                )
                .first()
            )
            if contact:
                resolved_email = resolved_email or contact.email
                resolved_phone = resolved_phone or contact.phone
                resolved_name = contact.name or resolved_name

        # Try WhatsApp contacts for phone resolution
        if contact_name and not resolved_phone:
            wa_contact = (
                session.query(WhatsAppContact)
                .filter(
                    WhatsAppContact.owner_id == owner_id,
                    WhatsAppContact.name.ilike(f"%{contact_name}%")
                    | WhatsAppContact.push_name.ilike(f"%{contact_name}%"),
                )
                .first()
            )
            if wa_contact:
                resolved_phone = wa_contact.phone_number
                resolved_name = wa_contact.name or wa_contact.push_name or resolved_name

        # -- Step 2: Query each channel ----------------------

        # Emails
        if resolved_email:
            emails = (
                session.query(Email)
                .filter(
                    Email.owner_id == owner_id,
                    Email.date >= cutoff,
                    Email.from_email.ilike(f"%{resolved_email}%")
                    | Email.to_email.ilike(f"%{resolved_email}%"),
                )
                .order_by(Email.date.desc())
                .limit(limit)
                .all()
            )
            for e in emails:
                is_from_me = not (e.from_email and resolved_email.lower() in e.from_email.lower())
                timeline.append(
                    {
                        "channel": "email",
                        "timestamp": e.date.isoformat() if e.date else None,
                        "dt": e.date,
                        "from_me": is_from_me,
                        "summary": e.subject or "(no subject)",
                        "preview": (e.snippet or "")[:200],
                    }
                )

        # Also search emails by contact name in from_name
        if contact_name and not resolved_email:
            emails = (
                session.query(Email)
                .filter(
                    Email.owner_id == owner_id,
                    Email.date >= cutoff,
                    Email.from_name.ilike(f"%{contact_name}%"),
                )
                .order_by(Email.date.desc())
                .limit(limit)
                .all()
            )
            for e in emails:
                timeline.append(
                    {
                        "channel": "email",
                        "timestamp": e.date.isoformat() if e.date else None,
                        "dt": e.date,
                        "from_me": False,
                        "summary": e.subject or "(no subject)",
                        "preview": (e.snippet or "")[:200],
                    }
                )

        # WhatsApp messages
        wa_jid = None
        if resolved_phone:
            clean = resolved_phone.replace("+", "").replace(" ", "")
            wa_jid = f"{clean}@s.whatsapp.net"
        elif contact_name:
            wa_contact = (
                session.query(WhatsAppContact)
                .filter(
                    WhatsAppContact.owner_id == owner_id,
                    WhatsAppContact.name.ilike(f"%{contact_name}%")
                    | WhatsAppContact.push_name.ilike(f"%{contact_name}%"),
                )
                .first()
            )
            if wa_contact:
                wa_jid = wa_contact.jid

        if wa_jid:
            wa_messages = (
                session.query(WhatsAppMessage)
                .filter(
                    WhatsAppMessage.owner_id == owner_id,
                    WhatsAppMessage.chat_jid == wa_jid,
                    WhatsAppMessage.timestamp >= cutoff,
                )
                .order_by(WhatsAppMessage.timestamp.desc())
                .limit(limit)
                .all()
            )
            for m in wa_messages:
                timeline.append(
                    {
                        "channel": "whatsapp",
                        "timestamp": (m.timestamp.isoformat() if m.timestamp else None),
                        "dt": m.timestamp,
                        "from_me": m.is_from_me,
                        "summary": (m.text or "")[:200],
                        "preview": None,
                    }
                )

        # MrCall conversations (phone calls)
        if resolved_phone:
            clean_phone = resolved_phone.replace("+", "").replace(" ", "")
            calls = (
                session.query(MrcallConversation)
                .filter(
                    MrcallConversation.owner_id == owner_id,
                    MrcallConversation.call_started_at >= cutoff,
                    MrcallConversation.contact_phone.contains(clean_phone),
                )
                .order_by(MrcallConversation.call_started_at.desc())
                .limit(limit)
                .all()
            )
            for c in calls:
                duration_s = (c.call_duration_ms or 0) / 1000
                timeline.append(
                    {
                        "channel": "call",
                        "timestamp": (c.call_started_at.isoformat() if c.call_started_at else None),
                        "dt": c.call_started_at,
                        "from_me": True,
                        "summary": c.subject or f"Phone call ({int(duration_s)}s)",
                        "preview": None,
                    }
                )

        # Also search calls by contact name
        if contact_name and not resolved_phone:
            calls = (
                session.query(MrcallConversation)
                .filter(
                    MrcallConversation.owner_id == owner_id,
                    MrcallConversation.call_started_at >= cutoff,
                    MrcallConversation.contact_name.ilike(f"%{contact_name}%"),
                )
                .order_by(MrcallConversation.call_started_at.desc())
                .limit(limit)
                .all()
            )
            for c in calls:
                duration_s = (c.call_duration_ms or 0) / 1000
                timeline.append(
                    {
                        "channel": "call",
                        "timestamp": (c.call_started_at.isoformat() if c.call_started_at else None),
                        "dt": c.call_started_at,
                        "from_me": True,
                        "summary": c.subject or f"Phone call ({int(duration_s)}s)",
                        "preview": None,
                    }
                )

    # -- Step 3: Sort and format --------------------------

    # Sort by timestamp descending (most recent first)
    timeline.sort(
        key=lambda x: x.get("dt") or datetime.min,
        reverse=True,
    )

    # Trim to limit
    timeline = timeline[:limit]

    # Remove internal dt field
    for item in timeline:
        item.pop("dt", None)

    # Count per channel
    channel_counts = {}
    for item in timeline:
        ch = item["channel"]
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    return {
        "contact": resolved_name or contact_email or contact_phone,
        "email": resolved_email,
        "phone": resolved_phone,
        "channels": channel_counts,
        "total": len(timeline),
        "days_back": days_back,
        "timeline": timeline,
    }
