"""Approval-gated MrCall calls authenticated with the current Firebase session."""

import logging

import httpx

from zylch.auth import NoActiveSession
from zylch.tools.base import Tool, ToolResult, ToolStatus
from .outbound import normalize_destination
from .starchat_firebase import make_starchat_client_from_firebase_session

logger = logging.getLogger(__name__)


class InitiateCallTool(Tool):
    def __init__(self, session_state=None):
        super().__init__(
            name="initiate_call",
            description=(
                "Request a phone call using an explicitly selected MrCall calling assistant. "
                "Uses its saved configuration, not a custom per-call script. "
                "Requires approval. Submission does not prove connection or working audio."
            ),
        )
        self.session_state = session_state

    async def execute(self, phone_number: str, business_id: str = None) -> ToolResult:
        client = None
        try:
            number = normalize_destination(phone_number)
            caller = business_id
            if not caller:
                raise ValueError("Select the calling assistant via business_id before calling")
            client = make_starchat_client_from_firebase_session()
            result = await client.initiate_outbound_call(number, caller)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=result,
                message=(
                    "Call request submitted to MrCall. This does not confirm an answer, "
                    "working audio, or a completed diagnostic."
                ),
            )
        except NoActiveSession:
            return ToolResult(ToolStatus.ERROR, None, error="Sign in to MrCall before calling")
        except ValueError as exc:
            return ToolResult(ToolStatus.ERROR, None, error=str(exc))
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            logger.warning("[initiate_call] HTTP failure status=%s", code)
            return ToolResult(
                ToolStatus.ERROR,
                {"http_status": code},
                error=(
                    "MrCall session expired; sign in again."
                    if code == 401
                    else f"MrCall returned HTTP {code}. No completed call confirmed; do not retry automatically."
                ),
            )
        except httpx.TransportError:
            logger.warning("[initiate_call] transport failed; submission outcome unknown")
            return ToolResult(
                ToolStatus.ERROR,
                {"status": "unknown"},
                error="Call submission outcome unknown. Do not retry: the call may have started.",
            )
        finally:
            if client is not None:
                try:
                    await client.client.aclose()
                except Exception:
                    logger.warning("[initiate_call] client cleanup failed")

    def get_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Destination including country code, e.g. +390289040671",
                    },
                    "business_id": {
                        "type": "string",
                        "description": (
                            "Calling assistant ID explicitly chosen by the user. "
                            "Not the destination customer's assistant. Required in every request."
                        ),
                    },
                },
                "required": ["phone_number", "business_id"],
                "additionalProperties": False,
            },
        }
