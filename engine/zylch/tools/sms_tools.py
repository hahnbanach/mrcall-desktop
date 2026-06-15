"""SMS tool for the assistant — send via the MrCall credits proxy.

Thin async wrapper over `zylch.tools.sms_send.send_sms_via_proxy` (the single
SMS code path, shared with the solve flow's `_send_sms`). Sends route through
mrcall-agent's `/api/desktop/sms/send` and bill the user's MrCall credits; the
sender is the server-side alphanumeric ID, so there is nothing to configure
per user. Honest failure messages: if the user isn't signed in / has no
credits / the service isn't up, the tool says so instead of failing silently.
"""

import asyncio
import logging
from typing import Any, Dict

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class SendSMSTool(Tool):
    """Send an SMS via MrCall (billed to MrCall credits)."""

    def __init__(self, session_state=None):
        super().__init__(
            name="send_sms",
            description=(
                "ALWAYS use this tool when the user asks to send an SMS or text "
                "message. Sends via MrCall (billed to MrCall credits); the user "
                "must be signed in to MrCall. NEVER claim you sent an SMS without "
                "calling this tool."
            ),
        )
        self.session_state = session_state

    async def execute(self, phone_number: str = "", message: str = "", **kwargs) -> ToolResult:
        """Send an SMS.

        Args:
            phone_number: Recipient in E.164 (e.g. +393281234567)
            message: Text to send
        """
        if not phone_number or not message:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    "Both phone_number (E.164, e.g. +393281234567) and message "
                    "are required."
                ),
            )

        from .sms_send import send_sms_via_proxy

        # The send is sync httpx; run it off the event loop so the assistant
        # stays responsive.
        loop = asyncio.get_running_loop()
        outcome = await loop.run_in_executor(None, send_sms_via_proxy, phone_number, message)

        if outcome.ok:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "recipient": phone_number,
                    "message_id": outcome.message_id,
                    "cost_credits": outcome.cost_credits,
                    "segments": outcome.segments,
                    "status": "sent",
                },
                message=outcome.message,
            )
        return ToolResult(status=ToolStatus.ERROR, data=None, error=outcome.message)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": (
                            "Recipient phone number in E.164 with country code "
                            "(e.g. +393281234567)"
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": "The text message to send",
                    },
                },
                "required": ["phone_number", "message"],
            },
        }
