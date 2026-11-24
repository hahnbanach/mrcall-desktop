"""Gmail and draft email tools.

Refactored for IMAP/SMTP (no Gmail/Outlook OAuth API).
GmailSearchTool uses IMAPClient.search().
Draft tools operate on the mailbox through the engine's mailbox service.
"""

from zylch.observability_producers import observed, observe, failure
import asyncio
import html
import logging
import re
import os
import smtplib
import socket
from typing import List, Optional

from ..services.approval_gate import draft_approval_card, draft_updates_from_card
from ..services import operator_reply_origin
from ..utils.safe_paths import PathRefused
from ..utils.msgid import canonical_draft_thread_id, clean_references
from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


#: Transport failures that carry a server verdict, or that happen before any
#: message bytes are offered. Nothing was delivered.
#:
#: The filesystem entries are not decoration. `IMAPClient.send` reads the
#: attachments while BUILDING the message, before a socket exists, and raises
#: `FileNotFoundError` for an attachment that has moved since the draft was
#: written. They are `OSError` subclasses like the socket failures below, so
#: without naming them here a missing file would be reported as "delivery
#: unknown" and park the draft in `sending` — for a mail that was never
#: offered to anyone.
_DELIVERY_REFUSED = (
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPDataError,
    smtplib.SMTPHeloError,
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPConnectError,
    smtplib.SMTPNotSupportedError,
    ConnectionRefusedError,
    socket.gaierror,
    # Building the message, not sending it.
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
    PermissionError,
)

#: Transport failures that answer nothing at all. The server may have taken
#: the message and died before saying so.
_DELIVERY_UNKNOWN = (
    smtplib.SMTPServerDisconnected,
    TimeoutError,  # socket.timeout is an alias of this
    ConnectionResetError,
    BrokenPipeError,
    OSError,  # every remaining socket / TLS failure
)


def delivery_is_uncertain(error: BaseException) -> bool:
    """Could the message have been accepted despite this exception?

    Not cosmetic: it decides both where the draft parks and what the operator
    is told. A server that refuses a recipient or rejects the DATA content
    answers with a code and nothing left the mailbox — say so. A socket that
    dies mid-DATA answers nothing, the message may already be in the
    recipient's inbox, and "nothing was sent" would be a confident lie.

    Ordered on purpose: the refusal classes are checked first because two of
    them (`ConnectionRefusedError`, `socket.gaierror`) are `OSError`
    subclasses that happen strictly before any message bytes are sent.
    """
    if isinstance(error, _DELIVERY_REFUSED):
        return False
    return isinstance(error, _DELIVERY_UNKNOWN)


def _normalize_attachment_paths(paths: Optional[List[str]]) -> List[str]:
    """Expand ~ and resolve to absolute paths. Does NOT verify existence.

    On a hosted engine each path must lie inside the document search set
    (raises PathRefused otherwise); see zylch.tools.paths.
    """
    from .paths import confine_attachment_paths

    if not paths:
        return []
    out: List[str] = []
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            continue
        out.append(os.path.abspath(os.path.expanduser(p)))
    return confine_attachment_paths(out)


