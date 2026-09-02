"""Gmail and draft email tools.

Refactored for IMAP/SMTP (no Gmail/Outlook OAuth API).
GmailSearchTool uses IMAPClient.search().
SendDraftTool uses IMAPClient.send_message() via SMTP.
CreateDraftTool and ListDraftsTool use Storage (DB drafts).
"""

import logging
import os
import smtplib
import socket
from typing import List, Optional

from ..services.approval_gate import draft_approval_card, draft_updates_from_card
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


#: Shortest abbreviated draft handle the send path will resolve. It is the
#: length the operator's review digest prints (`cs-kernel/cs/review.py`
#: renders `engine <id[:8]>` and calls it the form a draft is retired by), and
#: it is short enough to type while leaving collision risk at roughly 1e-6 for
#: a mailbox holding tens of drafts. Below it, a handle is refused rather than
#: guessed: resolving "ab" to whatever matches is how "send THAT draft" turns
#: into a mail to a different customer.
DRAFT_HANDLE_MIN_LENGTH = 8

#: How many matches an ambiguous handle is worth listing. The lookup asks for
#: one more than this so a saturated result can say "at least N" instead of
#: quoting the cap as if it were the count.
DRAFT_HANDLE_MATCH_CAP = 10


class DraftHandleError(Exception):
    """An abbreviated draft handle that cannot be resolved to ONE draft.

    Carries the sentence the operator should read. Distinct from "no such
    draft": an ambiguous or too-short handle means the send did not happen
    because the request was unclear, and the fix is to type more of the id —
    not to conclude that the draft is gone.
    """


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
    """Expand ~ and resolve to absolute paths. Does NOT verify existence."""
    if not paths:
        return []
    out: List[str] = []
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            continue
        out.append(os.path.abspath(os.path.expanduser(p)))
    return out


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


