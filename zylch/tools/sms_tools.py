"""SMS tools for sending messages via Vonage.

Wraps VonageClient to expose SMS functionality as Claude tools.
"""

import logging
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class SendSMSTool(Tool):
    """Send an SMS message to a phone number."""

    def __init__(self, session_state=None):
        super().__init__(
            name="send_sms",
            description="ALWAYS use this tool when user asks to send an SMS or text message. Actually sends the SMS via Vonage API. NEVER claim you sent an SMS without calling this tool."
        )
        self.session_state = session_state

    async def execute(
        self,
        phone_number: str,
        message: str,
        sender_name: Optional[str] = None
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
                    status=ToolStatus.ERROR,
                    data=None,
                    error="User not authenticated"
                )

            # Load Vonage credentials from Supabase for this user
            from zylch.api import token_storage
            vonage_keys = token_storage.get_vonage_keys(owner_id)

            if not vonage_keys or not vonage_keys.get('api_key'):
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Vonage not connected. Please use /connect vonage to set up SMS."
                )

            # Create Vonage client with user's credentials
            from .vonage import VonageClient
            vonage = VonageClient(
                api_key=vonage_keys['api_key'],
                api_secret=vonage_keys['api_secret'],
                from_number=vonage_keys.get('from_number', 'Zylch')
            )

            # Validate phone number format
            if not phone_number.startswith('+'):
                phone_number = '+' + phone_number.lstrip('0')

            result = await vonage.send_sms(
                recipient=phone_number,
                text=message,
                sender=sender_name
            )

            logger.info(f"Sent SMS to {phone_number}: {result['message_id']}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "message_id": result["message_id"],
                    "recipient": phone_number,
                    "status": "sent"
                },
                message=f"SMS sent successfully to {phone_number}"
            )

        except Exception as e:
            logger.error(f"Failed to send SMS to {phone_number}: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Recipient phone number with country code (e.g., +12025551234)"
                    },
                    "message": {
                        "type": "string",
                        "description": "The text message to send (max 160 characters for single SMS)"
                    },
                    "sender_name": {
                        "type": "string",
                        "description": "Optional sender name or number"
                    }
                },
                "required": ["phone_number", "message"]
            }
        }


class SendVerificationCodeTool(Tool):
    """Generate and send a verification code via SMS.

    This is useful for verifying phone ownership before making outbound calls.

    TODO: This tool needs migration to use Supabase `verification_codes` table
    instead of the removed legacy memory system.
    """

    def __init__(self, session_state, owner_id: str, zylch_assistant_id: str):
        super().__init__(
            name="send_verification_code",
            description="Send a 6-digit verification code to a phone number for phone ownership verification"
        )
        self.session_state = session_state
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _generate_code(self) -> str:
        """Generate a 6-digit verification code."""
        return ''.join(random.choices(string.digits, k=6))

    async def execute(
        self,
        phone_number: str,
        context: Optional[str] = None
    ) -> ToolResult:
        """Generate and send a verification code.

        Args:
            phone_number: Phone number to verify (with country code)
            context: Optional context for the verification (e.g., "callback request")

        Returns:
            ToolResult with verification details (code is NOT included for security)
        """
        if not self.owner_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="User not authenticated"
            )

        # Generate code
        code = self._generate_code()
        
        # Store in Supabase
        try:
            from zylch.storage import Storage
            storage = Storage.get_instance()
            storage.create_verification_code(
                owner_id=self.owner_id,
                phone_number=phone_number,
                code=code,
                context=context
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Failed to store verification code: {e}"
            )

        # Send via SMS
        # We reuse SendSMSTool logic or call it directly? 
        # Better to use the session's SendSMSTool if available, or duplicate logic.
        # Since this is a separate tool, we duplicate the Vonage logic or instantiate SendSMSTool.
        # Let's instantiate SendSMSTool.
        
        sms_tool = SendSMSTool(session_state=self.session_state)
        result = await sms_tool.execute(
            phone_number=phone_number,
            message=f"Your Zylch verification code is: {code}",
            sender_name="Zylch"
        )
        
        if result.status == ToolStatus.ERROR:
            return result
            
        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={"status": "sent", "recipient": phone_number},
            message=f"Verification code sent to {phone_number}"
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Phone number to verify (with country code, e.g., +12025551234)"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context for the verification (e.g., 'callback request')"
                    }
                },
                "required": ["phone_number"]
            }
        }


class VerifyCodeTool(Tool):
    """Verify a code that was sent via SMS.

    TODO: This tool needs migration to use Supabase `verification_codes` table
    instead of the removed legacy memory system.
    """

    def __init__(self, owner_id: str, zylch_assistant_id: str):
        super().__init__(
            name="verify_sms_code",
            description="Verify a code that was previously sent via SMS"
        )
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    async def execute(
        self,
        phone_number: str,
        code: str
    ) -> ToolResult:
        """Verify a code.

        Args:
            phone_number: Phone number the code was sent to
            code: The 6-digit code to verify

        Returns:
            ToolResult indicating if verification was successful
        """
        try:
            from zylch.storage import Storage
            storage = Storage.get_instance()
            is_valid = storage.verify_code(
                owner_id=self.owner_id,
                phone_number=phone_number,
                code=code
            )
            
            if is_valid:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"verified": True},
                    message=f"Phone number {phone_number} verified successfully!"
                )
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data={"verified": False},
                    error="Invalid or expired verification code."
                )
                
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Verification failed: {e}"
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Phone number the code was sent to (with country code)"
                    },
                    "code": {
                        "type": "string",
                        "description": "The 6-digit verification code"
                    }
                },
                "required": ["phone_number", "code"]
            }
        }