class GmailSearchTool(Tool):
    """Email search tool for contact enrichment.

    Uses IMAPClient instead of Gmail API.
    """

    def __init__(
        self,
        imap_client,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
    ):
        super().__init__(
            name="search_provider_emails",
            description=(
                "Search email provider for emails from or to"
                " a contact to understand relationship"
            ),
        )
        self.imap = imap_client
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _is_email(self, value: str) -> bool:
        """Check if value looks like an email address."""
        import re

        return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", value.strip()))

    def _extract_email_from_header(self, header: str) -> tuple:
        """Extract email and name from header."""
        import re

        match = re.search(r"([^<]*)<([^>]+)>", header)
        if match:
            name = match.group(1).strip().strip('"')
            email = match.group(2).strip()
            return email, name
        if self._is_email(header):
            return header.strip(), None
        return None, header.strip()

    def _find_emails_by_name(self, name: str, max_search: int = 50) -> list:
        """Search emails for contacts matching name."""
        messages = self.imap.search_messages(name, max_search)

        contacts = {}
        name_lower = name.lower()

        for msg in messages:
            from_email, from_name = self._extract_email_from_header(msg.get("from", ""))
            if from_email and from_name and name_lower in from_name.lower():
                contacts[from_email.lower()] = from_name

            to_field = msg.get("to", "")
            for part in to_field.split(","):
                to_email, to_name = self._extract_email_from_header(part.strip())
                if to_email and to_name and name_lower in to_name.lower():
                    contacts[to_email.lower()] = to_name

        return [{"email": email, "name": name} for email, name in contacts.items()]

    async def execute(
        self,
        contact: str,
        max_results: int = 20,
        search_all_history: bool = False,
        selected_emails: str = None,
    ):
        """Search emails for exchanges with a contact.

        Args:
            contact: Email address OR name to search for
            max_results: Maximum results (default 20)
            search_all_history: If True, search from 2020
            selected_emails: Comma-separated indices
        """
        from datetime import datetime, timedelta

        try:
            if not self._is_email(contact):
                found_contacts = self._find_emails_by_name(contact)

                if not found_contacts:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data={
                            "contact": contact,
                            "found_emails": [],
                        },
                        error=(f"No contact found with name" f" '{contact}' in emails."),
                    )

                if len(found_contacts) == 1:
                    emails_to_search = [found_contacts[0]["email"]]
                elif selected_emails:
                    try:
                        indices = [int(i.strip()) - 1 for i in selected_emails.split(",")]
                        emails_to_search = [
                            found_contacts[i]["email"]
                            for i in indices
                            if 0 <= i < len(found_contacts)
                        ]
                    except (ValueError, IndexError):
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=(
                                f"Invalid indices:"
                                f" {selected_emails}."
                                f" Use 1 to"
                                f" {len(found_contacts)}."
                            ),
                        )
                else:
                    options = "\n".join(
                        [
                            f"  {i+1}) {c['name']}" f" <{c['email']}>"
                            for i, c in enumerate(found_contacts)
                        ]
                    )
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data={
                            "contact": contact,
                            "found_emails": found_contacts,
                            "needs_selection": True,
                        },
                        message=(
                            f"Found {len(found_contacts)}"
                            f" emails for '{contact}':\n"
                            f"{options}\n\nWhich one?"
                        ),
                    )
            else:
                emails_to_search = [contact]

            all_messages = []
            for addr in emails_to_search:
                # Build IMAP-compatible query
                query = f"from:{addr} OR to:{addr}"

                if search_all_history:
                    query += " after:2020/01/01"
                    date_from = "2020-01-01"
                    warning = "WARNING: Full history search" " (from 2020). Expensive!"
                else:
                    one_year_ago = datetime.now() - timedelta(days=365)
                    date_from = one_year_ago.strftime("%Y-%m-%d")
                    query += " after:" + one_year_ago.strftime("%Y/%m/%d")
                    warning = None

                messages = self.imap.search_messages(query, max_results)
                all_messages.extend(messages)

            # Deduplicate by message_id
            seen_ids = set()
            unique_messages = []
            for msg in all_messages:
                msg_id = msg.get(
                    "message_id",
                    msg.get("subject", "") + msg.get("date", ""),
                )
                if msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    unique_messages.append(msg)

            result_data = {
                "contact": contact,
                "emails_searched": emails_to_search,
                "message_count": len(unique_messages),
                "search_scope": ("all_history_from_2020" if search_all_history else "last_year"),
                "messages": [
                    {
                        "from": msg.get("from", ""),
                        "to": msg.get("to", ""),
                        "subject": msg.get("subject", ""),
                        "date": msg.get("date", ""),
                        "snippet": msg.get("snippet", ""),
                    }
                    for msg in unique_messages
                ],
            }

            date_to = datetime.now().strftime("%Y-%m-%d")
            message = (
                f"Found {len(unique_messages)} email"
                f" exchanges"
                f" (from {date_from} to {date_to})"
            )
            if len(emails_to_search) > 1:
                message += f" [searched" f" {len(emails_to_search)}" " addresses]"
            if warning:
                message = f"{warning}\n{message}"
            if not search_all_history and len(unique_messages) == 0:
                message += (
                    "\nNo results in last year."
                    " Use search_all_history=true"
                    " to search from 2020."
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=result_data,
                message=message,
            )
        except Exception as e:
            logger.error(f"[search_provider_emails] Error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Search email history for emails from"
                " or to a contact. Can accept email"
                " address OR name. If name is provided,"
                " will find associated emails first."
                " By default searches last year only."
                " Use search_all_history=true to search"
                " from 2020 (WARNING: expensive)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": ("Email address OR person" " name to search for"),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": ("Maximum results" " (default 20)"),
                        "default": 20,
                    },
                    "search_all_history": {
                        "type": "boolean",
                        "description": ("If true, search from 2020." " WARNING: expensive!"),
                        "default": False,
                    },
                    "selected_emails": {
                        "type": "string",
                        "description": ("When multiple emails found," " specify which (e.g. '1')"),
                    },
                },
                "required": ["contact"],
            },
        }


