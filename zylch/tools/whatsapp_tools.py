"""WhatsApp LLM tools — search, conversation, send.

Analogous to gmail_tools.py for email. Queries local SQLite
(whatsapp_messages, whatsapp_contacts) and uses neonize for sending.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class SearchWhatsAppTool(Tool):
    """Search WhatsApp messages in local SQLite."""

    def __init__(self, session_state=None):
        super().__init__(
            name="search_whatsapp",
            description=(
                "Search WhatsApp messages by contact name, phone number, or text content. "
                "Use this when user asks about WhatsApp conversations, messages, or contacts."
            ),
        )
        self.session_state = session_state

    async def execute(
        self,
        query: str = "",
        contact_name: str = "",
        phone_number: str = "",
        days_back: int = 30,
        limit: int = 20,
        **kwargs,
    ) -> ToolResult:
        """Search WhatsApp messages.

        Args:
            query: Text to search in message content
            contact_name: Filter by sender/contact name
            phone_number: Filter by phone number (JID)
            days_back: Number of days to look back
            limit: Max results to return
        """
        try:
            from zylch.storage.database import get_session
            from zylch.storage.models import WhatsAppMessage

            owner_id = None
            if self.session_state:
                owner_id = self.session_state.get_owner_id()

            with get_session() as session:
                q = session.query(WhatsAppMessage)

                if owner_id:
                    q = q.filter(WhatsAppMessage.owner_id == owner_id)

                # Time filter
                cutoff = datetime.utcnow() - timedelta(days=days_back)
                q = q.filter(WhatsAppMessage.timestamp >= cutoff)

                # Text search
                if query:
                    q = q.filter(WhatsAppMessage.text.ilike(f"%{query}%"))

                # Contact name filter
                if contact_name:
                    q = q.filter(WhatsAppMessage.sender_name.ilike(f"%{contact_name}%"))

                # Phone/JID filter
                if phone_number:
                    clean_phone = phone_number.replace("+", "").replace(" ", "")
                    q = q.filter(
                        WhatsAppMessage.chat_jid.contains(clean_phone)
                        | WhatsAppMessage.sender_jid.contains(clean_phone)
                    )

                # Skip group messages by default
                q = q.filter(WhatsAppMessage.is_group == False)  # noqa: E712

                messages = q.order_by(WhatsAppMessage.timestamp.desc()).limit(limit).all()

                results = []
                for msg in messages:
                    results.append(
                        {
                            "sender": msg.sender_name or msg.sender_jid,
                            "text": msg.text,
                            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                            "from_me": msg.is_from_me,
                            "chat": msg.chat_jid,
                        }
                    )

            if not results:
                search_desc = query or contact_name or phone_number or "all"
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"messages": [], "total": 0},
                    message=f"No WhatsApp messages found for '{search_desc}' in last {days_back} days",
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"messages": results, "total": len(results)},
                message=f"Found {len(results)} WhatsApp messages",
            )

        except Exception as e:
            logger.error(f"[search_whatsapp] error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error searching WhatsApp: {str(e)}",
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search in message content",
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "Filter by sender/contact display name",
                    },
                    "phone_number": {
                        "type": "string",
                        "description": "Filter by phone number (with or without +)",
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Days to look back (default: 30)",
                        "default": 30,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 20)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        }


class GetWhatsAppConversationTool(Tool):
    """Get full WhatsApp conversation with a specific contact."""

    def __init__(self, session_state=None):
        super().__init__(
            name="get_whatsapp_conversation",
            description=(
                "Get the WhatsApp conversation history with a specific contact. "
                "Shows messages in chronological order. Use when user asks to see "
                "the full conversation with someone on WhatsApp."
            ),
        )
        self.session_state = session_state

    async def execute(
        self,
        contact_name: str = "",
        phone_number: str = "",
        days_back: int = 30,
        limit: int = 50,
        **kwargs,
    ) -> ToolResult:
        """Get conversation with a contact.

        Args:
            contact_name: Contact name to look up
            phone_number: Phone number (JID) of the contact
            days_back: How many days back to fetch
            limit: Max messages to return
        """
        try:
            from zylch.storage.database import get_session
            from zylch.storage.models import WhatsAppMessage, WhatsAppContact

            owner_id = None
            if self.session_state:
                owner_id = self.session_state.get_owner_id()

            # First, resolve contact to JID if searching by name
            chat_jid = None
            resolved_name = contact_name

            with get_session() as session:
                if contact_name and not phone_number:
                    contact = (
                        session.query(WhatsAppContact)
                        .filter(
                            WhatsAppContact.owner_id == owner_id,
                            WhatsAppContact.name.ilike(f"%{contact_name}%")
                            | WhatsAppContact.push_name.ilike(f"%{contact_name}%"),
                        )
                        .first()
                    )
                    if contact:
                        chat_jid = contact.jid
                        resolved_name = contact.name or contact.push_name or contact_name

                if phone_number and not chat_jid:
                    clean = phone_number.replace("+", "").replace(" ", "")
                    chat_jid = f"{clean}@s.whatsapp.net"

                if not chat_jid:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error=f"Contact '{contact_name or phone_number}' not found in WhatsApp",
                    )

                # Fetch messages for this conversation
                cutoff = datetime.utcnow() - timedelta(days=days_back)
                messages = (
                    session.query(WhatsAppMessage)
                    .filter(
                        WhatsAppMessage.owner_id == owner_id,
                        WhatsAppMessage.chat_jid == chat_jid,
                        WhatsAppMessage.timestamp >= cutoff,
                    )
                    .order_by(WhatsAppMessage.timestamp.asc())
                    .limit(limit)
                    .all()
                )

                if not messages:
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data={"conversation": [], "contact": resolved_name},
                        message=f"No messages with {resolved_name} in last {days_back} days",
                    )

                conversation = []
                for msg in messages:
                    sender = "You" if msg.is_from_me else (msg.sender_name or resolved_name)
                    conversation.append(
                        {
                            "sender": sender,
                            "text": msg.text,
                            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                        }
                    )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "conversation": conversation,
                    "contact": resolved_name,
                    "total": len(conversation),
                },
                message=f"Conversation with {resolved_name}: {len(conversation)} messages",
            )

        except Exception as e:
            logger.error(f"[get_whatsapp_conversation] error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error getting conversation: {str(e)}",
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Contact name to search for",
                    },
                    "phone_number": {
                        "type": "string",
                        "description": "Phone number with country code (e.g. +393281234567)",
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Days of history to fetch (default: 30)",
                        "default": 30,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max messages (default: 50)",
                        "default": 50,
                    },
                },
                "required": [],
            },
        }


class SendWhatsAppMessageTool(Tool):
    """Send a WhatsApp message to a contact."""

    def __init__(self, session_state=None):
        super().__init__(
            name="send_whatsapp_message",
            description=(
                "ALWAYS use this tool when user asks to send a WhatsApp message. "
                "Actually sends the message via neonize. "
                "NEVER claim you sent a WhatsApp without calling this tool."
            ),
        )
        self.session_state = session_state

    async def execute(
        self,
        contact_name: str = "",
        phone_number: str = "",
        message: str = "",
        **kwargs,
    ) -> ToolResult:
        """Send a WhatsApp message.

        Args:
            contact_name: Contact name to look up
            phone_number: Phone number with country code
            message: Text message to send
        """
        if not message:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Message text is required",
            )

        try:
            from zylch.whatsapp.client import WhatsAppClient
            from zylch.storage.database import get_session
            from zylch.storage.models import WhatsAppContact
            import time

            owner_id = None
            if self.session_state:
                owner_id = self.session_state.get_owner_id()

            # Resolve contact to JID
            jid = None
            resolved_name = contact_name

            if phone_number:
                clean = phone_number.replace("+", "").replace(" ", "")
                jid = f"{clean}@s.whatsapp.net"
                resolved_name = phone_number

            if contact_name and not jid:
                with get_session() as session:
                    contact = (
                        session.query(WhatsAppContact)
                        .filter(
                            WhatsAppContact.owner_id == owner_id,
                            WhatsAppContact.name.ilike(f"%{contact_name}%")
                            | WhatsAppContact.push_name.ilike(f"%{contact_name}%"),
                        )
                        .first()
                    )
                    if contact:
                        jid = contact.jid
                        resolved_name = contact.name or contact.push_name or contact_name
                        phone_number = contact.phone_number

            if not jid:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(
                        f"Contact '{contact_name or phone_number}' not found. "
                        "Provide a phone number with country code (e.g. +393281234567)"
                    ),
                )

            # Connect and send
            wa_client = WhatsAppClient()
            if not wa_client.has_session():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="WhatsApp not connected. Run /connect whatsapp first.",
                )

            wa_client.connect(blocking=False)
            for _ in range(10):
                if wa_client.is_connected():
                    break
                time.sleep(0.5)

            if not wa_client.is_connected():
                wa_client.disconnect()
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Could not connect to WhatsApp. Try /connect whatsapp.",
                )

            # Build JID object and send
            from neonize.utils import build_jid

            recipient = build_jid(jid.split("@")[0])
            wa_client.send_message(recipient, message)
            wa_client.disconnect()

            logger.info(f"[send_whatsapp] sent to {resolved_name} ({jid})")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "recipient": resolved_name,
                    "phone": phone_number or jid,
                    "message_preview": message[:100],
                },
                message=f"WhatsApp message sent to {resolved_name}",
            )

        except ImportError as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"WhatsApp dependency missing: {e}. Run: pip install neonize",
            )
        except Exception as e:
            logger.error(f"[send_whatsapp] error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Failed to send WhatsApp message: {str(e)}",
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Contact name to send to",
                    },
                    "phone_number": {
                        "type": "string",
                        "description": "Phone number with country code (e.g. +393281234567)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Text message to send",
                    },
                },
                "required": ["message"],
            },
        }


class WhatsAppGapAnalysisTool(Tool):
    """Detect unanswered WhatsApp messages and silent contacts."""

    def __init__(self, session_state=None):
        super().__init__(
            name="whatsapp_gap_analysis",
            description=(
                "Analyze WhatsApp conversations for relationship gaps: "
                "unanswered messages, silent contacts, missing follow-ups. "
                "Use when user asks about WhatsApp tasks, gaps, or who they need to reply to."
            ),
        )
        self.session_state = session_state

    async def execute(
        self,
        days_back: int = 7,
        silent_threshold_days: int = 30,
        **kwargs,
    ) -> ToolResult:
        """Analyze WhatsApp for relationship gaps.

        Args:
            days_back: Days to check for unanswered messages
            silent_threshold_days: Days of silence to flag a contact
        """
        try:
            from zylch.storage.database import get_session
            from zylch.storage.models import WhatsAppMessage

            owner_id = None
            if self.session_state:
                owner_id = self.session_state.get_owner_id()

            gaps = []

            with get_session() as session:
                cutoff = datetime.utcnow() - timedelta(days=days_back)

                # Get all 1:1 chats with recent activity
                from sqlalchemy import func as sa_func, and_

                chat_stats = (
                    session.query(
                        WhatsAppMessage.chat_jid,
                        sa_func.max(WhatsAppMessage.timestamp).label("last_msg"),
                        sa_func.max(WhatsAppMessage.sender_name).label("contact_name"),
                    )
                    .filter(
                        WhatsAppMessage.owner_id == owner_id,
                        WhatsAppMessage.is_group == False,  # noqa: E712
                        WhatsAppMessage.timestamp >= cutoff,
                    )
                    .group_by(WhatsAppMessage.chat_jid)
                    .all()
                )

                for chat_jid, last_msg_time, contact_name in chat_stats:
                    # Get the most recent message in this chat
                    last_msg = (
                        session.query(WhatsAppMessage)
                        .filter(
                            WhatsAppMessage.owner_id == owner_id,
                            WhatsAppMessage.chat_jid == chat_jid,
                        )
                        .order_by(WhatsAppMessage.timestamp.desc())
                        .first()
                    )

                    if not last_msg:
                        continue

                    # Gap type 1: Unanswered — last message is FROM contact (not from me)
                    if not last_msg.is_from_me and last_msg.text:
                        days_waiting = (datetime.utcnow() - last_msg.timestamp).days
                        if days_waiting >= 1:
                            gaps.append(
                                {
                                    "type": "whatsapp_unanswered",
                                    "contact": last_msg.sender_name or chat_jid,
                                    "last_message": (last_msg.text or "")[:200],
                                    "days_waiting": days_waiting,
                                    "urgency": "high" if days_waiting >= 3 else "medium",
                                }
                            )

                # Gap type 2: Silent contacts (had conversations but went quiet)
                silent_cutoff = datetime.utcnow() - timedelta(days=silent_threshold_days)
                active_cutoff = datetime.utcnow() - timedelta(days=90)

                silent_chats = (
                    session.query(
                        WhatsAppMessage.chat_jid,
                        sa_func.max(WhatsAppMessage.timestamp).label("last_msg"),
                        sa_func.max(WhatsAppMessage.sender_name).label("contact_name"),
                        sa_func.count(WhatsAppMessage.id).label("msg_count"),
                    )
                    .filter(
                        WhatsAppMessage.owner_id == owner_id,
                        WhatsAppMessage.is_group == False,  # noqa: E712
                        WhatsAppMessage.timestamp >= active_cutoff,
                    )
                    .group_by(WhatsAppMessage.chat_jid)
                    .having(
                        and_(
                            sa_func.max(WhatsAppMessage.timestamp) < silent_cutoff,
                            sa_func.count(WhatsAppMessage.id) >= 5,
                        )
                    )
                    .all()
                )

                for chat_jid, last_msg_time, contact_name, msg_count in silent_chats:
                    days_silent = (datetime.utcnow() - last_msg_time).days
                    gaps.append(
                        {
                            "type": "whatsapp_silent",
                            "contact": contact_name or chat_jid,
                            "days_silent": days_silent,
                            "previous_messages": msg_count,
                            "urgency": "low",
                            "suggestion": "Send a check-in message",
                        }
                    )

            # Sort by urgency
            urgency_order = {"high": 0, "medium": 1, "low": 2}
            gaps.sort(key=lambda g: urgency_order.get(g.get("urgency", "low"), 3))

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"gaps": gaps, "total": len(gaps)},
                message=(
                    f"Found {len(gaps)} WhatsApp gaps: "
                    f"{sum(1 for g in gaps if g['type'] == 'whatsapp_unanswered')} unanswered, "
                    f"{sum(1 for g in gaps if g['type'] == 'whatsapp_silent')} silent contacts"
                ),
            )

        except Exception as e:
            logger.error(f"[whatsapp_gap_analysis] error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error analyzing WhatsApp gaps: {str(e)}",
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "Days to check for unanswered messages (default: 7)",
                        "default": 7,
                    },
                    "silent_threshold_days": {
                        "type": "integer",
                        "description": "Days of silence to flag a contact (default: 30)",
                        "default": 30,
                    },
                },
                "required": [],
            },
        }
