"""Gmail and draft email tools.

Refactored for IMAP/SMTP (no Gmail/Outlook OAuth API).
GmailSearchTool uses IMAPClient.search().
SendDraftTool uses IMAPClient.send_message() via SMTP.
CreateDraftTool and ListDraftsTool use Storage (DB drafts).
"""

import logging
import os
import subprocess
import tempfile
from typing import List, Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


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
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "draft_id": draft.get("id"),
                    "attachment_paths": norm_paths,
                    "cc": cc_list,
                    "bcc": bcc_list,
                },
                message=(
                    f"Draft created{thread_info}!\n"
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


class EditDraftTool(Tool):
    """Edit a draft interactively with nano editor."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="edit_draft",
            description=("Open a draft in nano editor" " for manual editing"),
        )
        self.storage = storage
        self.owner_id = owner_id

    async def execute(self, draft_id: str):
        try:
            draft = self.storage.get_draft(self.owner_id, draft_id)
            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Draft not found: {draft_id}",
                )

            to_addresses = draft.get("to_addresses", [])
            to_str = ", ".join(to_addresses) if to_addresses else "Unknown"

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                temp_path = f.name
                f.write("# DRAFT METADATA (DO NOT EDIT)\n")
                f.write(f"# To: {to_str}\n")
                f.write(f"# Subject:" f" {draft.get('subject', '')}\n")
                f.write("#\n")
                f.write("# Edit the message body below:\n")
                f.write("# ==========================" "================\n\n")
                f.write(draft.get("body", ""))

            subprocess.run(["nano", temp_path], check=True)

            with open(temp_path, "r") as f:
                content = f.read()

            lines = content.split("\n")
            body_lines = [line for line in lines if not line.startswith("#")]
            body = "\n".join(body_lines).strip()

            self.storage.update_draft(
                self.owner_id,
                draft_id,
                {"body": body},
            )

            import os

            os.unlink(temp_path)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": draft_id},
                message=(
                    f"Draft edited and saved!\n"
                    f"To: {to_str}\n"
                    f"Subject:"
                    f" {draft.get('subject', '')}"
                ),
            )

        except subprocess.CalledProcessError:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Editing cancelled by user",
            )
        except Exception as e:
            logger.error(f"Failed to edit draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(f"Error editing draft: {str(e)}"),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Open a draft in nano text editor for"
                " manual editing. Changes are saved"
                " back when nano is closed."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": ("Draft ID to edit"),
                    },
                },
                "required": ["draft_id"],
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
                " call this tool. If no draft_id"
                " provided, sends most recent draft."
            ),
        )
        self.imap = imap_client
        self.storage = storage
        self.owner_id = owner_id

    async def execute(self, draft_id: str = None):
        try:
            if not draft_id:
                drafts = self.storage.list_drafts(self.owner_id)
                if not drafts:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error=("No drafts found." " Create a draft first."),
                    )
                draft = drafts[0]
                draft_id = draft["id"]
            else:
                draft = self.storage.get_draft(self.owner_id, draft_id)

            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(f"Draft not found: {draft_id}"),
                )

            to_addresses = draft.get("to_addresses", [])
            to = ", ".join(to_addresses) if to_addresses else None
            subject = draft.get("subject", "")
            body = draft.get("body", "")
            in_reply_to = draft.get("in_reply_to")
            references = draft.get("references")
            attachment_paths = draft.get("attachment_paths") or []
            cc_addresses = draft.get("cc_addresses") or []
            bcc_addresses = draft.get("bcc_addresses") or []

            if not to:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=("Draft has no recipient address"),
                )

            # Verify every attachment still exists -- never send a partial
            # email when an attachment has been moved or deleted since the
            # draft was created.
            for p in attachment_paths:
                if not os.path.isfile(p):
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error=(f"Attachment no longer exists: {p}." " Email NOT sent."),
                    )

            logger.debug(
                f"[send_draft] Sending to={to},"
                f" cc={cc_addresses}, bcc={len(bcc_addresses)},"
                f" subject={subject},"
                f" attachments={len(attachment_paths)}"
            )

            sent_message = self.imap.send_message(
                to=to,
                subject=subject,
                body=body,
                cc=cc_addresses or None,
                bcc=bcc_addresses or None,
                in_reply_to=in_reply_to,
                references=(" ".join(references) if references else None),
                attachment_paths=attachment_paths or None,
            )

            self.storage.mark_draft_sent(
                self.owner_id,
                draft_id,
                sent_message.get("id", ""),
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
                    message_id=sent_message.get("id"),
                    from_email=owner_email,
                    to_email=to,
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
                data={"message_id": sent_message.get("id")},
                message=(
                    f"Email sent successfully!\n"
                    f"To: {to}\n"
                    f"Subject: {subject}\n\n"
                    f"Email sent and draft"
                    f" marked as sent."
                ),
            )
        except Exception as e:
            logger.error(f"Failed to send draft: {e}")
            if draft_id:
                try:
                    self.storage.update_draft(
                        self.owner_id,
                        draft_id,
                        {
                            "status": "failed",
                            "error_message": str(e),
                        },
                    )
                except Exception:
                    pass
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(f"Error sending email: {str(e)}"),
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Send a draft email. If no draft_id"
                " provided, sends the most recent draft."
                " IMPORTANT: Always confirm with user"
                " before sending."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": (
                            "Draft ID to send" " (optional - uses most" " recent if not provided)"
                        ),
                    },
                },
                "required": [],
            },
        }