class CreateDraftTool(Tool):
    """Create a draft email in database."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="create_draft",
            description=("Create a draft email that the user can" " review and send later"),
        )
        self.storage = storage
        self.owner_id = owner_id

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
            refs_list = None
            if references:
                refs_list = (
                    [r.strip() for r in references.split()]
                    if isinstance(references, str)
                    else references
                )

            # Normalize + verify attachments BEFORE persisting so we fail fast.
            norm_paths = _normalize_attachment_paths(attachment_paths)
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
                thread_id=thread_id,
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
    """Update an existing draft in database."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="update_draft",
            description=("Update an existing draft" " with new content"),
        )
        self.storage = storage
        self.owner_id = owner_id

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
                norm_paths = _normalize_attachment_paths(attachment_paths)
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

            self.storage.update_draft(self.owner_id, draft_id, update_data)

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
        """Return the draft named by ``draft_id``, or ``None``.

        Accepts either the full id or an abbreviated handle of at least
        DRAFT_HANDLE_MIN_LENGTH characters, because the abbreviated form is
        what the operator is handed: the review digest prints the first 8
        characters and calls that the handle a draft is retired by. A send
        path that only accepts the full uuid refuses the only id its operator
        has in front of them.

        There is deliberately NO "most recent draft" fallback, and an
        abbreviated handle that matches two drafts RAISES rather than picking
        one. A mailbox normally holds several drafts, so resolving an unknown
        or ambiguous id to whatever happens to be newest turns "send THAT
        draft" into an email to a different recipient. An id that does not
        resolve must fail the send, never redirect it.

        Raises:
            DraftHandleError: the handle is too short to be safe, or it
                matches more than one draft.
        """
        if not draft_id:
            return None
        handle = str(draft_id).strip()
        if not handle:
            return None

        exact = self.storage.get_draft(self.owner_id, handle)
        if exact:
            return exact

        if len(handle) < DRAFT_HANDLE_MIN_LENGTH:
            raise DraftHandleError(
                f"'{handle}' is too short to identify a draft. Give at least"
                f" the first {DRAFT_HANDLE_MIN_LENGTH} characters of its id."
                " Nothing was sent."
            )

        matches = self.storage.find_drafts_by_id_prefix(
            self.owner_id, handle, limit=DRAFT_HANDLE_MATCH_CAP + 1
        )
        if not matches:
            return None
        if len(matches) > 1:
            listed = matches[:DRAFT_HANDLE_MATCH_CAP]
            saturated = len(matches) > DRAFT_HANDLE_MATCH_CAP
            count = f"at least {len(listed)}" if saturated else str(len(matches))
            ids = ", ".join(str(m.get("id")) for m in listed)
            more = ", and others" if saturated else ""
            raise DraftHandleError(
                f"'{handle}' matches {count} drafts ({ids}{more}). Give more"
                " of the id. Nothing was sent."
            )
        logger.debug(f"[send_draft] handle {handle} resolved to {matches[0].get('id')}")
        return matches[0]

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

        It resolves the handle exactly the way ``execute`` does, abbreviated
        forms included — the card and the send must never disagree about which
        draft an id names. An unresolvable handle hydrates nothing and leaves
        the refusal to ``execute``, which is the only place that can say
        "nothing was sent" truthfully.
        """
        data = dict(tool_input or {})
        try:
            draft = self._resolve_draft(data.get("draft_id"))
        except Exception as e:  # ambiguous handle or storage hiccup
            logger.warning(f"[send_draft] approval_input could not load draft: {e}")
            return data
        if not draft:
            return data
        return draft_approval_card(draft, data.get("draft_id"))

    async def execute(
        self,
        draft_id: str = None,
        to: str = None,
        subject: str = None,
        body: str = None,
        cc=None,
        bcc=None,
    ):
        # to / subject / body / cc / bcc arrive ONLY when the user edited
        # the send approval card (see approval_input). They override the
        # stored draft and are persisted before sending, so the sent copy
        # and the stored/thread copy stay in sync. Absent -> send as-is.
        #
        # The body runs in three phases and the split is load-bearing.
        #   1. Decide. Nothing is claimed yet, so any failure is a plain
        #      refusal and the draft is untouched.
        #   2. Claim the draft, then edit / extract / send. Everything that
        #      mutates the row happens INSIDE the claim, so a caller that lost
        #      the race never rewrites a row somebody else is mailing. Giving
        #      the claim back is conditional on still holding it.
        #   3. Bookkeeping, AFTER the mail is out. This phase may only ever
        #      drive the draft towards `sent`. A rollback here would make a
        #      delivered mail sendable again — which is exactly what a single
        #      try block spanning the transport call used to do.
        try:
            draft = self._resolve_draft(draft_id)
            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(
                        f"Draft not found: {draft_id}. Nothing was sent."
                        if draft_id
                        else (
                            "send_draft requires the draft_id of the draft to"
                            " send. Nothing was sent."
                        )
                    ),
                )
            # From here on `draft_id` is the RESOLVED row id, never the
            # argument. Every write below — the claim above all — must key on
            # this: `_resolve_draft` is where an operator-supplied handle
            # becomes a row, and a claim keyed on the raw argument would stop
            # matching the moment that handle is anything but a full uuid.
            draft_id = draft.get("id") or draft_id

            # A draft is sendable unless it has already been handed to a
            # transport. `get_draft` deliberately does NOT filter on status —
            # hiding rows there would surprise `approval_input`, the card
            # hydrator and `update_draft`, all of which must still see a sent
            # draft — so the refusal lives here. Without it, calling
            # `send_draft(draft_id=X)` twice mails the same customer twice.
            #
            # Only `sent` is refused here, and only because that refusal is
            # final and deserves its own words. `sending` is left to
            # `storage.claim_draft_for_send` in phase 2: a live claim loses
            # there anyway, while a claim abandoned by a killed daemon is
            # taken over rather than refused. Refusing every `sending` row up
            # front would leave those rows unsendable while no listing shows
            # them either (`drafts.list` filters `status='draft'`).
            #
            # `failed` stays sendable, and `/email send` agrees. A transport
            # error is the case where a retry by id is exactly what the
            # operator wants, and the two paths must not disagree about which
            # draft is sendable. Note that no live path writes `failed` any
            # more (both send paths restore the draft to `draft` on error,
            # which is also what keeps it visible in `drafts.list`); accepting
            # it is what makes rows stranded by the old behaviour recoverable.
            status = (draft.get("status") or "draft").lower()
            if status == "sent":
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(
                        f"Draft {draft_id} has already been sent. Nothing was"
                        " sent. Compose a new draft if you meant to write again."
                    ),
                )

            # Verify every attachment still exists -- never send a partial
            # email when an attachment has been moved or deleted since the
            # draft was created. The approval card cannot edit attachments,
            # so this decision does not depend on the edits applied below and
            # belongs in the cheap, unclaimed phase.
            for p in draft.get("attachment_paths") or []:
                if not os.path.isfile(p):
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error=(f"Attachment no longer exists: {p}." " Email NOT sent."),
                    )
        except DraftHandleError as e:
            # An unclear handle, not a missing draft: say which, so the
            # operator adds characters instead of hunting for a lost draft.
            logger.info(f"[send_draft] unresolvable handle: {e}")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))
        except Exception as e:
            # Phase 1 failure: the draft was never claimed, so there is
            # nothing to roll back and it stays exactly as sendable as it was.
            logger.error(f"Failed to prepare draft for sending: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(f"Error sending email: {str(e)}"),
            )

        # --- phase 2: claim FIRST, then mutate. NO await anywhere here. ---
        #
        # The claim precedes the card edits on purpose: a caller that loses
        # the race must not have written the operator's corrections into a row
        # another request is already mailing, or the delivered mail and the
        # stored `sent` copy say different things.
        if not self.storage.claim_draft_for_send(self.owner_id, draft_id):
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=self._claim_refusal(draft_id),
            )

        try:
            # Same translation the slash-command gate uses, so a correction
            # made in the approval card lands on the draft identically
            # whichever path is sending it.
            edits = draft_updates_from_card(
                {"to": to, "subject": subject, "body": body, "cc": cc, "bcc": bcc}
            )
            if edits:
                logger.debug(f"[send_draft] applying card edits keys={list(edits.keys())}")
                self.storage.update_draft(self.owner_id, draft_id, edits)
                draft = self.storage.get_draft(self.owner_id, draft_id) or draft

            to_addresses = draft.get("to_addresses", [])
            to_str = ", ".join(to_addresses) if to_addresses else None
            subject = draft.get("subject", "")
            body = draft.get("body", "")
            in_reply_to = draft.get("in_reply_to")
            references = draft.get("references")
            attachment_paths = draft.get("attachment_paths") or []
            cc_addresses = draft.get("cc_addresses") or []
            bcc_addresses = draft.get("bcc_addresses") or []

            if not to_str:
                raise ValueError("Draft has no recipient address")

            logger.debug(
                f"[send_draft] Sending to={to_str},"
                f" cc={cc_addresses}, bcc={len(bcc_addresses)},"
                f" subject={subject},"
                f" attachments={len(attachment_paths)}"
            )
        except Exception as e:
            # Still short of the transport, so the mail provably did not go
            # out: hand the claim back and leave the draft visible.
            logger.error(f"Failed to prepare claimed draft for sending: {e}")
            self.storage.release_draft_claim(self.owner_id, draft_id, "draft", str(e))
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(f"Error sending email: {str(e)}"),
            )

        try:
            sent_message = self.imap.send_message(
                to=to_str,
                subject=subject,
                body=body,
                cc=cc_addresses or None,
                bcc=bcc_addresses or None,
                in_reply_to=in_reply_to,
                references=(" ".join(references) if references else None),
                attachment_paths=attachment_paths or None,
            )
        except Exception as e:
            logger.error(f"Failed to send draft: {e}")
            uncertain = delivery_is_uncertain(e)
            try:
                # Back to `draft`, not `failed` — the same thing `/email
                # send` does on the same error, so the two paths agree.
                # Every surface that shows drafts (`drafts.list`, `/email
                # list --draft`, `list_drafts`) filters `status == "draft"`
                # and NOTHING reads `failed`, so parking a transport error
                # there deleted the draft from the operator's view: an
                # email nobody can see is an email nobody retries.
                # `error_message` keeps the diagnosis.
                #
                # Unless the transport died in a way that leaves delivery
                # UNKNOWN — a dropped socket may well have dropped after the
                # server took the message. Such a draft stays in `sending`,
                # which holds it for its claim window: neither sendable nor
                # discardable until that expires. The operator is told to
                # check the mailbox instead of being promised that nothing
                # went out.
                self.storage.release_draft_claim(
                    self.owner_id,
                    draft_id,
                    "sending" if uncertain else "draft",
                    str(e),
                )
            except Exception as restore_error:
                # The draft stays in `sending` and only the stale-claim
                # window will free it. Say so rather than swallowing it.
                logger.error(
                    f"[send_draft] draft {draft_id} left in `sending`:"
                    f" restore after transport error failed: {restore_error}"
                )
            if uncertain:
                from zylch.storage.storage import (
                    send_claim_recipient_count,
                    send_claim_window_minutes,
                )

                held_for = send_claim_window_minutes(
                    send_claim_recipient_count(to_addresses, cc_addresses, bcc_addresses)
                )
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(
                        f"The connection to the mail server dropped while sending"
                        f" draft {draft_id}: {str(e)}. It is NOT known whether the"
                        f" email went out — check the mailbox. The draft is held"
                        f" for {held_for} minutes and can be neither sent nor"
                        f" discarded until then."
                    ),
                )
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(f"Error sending email: {str(e)}. Nothing was sent."),
            )

        # --- phase 3: the mail is out. Only `sent` from here on. ---
        sent_id = sent_message.get("id", "")
        try:
            self.storage.mark_draft_sent(self.owner_id, draft_id, sent_id)
        except Exception as e:
            logger.error(f"[send_draft] mark_draft_sent failed after delivery: {e}")
            try:
                self.storage.force_draft_sent(self.owner_id, draft_id, sent_id)
            except Exception as force_error:
                # Worst case: a delivered mail whose draft is stuck in
                # `sending`, which the stale-claim window will eventually
                # offer up again. Loud, because only a human can settle it.
                logger.error(
                    f"[send_draft] draft {draft_id} DELIVERED but could not be"
                    f" marked sent: {force_error}"
                )

        # Persist the sent email so the thread view and task
        # reanalysis reflect that the user replied. Best-effort:
        # never block the send on a local-DB failure.
        try:
            from datetime import datetime, timezone

            from zylch.api.token_storage import get_email

            owner_email = get_email(self.owner_id) or ""
            attachment_filenames = [os.path.basename(p) for p in (attachment_paths or [])]
            self.storage.insert_sent_email(
                owner_id=self.owner_id,
                thread_id=draft.get("thread_id"),
                message_id=sent_id,
                from_email=owner_email,
                to_email=to_str,
                cc=cc_addresses,
                subject=subject,
                body_plain=body,
                sent_at=datetime.now(timezone.utc),
                attachment_filenames=attachment_filenames,
                in_reply_to=in_reply_to,
            )
        except Exception as e:
            logger.warning(f"[send_draft] persist failed (non-blocking): {e}")

        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={"message_id": sent_id},
            message=(
                f"Email sent successfully!\n"
                f"To: {to_str}\n"
                f"Subject: {subject}\n\n"
                f"Email sent and draft"
                f" marked as sent."
            ),
        )

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
