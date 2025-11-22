"""Main CLI interface for MrPark using prompt_toolkit."""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from ..agent import MrParkAgent
from ..agent.models import ModelSelector
from ..cache import JSONCache
from ..config import settings
from ..memory import ReasoningBankMemory
from ..tools.contacts import QueryContactsTool, UpdateContactTool, EnrichContactTool
from ..tools.gmail import GmailClient
from ..tools.gcalendar import (
    GoogleCalendarClient,
    ListCalendarEventsTool,
    CreateCalendarEventTool,
    SearchCalendarEventsTool,
    UpdateCalendarEventTool
)
from ..tools.email_sync import EmailSyncManager
from ..tools.calendar_sync import CalendarSyncManager
from ..tools.relationship_analyzer import RelationshipAnalyzer
from ..tools.task_manager import TaskManager
from ..tools.pipedrive import PipedriveClient
from ..tools.starchat import StarChatClient
from ..tools.web_search import WebSearchTool
from ..tools.base import Tool, ToolResult, ToolStatus

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# CLI style
cli_style = Style.from_dict({
    'prompt': 'ansicyan bold',
    'assistant': 'ansigreen',
    'error': 'ansired',
    'info': 'ansiyellow',
})


class MrParkCLI:
    """Interactive CLI for MrPark agent."""

    def __init__(self):
        """Initialize CLI."""
        self.agent = None
        self.session = None
        self.running = False
        self.current_business_id = None  # Track selected MrCall assistant
        self.starchat = None  # Store StarChat client reference
        self.memory = None  # ReasoningBank memory system

        # Initialize history file
        history_file = Path.home() / ".mrpark_history"
        self.history = FileHistory(str(history_file))

    async def initialize(self):
        """Initialize agent and all components."""
        print("🏗️  Initializing MrPark...")

        # Validate configuration
        if not settings.anthropic_api_key:
            print("❌ Error: ANTHROPIC_API_KEY not set in .env file")
            sys.exit(1)

        if not settings.starchat_password:
            print("❌ Error: STARCHAT_PASSWORD not set in .env file")
            sys.exit(1)

        # Initialize components
        try:
            # StarChat client
            self.starchat = StarChatClient(
                base_url=settings.starchat_api_url,
                username=settings.starchat_username,
                password=settings.starchat_password,
                realm="default",
            )

            # Set default business_id from config if available
            if settings.starchat_business_id:
                self.current_business_id = settings.starchat_business_id

            # Gmail client
            gmail = GmailClient(
                credentials_path=settings.google_credentials_path,
                token_dir=settings.google_token_path,
            )

            # Google Calendar client
            calendar = GoogleCalendarClient(
                credentials_path=settings.google_credentials_path,
                token_dir=settings.google_token_path,
                calendar_id=settings.calendar_id,
            )

            # Try to authenticate Google services silently (using existing tokens)
            try:
                # Check if tokens exist
                from pathlib import Path
                token_path = Path(settings.google_token_path) / "token.pickle"
                if token_path.exists():
                    gmail.authenticate()
                    print("✅ Google services authenticated (Gmail, Calendar)")
                else:
                    print("⚠️  Google authentication needed")
                    print("   Chiedi a MrPark di rinnovare i permessi quando sei pronto")
            except Exception as e:
                print(f"⚠️  Google authentication needed: {e}")
                print("   Chiedi a MrPark di rinnovare i permessi quando sei pronto")

            # Cache
            cache = JSONCache(
                cache_dir=settings.cache_dir,
                ttl_days=settings.cache_ttl_days,
            )

            # Email sync manager (batch mode - 30 days fixed)
            email_sync = EmailSyncManager(
                gmail_client=gmail,
                cache_dir=settings.cache_dir + "/emails",
                anthropic_api_key=settings.anthropic_api_key,
                days_back=30,  # Fixed: 1 month initial sync
            )

            # Pipedrive CRM client (optional)
            pipedrive = None
            if settings.pipedrive_api_token:
                try:
                    pipedrive = PipedriveClient(api_token=settings.pipedrive_api_token)
                    print("✅ Pipedrive CRM connected")
                except Exception as e:
                    print(f"⚠️  Pipedrive connection failed: {e}")
                    pipedrive = None

            # Task manager (person-centric view)
            my_emails_list = [email.strip() for email in settings.my_emails.split(',') if email.strip()]
            bot_emails_list = [email.strip() for email in settings.bot_emails.split(',') if email.strip()]
            task_manager = TaskManager(
                email_sync_manager=email_sync,
                starchat_client=self.starchat,
                anthropic_api_key=settings.anthropic_api_key,
                my_emails=my_emails_list,
                bot_emails=bot_emails_list,
                cache_dir=settings.cache_dir
            )
            print(f"✅ Task Manager initialized ({len(my_emails_list)} my_emails, {len(bot_emails_list)} bot_emails patterns)")

            # Initialize ReasoningBank memory system
            # TODO: make user_id configurable (for multi-user support)
            self.memory = ReasoningBankMemory(user_id="mario", cache_dir=settings.cache_dir)
            print(f"✅ Memory system initialized ({len(self.memory._memory['corrections'])} corrections learned)")

            # Initialize tools
            # Use Gmail-only tool for now (StarChat endpoints need configuration)
            class GmailSearchTool(Tool):
                """Gmail search tool for contact enrichment."""
                def __init__(self, gmail_client):
                    super().__init__(
                        name="search_gmail",
                        description="Search Gmail for emails from or to a contact to understand relationship"
                    )
                    self.gmail = gmail_client

                async def execute(self, email: str, max_results: int = 20):
                    try:
                        query = f"from:{email} OR to:{email}"
                        messages = self.gmail.search_messages(query, max_results)
                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={
                                "email": email,
                                "message_count": len(messages),
                                "messages": [{
                                    "from": msg["from"],
                                    "to": msg["to"],
                                    "subject": msg["subject"],
                                    "date": msg["date"],
                                    "snippet": msg["snippet"][:200]
                                } for msg in messages[:10]]
                            },
                            message=f"Found {len(messages)} email exchanges"
                        )
                    except Exception as e:
                        return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Search Gmail history for emails from or to a specific email address. Use this to understand the relationship, communication history, and context with a contact.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "email": {
                                    "type": "string",
                                    "description": "Email address to search for"
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Maximum results (default 20)",
                                    "default": 20
                                }
                            },
                            "required": ["email"]
                        }
                    }

            # Create Gmail draft tool
            class CreateDraftTool(Tool):
                """Create a Gmail draft."""
                def __init__(self, gmail_client):
                    super().__init__(
                        name="create_gmail_draft",
                        description="Create a draft email in Gmail that the user can review and send later"
                    )
                    self.gmail = gmail_client

                async def execute(self, to: str, subject: str, body: str, in_reply_to: str = None, references: str = None, thread_id: str = None):
                    try:
                        draft = self.gmail.create_draft(
                            to=to,
                            subject=subject,
                            body=body,
                            in_reply_to=in_reply_to,
                            references=references,
                            thread_id=thread_id
                        )

                        thread_info = " (in risposta al thread)" if in_reply_to else ""
                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"draft_id": draft.get('id')},
                            message=f"✅ Draft creata con successo{thread_info}!\n"
                                    f"📧 Destinatario: {to}\n"
                                    f"📝 Oggetto: {subject}\n\n"
                                    f"📄 Corpo del messaggio:\n"
                                    f"{'─' * 70}\n"
                                    f"{body}\n"
                                    f"{'─' * 70}\n\n"
                                    f"La draft è ora disponibile nella cartella Bozze di Gmail. "
                                    f"Puoi rivederla e inviarla quando vuoi."
                        )
                    except Exception as e:
                        logger.error(f"Failed to create draft: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore nella creazione della draft: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Create a draft email in Gmail. The draft will be saved in Gmail's Drafts folder for the user to review and send later. If this is a REPLY to an existing email, you MUST provide the in_reply_to and references headers from the original message to keep the draft in the same conversation thread.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "to": {
                                    "type": "string",
                                    "description": "Recipient email address"
                                },
                                "subject": {
                                    "type": "string",
                                    "description": "Email subject line"
                                },
                                "body": {
                                    "type": "string",
                                    "description": "Email body text (can include formatting)"
                                },
                                "in_reply_to": {
                                    "type": "string",
                                    "description": "Message-ID of the email being replied to (REQUIRED for replies to keep draft in thread). Find this in the original message headers."
                                },
                                "references": {
                                    "type": "string",
                                    "description": "References header from the original message (REQUIRED for replies to maintain conversation history). Copy this from the original message headers."
                                },
                                "thread_id": {
                                    "type": "string",
                                    "description": "Gmail thread ID from search_emails result (CRITICAL for replies). When replying, you MUST pass this to keep the draft in the conversation thread."
                                }
                            },
                            "required": ["to", "subject", "body"]
                        }
                    }

            # List Gmail drafts
            class ListDraftsTool(Tool):
                """List all Gmail drafts."""
                def __init__(self, gmail_client):
                    super().__init__(
                        name="list_gmail_drafts",
                        description="List all draft emails in Gmail"
                    )
                    self.gmail = gmail_client

                async def execute(self):
                    try:
                        drafts = self.gmail.list_drafts()

                        if not drafts:
                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data={"drafts": []},
                                message="📭 Nessuna bozza trovata in Gmail."
                            )

                        # Get details for each draft
                        draft_details = []
                        for draft in drafts[:20]:  # Limit to 20 most recent
                            draft_id = draft['id']
                            try:
                                details = self.gmail.get_draft(draft_id)
                                draft_details.append({
                                    'id': draft_id,
                                    'to': details['to'],
                                    'subject': details['subject'],
                                    'body_preview': details['body'][:100] + '...' if len(details['body']) > 100 else details['body']
                                })
                            except Exception as e:
                                logger.warning(f"Failed to get details for draft {draft_id}: {e}")
                                continue

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"drafts": draft_details},
                            message=f"📧 Trovate {len(draft_details)} bozze:\n\n" +
                                   "\n".join([
                                       f"**Draft {i+1}** (ID: {d['id']})\n"
                                       f"📧 A: {d['to']}\n"
                                       f"📝 Oggetto: {d['subject']}\n"
                                       f"Preview: {d['body_preview']}\n"
                                       for i, d in enumerate(draft_details)
                                   ])
                        )

                    except Exception as e:
                        logger.error(f"Failed to list drafts: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore nel recupero delle bozze: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "List all draft emails currently saved in Gmail. Returns draft IDs, recipients, subjects, and previews.",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }

            # Edit Gmail draft interactively with nano
            class EditDraftTool(Tool):
                """Edit a Gmail draft interactively with nano editor."""
                def __init__(self, gmail_client):
                    super().__init__(
                        name="edit_gmail_draft",
                        description="Open a Gmail draft in nano editor for manual editing"
                    )
                    self.gmail = gmail_client

                async def execute(self, draft_id: str):
                    import tempfile
                    import subprocess

                    try:
                        # Get draft content
                        draft = self.gmail.get_draft(draft_id)

                        # Create temp file with ONLY body (To/Subject are read-only)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                            temp_path = f.name
                            # Write header as comments (read-only info)
                            f.write(f"# DRAFT METADATA (DO NOT EDIT)\n")
                            f.write(f"# To: {draft['to']}\n")
                            f.write(f"# Subject: {draft['subject']}\n")
                            f.write(f"#\n")
                            f.write(f"# Edit the message body below:\n")
                            f.write(f"# ==========================================\n\n")
                            # Only the body is editable
                            f.write(draft['body'])

                        # Open nano
                        subprocess.run(['nano', temp_path], check=True)

                        # Read edited content
                        with open(temp_path, 'r') as f:
                            content = f.read()

                        # Extract only non-comment lines (body content)
                        lines = content.split('\n')
                        body_lines = []

                        for line in lines:
                            # Skip comment lines (read-only header)
                            if line.startswith('#'):
                                continue
                            body_lines.append(line)

                        # Join body (preserve all content after comments)
                        body = '\n'.join(body_lines).strip()

                        # Update draft - ONLY update body, keep To/Subject unchanged
                        self.gmail.update_draft(
                            draft_id=draft_id,
                            to=None,  # None = keep existing
                            subject=None,  # None = keep existing
                            body=body
                        )

                        # Clean up temp file
                        import os
                        os.unlink(temp_path)

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"draft_id": draft_id},
                            message=f"✅ Draft modificata manualmente e salvata!\n"
                                    f"📧 Destinatario: {draft['to']}\n"
                                    f"📝 Oggetto: {draft['subject']}"
                        )

                    except subprocess.CalledProcessError:
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error="Editing cancellato dall'utente"
                        )
                    except Exception as e:
                        logger.error(f"Failed to edit draft: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore nell'editing della draft: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Open a Gmail draft in nano text editor for manual editing by the user. The draft content will be opened in nano, user can modify it, and changes will be saved back to Gmail when nano is closed.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "draft_id": {
                                    "type": "string",
                                    "description": "Gmail draft ID to edit"
                                }
                            },
                            "required": ["draft_id"]
                        }
                    }

            # Update Gmail draft tool
            class UpdateDraftTool(Tool):
                """Update an existing Gmail draft."""
                def __init__(self, gmail_client):
                    super().__init__(
                        name="update_gmail_draft",
                        description="Update an existing Gmail draft with new content"
                    )
                    self.gmail = gmail_client

                async def execute(self, draft_id: str, to: str = None, subject: str = None, body: str = None):
                    try:
                        updated_draft = self.gmail.update_draft(
                            draft_id=draft_id,
                            to=to,
                            subject=subject,
                            body=body
                        )

                        # Build update summary
                        updates = []
                        if to:
                            updates.append(f"📧 Destinatario: {to}")
                        if subject:
                            updates.append(f"📝 Oggetto: {subject}")
                        if body:
                            updates.append(f"✍️  Corpo: aggiornato")

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"draft_id": updated_draft.get('id')},
                            message=f"✅ Draft aggiornata con successo!\n" + "\n".join(updates) + "\n\n"
                                    f"La draft aggiornata è disponibile nella cartella Bozze di Gmail."
                        )
                    except Exception as e:
                        logger.error(f"Failed to update draft: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore nell'aggiornamento della draft: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Update an existing Gmail draft. You can update the recipient, subject, body, or any combination. Fields not provided will remain unchanged.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "draft_id": {
                                    "type": "string",
                                    "description": "Gmail draft ID (returned when draft was created)"
                                },
                                "to": {
                                    "type": "string",
                                    "description": "New recipient email address (optional)"
                                },
                                "subject": {
                                    "type": "string",
                                    "description": "New email subject (optional)"
                                },
                                "body": {
                                    "type": "string",
                                    "description": "New email body text (optional)"
                                }
                            },
                            "required": ["draft_id"]
                        }
                    }

            # Send Gmail draft tool
            class SendDraftTool(Tool):
                """Send a Gmail draft."""
                def __init__(self, gmail_client):
                    super().__init__(
                        name="send_gmail_draft",
                        description="Send a Gmail draft email"
                    )
                    self.gmail = gmail_client

                async def execute(self, draft_id: str):
                    try:
                        # Get draft details before sending
                        draft = self.gmail.get_draft(draft_id)

                        # Send the draft
                        sent_message = self.gmail.send_draft(draft_id)

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"message_id": sent_message.get('id')},
                            message=f"📧 Email inviata con successo!\n"
                                    f"✉️  Destinatario: {draft['to']}\n"
                                    f"📝 Oggetto: {draft['subject']}\n\n"
                                    f"L'email è stata inviata e la bozza è stata rimossa dalla cartella Bozze."
                        )
                    except Exception as e:
                        logger.error(f"Failed to send draft: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore nell'invio dell'email: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Send a Gmail draft. The draft will be sent immediately and removed from the Drafts folder. IMPORTANT: Always confirm with the user before sending.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "draft_id": {
                                    "type": "string",
                                    "description": "Gmail draft ID to send (returned when draft was created)"
                                }
                            },
                            "required": ["draft_id"]
                        }
                    }

            # Google authentication refresh tool
            class RefreshGoogleAuthTool(Tool):
                """Refresh Google OAuth authentication."""
                def __init__(self, gmail_client, calendar_client):
                    super().__init__(
                        name="refresh_google_auth",
                        description="Refresh Google OAuth permissions for Gmail and Calendar"
                    )
                    self.gmail = gmail_client
                    self.calendar = calendar_client

                async def execute(self):
                    try:
                        # Delete existing tokens to force re-authentication
                        import shutil
                        from pathlib import Path

                        token_dir = Path(settings.google_token_path)
                        if token_dir.exists():
                            shutil.rmtree(token_dir)
                            token_dir.mkdir(parents=True, exist_ok=True)

                        # Re-authenticate
                        logger.info("🔐 Opening browser for Google authentication...")
                        print("\n🔐 Sto aprendo una finestra del browser per l'autenticazione Google...")
                        print("   Autorizza l'accesso a Gmail e Calendar nella finestra che si aprirà.\n")

                        self.gmail.authenticate()

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"authenticated": True},
                            message="Autenticazione Google completata con successo! Ora ho accesso a Gmail e Calendar."
                        )
                    except Exception as e:
                        logger.error(f"Failed to refresh Google auth: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore durante l'autenticazione: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Rinnova i permessi Google (Gmail e Calendar). Apre una finestra del browser per l'autenticazione OAuth. Usa questo quando l'utente chiede di rinnovare i permessi o quando ricevi errori di autenticazione.",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }

            # Email sync and search tools
            class SyncEmailsTool(Tool):
                """Sync emails from Gmail and cache with intelligent analysis."""
                def __init__(self, email_sync_manager):
                    super().__init__(
                        name="sync_emails",
                        description="Synchronize emails from Gmail, analyze them with AI, and cache for quick access"
                    )
                    self.email_sync = email_sync_manager

                async def execute(self, days_back: Optional[int] = None, force_full: bool = False):
                    try:
                        logger.info("Starting email sync...")
                        results = self.email_sync.sync_emails(force_full=force_full, days_back=days_back)

                        days_msg = f" (ultimi {days_back} giorni)" if days_back else ""
                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data=results,
                            message=f"Sincronizzate {results['total_messages']} email in {results['total_threads']} conversazioni{days_msg}. Nuove: {results['new_threads']}, Aggiornate: {results['updated_threads']}"
                        )
                    except Exception as e:
                        logger.error(f"Email sync failed: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore durante la sincronizzazione: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Sincronizza le email da Gmail in modalità BATCH (operazione lunga, ~15-30 minuti). Analizza con AI (riassunto, status open/closed, azioni richieste) e salva nella cache locale. Prima sincronizzazione: fisso 30 giorni (1 mese). NOTA: In futuro useremo notifiche real-time di Gmail.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "days_back": {
                                    "type": "integer",
                                    "description": "Numero di giorni da sincronizzare (default: 30 giorni fisso). Usa solo per testing."
                                },
                                "force_full": {
                                    "type": "boolean",
                                    "description": "Forza nuova sincronizzazione completa ignorando cache esistente",
                                    "default": False
                                }
                            },
                            "required": []
                        }
                    }

            class SearchEmailsTool(Tool):
                """Search cached emails with filters."""
                def __init__(self, email_sync_manager):
                    super().__init__(
                        name="search_emails",
                        description="Search cached emails with intelligent filters"
                    )
                    self.email_sync = email_sync_manager

                async def execute(
                    self,
                    query: Optional[str] = None,
                    open_only: bool = False,
                    expected_action: Optional[str] = None
                ):
                    try:
                        threads = self.email_sync.search_threads(
                            query=query,
                            open_only=open_only,
                            expected_action=expected_action
                        )

                        # Format results for display
                        results = []
                        for thread in threads[:20]:  # Limit to 20 results
                            last_email = thread.get("last_email", {})
                            results.append({
                                "subject": thread.get("subject"),
                                "participants": thread.get("participants"),
                                "summary": thread.get("summary"),
                                "open": thread.get("open"),
                                "expected_action": thread.get("expected_action"),
                                "date": last_email.get("date"),  # Real email date
                                "from": last_email.get("from"),  # Sender
                                "to": last_email.get("to"),  # Primary recipient
                                "cc": last_email.get("cc"),  # CC recipients
                                "body": last_email.get("body"),  # Full email body
                                # CRITICAL: Threading headers for replies
                                "message_id": last_email.get("message_id"),  # Message-ID header
                                "in_reply_to": last_email.get("in_reply_to"),  # In-Reply-To header
                                "references": last_email.get("references"),  # References header
                                "thread_id": thread.get("thread_id"),  # Gmail thread ID
                                "last_updated": thread.get("last_updated")  # Cache timestamp
                            })

                        message = f"Trovate {len(threads)} conversazioni"
                        if open_only:
                            message += " aperte"
                        if expected_action:
                            action_ita = "risposta" if expected_action == "answer" else "reminder"
                            message += f" che richiedono {action_ita}"

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"threads": results, "total": len(threads)},
                            message=message
                        )
                    except Exception as e:
                        logger.error(f"Email search failed: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore durante la ricerca: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Cerca nelle email cachate. Puoi filtrare per parole chiave, solo email aperte, o per azione richiesta (answer/reminder). Usa questo per trovare email specifiche o vedere cosa richiede azione. IMPORTANT: Results include threading headers (message_id, in_reply_to, references, thread_id) needed to create draft replies that stay in the conversation thread.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Parole chiave da cercare (cerca in oggetto e riassunto)"
                                },
                                "open_only": {
                                    "type": "boolean",
                                    "description": "Solo conversazioni aperte che richiedono azione",
                                    "default": False
                                },
                                "expected_action": {
                                    "type": "string",
                                    "enum": ["answer", "reminder"],
                                    "description": "Filtra per tipo di azione: 'answer' (devo rispondere) o 'reminder' (devo fare reminder)"
                                }
                            },
                            "required": []
                        }
                    }

            class CloseEmailThreadTool(Tool):
                """Mark email threads as closed/resolved."""
                def __init__(self, email_sync_manager):
                    super().__init__(
                        name="close_email_threads",
                        description="Mark email threads as closed/resolved (no action needed)"
                    )
                    self.email_sync = email_sync_manager

                async def execute(self, subjects: list):
                    """Close threads by subject keywords.

                    Args:
                        subjects: List of subject keywords to match
                    """
                    try:
                        results = self.email_sync.mark_threads_closed_by_subject(subjects)

                        if results['closed_count'] == 0:
                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data=results,
                                message="Nessuna conversazione trovata con questi oggetti"
                            )

                        # Format message
                        threads_list = '\n'.join([
                            f"  - {t['subject']}"
                            for t in results['threads'][:5]
                        ])

                        message = f"✅ Chiuse {results['closed_count']} conversazioni:\n{threads_list}"
                        if results['closed_count'] > 5:
                            message += f"\n  ... e altre {results['closed_count'] - 5}"

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data=results,
                            message=message
                        )
                    except Exception as e:
                        logger.error(f"Failed to close threads: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=str(e)
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Chiudi conversazioni email come risolte/gestite. Cerca per parole chiave nell'oggetto e marca come 'closed'. Usa quando l'utente dice 'ho gestito', 'fatto', 'risolto', ecc. Accetta lista di parole chiave negli oggetti delle email.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "subjects": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Lista di parole chiave negli oggetti email (es: ['Francesco Luzzana', 'WATI', 'HB SRL'])"
                                }
                            },
                            "required": ["subjects"]
                        }
                    }

            class EmailStatsTool(Tool):
                """Get email cache statistics."""
                def __init__(self, email_sync_manager):
                    super().__init__(
                        name="email_stats",
                        description="Get statistics about cached emails"
                    )
                    self.email_sync = email_sync_manager

                async def execute(self):
                    try:
                        stats = self.email_sync.get_stats()

                        message = f"Email cache: {stats['total_threads']} conversazioni totali. "
                        message += f"Aperte: {stats['open_threads']} (da rispondere: {stats['need_answer']}, reminder: {stats['need_reminder']}). "
                        message += f"Ultima sincronizzazione: {stats['last_sync'] or 'mai'}"

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data=stats,
                            message=message
                        )
                    except Exception as e:
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=str(e)
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Mostra statistiche sulle email cachate: quante conversazioni, quante aperte, quante richiedono risposta/reminder. Usa questo quando l'utente chiede 'cosa devo fare oggi?' o 'ho email da leggere?'",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }

            # Task management tools
            class BuildTasksTool(Tool):
                """Build tasks.json from threads.json."""
                def __init__(self, task_manager):
                    super().__init__(
                        name="build_tasks",
                        description="Build person-centric tasks from email threads"
                    )
                    self.task_manager = task_manager

                async def execute(self, force_rebuild: bool = False):
                    try:
                        logger.info("Building tasks from threads...")
                        results = self.task_manager.build_tasks_from_threads(force_rebuild=force_rebuild)

                        if results.get('cached'):
                            message = f"Tasks già in cache: {results['task_count']} tasks. Usa force_rebuild=true per ricostruire."
                        else:
                            message = f"✅ Tasks creati: {results['tasks_created']} su {results['total_contacts']} contatti. "
                            if results['tasks_failed'] > 0:
                                message += f"Falliti: {results['tasks_failed']}. "
                            message += f"Ultimo build: {results['last_build']}"

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data=results,
                            message=message
                        )
                    except Exception as e:
                        logger.error(f"Build tasks failed: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore durante build tasks: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Costruisce tasks.json aggregando tutti i thread per persona. Operazione lenta (usa Sonnet), eseguila periodicamente. Se già esiste cache, non ricostruisce a meno di force_rebuild.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "force_rebuild": {
                                    "type": "boolean",
                                    "description": "Forza rebuild anche se cache esiste",
                                    "default": False
                                }
                            },
                            "required": []
                        }
                    }

            class GetContactTaskTool(Tool):
                """Get task for specific contact."""
                def __init__(self, task_manager):
                    super().__init__(
                        name="get_contact_task",
                        description="Get task view for a specific contact by email"
                    )
                    self.task_manager = task_manager

                async def execute(self, contact_email: str):
                    try:
                        logger.info(f"Getting task for {contact_email}...")
                        task = self.task_manager.get_task_by_contact_email(contact_email)

                        if not task:
                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data=None,
                                message=f"Nessun task trovato per {contact_email}"
                            )

                        message = f"📋 **Task: {task['contact_name']}**\n\n"
                        message += f"Email: {task['contact_email']}\n"
                        if task.get('contact_phone'):
                            message += f"Phone: {task['contact_phone']}\n"
                        message += f"Status: {task['status']}\n"
                        message += f"Priority: {task['score']}/10\n"
                        message += f"Threads: {task['thread_count']}\n\n"
                        message += f"**View:**\n{task['view']}\n\n"
                        message += f"**Action:**\n{task['action']}"

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data=task,
                            message=message
                        )
                    except Exception as e:
                        logger.error(f"Get contact task failed: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore nel recupero task: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Ottieni task completo per un contatto specifico (rianalizza i thread on-demand se necessario). Usa quando l'utente chiede 'status di [persona]' o 'cosa devo fare con [persona]'.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "contact_email": {
                                    "type": "string",
                                    "description": "Email del contatto"
                                }
                            },
                            "required": ["contact_email"]
                        }
                    }

            class SearchTasksTool(Tool):
                """Search tasks with filters."""
                def __init__(self, task_manager):
                    super().__init__(
                        name="search_tasks",
                        description="Search and filter tasks by status, priority, or query"
                    )
                    self.task_manager = task_manager

                async def execute(
                    self,
                    status: Optional[str] = None,
                    min_score: Optional[int] = None,
                    query: Optional[str] = None
                ):
                    try:
                        tasks = self.task_manager.search_tasks(
                            status=status,
                            min_score=min_score,
                            query=query
                        )

                        if not tasks:
                            message = "Nessun task trovato"
                            if status:
                                message += f" con status '{status}'"
                            if min_score:
                                message += f" e priority >={min_score}"
                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data={"tasks": []},
                                message=message
                            )

                        # Format results
                        results = []
                        for task in tasks[:20]:  # Limit to 20
                            results.append({
                                "contact_name": task.get("contact_name"),
                                "contact_email": task.get("contact_email"),
                                "status": task.get("status"),
                                "score": task.get("score"),
                                "action": task.get("action"),
                                "view": task.get("view")[:200] + "..." if len(task.get("view", "")) > 200 else task.get("view"),
                                "thread_count": task.get("thread_count")
                            })

                        message = f"Trovati {len(tasks)} tasks"
                        if status:
                            message += f" (status: {status})"
                        if min_score:
                            message += f" (score >= {min_score})"

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={"tasks": results, "total": len(tasks)},
                            message=message
                        )
                    except Exception as e:
                        logger.error(f"Search tasks failed: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Errore nella ricerca tasks: {str(e)}"
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Cerca tasks con filtri. Usa per 'mostra task urgenti' (min_score=8), 'task aperti' (status=open), 'cosa devo fare oggi?' (status=open, min_score=7).",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "description": "Filter by status: open, closed, waiting"
                                },
                                "min_score": {
                                    "type": "integer",
                                    "description": "Minimum priority score (1-10)"
                                },
                                "query": {
                                    "type": "string",
                                    "description": "Search in name, email, view"
                                }
                            },
                            "required": []
                        }
                    }

            class TaskStatsTool(Tool):
                """Get task statistics."""
                def __init__(self, task_manager):
                    super().__init__(
                        name="task_stats",
                        description="Get statistics about tasks"
                    )
                    self.task_manager = task_manager

                async def execute(self):
                    try:
                        stats = self.task_manager.get_stats()

                        message = f"Tasks: {stats['total_tasks']} totali. "
                        message += f"Aperti: {stats['open_tasks']}, "
                        message += f"Urgenti (score>=8): {stats['urgent_tasks']}. "
                        message += f"Average score: {stats['average_score']:.1f}/10. "
                        message += f"Ultimo build: {stats['last_build'] or 'mai'}"

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data=stats,
                            message=message
                        )
                    except Exception as e:
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=str(e)
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Mostra statistiche sui tasks: quanti totali, aperti, urgenti, average priority. Usa quando l'utente chiede 'overview tasks' o 'situazione generale'.",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }

            # Add web search tool
            web_search = WebSearchTool(settings.anthropic_api_key)

            # Add save contact tool (needs access to CLI instance for business_id)
            class SaveContactTool(Tool):
                """Tool to save enriched contact to MrCall assistant."""
                def __init__(self, starchat_client, cli_instance):
                    super().__init__(
                        name="save_contact",
                        description="Save enriched contact data to the selected MrCall assistant's contact list"
                    )
                    self.starchat = starchat_client
                    self.cli = cli_instance

                async def execute(
                    self,
                    email: str,
                    name: Optional[str] = None,
                    phone: Optional[str] = None,
                    company: Optional[str] = None,
                    notes: Optional[str] = None,
                    relationship_type: str = "unknown",
                    priority_score: str = "5",
                ):
                    # Check if business is selected
                    if not self.cli.current_business_id:
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error="No assistant selected. Use /business <id> to select one first."
                        )

                    try:
                        # Prepare contact data matching CrmContact schema
                        contact_data = {
                            "provider": "2hb"  # Required value for StarChat database constraint
                        }

                        # Email must be a list of CrmContactEmail objects
                        if email:
                            contact_data["emails"] = [{"address": email}]

                        # Phone must be a list of CrmContactPhone objects
                        if phone:
                            contact_data["phones"] = [{"number": phone}]

                        # Name must be a CrmContactName object
                        if name:
                            # Try to parse name into first/last
                            name_parts = name.strip().split(None, 1)
                            name_obj = {
                                "first": name_parts[0] if name_parts else name
                            }
                            if len(name_parts) > 1:
                                name_obj["last"] = name_parts[1]

                            contact_data["name"] = name_obj
                            contact_data["displayName"] = name

                        # Organizations if company provided
                        if company:
                            contact_data["organizations"] = [{"company": company}]

                        # Notes
                        if notes:
                            contact_data["notes"] = [{"note": notes}]

                        # Prepare variables
                        variables = {
                            "RELATIONSHIP_TYPE": relationship_type,
                            "PRIORITY_SCORE": priority_score,
                            "LAST_ENRICHED": datetime.now().isoformat(),
                            "ENRICHMENT_SOURCES": json.dumps(["gmail", "web_search", "mrpark"]),
                            "EMAIL_ADDRESS": email,  # Store for searchability (workaround for API limitation)
                        }

                        if phone:
                            variables["PHONE_NUMBER"] = phone  # Store for searchability

                        if company:
                            variables["COMPANY_INFO"] = company
                        if notes:
                            variables["NOTES"] = notes

                        contact_data["variables"] = variables

                        # Check if contact already exists (proper upsert logic)
                        logger.info(f"Checking for existing contact with email={email}, business_id={self.cli.current_business_id}")
                        existing_contacts = await self.starchat.search_contacts(
                            email=email,
                            business_id=self.cli.current_business_id
                        )
                        logger.info(f"Found {len(existing_contacts)} existing contacts")

                        if existing_contacts:
                            # Update existing contact - use ID from first match
                            existing_id = existing_contacts[0].get("id")
                            logger.info(f"Contact exists (id: {existing_id}), updating instead of creating")
                            contact_data["id"] = existing_id

                            # Merge variables with existing ones to preserve other fields
                            if "variables" in existing_contacts[0]:
                                merged_vars = existing_contacts[0]["variables"].copy()
                                merged_vars.update(contact_data["variables"])
                                contact_data["variables"] = merged_vars
                        else:
                            logger.info(f"Contact does not exist, creating new")

                        # Save to StarChat (create if new, update if has id)
                        result = await self.starchat.create_contact(
                            contact_data,
                            business_id=self.cli.current_business_id
                        )

                        action = "updated" if existing_contacts else "created"
                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data=result,
                            message=f"Contact {action} in assistant: {self.cli.current_business_id}"
                        )

                    except Exception as e:
                        logger.error(f"Failed to save contact: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=str(e)
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "Save enriched contact information to the selected MrCall assistant's contact list. IMPORTANT: Always ask the user for explicit approval before saving. Say something like: 'Would you like me to save this contact to your assistant?'",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "email": {
                                    "type": "string",
                                    "description": "Contact email address"
                                },
                                "name": {
                                    "type": "string",
                                    "description": "Contact name"
                                },
                                "phone": {
                                    "type": "string",
                                    "description": "Contact phone number"
                                },
                                "company": {
                                    "type": "string",
                                    "description": "Company name and info"
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "Summary notes about the contact"
                                },
                                "relationship_type": {
                                    "type": "string",
                                    "description": "Relationship type: customer, lead, partner, prospect, unknown",
                                    "default": "unknown"
                                },
                                "priority_score": {
                                    "type": "string",
                                    "description": "Priority score 1-10",
                                    "default": "5"
                                }
                            },
                            "required": ["email"]
                        }
                    }

            save_contact_tool = SaveContactTool(self.starchat, self)

            # Add get contact tool
            class GetContactTool(Tool):
                """Tool to retrieve saved contact from MrCall assistant."""
                def __init__(self, starchat_client, cli_instance):
                    super().__init__(
                        name="get_contact",
                        description="Retrieve a saved contact from the selected MrCall assistant's contact list"
                    )
                    self.starchat = starchat_client
                    self.cli = cli_instance

                async def execute(
                    self,
                    email: Optional[str] = None,
                    contact_id: Optional[str] = None,
                ):
                    # Check if business is selected
                    if not self.cli.current_business_id:
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error="No assistant selected. Use /business <id> to select one first."
                        )

                    try:
                        # Get by contact_id if provided
                        if contact_id:
                            contact = await self.starchat.get_contact(contact_id)
                            if not contact:
                                return ToolResult(
                                    status=ToolStatus.ERROR,
                                    data=None,
                                    error=f"Contact not found: {contact_id}"
                                )
                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data=contact,
                                message=f"Retrieved contact: {contact_id}"
                            )

                        # Search by email if provided
                        if email:
                            logger.info(f"🔍 Calling search_contacts with business_id={self.cli.current_business_id}")
                            contacts = await self.starchat.search_contacts(
                                email=email,
                                business_id=self.cli.current_business_id
                            )
                            if not contacts:
                                return ToolResult(
                                    status=ToolStatus.SUCCESS,
                                    data=None,
                                    message=f"No contact found with email: {email}"
                                )

                            # Get first match (most recent)
                            first_contact = contacts[0]
                            count = len(contacts)

                            # Check if contact is fresh (< 24 hours old)
                            logger.info(f"DEBUG: first_contact type: {type(first_contact)}")
                            logger.info(f"DEBUG: has 'variables': {'variables' in first_contact if isinstance(first_contact, dict) else 'N/A'}")

                            if isinstance(first_contact, dict) and "variables" in first_contact:
                                logger.info(f"DEBUG: variables keys: {list(first_contact['variables'].keys())}")
                                last_enriched = first_contact["variables"].get("LAST_ENRICHED")
                                logger.info(f"DEBUG: LAST_ENRICHED value: {last_enriched}")
                                if last_enriched:
                                    try:
                                        from datetime import datetime, timedelta
                                        enriched_time = datetime.fromisoformat(last_enriched)
                                        age_hours = (datetime.now() - enriched_time).total_seconds() / 3600

                                        if age_hours < 24:
                                            # Contact is fresh - add freshness info to message
                                            if count > 1:
                                                logger.warning(f"Found {count} duplicate contacts for {email}, using most recent")
                                            return ToolResult(
                                                status=ToolStatus.SUCCESS,
                                                data=first_contact,
                                                message=f"✅ Found fresh contact (enriched {age_hours:.1f} hours ago). No need to re-enrich from Gmail/web."
                                            )
                                    except (ValueError, TypeError):
                                        pass  # Failed to parse, continue normally

                            # Return first contact (or all if needed for other purposes)
                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data=first_contact if count == 1 else contacts,
                                message=f"Found {count} contact(s) matching email: {email}"
                            )

                        # No search criteria provided
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error="Must provide either email or contact_id to search"
                        )

                    except Exception as e:
                        logger.error(f"Failed to retrieve contact: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=str(e)
                        )

                def get_schema(self):
                    return {
                        "name": self.name,
                        "description": "⚠️ ALWAYS USE THIS FIRST before searching Gmail or web! Retrieves contact from StarChat CRM and checks if data is fresh (< 24h). If contact is fresh, DO NOT call search_gmail or web_search_contact. Only search if contact is not found or is stale.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "email": {
                                    "type": "string",
                                    "description": "Email address to search for"
                                },
                                "contact_id": {
                                    "type": "string",
                                    "description": "Contact ID to retrieve (if known)"
                                }
                            }
                        }
                    }

            get_contact_tool = GetContactTool(self.starchat, self)

            # Add list all contacts tool (with business_id auto-detection)
            class ListContactsWithBusinessIDTool(Tool):
                """Wrapper for ListAllContactsTool that uses current business_id."""
                def __init__(self, starchat_client, cli_instance):
                    super().__init__(
                        name="list_all_contacts",
                        description="List all contacts associated with your selected business in StarChat"
                    )
                    self.starchat = starchat_client
                    self.cli = cli_instance

                async def execute(self, limit: Optional[int] = None) -> ToolResult:
                    """Execute contact listing using current business_id."""
                    # Check if business is selected
                    if not self.cli.current_business_id:
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error="No assistant selected. Use /business <id> to select one first."
                        )

                    try:
                        logger.info(f"Listing all contacts for business: {self.cli.current_business_id}")

                        contacts = await self.starchat.search_contacts_paginated(
                            business_id=self.cli.current_business_id,
                            page_size=100,
                            max_total=limit
                        )

                        # Group by relationship type for better summary
                        by_relationship = {}
                        for contact in contacts:
                            vars = contact.get('variables', {})
                            rel_type = vars.get('RELATIONSHIP_TYPE', 'unknown')
                            if rel_type not in by_relationship:
                                by_relationship[rel_type] = []
                            by_relationship[rel_type].append(contact)

                        return ToolResult(
                            status=ToolStatus.SUCCESS,
                            data={
                                "total_contacts": len(contacts),
                                "by_relationship": {k: len(v) for k, v in by_relationship.items()},
                                "contacts": contacts
                            },
                            message=f"Found {len(contacts)} total contacts: {', '.join(f'{k}={len(v)}' for k, v in sorted(by_relationship.items(), key=lambda x: len(x[1]), reverse=True))}"
                        )

                    except Exception as e:
                        logger.error(f"Failed to list contacts: {e}")
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=str(e)
                        )

                def get_schema(self) -> Dict[str, Any]:
                    """Get Anthropic function schema."""
                    return {
                        "name": self.name,
                        "description": self.description + ". Automatically uses the selected business from /business command. Returns all contacts with their relationship types and metadata.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum total results to fetch (optional, default=fetch all)"
                                }
                            },
                            "required": []
                        }
                    }

            list_contacts_tool = ListContactsWithBusinessIDTool(self.starchat, self)

            # Pipedrive CRM tools
            pipedrive_tools = []
            if pipedrive:
                class SearchPipedrivePersonTool(Tool):
                    """Search Pipedrive person by email."""
                    def __init__(self, pipedrive_client):
                        super().__init__(
                            name="search_pipedrive_person",
                            description="Search for a person in Pipedrive CRM by email address"
                        )
                        self.pipedrive = pipedrive_client

                    async def execute(self, email: str):
                        try:
                            person = self.pipedrive.search_person_by_email(email)

                            if not person:
                                return ToolResult(
                                    status=ToolStatus.SUCCESS,
                                    data={"found": False},
                                    message=f"Nessuna persona trovata in Pipedrive per: {email}"
                                )

                            # Extract emails and phones safely
                            emails = person.get("emails", [])
                            if isinstance(emails, str):
                                emails = [emails]
                            else:
                                emails = [e.get("value") if isinstance(e, dict) else e for e in emails]

                            phones = person.get("phones", [])
                            if isinstance(phones, str):
                                phones = [phones]
                            else:
                                phones = [p.get("value") if isinstance(p, dict) else p for p in phones]

                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data={
                                    "found": True,
                                    "person": {
                                        "id": person.get("id"),
                                        "name": person.get("name"),
                                        "org_name": person.get("org_name"),
                                        "owner_name": person.get("owner_name"),
                                        "emails": emails,
                                        "phones": phones,
                                        "open_deals_count": person.get("open_deals_count", 0),
                                        "closed_deals_count": person.get("closed_deals_count", 0),
                                    }
                                },
                                message=f"✅ Trovato in Pipedrive: {person.get('name')}\n"
                                        f"📧 Email: {email}\n"
                                        f"🏢 Azienda: {person.get('org_name', 'N/A')}\n"
                                        f"📊 Deal: {person.get('open_deals_count', 0)} aperti, "
                                        f"{person.get('closed_deals_count', 0)} chiusi"
                            )
                        except Exception as e:
                            return ToolResult(
                                status=ToolStatus.ERROR,
                                data=None,
                                error=f"Errore ricerca Pipedrive: {str(e)}"
                            )

                    def get_schema(self):
                        return {
                            "name": self.name,
                            "description": "Search for a person in Pipedrive CRM by email address. Returns person details including name, company, deal counts, and contact information.",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "email": {
                                        "type": "string",
                                        "description": "Email address to search"
                                    }
                                },
                                "required": ["email"]
                            }
                        }

                class GetPipedrivePersonDealsTool(Tool):
                    """Get deals for a Pipedrive person with filters."""
                    def __init__(self, pipedrive_client):
                        super().__init__(
                            name="get_pipedrive_deals",
                            description="Get deals for a person in Pipedrive with optional pipeline/stage filters"
                        )
                        self.pipedrive = pipedrive_client

                    async def execute(
                        self,
                        person_id: int,
                        status: str = "all_not_deleted",
                        pipeline_id: Optional[int] = None,
                        stage_id: Optional[int] = None
                    ):
                        try:
                            deals = self.pipedrive.get_person_deals(
                                person_id=person_id,
                                status=status,
                                pipeline_id=pipeline_id,
                                stage_id=stage_id
                            )

                            if not deals:
                                return ToolResult(
                                    status=ToolStatus.SUCCESS,
                                    data={"deals": [], "count": 0},
                                    message="Nessun deal trovato con i filtri specificati"
                                )

                            # Format deals for display
                            formatted_deals = []
                            for deal in deals:
                                formatted_deals.append({
                                    "id": deal.get("id"),
                                    "title": deal.get("title"),
                                    "value": deal.get("value"),
                                    "currency": deal.get("currency"),
                                    "status": deal.get("status"),
                                    "stage_name": deal.get("stage_name"),
                                    "pipeline_name": deal.get("pipeline_name"),
                                    "probability": deal.get("probability"),
                                    "expected_close_date": deal.get("expected_close_date"),
                                    "owner_name": deal.get("owner_name"),
                                })

                            message = f"✅ Trovati {len(deals)} deal"
                            if pipeline_id:
                                message += f" (pipeline ID: {pipeline_id})"
                            if stage_id:
                                message += f" (stage ID: {stage_id})"

                            return ToolResult(
                                status=ToolStatus.SUCCESS,
                                data={"deals": formatted_deals, "count": len(deals)},
                                message=message
                            )
                        except Exception as e:
                            return ToolResult(
                                status=ToolStatus.ERROR,
                                data=None,
                                error=f"Errore recupero deal: {str(e)}"
                            )

                    def get_schema(self):
                        return {
                            "name": self.name,
                            "description": "Get deals for a Pipedrive person. Can filter by status (open/won/lost), pipeline ID, or stage ID. Use this after finding a person to see their sales pipeline status.",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "person_id": {
                                        "type": "integer",
                                        "description": "Pipedrive person ID (from search_pipedrive_person)"
                                    },
                                    "status": {
                                        "type": "string",
                                        "description": "Deal status filter",
                                        "enum": ["open", "won", "lost", "deleted", "all_not_deleted"],
                                        "default": "all_not_deleted"
                                    },
                                    "pipeline_id": {
                                        "type": "integer",
                                        "description": "Filter by pipeline ID (optional)"
                                    },
                                    "stage_id": {
                                        "type": "integer",
                                        "description": "Filter by stage ID (optional)"
                                    }
                                },
                                "required": ["person_id"]
                            }
                        }

                pipedrive_tools = [
                    SearchPipedrivePersonTool(pipedrive),
                    GetPipedrivePersonDealsTool(pipedrive)
                ]

            tools = [
                GmailSearchTool(gmail),
                CreateDraftTool(gmail),
                ListDraftsTool(gmail),
                EditDraftTool(gmail),
                UpdateDraftTool(gmail),
                SendDraftTool(gmail),
                ListCalendarEventsTool(calendar),
                CreateCalendarEventTool(calendar),
                SearchCalendarEventsTool(calendar),
                UpdateCalendarEventTool(calendar),
                RefreshGoogleAuthTool(gmail, calendar),
                SyncEmailsTool(email_sync),
                SearchEmailsTool(email_sync),
                CloseEmailThreadTool(email_sync),
                EmailStatsTool(email_sync),
                BuildTasksTool(task_manager),
                GetContactTaskTool(task_manager),
                SearchTasksTool(task_manager),
                TaskStatsTool(task_manager),
                web_search,
                save_contact_tool,
                get_contact_tool,
                list_contacts_tool,
            ]

            # Add Pipedrive tools if available
            if pipedrive_tools:
                tools.extend(pipedrive_tools)

            # Model selector
            model_selector = ModelSelector(
                default_model=settings.default_model,
                classification_model=settings.classification_model,
                executive_model=settings.executive_model,
            )

            # Initialize agent
            self.agent = MrParkAgent(
                api_key=settings.anthropic_api_key,
                tools=tools,
                model_selector=model_selector,
                email_style_prompt=settings.email_style_prompt or None,
                memory_system=self.memory,
            )

            print("✅ MrPark initialized successfully")
            print()

        except Exception as e:
            print(f"❌ Failed to initialize MrPark: {e}")
            logger.exception("Initialization failed")
            sys.exit(1)

    def print_welcome(self):
        """Print welcome message."""
        print("=" * 60)
        print("🌟  MrPark - Email Intelligence Assistant")
        print("=" * 60)
        print()
        if self.current_business_id:
            print(f"📌 Current assistant: {self.current_business_id}")
        else:
            print("⚠️  No assistant selected - use /business <id> to select one")
        print()
        print("Commands:")
        print("  Type your message to interact with MrPark")
        print("  /help          - Show help")
        print("  /business <id> - Select which MrCall assistant to save contacts to")
        print("  /clear         - Clear conversation history")
        print("  /history       - Show conversation history")
        print("  /memory        - Manage behavioral memory (use /memory --help for details)")
        print("  /sync [days]   - Run morning sync (emails + calendar + gap analysis)")
        print("                   Examples: /sync (default 30 days), /sync 3 (last 3 days)")
        print("  /gaps          - Show relationship gaps briefing")
        print("  /cache         - Inspect and manage cache (use /cache --help for details)")
        print("  /quit          - Exit MrPark")
        print()

    async def run(self):
        """Run interactive CLI loop."""
        await self.initialize()
        self.print_welcome()

        # Create prompt session
        self.session = PromptSession(history=self.history)
        self.running = True

        while self.running:
            try:
                # Get user input
                user_input = await self.session.prompt_async(
                    "You: ",
                    style=cli_style,
                )

                # Handle commands
                if user_input.startswith("/"):
                    await self.handle_command(user_input)
                    continue

                # Process with agent
                if user_input.strip():
                    print()
                    print("MrPark: ", end="", flush=True)

                    try:
                        # Build context with current session state
                        context = {
                            "current_business_id": self.current_business_id
                        }
                        response = await self.agent.process_message(user_input, context=context)
                        print(response)
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        logger.exception("Agent processing failed")

                    print()

            except KeyboardInterrupt:
                print("\n\nUse /quit to exit")
                continue
            except EOFError:
                break

        print("\n👋 Goodbye!")

    def _handle_memory_command(self, command: str):
        """Handle Unix-style /memory subcommands.

        Supported commands:
        - /memory --help           - Show help
        - /memory --list           - List personal memories (default)
        - /memory --list --global  - List global memories
        - /memory --list --all     - List all memories (global + personal)
        - /memory --add            - Add a new memory (interactive or with args)
        - /memory --remove <id>    - Remove a memory by ID
        - /memory --remove <id> --global  - Remove from global memory
        - /memory --stats          - Show statistics
        - /memory --stats --global - Show global statistics
        - /memory --stats --all    - Show all statistics
        """
        import shlex

        # Parse command into parts
        parts = command.split(None, 1)
        if len(parts) == 1:
            # Just "/memory" with no args - show help
            self._print_memory_help()
            return

        # Parse arguments
        args_str = parts[1]
        try:
            args = shlex.split(args_str)
        except ValueError as e:
            print(f"❌ Error parsing arguments: {e}")
            return

        # Extract flags and positional arguments
        flags = {arg for arg in args if arg.startswith('--')}
        positional = [arg for arg in args if not arg.startswith('--')]

        # Handle --help
        if '--help' in flags or '-h' in flags:
            self._print_memory_help()
            return

        # Determine scope
        scope = 'personal'  # default
        if '--global' in flags:
            scope = 'global'
        elif '--all' in flags:
            scope = 'all'

        # Handle subcommands
        if '--list' in flags or (not flags and not positional):
            # List memories (default action)
            self._memory_list(scope)

        elif '--add' in flags:
            # Add memory
            is_global = (scope == 'global')
            if positional:
                # Parse from positional args: "what_went_wrong" "correct_behavior" channel
                if len(positional) < 3:
                    print("❌ Usage: /memory --add \"what went wrong\" \"correct behavior\" channel")
                    print("\nChannels: email, calendar, whatsapp, mrcall, task")
                    print("\nExamples:")
                    print('  /memory --add "Used tu instead of lei" "Always use lei" email')
                    print('  /memory --add --global "Didn\'t check style" "Check past communication style" email')
                    print('  /memory --add "Too formal" "Use casual tone" whatsapp')
                    return

                what_went_wrong = positional[0]
                correct_behavior = positional[1]
                channel = positional[2]

                try:
                    correction_id = self.memory.add_correction(
                        what_went_wrong=what_went_wrong,
                        correct_behavior=correct_behavior,
                        channel=channel,
                        is_global=is_global
                    )
                    scope_label = "🌍 global" if is_global else "👤 personal"
                    print(f"✅ Memory #{correction_id} added ({scope_label})!")
                    print(f"   Channel: {channel}")
                    print(f"   Starting confidence: 50%")
                except ValueError as e:
                    print(f"❌ {e}")
            else:
                # Interactive mode would go here (future enhancement)
                print("❌ Please provide arguments: /memory --add \"what went wrong\" \"correct behavior\" channel")

        elif '--remove' in flags:
            # Remove memory
            if not positional:
                print("❌ Usage: /memory --remove <id> [--global]")
                print("   Get IDs with: /memory --list")
                return

            try:
                memory_id = int(positional[0])
                is_global = (scope == 'global')
                if self.memory.delete_correction(memory_id, is_global=is_global):
                    scope_label = "🌍 global" if is_global else "👤 personal"
                    print(f"✅ Memory #{memory_id} deleted from {scope_label} memory")
                else:
                    scope_label = "🌍 global" if is_global else "👤 personal"
                    print(f"❌ Memory #{memory_id} not found in {scope_label} memory")
            except ValueError:
                print("❌ Invalid memory ID. Must be a number.")

        elif '--stats' in flags:
            # Show statistics
            self._memory_stats(scope)

        else:
            print("❌ Unknown subcommand")
            print("Use /memory --help to see available commands")

    def _print_memory_help(self):
        """Print help for /memory command."""
        print("\n=== 🧠 Memory Command Help ===\n")
        print("Manage behavioral corrections learned from user feedback")
        print()
        print("Usage:")
        print("  /memory --help              Show this help")
        print("  /memory --list              List personal memories (default)")
        print("  /memory --list --global     List global memories (shared)")
        print("  /memory --list --all        List all memories")
        print()
        print("  /memory --add \"what went wrong\" \"correct behavior\" channel")
        print("                              Add a personal correction")
        print("  /memory --add --global \"wrong\" \"correct\" channel")
        print("                              Add a global correction (admin)")
        print()
        print("  /memory --remove <id>       Remove a personal memory")
        print("  /memory --remove <id> --global")
        print("                              Remove a global memory")
        print()
        print("  /memory --stats             Show personal memory stats")
        print("  /memory --stats --global    Show global memory stats")
        print("  /memory --stats --all       Show all memory stats")
        print()
        print("Channels:")
        print("  email      - Email drafting and replies")
        print("  calendar   - Calendar events and scheduling")
        print("  whatsapp   - WhatsApp messaging")
        print("  mrcall     - Phone call scripts and notes")
        print("  task       - MrPark task management")
        print()
        print("Examples:")
        print('  /memory --add "Used tu instead of lei" "Always use lei" email luisa@email.com')
        print('  /memory --add --global "Didn\'t check style" "Check past emails" email')
        print('  /memory --add "Too formal" "Use casual tone" whatsapp john@example.com')
        print('  /memory --list --all')
        print('  /memory --remove 5')
        print()

    def _memory_list(self, scope: str):
        """List memories with given scope."""
        memories = self.memory.export_memories(scope=scope)
        if not memories:
            scope_label = {
                'personal': '👤 personal',
                'global': '🌍 global',
                'all': 'any'
            }[scope]
            print(f"📭 No {scope_label} memories learned yet")
            print("\nAdd your first correction with:")
            print('  /memory --add "what went wrong" "correct behavior" email contact@email.com')
        else:
            scope_label = {
                'personal': '👤 Personal',
                'global': '🌍 Global',
                'all': '🌍/👤 All'
            }[scope]
            print(f"\n=== 🧠 {scope_label} Memory Bank ({len(memories)} corrections) ===\n")
            for mem in memories:
                conf_emoji = "🟢" if mem['confidence'] > 0.7 else "🟡" if mem['confidence'] > 0.4 else "🔴"
                scope_icon = "🌍" if mem.get('_scope') == 'global' else "👤"
                channel = mem.get('channel', 'unknown').upper()
                print(f"{scope_icon} {mem['id']}. {conf_emoji} [{channel}]")
                print(f"   ❌ {mem['what_went_wrong']}")
                print(f"   ✅ {mem['correct_behavior']}")
                print(f"   📊 Confidence: {mem['confidence']:.0%} ({mem['times_successful']}/{mem['times_applied']} successes)")
                print()

    def _memory_stats(self, scope: str):
        """Show memory statistics for given scope."""
        stats = self.memory.get_stats(scope=scope)
        scope_label = {
            'personal': '👤 Personal',
            'global': '🌍 Global',
            'all': '🌍/👤 All'
        }[scope]
        print(f"\n=== 🧠 {scope_label} Memory Statistics ===\n")
        print(f"Total corrections: {stats['total_corrections']}")
        if scope == 'all' and 'by_scope' in stats:
            print(f"  - 👤 Personal: {stats['personal_corrections']}")
            print(f"  - 🌍 Global: {stats['global_corrections']}")
        print(f"Average confidence: {stats['avg_confidence']:.0%}")
        print(f"Total applications: {stats['total_applications']}")
        print(f"Success rate: {stats['success_rate']:.0%}")
        print(f"High-confidence rules (>70%): {stats['high_confidence_rules']}")
        if stats.get('by_channel'):
            print("\nBy channel:")
            for channel, count in stats['by_channel'].items():
                print(f"  - {channel}: {count}")
        print()

    async def _handle_sync_command(self, days_back: Optional[int] = None):
        """Handle /sync command - run morning sync workflow.

        Args:
            days_back: Optional number of days to sync (default: 30 for emails, 7 for gaps)
        """
        if days_back:
            print(f"\n🌅 Starting sync workflow (last {days_back} days)...\n")
        else:
            print("\n🌅 Starting morning sync workflow...\n")

        # Initialize clients if not already done
        if not hasattr(self, 'gmail_client'):
            print("📧 Initializing Gmail client...")
            from ..tools.gmail import GmailClient
            self.gmail_client = GmailClient(
                credentials_path=settings.google_credentials_path,
                token_dir=settings.google_token_path
            )
            self.gmail_client.authenticate()

        if not hasattr(self, 'calendar_client'):
            print("📅 Initializing Calendar client...")
            self.calendar_client = GoogleCalendarClient(
                credentials_path=settings.google_credentials_path,
                token_dir=settings.google_token_path,
                calendar_id=settings.calendar_id
            )
            self.calendar_client.authenticate()

        # Step 1: Sync emails
        if days_back:
            print(f"📧 STEP 1/3: Syncing email threads (last {days_back} days)...")
        else:
            print("📧 STEP 1/3: Syncing email threads...")
        try:
            email_sync = EmailSyncManager(
                gmail_client=self.gmail_client,
                anthropic_api_key=settings.anthropic_api_key
            )
            email_results = email_sync.sync_emails(days_back=days_back)
            print(f"   ✅ Email sync complete: {email_results.get('new_threads', 0)} new, "
                  f"{email_results.get('updated_threads', 0)} updated\n")
        except Exception as e:
            print(f"   ❌ Email sync failed: {e}\n")

        # Step 2: Sync calendar
        print("📅 STEP 2/3: Syncing calendar events...")
        try:
            # Parse my_emails for external attendee detection
            my_emails_list = [email.strip() for email in settings.my_emails.split(',') if email.strip()]

            calendar_sync = CalendarSyncManager(
                calendar_client=self.calendar_client,
                anthropic_api_key=settings.anthropic_api_key,
                my_emails=my_emails_list
            )
            calendar_results = calendar_sync.sync_events()
            print(f"   ✅ Calendar sync complete: {calendar_results.get('new_events', 0)} new, "
                  f"{calendar_results.get('updated_events', 0)} updated\n")
        except Exception as e:
            print(f"   ❌ Calendar sync failed: {e}\n")

        # Step 3: Analyze gaps
        gap_days = days_back if days_back else 7
        print(f"🔍 STEP 3/3: Analyzing relationship gaps (last {gap_days} days)...")
        try:
            analyzer = RelationshipAnalyzer(
                anthropic_api_key=settings.anthropic_api_key,
                memory_bank=self.memory
            )
            gap_results = analyzer.analyze_all_gaps(days_back=gap_days)

            # Save results
            output_path = Path("cache/relationship_gaps.json")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(gap_results, f, indent=2, default=str)

            total_tasks = (
                len(gap_results.get('email_tasks', [])) +
                len(gap_results.get('meeting_followup_tasks', [])) +
                len(gap_results.get('silent_contacts', []))
            )

            print(f"   ✅ Task analysis complete: {total_tasks} TASKS found")
            print(f"      - Email tasks: {len(gap_results.get('email_tasks', []))}")
            print(f"      - Meeting follow-up tasks: {len(gap_results.get('meeting_followup_tasks', []))}")
            print(f"      - Silent contacts: {len(gap_results.get('silent_contacts', []))}\n")
        except Exception as e:
            print(f"   ❌ Gap analysis failed: {e}\n")

        print("✅ Morning sync complete! Use /gaps to see your briefing.\n")

    def _handle_gaps_command(self):
        """Handle /gaps command - show relationship gaps briefing."""
        gaps_file = Path("cache/relationship_gaps.json")

        if not gaps_file.exists():
            print("\n⚠️  No gap analysis found. Run /sync first to analyze your relationships.\n")
            return

        # Load gaps
        with open(gaps_file, 'r') as f:
            gaps = json.load(f)

        analyzed_at = gaps.get('analyzed_at', 'unknown')
        print(f"\n📋 RELATIONSHIP BRIEFING")
        print(f"   Analyzed: {analyzed_at}")
        print("=" * 60)

        # Show email tasks (person-level)
        email_tasks = gaps.get('email_tasks', [])
        if email_tasks:
            print("\n📧 EMAIL TASKS (by person):")
            for i, task in enumerate(email_tasks[:15], 1):
                name = task.get('contact_name', 'Unknown')
                email = task.get('contact_email', '')
                thread_count = task.get('thread_count', 1)
                task_desc = task.get('task_description', 'Follow up')
                reason = task.get('reason', '')

                print(f"\n{i}. {name} <{email}>")
                print(f"   💬 {thread_count} conversation{'s' if thread_count != 1 else ''}")
                print(f"   ✅ Task: {task_desc}")
                if reason:
                    print(f"   💡 Why: {reason}")

        # Show meeting follow-up tasks
        meeting_tasks = gaps.get('meeting_followup_tasks', [])
        if meeting_tasks:
            print("\n📅 MEETING FOLLOW-UP TASKS:")
            for i, task in enumerate(meeting_tasks[:5], 1):
                days = task['days_ago']
                time_ago = f"{days} day{'s' if days != 1 else ''} ago"
                print(f"\n{i}. Meeting with {task['contact_name']} ({time_ago})")
                print(f"   📅 {task['meeting_summary']}")
                print(f"   ✉️  No follow-up email sent yet")

        # Show silent contacts
        silent_contacts = gaps.get('silent_contacts', [])
        if silent_contacts:
            print("\n💤 SILENT CONTACTS:")
            for i, contact in enumerate(silent_contacts[:5], 1):
                print(f"\n{i}. {contact['contact_name']}")
                print(f"   📊 {contact['total_interactions']} past interactions ({contact['total_emails']} emails, {contact['total_meetings']} meetings)")
                print(f"   ⏰ {contact['days_silent']} days since last contact")

        # Summary
        total = len(email_tasks) + len(meeting_tasks) + len(silent_contacts)
        if total == 0:
            print("\n✅ All clear! No TASKS found.")
        else:
            print(f"\n📊 SUMMARY: {total} total TASKS")

        print("\n" + "=" * 60 + "\n")

    def _handle_cache_command(self, command: str):
        """Handle /cache command - cache inspection and management.

        Subcommands:
            /cache            - Show cache overview
            /cache --help     - Show help
            /cache emails     - Show email cache details
            /cache calendar   - Show calendar cache details
            /cache gaps       - Show gaps cache details
            /cache --clear emails     - Clear email cache
            /cache --clear calendar   - Clear calendar cache
            /cache --clear gaps       - Clear gaps cache
            /cache --clear all        - Clear all caches
        """
        args = command.split()[1:] if len(command.split()) > 1 else []
        flags = [arg for arg in args if arg.startswith('--')]
        positional = [arg for arg in args if not arg.startswith('--')]

        # Handle --help
        if '--help' in flags or '-h' in flags:
            print("\n📦 CACHE MANAGEMENT")
            print("=" * 60)
            print("\nUsage:")
            print("  /cache              - Show cache overview (all channels)")
            print("  /cache emails       - Show email cache details")
            print("  /cache calendar     - Show calendar cache details")
            print("  /cache gaps         - Show gaps cache details")
            print("\nClear cache:")
            print("  /cache --clear emails     - Clear email cache")
            print("  /cache --clear calendar   - Clear calendar cache")
            print("  /cache --clear gaps       - Clear gaps cache")
            print("  /cache --clear all        - Clear ALL caches")
            print("\n" + "=" * 60 + "\n")
            return

        # Handle --clear
        if '--clear' in flags:
            if not positional:
                print("❌ Usage: /cache --clear <target>")
                print("   Targets: emails, calendar, gaps, all")
                return

            target = positional[0]
            self._clear_cache(target)
            return

        # Default: show cache overview or specific cache
        if positional:
            target = positional[0]
            if target == 'emails':
                self._show_email_cache()
            elif target == 'calendar':
                self._show_calendar_cache()
            elif target == 'gaps':
                self._show_gaps_cache()
            else:
                print(f"❌ Unknown cache: {target}")
                print("   Valid caches: emails, calendar, gaps")
        else:
            # Show overview of all caches
            self._show_cache_overview()

    def _show_cache_overview(self):
        """Show overview of all caches."""
        print("\n📦 CACHE OVERVIEW")
        print("=" * 60)

        # Email cache
        email_cache_path = Path("cache/emails/threads.json")
        if email_cache_path.exists():
            with open(email_cache_path, 'r') as f:
                email_data = json.load(f)
            last_sync = email_data.get('last_sync', 'Never')
            thread_count = len(email_data.get('threads', {}))
            print(f"\n📧 EMAIL CACHE:")
            print(f"   Location: {email_cache_path}")
            print(f"   Last sync: {last_sync}")
            print(f"   Threads: {thread_count}")
        else:
            print(f"\n📧 EMAIL CACHE: ❌ Not found")

        # Calendar cache
        calendar_cache_path = Path("cache/calendar/events.json")
        if calendar_cache_path.exists():
            with open(calendar_cache_path, 'r') as f:
                calendar_data = json.load(f)
            last_sync = calendar_data.get('last_sync', 'Never')
            event_count = len(calendar_data.get('events', {}))
            sync_window = calendar_data.get('sync_window', {})
            time_min = sync_window.get('time_min', 'Unknown')
            time_max = sync_window.get('time_max', 'Unknown')
            print(f"\n📅 CALENDAR CACHE:")
            print(f"   Location: {calendar_cache_path}")
            print(f"   Last sync: {last_sync}")
            print(f"   Events: {event_count}")
            print(f"   Window: {time_min[:10]} to {time_max[:10]}")
        else:
            print(f"\n📅 CALENDAR CACHE: ❌ Not found")

        # Gaps cache
        gaps_cache_path = Path("cache/relationship_gaps.json")
        if gaps_cache_path.exists():
            with open(gaps_cache_path, 'r') as f:
                gaps_data = json.load(f)
            analyzed_at = gaps_data.get('analyzed_at', 'Never')
            email_tasks = len(gaps_data.get('email_tasks', []))
            meeting_tasks = len(gaps_data.get('meeting_followup_tasks', []))
            silent = len(gaps_data.get('silent_contacts', []))
            print(f"\n🔍 RELATIONSHIP GAPS:")
            print(f"   Location: {gaps_cache_path}")
            print(f"   Analyzed: {analyzed_at}")
            print(f"   Email tasks: {email_tasks}")
            print(f"   Meeting follow-ups: {meeting_tasks}")
            print(f"   Silent contacts: {silent}")
        else:
            print(f"\n🔍 RELATIONSHIP GAPS: ❌ Not found")

        print("\n" + "=" * 60 + "\n")

    def _show_email_cache(self):
        """Show detailed email cache info."""
        email_cache_path = Path("cache/emails/threads.json")
        if not email_cache_path.exists():
            print("\n❌ Email cache not found\n")
            return

        with open(email_cache_path, 'r') as f:
            data = json.load(f)

        threads = data.get('threads', {})
        last_sync = data.get('last_sync', 'Never')

        print("\n📧 EMAIL CACHE DETAILS")
        print("=" * 60)
        print(f"Last sync: {last_sync}")
        print(f"Total threads: {len(threads)}")

        if threads:
            # Find date range
            dates = []
            for thread in threads.values():
                date_str = thread.get('last_message_date', '')
                if date_str:
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(date_str)
                        dates.append(dt)
                    except:
                        pass

            if dates:
                oldest = min(dates).strftime('%Y-%m-%d')
                newest = max(dates).strftime('%Y-%m-%d')
                print(f"Date range: {oldest} to {newest}")

            # Count by status
            action_needed = sum(1 for t in threads.values() if t.get('requires_action'))
            print(f"Requires action: {action_needed}")

        print("\n" + "=" * 60 + "\n")

    def _show_calendar_cache(self):
        """Show detailed calendar cache info."""
        calendar_cache_path = Path("cache/calendar/events.json")
        if not calendar_cache_path.exists():
            print("\n❌ Calendar cache not found\n")
            return

        with open(calendar_cache_path, 'r') as f:
            data = json.load(f)

        events = data.get('events', {})
        last_sync = data.get('last_sync', 'Never')
        sync_window = data.get('sync_window', {})

        print("\n📅 CALENDAR CACHE DETAILS")
        print("=" * 60)
        print(f"Last sync: {last_sync}")
        print(f"Total events: {len(events)}")

        time_min = sync_window.get('time_min', 'Unknown')
        time_max = sync_window.get('time_max', 'Unknown')
        print(f"Sync window: {time_min[:10]} to {time_max[:10]}")

        # Count past vs future
        past_count = sum(1 for e in events.values() if e.get('is_past') == True)
        future_count = sum(1 for e in events.values() if e.get('is_past') == False)
        unknown_count = sum(1 for e in events.values() if e.get('is_past') is None)

        print(f"Past events: {past_count}")
        print(f"Future events: {future_count}")
        if unknown_count > 0:
            print(f"Unknown status: {unknown_count} (is_past=null)")

        # Count external meetings
        external_count = sum(1 for e in events.values() if e.get('external_attendees'))
        print(f"External meetings: {external_count}")

        print("\n" + "=" * 60 + "\n")

    def _show_gaps_cache(self):
        """Show detailed gaps cache info."""
        gaps_cache_path = Path("cache/relationship_gaps.json")
        if not gaps_cache_path.exists():
            print("\n❌ Gaps cache not found\n")
            return

        with open(gaps_cache_path, 'r') as f:
            data = json.load(f)

        print("\n🔍 RELATIONSHIP GAPS DETAILS")
        print("=" * 60)
        print(f"Analyzed: {data.get('analyzed_at', 'Never')}")

        email_tasks = data.get('email_tasks', [])
        meeting_tasks = data.get('meeting_followup_tasks', [])
        silent = data.get('silent_contacts', [])

        print(f"\nEmail tasks: {len(email_tasks)}")
        if email_tasks:
            contacts = [t.get('contact_name', 'Unknown') for t in email_tasks[:5]]
            print(f"  Top 5: {', '.join(contacts)}")

        print(f"\nMeeting follow-ups: {len(meeting_tasks)}")
        if meeting_tasks:
            contacts = [t.get('contact_name', 'Unknown') for t in meeting_tasks[:5]]
            print(f"  Top 5: {', '.join(contacts)}")

        print(f"\nSilent contacts: {len(silent)}")
        if silent:
            contacts = [c.get('contact_name', 'Unknown') for c in silent[:5]]
            print(f"  Top 5: {', '.join(contacts)}")

        print("\n" + "=" * 60 + "\n")

    def _clear_cache(self, target: str):
        """Clear specified cache(s).

        Args:
            target: 'emails', 'calendar', 'gaps', or 'all'
        """
        import shutil

        cleared = []

        if target == 'emails' or target == 'all':
            email_cache = Path("cache/emails")
            if email_cache.exists():
                shutil.rmtree(email_cache)
                email_cache.mkdir(parents=True, exist_ok=True)
                cleared.append("emails")

        if target == 'calendar' or target == 'all':
            calendar_cache = Path("cache/calendar")
            if calendar_cache.exists():
                shutil.rmtree(calendar_cache)
                calendar_cache.mkdir(parents=True, exist_ok=True)
                cleared.append("calendar")

        if target == 'gaps' or target == 'all':
            gaps_file = Path("cache/relationship_gaps.json")
            if gaps_file.exists():
                gaps_file.unlink()
                cleared.append("gaps")

        if cleared:
            print(f"\n✅ Cleared cache: {', '.join(cleared)}\n")
        else:
            print(f"\n⚠️  No caches found to clear for: {target}\n")

    async def handle_command(self, command: str):
        """Handle CLI commands.

        Args:
            command: Command string
        """
        cmd = command.lower().strip()

        if cmd == "/help":
            self.print_welcome()

        elif cmd.startswith("/business "):
            # Extract business_id
            business_id = command[10:].strip()
            if business_id:
                self.current_business_id = business_id
                print(f"✅ Now saving contacts to assistant: {business_id}")
                print(f"   All enriched contacts will be saved to this assistant's contact list")
            else:
                print("Usage: /business <business_id>")
                print("Example: /business hahnbanach_personal")

        elif cmd == "/business":
            if self.current_business_id:
                print(f"📌 Current assistant: {self.current_business_id}")
            else:
                print("⚠️  No assistant selected")
                print("Use: /business <business_id>")

        elif cmd == "/clear":
            self.agent.clear_history()
            print("✅ Conversation history cleared")

        elif cmd == "/history":
            history = self.agent.get_history()
            if not history:
                print("No conversation history")
            else:
                print("\n=== Conversation History ===")
                for i, turn in enumerate(history, 1):
                    role = turn["role"].capitalize()
                    content = turn["content"]
                    if isinstance(content, str):
                        print(f"\n{i}. {role}: {content[:100]}...")
                    else:
                        print(f"\n{i}. {role}: [Tool use]")
                print()

        elif cmd == "/quit" or cmd == "/exit":
            self.running = False

        elif cmd.startswith("/memory"):
            # Unix-style memory subcommands: /memory --help, /memory --add, /memory --list, etc.
            self._handle_memory_command(command)

        elif cmd.startswith("/sync"):
            # Morning sync workflow
            # Parse optional days parameter: /sync 3 (last 3 days)
            parts = command.split()
            days = None
            if len(parts) > 1:
                try:
                    days = int(parts[1])
                except ValueError:
                    print(f"❌ Invalid days parameter: {parts[1]}")
                    print("Usage: /sync [days]")
                    print("Example: /sync 3  (sync last 3 days)")
                    return
            await self._handle_sync_command(days_back=days)

        elif cmd == "/gaps" or cmd == "/briefing":
            # Show relationship gaps
            self._handle_gaps_command()

        elif cmd.startswith("/cache"):
            # Cache management
            self._handle_cache_command(command)

        else:
            print(f"Unknown command: {cmd}")
            print("Type /help for available commands")


def main():
    """Entry point for MrPark CLI."""
    cli = MrParkCLI()

    try:
        asyncio.run(cli.run())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
