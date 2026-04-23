"""SMS tools for sending messages via Vonage.

Wraps VonageClient to expose SMS functionality as Claude tools.
"""

import logging
from typing import Dict, Any, Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class SendSMSTool(Tool):
    """Send an SMS message to a phone number."""

    def __init__(self, session_state=None):
        super().__init__(
            name="send_sms",
            description="ALWAYS use this tool when user asks to send an SMS or text message. Actually sends the SMS via Vonage API. NEVER claim you sent an SMS without calling this tool.",
        )
        self.session_state = session_state

    async def execute(
        self, phone_number: str, message: str, sender_name: Optional[str] = None
    ) -> ToolResult:
        """Send an SMS message.

        Args:
            phone_number: Recipient phone number (with country code, e.g., +1234567890)
            message: The text message to send
            sender_name: Optional sender name (defaults to configured number)

        Returns:
            ToolResult with message ID on success
        """
        try:
            # Get owner_id from session state
            owner_id = None
            if self.session_state:
                owner_id = self.session_state.get_owner_id()

            if not owner_id:
                return ToolResult(
                    status=ToolStatus.ERROR, data=None, error="User not authenticated"
                )

            # Load Vonage credentials from Supabase for this user
            from zylch.api import token_storage

            vonage_keys = token_storage.get_vonage_keys(owner_id)

            if not vonage_keys or not vonage_keys.get("api_key"):
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Vonage not connected. Please use /connect vonage to set up SMS.",
                )

            # Create Vonage client with user's credentials
            from .vonage import VonageClient

            vonage = VonageClient(
                api_key=vonage_keys["api_key"],
                api_secret=vonage_keys["api_secret"],
                from_number=vonage_keys.get("from_number", "Zylch"),
            )

            # Validate phone number format
            if not phone_number.startswith("+"):
                phone_number = "+" + phone_number.lstrip("0")

            result = await vonage.send_sms(recipient=phone_number, text=message, sender=sender_name)

            logger.info(f"Sent SMS to {phone_number}: {result['message_id']}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "message_id": result["message_id"],
                    "recipient": phone_number,
                    "status": "sent",
                },
                message=f"SMS sent successfully to {phone_number}",
            )

        except Exception as e:
            logger.error(f"Failed to send SMS to {phone_number}: {e}")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Recipient phone number with country code (e.g., +12025551234)",
                    },
                    "message": {
                        "type": "string",
                        "description": "The text message to send (max 160 characters for single SMS)",
                    },
                    "sender_name": {
                        "type": "string",
                        "description": "Optional sender name or number",
                    },
                },
                "required": ["phone_number", "message"],
            },
        }
