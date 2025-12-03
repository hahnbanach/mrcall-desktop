"""Microsoft Outlook API integration using Microsoft Graph.

Provides email operations for Outlook/Microsoft 365 accounts.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Microsoft Graph API base URL
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class OutlookClient:
    """Client for Microsoft Outlook via Graph API.

    Handles authentication and email operations for Outlook/Microsoft 365.
    """

    def __init__(
        self,
        graph_token: Optional[str] = None,
        account: Optional[str] = None,
    ):
        """Initialize Outlook client.

        Args:
            graph_token: Microsoft Graph API access token
            account: Email account identifier
        """
        self.graph_token = graph_token
        self.account = account
        self.session = requests.Session()

        logger.info(f"Initialized Outlook client for account: {account or 'default'}")

    def authenticate(self) -> bool:
        """Verify Graph API token is valid.

        Returns:
            True if token is valid, False otherwise
        """
        if not self.graph_token:
            logger.error("No Graph API token provided")
            return False

        try:
            # Test token by fetching user profile
            response = self._make_request("GET", "/me")
            if response.status_code == 200:
                user_data = response.json()
                logger.info(f"Outlook API authenticated successfully for {user_data.get('userPrincipalName')}")
                return True
            else:
                logger.error(f"Token validation failed: {response.status_code}")
                return False

        except Exception as e:
            logger.exception(f"Authentication error: {e}")
            return False

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> requests.Response:
        """Make authenticated request to Graph API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/me/messages")
            params: Query parameters
            json_data: JSON body data

        Returns:
            Response object
        """
        url = f"{GRAPH_API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.graph_token}",
            "Content-Type": "application/json",
        }

        response = self.session.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
        )

        return response

    def search_messages(
        self,
        query: str = "",
        max_results: int = 50,
        folder: str = "inbox",
    ) -> List[Dict[str, Any]]:
        """Search emails using Graph API.

        Args:
            query: Search query (OData $filter or $search)
            max_results: Maximum number of messages to return
            folder: Folder to search (inbox, sent, drafts, etc.)

        Returns:
            List of normalized message dicts
        """
        try:
            params = {
                "$top": max_results,
                "$orderby": "receivedDateTime desc",
            }

            # Add search query if provided
            if query:
                # Use $search for full-text search
                params["$search"] = f'"{query}"'

            endpoint = f"/me/mailFolders/{folder}/messages"
            response = self._make_request("GET", endpoint, params=params)

            if response.status_code != 200:
                logger.error(f"Search failed: {response.status_code} - {response.text}")
                return []

            data = response.json()
            messages = data.get("value", [])

            # Normalize messages to match Gmail format
            normalized = [self._parse_message(msg) for msg in messages]

            logger.info(f"Found {len(normalized)} messages")
            return normalized

        except Exception as e:
            logger.exception(f"Search error: {e}")
            return []

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get a single message by ID.

        Args:
            message_id: Graph API message ID

        Returns:
            Normalized message dict or None
        """
        try:
            endpoint = f"/me/messages/{message_id}"
            response = self._make_request("GET", endpoint)

            if response.status_code != 200:
                logger.error(f"Get message failed: {response.status_code}")
                return None

            message = response.json()
            return self._parse_message(message)

        except Exception as e:
            logger.exception(f"Get message error: {e}")
            return None

    def _parse_message(self, msg: Dict) -> Dict[str, Any]:
        """Parse Graph API message to normalized format.

        Matches the format returned by GmailClient for compatibility.

        Args:
            msg: Raw Graph API message object

        Returns:
            Normalized message dict
        """
        # Extract email addresses from recipient objects
        def extract_email(recipient_obj):
            if isinstance(recipient_obj, dict):
                email_address = recipient_obj.get("emailAddress", {})
                return email_address.get("address", "")
            return ""

        from_addr = extract_email(msg.get("from"))
        to_addrs = [extract_email(r) for r in msg.get("toRecipients", [])]
        cc_addrs = [extract_email(r) for r in msg.get("ccRecipients", [])]

        # Extract body (prefer plain text, fallback to HTML)
        body_obj = msg.get("body", {})
        body_type = body_obj.get("contentType", "text")
        body_content = body_obj.get("content", "")

        # If HTML, try to extract plain text (basic)
        if body_type.lower() == "html":
            # TODO: Add proper HTML to text conversion
            body = body_content
        else:
            body = body_content

        # Parse date
        received_dt = msg.get("receivedDateTime")
        date_str = received_dt if received_dt else datetime.now(timezone.utc).isoformat()

        return {
            "id": msg.get("id", ""),
            "thread_id": msg.get("conversationId", ""),  # Graph API conversation ID
            "from": from_addr,
            "to": to_addrs,
            "cc": cc_addrs,
            "subject": msg.get("subject", "(No Subject)"),
            "date": date_str,
            "body": body,
            "message_id": msg.get("internetMessageId", ""),  # Email Message-ID header
            "in_reply_to": "",  # TODO: Extract from internetMessageHeaders
            "references": "",   # TODO: Extract from internetMessageHeaders
        }

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
    ) -> Optional[Dict]:
        """Send an email message.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            from_email: Sender email (ignored, uses authenticated user)

        Returns:
            Sent message dict or None on failure
        """
        try:
            message = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "Text",
                        "content": body,
                    },
                    "toRecipients": [
                        {
                            "emailAddress": {
                                "address": to
                            }
                        }
                    ],
                }
            }

            response = self._make_request("POST", "/me/sendMail", json_data=message)

            if response.status_code == 202:  # Accepted
                logger.info(f"Email sent to {to}")
                return {"status": "sent", "to": to, "subject": subject}
            else:
                logger.error(f"Send failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.exception(f"Send error: {e}")
            return None

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Create a draft email.

        Args:
            to: Recipient email
            subject: Email subject
            body: Email body (plain text)
            in_reply_to: Message-ID of email being replied to
            references: Message-IDs for threading
            thread_id: Conversation ID for threading

        Returns:
            Draft message dict or None
        """
        try:
            draft_data = {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to
                        }
                    }
                ],
            }

            # TODO: Handle threading with conversationId

            response = self._make_request("POST", "/me/messages", json_data=draft_data)

            if response.status_code == 201:  # Created
                draft = response.json()
                logger.info(f"Draft created: {draft.get('id')}")
                return self._parse_message(draft)
            else:
                logger.error(f"Create draft failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.exception(f"Create draft error: {e}")
            return None

    def list_drafts(self) -> List[Dict]:
        """List all draft messages.

        Returns:
            List of normalized draft message dicts
        """
        try:
            endpoint = "/me/mailFolders/Drafts/messages"
            response = self._make_request("GET", endpoint)

            if response.status_code != 200:
                logger.error(f"List drafts failed: {response.status_code}")
                return []

            data = response.json()
            messages = data.get("value", [])

            return [self._parse_message(msg) for msg in messages]

        except Exception as e:
            logger.exception(f"List drafts error: {e}")
            return []

    def send_draft(self, draft_id: str) -> bool:
        """Send an existing draft.

        Args:
            draft_id: Graph API message ID of the draft

        Returns:
            True if sent successfully
        """
        try:
            endpoint = f"/me/messages/{draft_id}/send"
            response = self._make_request("POST", endpoint)

            if response.status_code == 202:  # Accepted
                logger.info(f"Draft sent: {draft_id}")
                return True
            else:
                logger.error(f"Send draft failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.exception(f"Send draft error: {e}")
            return False

    def update_draft(
        self,
        draft_id: str,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
    ) -> Optional[Dict]:
        """Update an existing draft.

        Args:
            draft_id: Graph API message ID of the draft
            to: New recipient (optional)
            subject: New subject (optional)
            body: New body (optional)

        Returns:
            Updated draft dict or None
        """
        try:
            update_data = {}

            if subject is not None:
                update_data["subject"] = subject

            if body is not None:
                update_data["body"] = {
                    "contentType": "Text",
                    "content": body,
                }

            if to is not None:
                update_data["toRecipients"] = [
                    {
                        "emailAddress": {
                            "address": to
                        }
                    }
                ]

            endpoint = f"/me/messages/{draft_id}"
            response = self._make_request("PATCH", endpoint, json_data=update_data)

            if response.status_code == 200:
                draft = response.json()
                logger.info(f"Draft updated: {draft_id}")
                return self._parse_message(draft)
            else:
                logger.error(f"Update draft failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.exception(f"Update draft error: {e}")
            return None
