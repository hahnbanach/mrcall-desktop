"""Download attachments from an email (ported from solve_tools._download_attachment).

Exposes attachment download as a canonical Tool subclass so ChatService can
solve attachment-heavy tasks (e.g. Jacobacci patent review) without going
through TaskExecutor.
"""

import logging
import os
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolStatus
from .session_state import SessionState

logger = logging.getLogger(__name__)


class DownloadAttachmentTool(Tool):
    """Download attachments from an email via IMAP."""

    def __init__(
        self,
        storage,
        session_state: Optional[SessionState] = None,
        owner_id: Optional[str] = None,
    ):
        super().__init__(
            name="download_attachment",
            description=(
                "Download attachments from an email."
                " Use the email ID from search_emails results."
                " Saves to /tmp/zylch/attachments/."
            ),
        )
        self.storage = storage
        self.session_state = session_state
        self._owner_id = owner_id

    def _get_owner_id(self) -> Optional[str]:
        if self.session_state is not None:
            oid = self.session_state.get_owner_id()
            if oid:
                return oid
        return self._owner_id

    async def execute(self, email_id: str = "", **kwargs) -> ToolResult:
        logger.debug(f"[download_attachment] execute(args={{'email_id': '{email_id}'}})")
        if not email_id:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No email_id provided",
            )
            logger.debug(f"[download_attachment] -> status={result.status}")
            return result

        owner_id = self._get_owner_id()
        if not owner_id:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No owner_id available",
            )
            logger.debug(f"[download_attachment] -> status={result.status}")
            return result

        # Try internal UUID first, then fall back to gmail_id
        email = self.storage.get_email_by_supabase_id(owner_id, email_id)
        if not email:
            email = self.storage.get_email_by_id(owner_id, email_id)
        if not email:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Email {email_id} not found",
            )
            logger.debug(f"[download_attachment] -> status={result.status}")
            return result

        message_id = email.get("message_id", email_id)

        try:
            from zylch.email.imap_client import IMAPClient

            client = IMAPClient(
                email_addr=os.environ.get("EMAIL_ADDRESS", ""),
                password=os.environ.get("EMAIL_PASSWORD", ""),
                imap_host=os.environ.get("IMAP_HOST") or None,
            )
            attachments = client.fetch_attachments(message_id)
            if not attachments:
                result = ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"attachments": []},
                    message="No attachments found in this email",
                )
                logger.debug(f"[download_attachment] -> status={result.status}")
                return result

            # Normalize: return list of {local_path, filename, size}
            normalized = []
            lines = [f"Downloaded {len(attachments)} attachment(s):"]
            for a in attachments:
                entry = {
                    "local_path": a.get("path", ""),
                    "filename": a.get("filename", ""),
                    "size": int(a.get("size", 0) or 0),
                    "content_type": a.get("content_type", ""),
                }
                normalized.append(entry)
                lines.append(
                    f"- {entry['filename']} ({entry['content_type']},"
                    f" {entry['size']} bytes) -> {entry['local_path']}"
                )

            data: Dict[str, Any]
            if len(normalized) == 1:
                single = normalized[0]
                data = {
                    "local_path": single["local_path"],
                    "filename": single["filename"],
                    "size": single["size"],
                    "attachments": normalized,
                }
            else:
                data = {"attachments": normalized}

            result = ToolResult(
                status=ToolStatus.SUCCESS,
                data=data,
                message="\n".join(lines),
            )
            logger.debug(
                f"[download_attachment] -> status={result.status}" f" count={len(normalized)}"
            )
            return result
        except Exception as e:
            logger.error(f"[download_attachment] failed: {e}")
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Download failed: {e}",
            )
            logger.debug(f"[download_attachment] -> status={result.status}")
            return result

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": (
                            "Email ID (UUID from search_emails," " NOT the subject line)"
                        ),
                    },
                },
                "required": ["email_id"],
            },
        }
