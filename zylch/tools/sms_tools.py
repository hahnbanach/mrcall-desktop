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

    def __init__(self, vonage_client):
        super().__init__(
            name="send_sms",
            description="Send an SMS text message to a phone number"
        )
        self.vonage = vonage_client

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
            # Validate phone number format
            if not phone_number.startswith('+'):
                phone_number = '+' + phone_number.lstrip('0')

            result = await self.vonage.send_sms(
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
    """

    def __init__(self, vonage_client, zylch_memory, owner_id: str, zylch_assistant_id: str):
        super().__init__(
            name="send_verification_code",
            description="Send a 6-digit verification code to a phone number for phone ownership verification"
        )
        self.vonage = vonage_client
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _get_namespace(self) -> str:
        """Get the verification codes namespace."""
        return f"{self.owner_id}:{self.zylch_assistant_id}:verification_codes"

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
        try:
            # Validate phone number format
            if not phone_number.startswith('+'):
                phone_number = '+' + phone_number.lstrip('0')

            # Generate code
            code = self._generate_code()
            expires_at = datetime.utcnow() + timedelta(minutes=10)

            # Store code in memory for later verification
            namespace = self._get_namespace()
            verification_data = {
                "phone": phone_number,
                "code": code,
                "expires_at": expires_at.isoformat(),
                "context": context or "phone verification",
                "attempts": 0,
                "max_attempts": 3
            }

            import json
            self.zylch_memory.store_memory(
                namespace=namespace,
                category="verification",
                context=f"Verification code for {phone_number}",
                pattern=json.dumps(verification_data),
                examples=[],
                metadata={"phone": phone_number}
            )

            # Send SMS with code
            message = f"Your Zylch verification code is: {code}\n\nThis code expires in 10 minutes."
            await self.vonage.send_sms(
                recipient=phone_number,
                text=message
            )

            logger.info(f"Sent verification code to {phone_number}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "phone": phone_number,
                    "expires_in_minutes": 10,
                    "context": context or "phone verification"
                },
                message=f"Verification code sent to {phone_number}. Code expires in 10 minutes."
            )

        except Exception as e:
            logger.error(f"Failed to send verification code: {e}")
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
    """Verify a code that was sent via SMS."""

    def __init__(self, zylch_memory, owner_id: str, zylch_assistant_id: str):
        super().__init__(
            name="verify_sms_code",
            description="Verify a code that was previously sent via SMS"
        )
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _get_namespace(self) -> str:
        """Get the verification codes namespace."""
        return f"{self.owner_id}:{self.zylch_assistant_id}:verification_codes"

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
        import json
        from datetime import datetime

        try:
            # Normalize phone number
            if not phone_number.startswith('+'):
                phone_number = '+' + phone_number.lstrip('0')

            # Retrieve verification data from memory
            namespace = self._get_namespace()
            memories = self.zylch_memory.retrieve_memories(
                query=phone_number,
                namespace=namespace,
                category="verification",
                limit=5
            )

            if not memories:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data={"verified": False},
                    error="No verification code found for this phone number"
                )

            # Find the most recent code for this phone
            for memory in memories:
                try:
                    data = json.loads(memory.get("pattern", "{}"))
                    if data.get("phone") == phone_number:
                        # Check expiration
                        expires_at = datetime.fromisoformat(data["expires_at"])
                        if datetime.utcnow() > expires_at:
                            return ToolResult(
                                status=ToolStatus.ERROR,
                                data={"verified": False},
                                error="Verification code has expired. Please request a new one."
                            )

                        # Check attempts
                        attempts = data.get("attempts", 0)
                        if attempts >= data.get("max_attempts", 3):
                            return ToolResult(
                                status=ToolStatus.ERROR,
                                data={"verified": False},
                                error="Too many failed attempts. Please request a new code."
                            )

                        # Verify code
                        if data.get("code") == code:
                            logger.info(f"Successfully verified phone: {phone_number}")
                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data={
                                    "verified": True,
                                    "phone": phone_number,
                                    "context": data.get("context")
                                },
                                message=f"Phone number {phone_number} verified successfully!"
                            )
                        else:
                            # Increment attempts (would need update mechanism)
                            logger.warning(f"Invalid code attempt for {phone_number}")
                            return ToolResult(
                                status=ToolStatus.ERROR,
                                data={"verified": False, "attempts_remaining": data.get("max_attempts", 3) - attempts - 1},
                                error="Invalid verification code. Please try again."
                            )

                except (json.JSONDecodeError, KeyError):
                    continue

            return ToolResult(
                status=ToolStatus.ERROR,
                data={"verified": False},
                error="Verification code not found or expired"
            )

        except Exception as e:
            logger.error(f"Failed to verify code: {e}")
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
