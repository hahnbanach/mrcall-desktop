"""Gmail API integration for email operations."""

import base64
import logging
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from zylch.config import settings
from zylch.api import token_storage

logger = logging.getLogger(__name__)

# Google API scopes (Gmail + Calendar combined)
SCOPES = [
    # Gmail scopes
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    # Calendar scopes
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]


class GmailClient:
    """Client for Gmail API operations.

    Handles OAuth authentication and email operations.
    Supports both filesystem tokens (local dev) and Supabase tokens (production).
    """

    def __init__(
        self,
        credentials_path: str = "credentials/gmail_oauth.json",
        token_dir: str = "credentials/gmail_tokens/",
        account: Optional[str] = None,
        owner_id: Optional[str] = None,
    ):
        """Initialize Gmail client.

        Args:
            credentials_path: Path to OAuth credentials JSON
            token_dir: Directory to store tokens (filesystem fallback)
            account: Email account (for multi-account support)
            owner_id: Firebase UID (enables Supabase token storage)
        """
        self.credentials_path = Path(credentials_path)
        self.token_dir = Path(token_dir)
        self.token_dir.mkdir(parents=True, exist_ok=True)
        self.account = account
        self.owner_id = owner_id
        self.service = None

        # Use Supabase token storage if owner_id is provided
        self._use_token_storage = bool(owner_id)

        logger.info(f"Initialized Gmail client for account: {account or 'default'}, owner_id: {owner_id or 'none'}")

    def _get_token_path(self) -> Path:
        """Get token file path for this account."""
        if self.account:
            # Use account-specific token
            safe_account = self.account.replace("@", "_at_").replace(".", "_")
            return self.token_dir / f"token_{safe_account}.pickle"
        else:
            return self.token_dir / "token.pickle"

    def authenticate(self) -> None:
        """Authenticate with Gmail API using OAuth 2.0.

        Uses Supabase token storage when owner_id is set, otherwise filesystem.
        """
        creds = None

        # Load existing token from appropriate backend
        if self._use_token_storage:
            # Load from Supabase via token_storage
            creds = token_storage.get_google_credentials(self.owner_id)
            if creds:
                logger.info(f"Loaded credentials from Supabase for owner {self.owner_id}")
        else:
            # Load from filesystem
            token_path = self._get_token_path()
            if token_path.exists():
                with open(token_path, "rb") as token:
                    creds = pickle.load(token)

        # If no valid credentials, request new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired credentials")
                creds.refresh(Request())
                # Save refreshed credentials
                self._save_credentials(creds)
            else:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {self.credentials_path}. "
                        "Please download OAuth credentials from Google Cloud Console."
                    )

                logger.info("Starting OAuth flow for new credentials")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

                # Save credentials
                self._save_credentials(creds)

        # Build Gmail service
        # cache_discovery=False avoids warning about file_cache requiring oauth2client<4.0.0
        self.service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
        logger.info("Gmail API authenticated successfully")

    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials to appropriate backend.

        Args:
            creds: Google OAuth credentials
        """
        if self._use_token_storage:
            # Save to Supabase via token_storage
            token_storage.save_google_credentials(
                owner_id=self.owner_id,
                credentials=creds,
                email=self.account or ""
            )
            logger.info(f"Saved credentials to Supabase for owner {self.owner_id}")
        else:
            # Save to filesystem
            token_path = self._get_token_path()
            with open(token_path, "wb") as token:
                pickle.dump(creds, token)
            logger.info(f"Saved credentials to {token_path}")

    def search_messages(
        self,
        query: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search Gmail messages.

        Args:
            query: Gmail search query (e.g., "from:example@gmail.com")
            max_results: Maximum results to return

        Returns:
            List of message objects
        """
        if not self.service:
            self.authenticate()

        logger.debug(f"Searching Gmail: {query}")

        try:
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            messages = results.get('messages', [])

            # Fetch full message details
            full_messages = []
            for msg in messages:
                full_msg = self.service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()
                full_messages.append(self._parse_message(full_msg))

            logger.info(f"Found {len(full_messages)} messages")
            return full_messages

        except Exception as e:
            logger.error(f"Failed to search Gmail: {e}")
            raise

    def _extract_body_from_parts(self, parts: List[Dict]) -> tuple[str, str]:
        """Recursively extract plain text and HTML body from email parts.

        Args:
            parts: List of MIME parts

        Returns:
            Tuple of (plain_text, html_text)
        """
        plain_text = ""
        html_text = ""

        for part in parts:
            mime_type = part.get('mimeType', '')

            # Handle nested parts (multipart/alternative, etc.)
            if 'parts' in part:
                nested_plain, nested_html = self._extract_body_from_parts(part['parts'])
                if not plain_text:
                    plain_text = nested_plain
                if not html_text:
                    html_text = nested_html

            # Extract text/plain
            elif mime_type == 'text/plain':
                body_data = part.get('body', {}).get('data', '')
                if body_data:
                    try:
                        plain_text = base64.urlsafe_b64decode(body_data).decode('utf-8')
                    except Exception as e:
                        logger.debug(f"Failed to decode plain text: {e}")

            # Extract text/html
            elif mime_type == 'text/html':
                body_data = part.get('body', {}).get('data', '')
                if body_data:
                    try:
                        html_text = base64.urlsafe_b64decode(body_data).decode('utf-8')
                    except Exception as e:
                        logger.debug(f"Failed to decode HTML: {e}")

        return plain_text, html_text

    def _parse_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Gmail message into simplified format.

        Args:
            msg: Raw Gmail message object

        Returns:
            Parsed message with key fields
        """
        headers = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}

        # Extract body (prefer text/plain, fallback to text/html)
        body = ""

        if 'parts' in msg['payload']:
            # Recursively extract from parts
            plain_text, html_text = self._extract_body_from_parts(msg['payload']['parts'])
            body = plain_text or html_text

        elif 'body' in msg['payload'] and msg['payload']['body'].get('data'):
            # Simple message with body directly in payload
            body_data = msg['payload']['body']['data']
            try:
                body = base64.urlsafe_b64decode(body_data).decode('utf-8')
            except Exception as e:
                logger.debug(f"Failed to decode body: {e}")

        return {
            'id': msg['id'],
            'thread_id': msg['threadId'],
            'from': headers.get('From', ''),
            'to': headers.get('To', ''),
            'cc': headers.get('Cc', ''),
            'subject': headers.get('Subject', ''),
            'date': headers.get('Date', ''),
            'snippet': msg.get('snippet', ''),
            'body': body,
            'labels': msg.get('labelIds', []),
            # Threading headers needed for replies
            'message_id': headers.get('Message-ID', ''),
            'in_reply_to': headers.get('In-Reply-To', ''),
            'references': headers.get('References', ''),
        }

    def get_message(self, message_id: str) -> Dict[str, Any]:
        """Get single message by ID.

        Args:
            message_id: Gmail message ID

        Returns:
            Parsed message
        """
        if not self.service:
            self.authenticate()

        msg = self.service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()

        return self._parse_message(msg)

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send email via Gmail API.

        Args:
            to: Recipient email
            subject: Email subject
            body: Email body (plain text or HTML)
            from_email: Sender email (optional)

        Returns:
            Sent message info
        """
        if not self.service:
            self.authenticate()

        # Create message
        from email.mime.text import MIMEText

        # Append Zylch signature to body
        body_with_signature = f"{body}\n\n{settings.made_by_zylch_email}"

        message = MIMEText(body_with_signature)
        message['to'] = to
        message['subject'] = subject
        if from_email:
            message['from'] = from_email

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        try:
            sent_message = self.service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()

            logger.info(f"Sent email to {to}: {subject}")
            return sent_message

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            raise

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Gmail draft.

        Args:
            to: Recipient email
            subject: Email subject
            body: Email body
            in_reply_to: Message-ID of the message being replied to (for threading)
            references: References header for conversation threading
            thread_id: Gmail thread ID to place this draft in (for replies)

        Returns:
            Draft info
        """
        if not self.service:
            self.authenticate()

        from email.mime.text import MIMEText

        # Append Zylch signature to body
        body_with_signature = f"{body}\n\n{settings.made_by_zylch_email}"

        message = MIMEText(body_with_signature)
        message['to'] = to
        message['subject'] = subject

        # Add threading headers if this is a reply
        if in_reply_to:
            message['In-Reply-To'] = in_reply_to
        if references:
            message['References'] = references

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        try:
            # Build request body
            create_body = {'message': {'raw': raw_message}}

            # CRITICAL: Include threadId to place draft in existing conversation
            if thread_id:
                create_body['message']['threadId'] = thread_id

            draft = self.service.users().drafts().create(
                userId='me',
                body=create_body
            ).execute()

            logger.info(f"Created draft to {to}: {subject}" + (f" in thread {thread_id}" if thread_id else ""))
            return draft

        except Exception as e:
            logger.error(f"Failed to create draft: {e}")
            raise

    def update_draft(
        self,
        draft_id: str,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing Gmail draft.

        IMPORTANT: To preserve threadId, we delete the old draft and create a new one.
        Gmail API's update() doesn't preserve threadId, so this is the only way.

        Args:
            draft_id: Gmail draft ID
            to: New recipient (optional, keeps existing if None)
            subject: New subject (optional, keeps existing if None)
            body: New body (optional, keeps existing if None)

        Returns:
            New draft info (with different ID but same threadId)
        """
        if not self.service:
            self.authenticate()

        from email.mime.text import MIMEText

        try:
            # Get existing draft
            existing = self.service.users().drafts().get(
                userId='me',
                id=draft_id,
                format='full'
            ).execute()

            # Parse existing message to get current values
            existing_msg = existing['message']
            existing_payload = existing_msg.get('payload', {})
            # Use lowercase keys for case-insensitive lookup
            existing_headers = {h['name'].lower(): h['value'] for h in existing_payload.get('headers', [])}

            # Extract threadId (CRITICAL for preserving thread association)
            existing_thread_id = existing_msg.get('threadId')

            # Use provided values or keep existing
            final_to = to if to is not None else existing_headers.get('to', '')
            final_subject = subject if subject is not None else existing_headers.get('subject', '')

            # For body, decode existing if not provided
            if body is None:
                # Try to extract existing body (already has signature if created via create_draft)
                if 'parts' in existing_payload:
                    plain_text, html_text = self._extract_body_from_parts(existing_payload['parts'])
                    final_body = plain_text or html_text
                elif 'data' in existing_payload.get('body', {}):
                    body_data = existing_payload['body']['data']
                    final_body = base64.urlsafe_b64decode(body_data).decode('utf-8')
                else:
                    final_body = ""
            else:
                # New body provided - append signature
                final_body = f"{body}\n\n{settings.made_by_zylch_email}"

            # Create new message with preserved headers
            message = MIMEText(final_body)
            message['to'] = final_to
            message['subject'] = final_subject

            # CRITICAL: Preserve threading headers
            if existing_headers.get('in-reply-to'):
                message['In-Reply-To'] = existing_headers['in-reply-to']
            if existing_headers.get('references'):
                message['References'] = existing_headers['references']

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

            # Delete old draft
            self.service.users().drafts().delete(
                userId='me',
                id=draft_id
            ).execute()

            logger.info(f"Deleted old draft {draft_id}")

            # Create new draft with threadId preserved
            create_body = {'message': {'raw': raw_message}}
            if existing_thread_id:
                create_body['message']['threadId'] = existing_thread_id

            new_draft = self.service.users().drafts().create(
                userId='me',
                body=create_body
            ).execute()

            logger.info(f"Created new draft {new_draft['id']} in thread {existing_thread_id}")
            return new_draft

        except Exception as e:
            logger.error(f"Failed to update draft {draft_id}: {e}")
            raise

    def get_draft(self, draft_id: str) -> Dict[str, Any]:
        """Get a specific draft by ID with full details.

        Args:
            draft_id: Gmail draft ID

        Returns:
            Draft with parsed message (to, subject, body)
        """
        if not self.service:
            self.authenticate()

        try:
            draft = self.service.users().drafts().get(
                userId='me',
                id=draft_id,
                format='full'
            ).execute()

            # Parse message details
            msg = draft['message']
            payload = msg.get('payload', {})
            # Create case-insensitive headers dict (lowercase keys)
            headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}

            # Extract body
            body = ""
            if 'parts' in payload:
                plain_text, html_text = self._extract_body_from_parts(payload['parts'])
                body = plain_text or html_text
            elif 'data' in payload.get('body', {}):
                body_data = payload['body']['data']
                body = base64.urlsafe_b64decode(body_data).decode('utf-8')

            return {
                'id': draft_id,
                'to': headers.get('to', ''),
                'subject': headers.get('subject', ''),
                'body': body,
                # Preserve thread headers for replies
                'in_reply_to': headers.get('in-reply-to', ''),
                'references': headers.get('references', ''),
                'message_id': headers.get('message-id', '')
            }

        except Exception as e:
            logger.error(f"Failed to get draft {draft_id}: {e}")
            raise

    def list_drafts(self) -> List[Dict[str, Any]]:
        """List Gmail drafts.

        Returns:
            List of drafts
        """
        if not self.service:
            self.authenticate()

        try:
            results = self.service.users().drafts().list(userId='me').execute()
            drafts = results.get('drafts', [])

            logger.info(f"Found {len(drafts)} drafts")
            return drafts

        except Exception as e:
            logger.error(f"Failed to list drafts: {e}")
            raise

    def send_draft(self, draft_id: str) -> Dict[str, Any]:
        """Send a Gmail draft.

        Args:
            draft_id: Gmail draft ID to send

        Returns:
            Sent message info
        """
        if not self.service:
            self.authenticate()

        try:
            # Send the draft
            sent_message = self.service.users().drafts().send(
                userId='me',
                body={'id': draft_id}
            ).execute()

            logger.info(f"Sent draft {draft_id}")
            return sent_message

        except Exception as e:
            logger.error(f"Failed to send draft {draft_id}: {e}")
            raise
