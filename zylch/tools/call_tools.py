"""Call tools for initiating phone calls via StarChat/MrCall.

Wraps StarChatClient to expose call functionality as Claude tools.
"""

import logging
from typing import Dict, Any, Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class InitiateCallTool(Tool):
    """Initiate an outbound phone call via MrCall AI.

    This tool triggers an AI-powered outbound call to the specified phone number.
    The MrCall assistant will handle the conversation according to its configuration.
    """

    def __init__(self, starchat_client, session_state):
        """Initialize the call tool.

        Args:
            starchat_client: StarChatClient instance
            session_state: SessionState for current business_id
        """
        super().__init__(
            name="initiate_call",
            description="Initiate an outbound phone call to a contact using the MrCall AI assistant"
        )
        self.starchat = starchat_client
        self.session_state = session_state

    async def execute(
        self,
        phone_number: str,
        purpose: Optional[str] = None,
        contact_name: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> ToolResult:
        """Initiate an outbound call.

        Args:
            phone_number: Phone number to call (with country code, e.g., +12025551234)
            purpose: Optional purpose/context for the call (passed to assistant)
            contact_name: Optional contact name for personalization
            business_id: Optional specific business/assistant ID (uses session default if not provided)

        Returns:
            ToolResult with call status
        """
        try:
            # Get business_id from parameter or session state
            effective_business_id = business_id or self.session_state.get_business_id()

            if not effective_business_id:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="No MrCall assistant selected. Use /mrcall <business_id> to select one, or provide business_id parameter."
                )

            # Normalize phone number
            if not phone_number.startswith('+'):
                phone_number = '+' + phone_number.lstrip('0')

            # Build variables for the call
            variables = {}
            if purpose:
                variables["CALL_PURPOSE"] = purpose
            if contact_name:
                variables["CONTACT_NAME"] = contact_name

            # Initiate the call
            result = await self.starchat.initiate_outbound_call(
                phone_number=phone_number,
                business_id=effective_business_id,
                variables=variables if variables else None,
            )

            logger.info(f"Outbound call initiated to {phone_number}: {result}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "phone_number": phone_number,
                    "business_id": effective_business_id,
                    "call_id": result.get("call_id"),
                    "status": result.get("status", "initiated"),
                },
                message=f"Call initiated to {phone_number}. The MrCall AI assistant will handle the conversation."
            )

        except Exception as e:
            logger.error(f"Failed to initiate call to {phone_number}: {e}")
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
                        "description": "Phone number to call (with country code, e.g., +12025551234)"
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Purpose or context for the call (e.g., 'demo follow-up', 'schedule meeting')"
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "Name of the person being called (for personalization)"
                    },
                    "business_id": {
                        "type": "string",
                        "description": "Specific MrCall assistant/business ID to use (optional, uses session default)"
                    }
                },
                "required": ["phone_number"]
            }
        }
