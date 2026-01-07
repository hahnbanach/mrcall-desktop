"""Sharing tools for the Zylch AI agent.

Tools for sharing and retrieving contact intelligence between Zylch users.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, ToolStatus
from ..sharing import SharingAuthorizationManager, IntelShareManager

logger = logging.getLogger(__name__)


class ShareContactIntelTool(Tool):
    """Tool for sharing contact intelligence with another Zylch user.

    Used when user says things like:
    - "Condividi con Luigi che Marco Ferrari ha firmato il contratto"
    - "Share with Mario that the deal is closed"
    """

    def __init__(
        self,
        intel_share_manager: IntelShareManager,
        auth_manager: SharingAuthorizationManager,
        owner_id: str,
        user_email: str,
        user_display_name: Optional[str] = None
    ):
        super().__init__(
            name="share_contact_intel",
            description="Share contact intelligence with another authorized Zylch user"
        )
        self.intel_share = intel_share_manager
        self.auth_manager = auth_manager
        self.owner_id = owner_id
        self.user_email = user_email
        self.user_display_name = user_display_name

    def get_schema(self) -> Dict[str, Any]:
        """Get tool schema for Anthropic API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "recipient_email": {
                        "type": "string",
                        "description": "Email of the Zylch user to share with"
                    },
                    "recipient_name": {
                        "type": "string",
                        "description": "Name of the recipient (will be resolved to email)"
                    },
                    "intel": {
                        "type": "string",
                        "description": "The intelligence to share (e.g., 'Marco Ferrari ha firmato il contratto')"
                    },
                    "contact_email": {
                        "type": "string",
                        "description": "Email of the contact the intel is about"
                    },
                    "contact_phone": {
                        "type": "string",
                        "description": "Phone number of the contact"
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "Name of the contact the intel is about"
                    }
                },
                "required": ["intel"]
            }
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the share intel tool."""
        intel = kwargs.get("intel")
        recipient_email = kwargs.get("recipient_email")
        recipient_name = kwargs.get("recipient_name")
        contact_email = kwargs.get("contact_email")
        contact_phone = kwargs.get("contact_phone")
        contact_name = kwargs.get("contact_name")

        if not intel:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"error": "Intel content is required"}
            )

        # Validate user email is configured
        if not self.user_email:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"error": "User email not configured. Add USER_EMAIL to .env file."}
            )

        # Resolve recipient
        if not recipient_email and recipient_name:
            # Try to find recipient by name in authorized recipients
            authorized = self.auth_manager.list_authorized_recipients(self.user_email)
            for r in authorized:
                if r.get("display_name") and recipient_name.lower() in r["display_name"].lower():
                    recipient_email = r["recipient_email"]
                    break

            # Also check pending registrations
            if not recipient_email:
                pending = self.auth_manager.list_pending_registrations(self.user_email)
                for r in pending:
                    if r.get("display_name") and recipient_name.lower() in r["display_name"].lower():
                        recipient_email = r["recipient_email"]
                        break

        if not recipient_email:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={
                    "error": f"Recipient not found. Use /share <email> to register a recipient first.",
                    "suggestion": "Specifica l'email del destinatario o usa /share per registrarlo."
                }
            )

        # Get recipient's owner_id
        recipient_user = self.auth_manager.get_user_by_email(recipient_email)
        if not recipient_user:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={
                    "error": f"{recipient_email} non è un utente Zylch registrato.",
                    "suggestion": "L'utente deve avere Zylch configurato per ricevere condivisioni."
                }
            )

        recipient_owner_id = recipient_user["owner_id"]

        # Build identifiers
        identifiers = {}
        if contact_email:
            identifiers["email"] = contact_email
        if contact_phone:
            identifiers["phone"] = contact_phone
        if contact_name:
            identifiers["name"] = contact_name

        if not identifiers:
            # Try to extract name from intel
            identifiers["name"] = intel.split()[0] if intel else "Unknown"

        # Share the intel
        success, message = self.intel_share.share_intel(
            sender_owner_id=self.owner_id,
            sender_email=self.user_email,
            recipient_owner_id=recipient_owner_id,
            recipient_email=recipient_email,
            context=intel,
            identifiers=identifiers,
            sender_display_name=self.user_display_name
        )

        if success:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "shared": True,
                    "recipient": recipient_email,
                    "intel": intel,
                    "identifiers": identifiers,
                    "message": message
                }
            )
        else:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={
                    "error": message,
                    "recipient": recipient_email
                }
            )


class GetSharedIntelTool(Tool):
    """Tool for retrieving shared intelligence about a contact.

    Automatically called when searching for contact information to include
    intel shared by other Zylch users.
    """

    def __init__(
        self,
        intel_share_manager: IntelShareManager,
        owner_id: str,
        user_email: str
    ):
        super().__init__(
            name="get_shared_intel",
            description="Retrieve intelligence about a contact shared by other Zylch users"
        )
        self.intel_share = intel_share_manager
        self.owner_id = owner_id
        self.user_email = user_email

    def get_schema(self) -> Dict[str, Any]:
        """Get tool schema for Anthropic API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_email": {
                        "type": "string",
                        "description": "Email of the contact to look up"
                    },
                    "contact_phone": {
                        "type": "string",
                        "description": "Phone number of the contact"
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "Name of the contact (for context, not matching)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of shared intel items to return",
                        "default": 10
                    }
                }
            }
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the get shared intel tool."""
        contact_email = kwargs.get("contact_email")
        contact_phone = kwargs.get("contact_phone")
        contact_name = kwargs.get("contact_name")
        limit = kwargs.get("limit", 10)

        # Need at least email or phone for matching
        if not contact_email and not contact_phone:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "shared_intel": [],
                    "message": "No email or phone provided for matching"
                }
            )

        # Build identifiers
        identifiers = {}
        if contact_email:
            identifiers["email"] = contact_email
        if contact_phone:
            identifiers["phone"] = contact_phone
        if contact_name:
            identifiers["name"] = contact_name

        # Get shared intel
        shared_intel = self.intel_share.get_shared_intel(
            recipient_owner_id=self.owner_id,
            identifiers=identifiers,
            limit=limit
        )

        if not shared_intel:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "shared_intel": [],
                    "message": "No shared intel found for this contact"
                }
            )

        # Convert to serializable format
        intel_list = [intel.to_dict() for intel in shared_intel]

        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={
                "shared_intel": intel_list,
                "count": len(intel_list),
                "contact_email": contact_email,
                "contact_phone": contact_phone
            }
        )


class AcceptShareRequestTool(Tool):
    """Tool for accepting sharing requests from other users.

    Called when user responds positively to a pending share request.
    """

    def __init__(
        self,
        intel_share_manager: IntelShareManager,
        auth_manager: SharingAuthorizationManager,
        owner_id: str,
        user_email: str
    ):
        super().__init__(
            name="accept_share_request",
            description="Accept a pending sharing request from another Zylch user"
        )
        self.intel_share = intel_share_manager
        self.auth_manager = auth_manager
        self.owner_id = owner_id
        self.user_email = user_email

    def get_schema(self) -> Dict[str, Any]:
        """Get tool schema for Anthropic API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "sender_email": {
                        "type": "string",
                        "description": "Email of the sender whose request to accept"
                    },
                    "sender_name": {
                        "type": "string",
                        "description": "Name of the sender (will be resolved to email)"
                    }
                }
            }
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the accept share request tool."""
        sender_email = kwargs.get("sender_email")
        sender_name = kwargs.get("sender_name")

        if not self.user_email:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"error": "User email not configured"}
            )

        # If no sender specified, try to get pending requests
        pending = self.auth_manager.get_pending_requests(self.user_email)

        if not sender_email and not sender_name:
            # Accept the first/only pending request if there's just one
            if len(pending) == 1:
                sender_email = pending[0]["sender_email"]
            elif len(pending) > 1:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data={
                        "error": "Multiple pending requests. Please specify which one to accept.",
                        "pending_requests": [
                            {
                                "sender_email": p["sender_email"],
                                "sender_name": p.get("sender_display_name"),
                                "intel_preview": p["intel_context"]
                            }
                            for p in pending
                        ]
                    }
                )
            else:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"message": "No pending share requests to accept"}
                )

        # Resolve sender by name if needed
        if not sender_email and sender_name:
            for p in pending:
                if p.get("sender_display_name") and sender_name.lower() in p["sender_display_name"].lower():
                    sender_email = p["sender_email"]
                    break
                if sender_name.lower() in p["sender_email"].lower():
                    sender_email = p["sender_email"]
                    break

        if not sender_email:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"error": f"No pending request found from {sender_name}"}
            )

        # Accept the authorization
        success, message = self.auth_manager.accept_authorization(
            recipient_email=self.user_email,
            sender_email=sender_email
        )

        if not success:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"error": message}
            )

        # Process pending shares (move from queue to shared namespace)
        processed = self.intel_share.process_accepted_authorization(
            recipient_owner_id=self.owner_id,
            recipient_email=self.user_email,
            sender_email=sender_email
        )

        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={
                "accepted": True,
                "sender_email": sender_email,
                "processed_shares": processed,
                "message": f"Accettato. {sender_email} può ora condividere informazioni con te. {processed} info già condivise sono ora visibili."
            }
        )


class RejectShareRequestTool(Tool):
    """Tool for rejecting sharing requests from other users."""

    def __init__(
        self,
        auth_manager: SharingAuthorizationManager,
        user_email: str
    ):
        super().__init__(
            name="reject_share_request",
            description="Reject a pending sharing request from another Zylch user"
        )
        self.auth_manager = auth_manager
        self.user_email = user_email

    def get_schema(self) -> Dict[str, Any]:
        """Get tool schema for Anthropic API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "sender_email": {
                        "type": "string",
                        "description": "Email of the sender whose request to reject"
                    }
                }
            }
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the reject share request tool."""
        sender_email = kwargs.get("sender_email")

        if not self.user_email:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"error": "User email not configured"}
            )

        if not sender_email:
            # Get pending and reject first one if only one
            pending = self.auth_manager.get_pending_requests(self.user_email)
            if len(pending) == 1:
                sender_email = pending[0]["sender_email"]
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data={"error": "Please specify which sender's request to reject"}
                )

        success, message = self.auth_manager.reject_authorization(
            recipient_email=self.user_email,
            sender_email=sender_email
        )

        if success:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "rejected": True,
                    "sender_email": sender_email,
                    "message": message
                }
            )
        else:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"error": message}
            )
