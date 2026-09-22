"""Call tools for initiating phone calls via StarChat/MrCall.

Wraps StarChatClient to expose call functionality as Claude tools.
"""

import logging
from typing import Dict, Any, List

import httpx

from .base import Tool, ToolResult, ToolStatus

# Compatibility import: callers historically import both tools from this module.
from .mrcall.outbound_tool import InitiateCallTool  # noqa: F401

logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://dashboard.mrcall.ai"


class ListMrCallAssistantsTool(Tool):
    """List the signed-in user's MrCall AI phone assistants (businesses).

    Read-only. Self-authenticates from the active Firebase session at
    execute() time (mirrors `rpc/mrcall_actions.mrcall_list_my_businesses`)
    rather than depending on a legacy OAuth StarChat client — the desktop
    is Firebase-only. Builds its own StarChat client per call and closes it.
    Degrades gracefully: never raises out of execute().
    """

    def __init__(self, session_state=None):
        """Initialize the tool.

        Args:
            session_state: Optional SessionState. Only used to read the
                owner_id so we can mark the currently-linked assistant.
                The auth itself comes from the Firebase session, not here.
        """
        super().__init__(
            name="list_mrcall_assistants",
            description=(
                "List all MrCall AI phone assistants (businesses) configured "
                "under the signed-in account — their id, name, service number, "
                "template and subscription status. Use when the user asks which "
                "MrCall assistants they have, or to find a business_id for "
                "initiate_call."
            ),
        )
        self.session_state = session_state

    async def execute(self, limit: int = 100) -> ToolResult:
        """List the user's MrCall assistants.

        Args:
            limit: Max assistants to return (default 100).

        Returns:
            ToolResult with a readable list plus structured data. Always a
            ToolResult — sign-in / auth / network failures map to a friendly
            message, never an exception.
        """
        # Lazy imports keep the module import cheap and avoid a hard
        # dependency on auth/storage at tool-construction time.
        from zylch.auth import NoActiveSession
        from zylch.tools.mrcall.starchat_firebase import (
            make_starchat_client_from_firebase_session,
        )

        try:
            size = int(limit)
        except (TypeError, ValueError):
            size = 100
        if size <= 0:
            size = 100

        try:
            client = make_starchat_client_from_firebase_session()
        except NoActiveSession as e:
            logger.info(f"list_mrcall_assistants: no active session ({e})")
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"signed_in": False},
                message=(
                    "You're not signed in to MrCall yet. Sign in to the "
                    "desktop app (top-right) to list your assistants."
                ),
            )

        try:
            # Use the {"from","size"} convention exercised by the mature
            # `/mrcall list` slash command — NOT the RPC's {"offset","limit"}.
            endpoint = f"/mrcall/v1/{client.realm}/crm/business/search"
            logger.info(f"list_mrcall_assistants: POST {endpoint} size={size}")
            response = await client.client.post(endpoint, json={"from": 0, "size": size})

            if response.status_code == 401:
                logger.info("list_mrcall_assistants: StarChat returned 401")
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"signed_in": False},
                    message=(
                        "Your MrCall session has expired. Please sign in again "
                        "in the desktop app to list your assistants."
                    ),
                )

            response.raise_for_status()
            businesses = response.json()
            if not isinstance(businesses, list):
                businesses = []
            logger.info(f"list_mrcall_assistants: count={len(businesses)}")

            # Determine the currently-linked assistant (if owner_id known).
            current_business_id = None
            try:
                from zylch.storage import Storage

                owner_id = self.session_state.get_owner_id() if self.session_state else None
                if owner_id:
                    current_business_id = Storage().get_mrcall_link(owner_id)
                    logger.debug(
                        f"list_mrcall_assistants: linked business_id={current_business_id}"
                    )
            except Exception as e:
                logger.warning(f"list_mrcall_assistants: get_mrcall_link failed: {e}")

            if not businesses:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"signed_in": True, "count": 0, "assistants": []},
                    message=(f"No MrCall assistants found. Create one at {DASHBOARD_URL}"),
                )

            structured: List[Dict[str, Any]] = []
            blocks: List[str] = [f"You have {len(businesses)} MrCall assistant(s):", ""]
            for i, biz in enumerate(businesses, 1):
                biz_id = biz.get("businessId") or biz.get("id")
                nickname = biz.get("nickname") or "Unnamed"
                company = biz.get("companyName") or ""
                service_number = biz.get("serviceNumber") or ""
                email_address = biz.get("emailAddress") or ""
                user_phone = biz.get("userPhoneNumber") or ""
                template = biz.get("template") or ""
                subscription_status = biz.get("subscriptionStatus") or ""
                is_linked = bool(biz_id) and biz_id == current_business_id
                linked_marker = " ← LINKED" if is_linked else ""

                title = f"{i}. {nickname}"
                if company:
                    title += f" ({company})"
                blocks.append(title + linked_marker)
                blocks.append(f"   id: {biz_id}")
                if email_address:
                    blocks.append(f"   email: {email_address}")
                if user_phone:
                    blocks.append(f"   user phone: {user_phone}")
                if service_number:
                    blocks.append(f"   service number: {service_number}")
                if template:
                    blocks.append(f"   template: {template}")
                if subscription_status:
                    blocks.append(f"   subscription: {subscription_status}")
                blocks.append("")

                structured.append(
                    {
                        "business_id": biz_id,
                        "nickname": nickname,
                        "company_name": company,
                        "service_number": service_number,
                        "email_address": email_address,
                        "user_phone_number": user_phone,
                        "template": template,
                        "subscription_status": subscription_status,
                        "linked": is_linked,
                    }
                )

            blocks.append(f"Manage or create assistants at {DASHBOARD_URL}")
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "signed_in": True,
                    "count": len(structured),
                    "assistants": structured,
                    "linked_business_id": current_business_id,
                },
                message="\n".join(blocks),
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"list_mrcall_assistants: StarChat error "
                f"status={e.response.status_code} body={e.response.text}"
            )
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    "Couldn't reach MrCall to list your assistants right now. "
                    "Please try again in a moment."
                ),
            )
        except Exception as e:
            logger.error(f"list_mrcall_assistants: unexpected error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    "Couldn't list your MrCall assistants due to an unexpected "
                    "error. Please try again in a moment."
                ),
            )
        finally:
            try:
                await client.client.aclose()
            except Exception:
                pass

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of assistants to return (default 100)",
                        "default": 100,
                    },
                },
                "required": [],
            },
        }
