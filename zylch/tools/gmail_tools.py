"""Gmail and draft email tools."""

import logging
import subprocess
import tempfile
from typing import Optional

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class GmailSearchTool(Tool):
    """Gmail search tool for contact enrichment."""

    def __init__(
        self,
        gmail_client,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
    ):
        super().__init__(
            name="search_provider_emails",
            description=(
                "Search email provider for emails from or to a contact"
                " to understand relationship"
            ),
        )
        self.gmail = gmail_client
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _is_email(self, value: str) -> bool:
        """Check if value looks like an email address."""
        import re

        return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", value.strip()))

    def _extract_email_from_header(self, header: str) -> tuple:
        """Extract email and name from 'Name <email>' header."""
        import re

        match = re.search(r"([^<]*)<([^>]+)>", header)
        if match:
            name = match.group(1).strip().strip('"')
            email = match.group(2).strip()
            return email, name
        if self._is_email(header):
            return header.strip(), None
        return None, header.strip()

    def _find_emails_by_name(
        self, name: str, max_search: int = 50
    ) -> list:
        """Search Gmail for emails containing this name."""
        messages = self.gmail.search_messages(name, max_search)

        contacts = {}  # email -> name
        name_lower = name.lower()

        for msg in messages:
            from_email, from_name = self._extract_email_from_header(
                msg.get("from", "")
            )
            if (
                from_email
                and from_name
                and name_lower in from_name.lower()
            ):
                contacts[from_email.lower()] = from_name

            to_field = msg.get("to", "")
            for part in to_field.split(","):
                to_email, to_name = self._extract_email_from_header(
                    part.strip()
                )
                if (
                    to_email
                    and to_name
                    and name_lower in to_name.lower()
                ):
                    contacts[to_email.lower()] = to_name

        return [
            {"email": email, "name": name}
            for email, name in contacts.items()
        ]

    async def execute(
        self,
        contact: str,
        max_results: int = 20,
        search_all_history: bool = False,
        selected_emails: str = None,
    ):
        """Search Gmail for emails with a contact.

        Args:
            contact: Email address OR name to search for
            max_results: Maximum results (default 20)
            search_all_history: If True, search from 2020
            selected_emails: Comma-separated indices when multiple found
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
                        error=(
                            f"No contact found with name '{contact}'"
                            " in emails."
                        ),
                    )

                if len(found_contacts) == 1:
                    c = found_contacts[0]
                    emails_to_search = [c["email"]]
                elif selected_emails:
                    try:
                        indices = [
                            int(i.strip()) - 1
                            for i in selected_emails.split(",")
                        ]
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
                                f"Indici non validi: {selected_emails}."
                                f" Usa numeri da 1 a"
                                f" {len(found_contacts)}."
                            ),
                        )
                else:
                    options = "\n".join([
                        f"  {i+1}) {c['name']} <{c['email']}>"
                        for i, c in enumerate(found_contacts)
                    ])
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data={
                            "contact": contact,
                            "found_emails": found_contacts,
                            "needs_selection": True,
                        },
                        message=(
                            f"Found {len(found_contacts)} emails"
                            f" associated with '{contact}':\n"
                            f"{options}\n\nWhich one to use?"
                            " (e.g., '1' or '1,3' for multiple)"
                        ),
                    )
            else:
                emails_to_search = [contact]

            all_messages = []
            for email in emails_to_search:
                base_query = f"from:{email} OR to:{email}"

                if search_all_history:
                    date_from = "2020-01-01"
                    query = f"{base_query} after:2020/01/01"
                    warning = (
                        "WARNING: Full history search (from 2020)."
                        " This operation may cost many tokens!"
                    )
                else:
                    one_year_ago = (
                        datetime.now() - timedelta(days=365)
                    )
                    date_from = one_year_ago.strftime("%Y-%m-%d")
                    query = (
                        f"{base_query}"
                        f" after:{one_year_ago.strftime('%Y/%m/%d')}"
                    )
                    warning = None

                messages = self.gmail.search_messages(
                    query, max_results
                )
                all_messages.extend(messages)

            seen_ids = set()
            unique_messages = []
            for msg in all_messages:
                msg_id = msg.get(
                    "id",
                    msg.get("subject", "") + msg.get("date", ""),
                )
                if msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    unique_messages.append(msg)

            result_data = {
                "contact": contact,
                "emails_searched": emails_to_search,
                "message_count": len(unique_messages),
                "search_scope": (
                    "all_history_from_2020"
                    if search_all_history
                    else "last_year"
                ),
                "messages": [
                    {
                        "from": msg["from"],
                        "to": msg["to"],
                        "subject": msg["subject"],
                        "date": msg["date"],
                        "snippet": msg["snippet"],
                    }
                    for msg in unique_messages
                ],
            }

            date_to = datetime.now().strftime("%Y-%m-%d")
            message = (
                f"Found {len(unique_messages)} email exchanges"
                f" (from {date_from} to {date_to})"
            )
            if len(emails_to_search) > 1:
                message += (
                    f" [searched {len(emails_to_search)}"
                    " email addresses]"
                )
            if warning:
                message = f"{warning}\n{message}"
            if not search_all_history and len(unique_messages) == 0:
                message += (
                    "\nNo results in last year."
                    " Use search_all_history=true to search"
                    " from 2020 (more expensive)."
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=result_data,
                message=message,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, data=None, error=str(e)
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Search Gmail history for emails from or to a contact."
                " Can accept email address OR name. If name is"
                " provided, will find associated emails first."
                " By default searches last year only."
                " Use search_all_history=true to search from 2020"
                " (WARNING: expensive)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": (
                            "Email address OR person name"
                            " to search for"
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum results (default 20)"
                        ),
                        "default": 20,
                    },
                    "search_all_history": {
                        "type": "boolean",
                        "description": (
                            "If true, search from 2020 instead of"
                            " last year. WARNING: expensive!"
                        ),
                        "default": False,
                    },
                    "selected_emails": {
                        "type": "string",
                        "description": (
                            "When multiple emails found for a name,"
                            " specify which to use (e.g. '1' or '1,3')"
                        ),
                    },
                },
                "required": ["contact"],
            },
        }


class CreateDraftTool(Tool):
    """Create a draft email in Supabase."""

    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="create_draft",
            description=(
                "Create a draft email that the user can review"
                " and send later"
            ),
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
    ):
        try:
            refs_list = None
            if references:
                refs_list = (
                    [r.strip() for r in references.split()]
                    if isinstance(references, str)
                    else references
                )

            draft = self.storage.create_draft(
                owner_id=self.owner_id,
                to=to,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
                references=refs_list,
                thread_id=thread_id,
            )

            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Failed to create draft in database",
                )

            thread_info = (
                " (in reply to thread)" if in_reply_to else ""
            )
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": draft.get("id")},
                message=(
                    f"Draft created successfully{thread_info}!\n"
                    f"To: {to}\n"
                    f"Subject: {subject}\n\n"
                    f"Message body:\n"
                    f"{'─' * 70}\n"
                    f"{body}\n"
                    f"{'─' * 70}\n\n"
                    f"Draft saved. Say 'send it' when ready to send."
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
                "Create a draft email. The draft is saved locally"
                " and can be sent later. If this is a REPLY to an"
                " existing email, provide the in_reply_to and"
                " references headers from the original message."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line",
                    },
                    "body": {
                        "type": "string",
                        "description": (
                            "Email body text (can include formatting)"
                        ),
                    },
                    "in_reply_to": {
                        "type": "string",
                        "description": (
                            "Message-ID of the email being replied to"
                        ),
                    },
                    "references": {
                        "type": "string",
                        "description": (
                            "References header from the original"
                            " message (for replies)"
                        ),
                    },
                    "thread_id": {
                        "type": "string",
                        "description": (
                            "Gmail thread ID (for replies to keep"
                            " in conversation)"
                        ),
                    },
                },
                "required": ["to", "subject", "body"],
            },
        }


class ListDraftsTool(Tool):
    """List all drafts from Supabase."""

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
                to_str = (
                    ", ".join(to_addresses)
                    if to_addresses
                    else "Unknown"
                )
                body = draft.get("body", "")
                draft_details.append({
                    "id": draft["id"],
                    "to": to_str,
                    "subject": draft.get("subject", "(no subject)"),
                    "body_preview": body,
                    "created_at": draft.get("created_at"),
                })

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"drafts": draft_details},
                message=(
                    f"Found {len(draft_details)} drafts:\n\n"
                    + "\n".join([
                        f"**Draft {i+1}** (ID: {d['id']})\n"
                        f"To: {d['to']}\n"
                        f"Subject: {d['subject']}\n"
                        f"Preview: {d['body_preview']}\n"
                        for i, d in enumerate(draft_details)
                    ])
                ),
            )

        except Exception as e:
            logger.error(f"Failed to list drafts: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error retrieving drafts: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "List all draft emails. Returns draft IDs,"
                " recipients, subjects, and previews."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }


class EditDraftTool(Tool):
    """Edit a draft interactively with nano editor."""

    def __init__(self, gmail_client):
        super().__init__(
            name="edit_draft",
            description=(
                "Open a draft in nano editor for manual editing"
            ),
        )
        self.gmail = gmail_client

    async def execute(self, draft_id: str):
        try:
            draft = self.gmail.get_draft(draft_id)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                temp_path = f.name
                f.write("# DRAFT METADATA (DO NOT EDIT)\n")
                f.write(f"# To: {draft['to']}\n")
                f.write(f"# Subject: {draft['subject']}\n")
                f.write("#\n")
                f.write("# Edit the message body below:\n")
                f.write(
                    "# ==========================================\n\n"
                )
                f.write(draft["body"])

            subprocess.run(["nano", temp_path], check=True)

            with open(temp_path, "r") as f:
                content = f.read()

            lines = content.split("\n")
            body_lines = []
            for line in lines:
                if line.startswith("#"):
                    continue
                body_lines.append(line)

            body = "\n".join(body_lines).strip()

            self.gmail.update_draft(
                draft_id=draft_id,
                to=None,
                subject=None,
                body=body,
            )

            import os

            os.unlink(temp_path)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": draft_id},
                message=(
                    f"Draft manually edited and saved!\n"
                    f"To: {draft['to']}\n"
                    f"Subject: {draft['subject']}"
                ),
            )

        except subprocess.CalledProcessError:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Editing cancellato dall'utente",
            )
        except Exception as e:
            logger.error(f"Failed to edit draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error editing draft: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Open a Gmail draft in nano text editor for manual"
                " editing by the user. The draft content will be"
                " opened in nano, user can modify it, and changes"
                " will be saved back to Gmail when nano is closed."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": "Gmail draft ID to edit",
                    },
                },
                "required": ["draft_id"],
            },
        }


class UpdateDraftTool(Tool):
    """Update an existing draft."""

    def __init__(self, gmail_client):
        super().__init__(
            name="update_draft",
            description=(
                "Update an existing draft with new content"
            ),
        )
        self.gmail = gmail_client

    async def execute(
        self,
        draft_id: str,
        to: str = None,
        subject: str = None,
        body: str = None,
    ):
        try:
            updated_draft = self.gmail.update_draft(
                draft_id=draft_id,
                to=to,
                subject=subject,
                body=body,
            )

            updates = []
            if to:
                updates.append(f"To: {to}")
            if subject:
                updates.append(f"Subject: {subject}")
            if body:
                updates.append("Body: updated")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": updated_draft.get("id")},
                message=(
                    "Draft updated successfully!\n"
                    + "\n".join(updates)
                    + "\n\nThe updated draft is available"
                    " in Gmail Drafts folder."
                ),
            )
        except Exception as e:
            logger.error(f"Failed to update draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error updating draft: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Update an existing Gmail draft. You can update"
                " the recipient, subject, body, or any combination."
                " Fields not provided will remain unchanged."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": (
                            "Gmail draft ID (returned when draft"
                            " was created)"
                        ),
                    },
                    "to": {
                        "type": "string",
                        "description": (
                            "New recipient email address (optional)"
                        ),
                    },
                    "subject": {
                        "type": "string",
                        "description": (
                            "New email subject (optional)"
                        ),
                    },
                    "body": {
                        "type": "string",
                        "description": (
                            "New email body text (optional)"
                        ),
                    },
                },
                "required": ["draft_id"],
            },
        }


class SendDraftTool(Tool):
    """Send a draft from Supabase via Gmail/Outlook API."""

    def __init__(self, gmail_client, storage, owner_id: str):
        super().__init__(
            name="send_draft",
            description=(
                "Send a draft email. When user says 'send it',"
                " 'inviala', 'spedisci', call this tool."
                " If no draft_id provided, sends the most"
                " recent draft."
            ),
        )
        self.gmail = gmail_client
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
                        error=(
                            "No drafts found. Create a draft first."
                        ),
                    )
                draft = drafts[0]
                draft_id = draft["id"]
            else:
                draft = self.storage.get_draft(
                    self.owner_id, draft_id
                )

            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Draft not found: {draft_id}",
                )

            to_addresses = draft.get("to_addresses", [])
            to = (
                ", ".join(to_addresses) if to_addresses else None
            )
            subject = draft.get("subject", "")
            body = draft.get("body", "")
            in_reply_to = draft.get("in_reply_to")
            references = draft.get("references")
            thread_id = draft.get("thread_id")

            if not to:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Draft has no recipient address",
                )

            sent_message = self.gmail.send_message(
                to=to,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
                references=(
                    " ".join(references) if references else None
                ),
                thread_id=thread_id,
            )

            self.storage.mark_draft_sent(
                self.owner_id,
                draft_id,
                sent_message.get("id", ""),
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"message_id": sent_message.get("id")},
                message=(
                    f"Email sent successfully!\n"
                    f"To: {to}\n"
                    f"Subject: {subject}\n\n"
                    f"Email sent and draft marked as sent."
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
                error=f"Error sending email: {str(e)}",
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Send a draft email. If no draft_id provided,"
                " sends the most recent draft. IMPORTANT: Always"
                " confirm with the user before sending."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": (
                            "Draft ID to send (optional - uses"
                            " most recent if not provided)"
                        ),
                    },
                },
                "required": [],
            },
        }


class RefreshGoogleAuthTool(Tool):
    """Refresh Google OAuth authentication."""

    def __init__(self, gmail_client, calendar_client):
        super().__init__(
            name="refresh_google_auth",
            description=(
                "Refresh Google OAuth permissions for Gmail"
                " and Calendar"
            ),
        )
        self.gmail = gmail_client
        self.calendar = calendar_client

    async def execute(self):
        return ToolResult(
            status=ToolStatus.ERROR,
            data=None,
            error=(
                "To refresh Google authentication, please use:"
                " /connect google reset\n"
                "Then reconnect with: /connect google"
            ),
        )

    def get_schema(self):
        return {
            "name": self.name,
            "description": (
                "Rinnova i permessi Google (Gmail e Calendar)."
                " Guida l'utente a usare /connect google"
                " per riautenticarsi."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