def _draft_rfc_identifier(value):
    if not isinstance(value, str):
        return value
    if "\r" in value or "\n" in value:
        raise ValueError("Draft threading identifier contains a line break")
    if value.startswith("<") and value.endswith(">"):
        return value
    decoded = html.unescape(value)
    if decoded == value or not any(c in decoded + html.unescape(decoded) for c in "<>"):
        return value
    if (
        not value.startswith("&lt;")
        or not value.endswith("&gt;")
        or decoded != html.unescape(decoded)
        or value not in (html.escape(decoded, quote=False), html.escape(decoded, quote=True))
        or re.fullmatch(r"<[^<>\s@]+@[^<>\s@]+>", decoded) is None
    ):
        raise ValueError("Draft threading identifier encoding is ambiguous")
    return decoded


class CreateDraftTool(Tool):
    """Create a draft email in database."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="create_draft",
            description=("Create a draft email that the user can" " review and send later"),
        )
        self.storage = storage
        self.owner_id = owner_id

    @observed("persistence", "create_draft", private=True)
    async def execute(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str = None,
        references: str = None,
        thread_id: str = None,
        attachment_paths: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ):
        try:
            thread_id = _draft_rfc_identifier(thread_id)
            in_reply_to = _draft_rfc_identifier(in_reply_to)
            refs_list = None
            if references:
                # A References header is folded over several lines, and the
                # archive stores it that way: a line break between two
                # identifiers is whitespace. Each identifier is checked
                # below, so none of them carries one.
                refs_list = (
                    [r.strip() for r in references.split()]
                    if isinstance(references, str)
                    else references
                )
                if isinstance(refs_list, list):
                    refs_list = [_draft_rfc_identifier(value) for value in refs_list]

            # Normalize + verify attachments BEFORE persisting so we fail fast.
            try:
                norm_paths = _normalize_attachment_paths(attachment_paths)
            except PathRefused as e:
                return ToolResult(status=ToolStatus.ERROR, data=None, error=f"Attachment refused: {e}")
            for p in norm_paths:
                if not os.path.isfile(p):
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error=f"Attachment not found: {p}",
                    )

            # Basic normalization: strip, drop empties. We deliberately do
            # NOT reject malformed addresses -- SMTP will surface that at
            # send time -- but obvious garbage like empty strings is filtered.
            cc_list = [a.strip() for a in (cc or []) if isinstance(a, str) and a.strip()]
            bcc_list = [a.strip() for a in (bcc or []) if isinstance(a, str) and a.strip()]

            draft = self.storage.create_draft(
                owner_id=self.owner_id,
                to=to,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
                references=refs_list,
                thread_id=canonical_draft_thread_id(thread_id),
                attachment_paths=norm_paths,
                cc=cc_list,
                bcc=bcc_list,
            )

            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=("Failed to create draft" " in database"),
                )

            # The provider may return an existing human-edited draft. Present
            # its saved bytes rather than unpersisted model output.
            to = ", ".join(draft.get("to_addresses") or [])
            subject, body = draft.get("subject", ""), draft.get("body", "")
            cc_list, bcc_list = draft.get("cc_addresses") or [], draft.get("bcc_addresses") or []
            in_reply_to = draft.get("in_reply_to")
            thread_info = " (in reply to thread)" if in_reply_to else ""
            attach_info = ""
            if norm_paths:
                attach_info = "\nAttachments:\n" + "\n".join(
                    f"  - {os.path.basename(p)}" for p in norm_paths
                )
            cc_info = f"\nCc: {', '.join(cc_list)}" if cc_list else ""
            bcc_info = f"\nBcc: {', '.join(bcc_list)}" if bcc_list else ""
            # `create_draft` is idempotent: an identical unsent draft written
            # in the last day is returned rather than duplicated. Say which
            # happened, because a caller that watches for a NEW draft (the
            # operator tooling diffs `drafts.list` around a turn) would
            # otherwise read a reused id as "nothing was composed".
            created = draft.get("created", True)
            headline = "Draft created" if created else "Draft already exists"
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "draft_id": draft.get("id"),
                    "created": created,
                    "attachment_paths": norm_paths,
                    "cc": cc_list,
                    "bcc": bcc_list,
                },
                message=(
                    f"{headline}{thread_info}!\n"
                    f"To: {to}"
                    f"{cc_info}"
                    f"{bcc_info}\n"
                    f"Subject: {subject}"
                    f"{attach_info}\n\n"
                    f"Message body:\n"
                    f"{'─' * 70}\n"
                    f"{body}\n"
                    f"{'─' * 70}\n\n"
                    f"Draft saved. Say 'send it'"
                    f" when ready."
                ),
            )
        except Exception as e:
            failure("persistence", e)
            logger.error(f"Failed to create draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error creating draft: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Create a draft email. The draft is saved"
                " locally and can be sent later. If this"
                " is a REPLY, provide in_reply_to and"
                " references from the original message."
                " attachment_paths: optional list of local"
                " file paths (absolute or ~-expanded) to"
                " attach when the draft is sent."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": ("Recipient email address"),
                    },
                    "subject": {
                        "type": "string",
                        "description": ("Email subject line"),
                    },
                    "body": {
                        "type": "string",
                        "description": ("Email body text"),
                    },
                    "in_reply_to": {
                        "type": "string",
                        "description": ("Message-ID of email being" " replied to"),
                    },
                    "references": {
                        "type": "string",
                        "description": ("References header from" " original message"),
                    },
                    "thread_id": {
                        "type": "string",
                        "description": ("Thread ID for replies"),
                    },
                    "attachment_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of local file paths"
                            " to attach (absolute or ~-expanded)."
                        ),
                    },
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "CC recipients (optional). Use when"
                            " the user wants to reply-to-all or"
                            " add additional recipients."
                        ),
                    },
                    "bcc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "BCC recipients (optional). Use when"
                            " the user wants blind-copied additional"
                            " recipients not visible to others."
                        ),
                    },
                },
                "required": ["to", "subject", "body"],
            },
        }


class ListDraftsTool(Tool):
    """List all drafts from database."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="list_drafts",
            description="List all draft emails",
        )
        self.storage = storage
        self.owner_id = owner_id

    async def execute(self):
        try:
            drafts = self.storage.list_drafts(self.owner_id)

            if not drafts:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"drafts": []},
                    message="No drafts found.",
                )

            draft_details = []
            for draft in drafts:
                to_addresses = draft.get("to_addresses", [])
                to_str = ", ".join(to_addresses) if to_addresses else "Unknown"
                body = draft.get("body", "")
                draft_details.append(
                    {
                        "id": draft["id"],
                        "to": to_str,
                        "subject": draft.get("subject", "(no subject)"),
                        "body_preview": body,
                        "created_at": draft.get("created_at"),
                    }
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"drafts": draft_details},
                message=(
                    f"Found {len(draft_details)} drafts:"
                    "\n\n"
                    + "\n".join(
                        [
                            f"**Draft {i+1}**"
                            f" (ID: {d['id']})\n"
                            f"To: {d['to']}\n"
                            f"Subject: {d['subject']}\n"
                            f"Preview: {d['body_preview']}\n"
                            for i, d in enumerate(draft_details)
                        ]
                    )
                ),
            )

        except Exception as e:
            logger.error(f"Failed to list drafts: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(f"Error retrieving drafts:" f" {str(e)}"),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "List all draft emails. Returns draft" " IDs, recipients, subjects, previews."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }


class UpdateDraftTool(Tool):
    """Replace a mailbox draft and return its current exact handle."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="update_draft",
            description=("Update an existing draft" " with new content"),
        )
        self.storage = storage
        self.owner_id = owner_id

    @observed("persistence", "update_draft", private=True)
    async def execute(
        self,
        draft_id: str,
        to: str = None,
        subject: str = None,
        body: str = None,
        attachment_paths: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ):
        try:
            update_data = {}
            if to is not None:
                update_data["to_addresses"] = [addr.strip() for addr in to.split(",")]
            if subject is not None:
                update_data["subject"] = subject
            if body is not None:
                update_data["body"] = body
            if attachment_paths is not None:
                try:
                    norm_paths = _normalize_attachment_paths(attachment_paths)
                except PathRefused as e:
                    return ToolResult(
                        status=ToolStatus.ERROR, data=None, error=f"Attachment refused: {e}"
                    )
                for p in norm_paths:
                    if not os.path.isfile(p):
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Attachment not found: {p}",
                        )
                update_data["attachment_paths"] = norm_paths
            if cc is not None:
                update_data["cc_addresses"] = [
                    a.strip() for a in cc if isinstance(a, str) and a.strip()
                ]
            if bcc is not None:
                update_data["bcc_addresses"] = [
                    a.strip() for a in bcc if isinstance(a, str) and a.strip()
                ]

            changed = self.storage.update_draft(self.owner_id, draft_id, update_data)
            if changed is None:
                raise ValueError("The named mailbox draft is no longer available")
            draft_id = changed["id"]

            updates = []
            if to:
                updates.append(f"To: {to}")
            if subject:
                updates.append(f"Subject: {subject}")
            if body:
                updates.append("Body: updated")
            if attachment_paths is not None:
                updates.append(
                    f"Attachments: {len(update_data.get('attachment_paths', []))} file(s)"
                )
            if cc is not None:
                cc_vals = update_data.get("cc_addresses", [])
                updates.append(f"Cc: {', '.join(cc_vals) if cc_vals else '(cleared)'}")
            if bcc is not None:
                bcc_vals = update_data.get("bcc_addresses", [])
                updates.append(f"Bcc: {', '.join(bcc_vals) if bcc_vals else '(cleared)'}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": draft_id},
                message=("Draft updated successfully!\n" + "\n".join(updates)),
            )
        except Exception as e:
            failure("persistence", e)
            logger.error(f"Failed to update draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(f"Error updating draft: {str(e)}"),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Update an existing draft. You can update"
                " recipient, subject, body, attachment_paths,"
                " or any combo. Fields not provided stay unchanged."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": ("Draft ID to update"),
                    },
                    "to": {
                        "type": "string",
                        "description": ("New recipient email"),
                    },
                    "subject": {
                        "type": "string",
                        "description": ("New email subject"),
                    },
                    "body": {
                        "type": "string",
                        "description": ("New email body text"),
                    },
                    "attachment_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Replacement list of local file" " paths to attach. Pass [] to clear."
                        ),
                    },
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Replacement list of CC recipients."
                            " Pass [] to clear. Use when the user"
                            " wants to reply-to-all or add"
                            " additional recipients."
                        ),
                    },
                    "bcc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": ("Replacement list of BCC recipients." " Pass [] to clear."),
                    },
                },
                "required": ["draft_id"],
            },
        }


class DeleteDraftTool(Tool):
    """Delete a draft from the local DB."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="delete_draft",
            description=(
                "Delete a draft by id. Use when user says"
                " 'cancella', 'delete', 'discard' a draft."
            ),
        )
        self.storage = storage
        self.owner_id = owner_id

    async def execute(self, draft_id: str):
        try:
            deleted = self.storage.delete_draft(self.owner_id, draft_id)
            if not deleted:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Draft not found: {draft_id}",
                )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": draft_id},
                message=f"Draft {draft_id} deleted",
            )
        except Exception as e:
            logger.error(f"Failed to delete draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error deleting draft: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Delete a draft by id from the local DB."
                " Use when the user says 'cancella',"
                " 'delete', or 'discard' a draft."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": "Draft ID to delete",
                    },
                },
                "required": ["draft_id"],
            },
        }


