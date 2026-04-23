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
from ..assistant.turn_context import get_turn_id

logger = logging.getLogger(__name__)


DEFAULT_FALLBACK_DIR = "/tmp/zylch/attachments"


def _resolve_target_dir(target_dir: Optional[str]) -> str:
    """Resolve the directory where attachments should be written.

    Rules:
      1. If `target_dir` is provided (explicit param from the LLM), expand ``~`` and return it.
      2. Else if DOWNLOADS_DIR env var is set (user preference from Settings), use it.
      3. Otherwise default to ``~/Downloads``.
      4. If the home directory does not exist, fall back to ``/tmp/zylch/attachments``.

    The directory is created if missing.
    """
    if target_dir:
        resolved = os.path.expanduser(target_dir)
    else:
        configured = os.environ.get("DOWNLOADS_DIR", "").strip()
        if configured:
            resolved = os.path.expanduser(configured)
        else:
            home = os.path.expanduser("~")
            if not os.path.isdir(home):
                resolved = DEFAULT_FALLBACK_DIR
            else:
                resolved = os.path.join(home, "Downloads")

    try:
        os.makedirs(resolved, exist_ok=True)
    except OSError:
        # Last-ditch fallback if we can't create the requested dir.
        resolved = DEFAULT_FALLBACK_DIR
        os.makedirs(resolved, exist_ok=True)

    return resolved


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
                "Download attachments from an email. Resolves the email by ID from"
                " the local SQLite store, fetches the attachments over IMAP, and saves"
                " them to disk. Works for any email provider (Gmail, Outlook, Exchange,"
                " generic IMAP). Files are saved to `target_dir` (default: the user's"
                " ~/Downloads folder)."
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

    async def execute(
        self, email_id: str = "", target_dir: Optional[str] = None, **kwargs
    ) -> ToolResult:
        turn_id = get_turn_id()
        logger.debug(
            f"[download_attachment turn={turn_id}] execute("
            f"email_id={email_id!r}, target_dir={target_dir!r})"
        )
        if not email_id:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No email_id provided",
            )
            logger.debug(f"[download_attachment turn={turn_id}] -> status={result.status}")
            return result

        owner_id = self._get_owner_id()
        if not owner_id:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No owner_id available",
            )
            logger.debug(f"[download_attachment turn={turn_id}] -> status={result.status}")
            return result

        # Fail-loud IMAP credential check BEFORE touching anything else.
        # Without this, an empty IMAPClient would fail in an opaque way and the LLM
        # would hallucinate explanations ("different account / server Outlook").
        email_addr = os.environ.get("EMAIL_ADDRESS", "").strip()
        email_pass = os.environ.get("EMAIL_PASSWORD", "").strip()
        if not email_addr or not email_pass:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    "IMAP credentials missing: set EMAIL_ADDRESS and EMAIL_PASSWORD"
                    " in the profile .env file. The attachment cannot be downloaded"
                    " until IMAP is configured."
                ),
            )
            logger.debug(
                f"[download_attachment turn={turn_id}] -> status={result.status}"
                " reason=imap_credentials_missing"
            )
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
            logger.debug(f"[download_attachment turn={turn_id}] -> status={result.status}")
            return result

        message_id = email.get("message_id") or email.get("message_id_header") or email_id

        save_dir = _resolve_target_dir(target_dir)
        logger.debug(
            f"[download_attachment turn={turn_id}] resolved save_dir={save_dir}"
            f" message_id={message_id!r}"
        )

        try:
            from zylch.email.imap_client import IMAPClient

            client = IMAPClient(
                email_addr=email_addr,
                password=email_pass,
                imap_host=os.environ.get("IMAP_HOST") or None,
            )
            attachments = client.fetch_attachments(message_id, save_dir=save_dir)
            if not attachments:
                result = ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"attachments": [], "save_dir": save_dir},
                    message="No attachments found in this email",
                )
                logger.debug(f"[download_attachment turn={turn_id}] -> status={result.status}")
                return result

            # Normalize: return list of {local_path, filename, size}
            normalized = []
            lines = [f"Downloaded {len(attachments)} attachment(s) to {save_dir}:"]
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
                    "save_dir": save_dir,
                    "attachments": normalized,
                }
            else:
                data = {"save_dir": save_dir, "attachments": normalized}

            result = ToolResult(
                status=ToolStatus.SUCCESS,
                data=data,
                message="\n".join(lines),
            )
            logger.debug(
                f"[download_attachment turn={turn_id}] -> status={result.status}"
                f" count={len(normalized)} save_dir={save_dir}"
            )
            return result
        except Exception as e:
            logger.error(f"[download_attachment turn={turn_id}] failed: {e}")
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Download failed: {e}",
            )
            logger.debug(f"[download_attachment turn={turn_id}] -> status={result.status}")
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
                            "Email ID (UUID from search_emails, or the provider's"
                            " message_id). NOT the subject line."
                        ),
                    },
                    "target_dir": {
                        "type": "string",
                        "description": (
                            "Optional directory to save the attachments in. Accepts"
                            " ~-expanded paths. Defaults to the user's ~/Downloads"
                            " folder."
                        ),
                    },
                },
                "required": ["email_id"],
            },
        }