class SendDraftTool(Tool):
    """Send a draft via SMTP (using IMAPClient)."""

    def __init__(self, imap_client, storage, owner_id: str):
        super().__init__(
            name="send_draft",
            description=(
                "Send a draft email. When user says"
                " 'send it', 'inviala', 'spedisci',"
                " call this tool with the draft_id of"
                " the draft being discussed."
            ),
        )
        self.imap = imap_client
        self.storage = storage
        self.owner_id = owner_id

    def _resolve_draft(self, draft_id):
        """Read only the exact mailbox-bound handle; preserve provider failures."""
        if not draft_id:
            return None
        handle = str(draft_id).strip()
        if not handle:
            return None

        return self.storage.get_draft(self.owner_id, handle)

    def _claim_refusal(self, draft_id: str) -> str:
        """Word the refusal after a lost claim by what the row now says.

        A claim can fail for two different reasons and they are not the same
        news for the operator: another request is mailing this draft right
        now, or the mail has already gone out. Re-read rather than guess.
        """
        try:
            current = self.storage.get_draft(self.owner_id, draft_id) or {}
        except Exception as e:  # storage hiccup — fall back to the vaguer text
            logger.warning(f"[send_draft] could not re-read draft after lost claim: {e}")
            current = {}
        status = (current.get("status") or "").lower()
        if status == "sent":
            return (
                f"Draft {draft_id} has already been sent. Nothing was sent."
                " Compose a new draft if you meant to write again."
            )
        if not current:
            return f"Draft not found: {draft_id}. Nothing was sent."
        return f"Draft {draft_id} is already being sent by another request." " Nothing was sent."

    def approval_input(self, tool_input):
        """Hydrate the send-approval card with the draft's editable content.

        The model only supplies ``draft_id``, but the human needs To /
        Subject / Body in front of them to review
        and correct before the email goes out — the same inline-edit
        affordance the WhatsApp card already has. ``draft_id`` rides along
        (hidden in the card) so ``execute`` still knows which draft to send;
        ``execute`` accepts the edited To / Subject / Body / Cc back and
        applies them to the draft before sending.

        It reads the same full mailbox-bound handle used by ``execute``.
        An unresolved handle hydrates nothing and remains unchanged for the
        eventual send refusal.
        """
        data = dict(tool_input or {})
        try:
            draft = self._resolve_draft(data.get("draft_id"))
        except Exception as e:  # Invalid mailbox handle or provider read failure.
            logger.warning(f"[send_draft] approval_input could not load draft: {e}")
            return data
        if not draft:
            return data
        return draft_approval_card(draft, data.get("draft_id"))

    async def execute(self, draft_id=None, to=None, subject=None, body=None, cc=None, bcc=None):
        """Send current mailbox content, with one durable key for this draft."""
        from zylch.services.mailbox_drafts import MailboxDrafts
        from zylch.services.request_policy import assert_tool_allowed
        try:
            assert_tool_allowed("send_draft")
            if not draft_id:
                raise ValueError("draft_id is required")
            service = MailboxDrafts(self.owner_id)
            edits = {key: value for key, value in
                     {"to": to, "subject": subject, "body": body, "cc": cc, "bcc": bcc}.items()
                     if value is not None}
            if edits:
                changed = await asyncio.to_thread(service.update, draft_id, **edits)
                if changed is None:
                    raise ValueError("The named mailbox draft is no longer available")
                draft_id = changed["id"]
            from uuid import uuid4
            # Each newly approved action is an attempt. The durable per-draft
            # fence returns any earlier uncertain/confirmed send across keys.
            result = await asyncio.to_thread(service.send, draft_id, "chat-send:" + str(uuid4()))
            if not result.get("ok"):
                return ToolResult(status=ToolStatus.ERROR, data=result,
                    error="Mailbox send " + str(result.get("state")) + ": " + str(result.get("cause", "Sent confirmation pending")))
            return ToolResult(status=ToolStatus.SUCCESS, data=result,
                message="Email confirmed in Sent. Message-ID: " + str(result.get("message_id", "")))
        except Exception as error:
            logger.exception("[send_draft] mailbox operation failed")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(error))

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Send a draft email. The draft_id is"
                " REQUIRED and must be the id of the"
                " draft the user meant: nothing is sent"
                " if it is missing or unknown."
                " IMPORTANT: Always confirm with user"
                " before sending."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": (
                            "Exact ID of the draft to send"
                            " (from create_draft or list_drafts)."
                            " Never guess it."
                        ),
                    },
                },
                "required": ["draft_id"],
            },
        }
