"""Tool factory for centralizing tool initialization."""

import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from zylch.config import settings
from .base import Tool, ToolResult, ToolStatus


class SessionState:
    """Shared session state that can be updated at runtime.

    This allows tools to access current values (like business_id, owner_id) that may
    change during the session (e.g., when user runs /mrcall <id>).

    Also manages task focus mode - when a user enters a task "virtualenv" to
    work on a specific task with dedicated orchestration.

    Also manages MrCall config mode - when a user enters `/mrcall open` to
    configure their MrCall assistant with dedicated orchestration.
    """
    def __init__(self, business_id: Optional[str] = None, owner_id: Optional[str] = None):
        self.business_id = business_id
        self.owner_id = owner_id
        # Task focus mode
        self.task_id: Optional[str] = None
        self.task_context: Optional[Dict] = None
        self.last_action_result: Optional[Dict] = None
        # MrCall config mode
        self.mrcall_config_mode: bool = False
        self.mrcall_config_business_id: Optional[str] = None

    def set_business_id(self, business_id: Optional[str]):
        """Update the current business ID."""
        self.business_id = business_id

    def get_business_id(self) -> Optional[str]:
        """Get the current business ID."""
        return self.business_id

    def set_owner_id(self, owner_id: Optional[str]):
        """Update the current owner ID."""
        self.owner_id = owner_id

    def get_owner_id(self) -> Optional[str]:
        """Get the current owner ID."""
        return self.owner_id

    # Task focus mode methods
    def enter_task_mode(self, task_id: str, task_data: Dict):
        """Enter task focus mode for a specific task.

        Args:
            task_id: UUID of the task to focus on
            task_data: Full task data from task_items table
        """
        self.task_id = task_id
        self.task_context = task_data
        self.last_action_result = None

    def exit_task_mode(self):
        """Exit task focus mode and return to normal chat."""
        self.task_id = None
        self.task_context = None
        self.last_action_result = None

    def is_task_mode(self) -> bool:
        """Check if currently in task focus mode."""
        return self.task_id is not None

    def get_task_id(self) -> Optional[str]:
        """Get the current task ID (None if not in task mode)."""
        return self.task_id

    def get_task_context(self) -> Optional[Dict]:
        """Get the current task context data."""
        return self.task_context

    def set_last_action_result(self, result: Dict):
        """Store the result of the last action for confirmation workflow."""
        self.last_action_result = result

    def get_last_action_result(self) -> Optional[Dict]:
        """Get the result of the last action."""
        return self.last_action_result

    # MrCall config mode methods
    def enter_mrcall_config_mode(self, business_id: str):
        """Enter MrCall configuration mode for a specific assistant.

        Args:
            business_id: UUID of the MrCall assistant to configure
        """
        self.mrcall_config_mode = True
        self.mrcall_config_business_id = business_id
        # MrCall config mode and task mode are mutually exclusive
        self.exit_task_mode()

    def exit_mrcall_config_mode(self):
        """Exit MrCall configuration mode and return to normal chat."""
        self.mrcall_config_mode = False
        self.mrcall_config_business_id = None

    def is_mrcall_config_mode(self) -> bool:
        """Check if currently in MrCall configuration mode."""
        return self.mrcall_config_mode

    def get_mrcall_config_business_id(self) -> Optional[str]:
        """Get the business ID for the current MrCall config session."""
        return self.mrcall_config_business_id


from .config import ToolConfig
from ..config import settings
from zylch.memory import EmbeddingEngine, HybridSearchEngine, MemoryConfig
from .gcalendar import (
    ListCalendarEventsTool,
    CreateCalendarEventTool,
    SearchCalendarEventsTool,
    UpdateCalendarEventTool,
)
from .web_search import WebSearchTool

# External service imports
from .gmail import GmailClient
from .outlook import OutlookClient
from .gcalendar import GoogleCalendarClient
from .outlook_calendar import OutlookCalendarClient
from .starchat import StarChatClient
from .pipedrive import PipedriveClient
# VonageClient imported dynamically in SMS tools at execution time
from .email_archive import EmailArchiveManager
from .email_sync import EmailSyncManager
# TaskManager removed - tasks now served via task_items table
from ..memory import EmbeddingEngine
from ..assistant.models import ModelSelector

from .sms_tools import (
    SendSMSTool,
    SendVerificationCodeTool,
    VerifyCodeTool,
)
from .call_tools import InitiateCallTool

logger = logging.getLogger(__name__)


class ToolFactory:
    """Factory for creating and initializing Zylch AI tools.

    Centralizes all tool initialization logic previously scattered in CLI.
    Both API services and CLI can use this factory to get identical tool sets.
    """

    # Class attributes for storing service client references
    # These are set during create_all_tools() and can be accessed by CLI
    _starchat_client = None
    _email_client = None  # GmailClient or OutlookClient
    _calendar_client = None  # GoogleCalendarClient or OutlookCalendarClient
    _email_archive = None
    _session_state = None  # Shared session state for runtime updates

    @staticmethod
    async def create_all_tools(
        config: ToolConfig,
        current_business_id: Optional[str] = None
    ) -> tuple:
        """Create and initialize all Zylch AI tools.

        Args:
            config: Tool configuration
            current_business_id: Current StarChat business ID for contact tools

        Returns:
            Tuple of (tools, session_state):
            - tools: List of initialized tool instances
            - session_state: SessionState for runtime updates

        Raises:
            Exception: If required services fail to initialize
        """
        logger.info("Initializing Zylch AI tools...")

        # Create shared session state
        session_state = SessionState(business_id=current_business_id, owner_id=config.owner_id)
        ToolFactory._session_state = session_state

        # Initialize external service clients
        try:
            # StarChat client - DISABLED pending OAuth2.0 implementation
            # Credentials will be per-user via /connect starchat (OAuth2.0)
            # For now, StarChat features are disabled
            starchat = None
            logger.info("StarChat disabled - pending OAuth2.0 implementation")

            # Email client - choose based on auth provider
            if config.auth_provider == "microsoft":
                # Microsoft Outlook client
                email_client = OutlookClient(
                    graph_token=config.graph_token,
                    account=config.user_email,
                )
                logger.info("Using Microsoft Outlook for email")

                # Try to authenticate
                try:
                    if config.graph_token:
                        email_client.authenticate()
                        logger.info("Microsoft Graph API authenticated")
                    else:
                        logger.warning("Microsoft Graph token not found")
                except Exception as e:
                    logger.warning(f"Microsoft authentication needed: {e}")

            else:
                # Gmail client (default)
                # Requires owner_id for Supabase token storage
                owner_id = config.owner_id if config.owner_id != "owner_default" else None
                if not owner_id:
                    raise ValueError("owner_id is required for Gmail client - Zylch uses Supabase for all token storage")

                email_client = GmailClient(
                    account=config.user_email,
                    owner_id=owner_id,
                )
                logger.info("Using Gmail for email")

                # Try to authenticate Google services silently
                try:
                    from ..api import token_storage
                    if token_storage.has_google_credentials(owner_id):
                        email_client.authenticate()
                        logger.info("Google services authenticated (Gmail)")
                    else:
                        logger.warning("Google authentication needed - tokens not found in Supabase")
                except Exception as e:
                    logger.warning(f"Google authentication needed: {e}")

            # Calendar client (conditional based on provider)
            calendar = None
            if config.auth_provider == "google":
                # Gmail users get Google Calendar automatically
                # Requires owner_id for Supabase token storage
                calendar = GoogleCalendarClient(
                    calendar_id="primary",  # Default calendar
                    account=config.user_email,
                    owner_id=owner_id,  # Reuse owner_id from Gmail client initialization
                )
                logger.info("Google Calendar initialized for Gmail user")
            elif config.auth_provider == "microsoft":
                # Microsoft users get Outlook Calendar automatically
                # Use the graph_token from OutlookClient for authentication
                if isinstance(email_client, OutlookClient) and email_client.graph_token:
                    calendar = OutlookCalendarClient(
                        graph_token=email_client.graph_token,
                        calendar_id="primary",
                    )
                    logger.info("Outlook Calendar initialized for Microsoft user")
                else:
                    logger.warning("Outlook Calendar not available - email client not authenticated")
            else:
                logger.info("No calendar provider configured")

            # Save clients to class variables for access by other services
            ToolFactory._email_client = email_client
            ToolFactory._calendar_client = calendar

            # Email archive manager (lazy auth - won't fail if Gmail not configured)
            email_archive = None
            try:
                email_archive = EmailArchiveManager(gmail_client=email_client)
            except Exception as e:
                logger.warning(f"EmailArchiveManager initialization skipped: {e}")

            # Email sync manager
            email_sync = None
            if email_archive and config.anthropic_api_key and config.llm_provider:
                email_sync = EmailSyncManager(
                    email_archive=email_archive,
                    api_key=config.anthropic_api_key,
                    provider=config.llm_provider,
                    days_back=30,
                    owner_id=config.owner_id,
                    supabase_storage=supabase_storage,
                )

            # Pipedrive CRM client (optional - enabled when token is set via /connect pipedrive)
            pipedrive = None
            if config.pipedrive_api_token:
                try:
                    pipedrive = PipedriveClient(api_token=config.pipedrive_api_token)
                    logger.info("Pipedrive CRM connected")
                except Exception as e:
                    logger.warning(f"Pipedrive connection failed: {e}")
                    pipedrive = None

            # Vonage SMS: credentials are loaded dynamically per-user in SendSMSTool.execute()
            # No client initialization needed here - tool is always available

            # Initialize hybrid search engine for blob search
            from zylch.storage.supabase_client import SupabaseStorage
            supabase_storage = SupabaseStorage.get_instance()
            mem_config = MemoryConfig()
            embedding_engine = EmbeddingEngine(mem_config)
            search_engine = HybridSearchEngine(
                supabase_client=supabase_storage.client,
                embedding_engine=embedding_engine,
                default_alpha=0.3  # FTS weight (0.3 = 70% semantic, 30% FTS)
            )
            logger.info("Hybrid search engine initialized")

        except Exception as e:
            logger.error(f"Failed to initialize service clients: {e}")
            raise

        # Initialize tools list
        tools = []

        # Email tools (7 tools) - Gmail or Outlook
        tools.extend(ToolFactory._create_gmail_tools(
            email_client, calendar, supabase_storage, email_sync,
            config.owner_id, config.zylch_assistant_id
        ))

        # Email sync tools (4 tools)
        tools.extend(ToolFactory._create_email_sync_tools(
            email_sync, supabase_storage, config.owner_id
        ))

        # Memory search tools (search_local_memory with hybrid FTS + semantic search)
        tools.extend(ToolFactory._create_contact_tools(
            starchat,
            session_state,
            search_engine,
            config.owner_id,
            config.zylch_assistant_id
        ))

        # Calendar tools (4 tools)
        tools.extend(ToolFactory._create_calendar_tools(calendar))

        # Web search tool (1 tool) - Anthropic-only feature
        # Pass provider so WebSearchTool can show clear error for non-Anthropic providers
        tools.append(WebSearchTool(
            api_key=config.anthropic_api_key,
            provider=getattr(config, 'llm_provider', 'anthropic')
        ))

        # Pipedrive tools (2 tools) - optional
        if pipedrive:
            tools.extend(ToolFactory._create_pipedrive_tools(pipedrive))

        # MrCall configuration tools (3 tools) - requires StarChat
        if starchat:
            tools.extend(ToolFactory._create_mrcall_tools(
                starchat_client=starchat,
                session_state=session_state,
                storage=supabase_storage,
                owner_id=config.owner_id,
                api_key=config.anthropic_api_key,
                provider=getattr(config, 'llm_provider', 'anthropic')
            ))

        # Sharing tools (4 tools) - for intelligence sharing between users
        # TODO: Re-enable when migrated to Supabase blobs
        # if config.user_email:
        #     sharing_tools = ToolFactory._create_sharing_tools(
        #         owner_id=config.owner_id,
        #         user_email=config.user_email,
        #         user_display_name=config.user_display_name if hasattr(config, 'user_display_name') else None
        #     )
        #     tools.extend(sharing_tools)
        #     logger.info(f"Sharing tools initialized ({len(sharing_tools)} tools)")



        # SMS tools (always available - credentials loaded per-user at execution time)
        tools.extend(ToolFactory._create_sms_tools(
            session_state=session_state,
            owner_id=config.owner_id,
            zylch_assistant_id=config.zylch_assistant_id
        ))
        logger.info("SMS tools initialized (credentials loaded per-user)")

        # Call tools (1 tool) - for outbound calls via MrCall
        if starchat:
            tools.append(InitiateCallTool(
                starchat_client=starchat,
                session_state=session_state
            ))
            logger.info("Call tool initialized (StarChat/MrCall)")

        # Get Tasks tool - returns task list from task_items table
        tools.append(_GetTasksTool(session_state=session_state))
        logger.info("Get Tasks tool initialized")

        # Compose Email tool - writes emails with full context from memory
        tools.append(_ComposeEmailTool(
            session_state=session_state,
            api_key=config.anthropic_api_key,
            provider=getattr(config, 'llm_provider', 'anthropic')
        ))
        logger.info("Compose Email tool initialized")

        # Store service client references for CLI access
        ToolFactory._starchat_client = starchat
        ToolFactory._email_archive = email_archive

        logger.info(f"Initialized {len(tools)} tools")
        return tools, session_state

    @staticmethod
    def create_model_selector(config: ToolConfig) -> ModelSelector:
        """Create model selector with configuration.

        Args:
            config: Tool configuration

        Returns:
            Configured ModelSelector instance
        """
        return ModelSelector(
            default_model=config.default_model,
            classification_model=config.classification_model,
            executive_model=config.executive_model,
        )

    @staticmethod
    def _create_gmail_tools(
        gmail_client,
        calendar_client,
        storage,
        email_sync_manager=None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
    ) -> List[Tool]:
        """Create Gmail-related tools."""
        return [
            _GmailSearchTool(gmail_client, owner_id, zylch_assistant_id),
            _CreateDraftTool(storage, owner_id),
            _ListDraftsTool(storage, owner_id),
            _EditDraftTool(gmail_client),
            _UpdateDraftTool(gmail_client),
            _SendDraftTool(gmail_client, storage, owner_id),
            _RefreshGoogleAuthTool(gmail_client, calendar_client),
        ]

    @staticmethod
    def _create_email_sync_tools(email_sync_manager, storage, owner_id: str) -> List[Tool]:
        """Create email sync tools."""
        return [
            _SyncEmailsTool(email_sync_manager),
            _SearchEmailsTool(email_sync_manager, storage, owner_id),
            _CloseEmailThreadTool(email_sync_manager),
            _EmailStatsTool(email_sync_manager),
        ]

    @staticmethod
    def _create_contact_tools(
        starchat_client,
        session_state: SessionState,
        search_engine: Optional[HybridSearchEngine] = None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant"
    ) -> List[Tool]:
        """Create memory search tools.

        ZYLCH IS PERSON-CENTRIC: A person can have multiple emails/phones.
        search_local_memory provides hybrid FTS + semantic search.
        """
        return [
            _SearchLocalMemoryTool(search_engine, owner_id, zylch_assistant_id),
            _GetContactTool(starchat_client, session_state),
            _GetWhatsAppContactsTool(starchat_client, session_state),
        ]

    @staticmethod
    def _create_calendar_tools(calendar_client) -> List[Tool]:
        """Create calendar tools."""
        return [
            ListCalendarEventsTool(calendar_client),
            CreateCalendarEventTool(calendar_client),
            SearchCalendarEventsTool(calendar_client),
            UpdateCalendarEventTool(calendar_client),
        ]

    @staticmethod
    def _create_pipedrive_tools(pipedrive_client) -> List[Tool]:
        """Create Pipedrive CRM tools."""
        return [
            _SearchPipedrivePersonTool(pipedrive_client),
            _GetPipedrivePersonDealsTool(pipedrive_client),
        ]

    @staticmethod
    def _create_mrcall_tools(
        starchat_client,
        session_state: SessionState,
        storage,
        owner_id: str,
        api_key: str,
        provider: str
    ) -> List[Tool]:
        """Create MrCall assistant configuration tools.

        These tools enable natural language configuration of MrCall assistants.
        Features:
        - Preview + confirm workflow for all changes
        - Variable preservation during prompt modifications
        - Dynamic sub-prompt generation via MrCallConfiguratorTrainer
        """
        from .mrcall import (
            GetAssistantCatalogTool,
            ConfigureAssistantTool,
        )
        from .mrcall.feature_context_tool import GetMrCallFeatureContextTool
        from zylch.agents.trainers import MrCallConfiguratorTrainer

        # Create trainer for sub-prompt generation
        trainer = MrCallConfiguratorTrainer(
            storage=storage,
            starchat_client=starchat_client,
            owner_id=owner_id,
            api_key=api_key,
            provider=provider,
        )

        return [
            GetAssistantCatalogTool(starchat_client, session_state),
            GetMrCallFeatureContextTool(trainer, session_state),
            ConfigureAssistantTool(
                starchat_client,
                session_state,
                trainer,
                api_key,
                provider,
            ),
        ]

    @staticmethod
    def _create_sharing_tools(
        owner_id: str,
        user_email: str,
        user_display_name: Optional[str] = None
    ) -> List[Tool]:
        """Create intelligence sharing tools.

        TODO: These tools currently disabled - need migration from legacy memory system to Supabase blobs.
        """
        # TODO: Re-enable when IntelShareManager is migrated to use Supabase blobs
        return []



    @staticmethod
    def _create_sms_tools(
        session_state,
        owner_id: str,
        zylch_assistant_id: str
    ) -> List[Tool]:
        """Create SMS tools for sending messages via Vonage.

        Credentials are loaded per-user at execution time from Supabase.

        Tools:
        - send_sms: Send a text message to a phone number
        - send_verification_code: Send a 6-digit code for phone verification
        - verify_sms_code: Verify a code that was sent via SMS
        """
        return [
            SendSMSTool(session_state=session_state),
            SendVerificationCodeTool(
                session_state=session_state,
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id
            ),
            VerifyCodeTool(owner_id=owner_id, zylch_assistant_id=zylch_assistant_id),
        ]

# ============================================================================
# INLINE TOOL DEFINITIONS
# These are extracted from CLI but kept as private classes in this module
# ============================================================================

class _GmailSearchTool(Tool):
    """Gmail search tool for contact enrichment."""
    def __init__(
        self,
        gmail_client,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant"
    ):
        super().__init__(
            name="search_provider_emails",
            description="Search email provider for emails from or to a contact to understand relationship"
        )
        self.gmail = gmail_client
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    def _is_email(self, value: str) -> bool:
        """Check if value looks like an email address."""
        import re
        return bool(re.match(r'^[^@]+@[^@]+\.[^@]+$', value.strip()))

    def _extract_email_from_header(self, header: str) -> tuple:
        """Extract email and name from header like 'Name <email@example.com>'."""
        import re
        match = re.search(r'([^<]*)<([^>]+)>', header)
        if match:
            name = match.group(1).strip().strip('"')
            email = match.group(2).strip()
            return email, name
        # Just email
        if self._is_email(header):
            return header.strip(), None
        return None, header.strip()

    def _find_emails_by_name(self, name: str, max_search: int = 50) -> list:
        """Search Gmail for emails containing this name and extract unique email addresses."""
        # Search for the name in Gmail
        messages = self.gmail.search_messages(name, max_search)

        # Extract unique emails with names
        contacts = {}  # email -> name
        name_lower = name.lower()

        for msg in messages:
            # Check from field
            from_email, from_name = self._extract_email_from_header(msg.get('from', ''))
            if from_email and from_name and name_lower in from_name.lower():
                contacts[from_email.lower()] = from_name

            # Check to field (can be multiple)
            to_field = msg.get('to', '')
            for part in to_field.split(','):
                to_email, to_name = self._extract_email_from_header(part.strip())
                if to_email and to_name and name_lower in to_name.lower():
                    contacts[to_email.lower()] = to_name

        return [{"email": email, "name": name} for email, name in contacts.items()]

    async def execute(
        self,
        contact: str,
        max_results: int = 20,
        search_all_history: bool = False,
        selected_emails: str = None
    ):
        """Search Gmail for emails with a contact.

        Args:
            contact: Email address OR name to search for
            max_results: Maximum results (default 20)
            search_all_history: If True, search from 2020. WARNING: expensive operation!
            selected_emails: Comma-separated indices (e.g. "1,3") when multiple emails found for a name
        """
        from datetime import datetime, timedelta

        try:
            # Check if input is an email or a name
            if not self._is_email(contact):
                # It's a name - find associated emails first
                found_contacts = self._find_emails_by_name(contact)

                if not found_contacts:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data={"contact": contact, "found_emails": []},
                        error=f"No contact found with name '{contact}' in emails."
                    )

                if len(found_contacts) == 1:
                    # Single match - proceed automatically
                    c = found_contacts[0]
                    emails_to_search = [c['email']]
                elif selected_emails:
                    # User selected specific indices (e.g. "1,3")
                    try:
                        indices = [int(i.strip()) - 1 for i in selected_emails.split(',')]
                        emails_to_search = [found_contacts[i]['email'] for i in indices if 0 <= i < len(found_contacts)]
                    except (ValueError, IndexError):
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            data=None,
                            error=f"Indici non validi: {selected_emails}. Usa numeri da 1 a {len(found_contacts)}."
                        )
                else:
                    # Multiple matches - ask user to choose
                    options = "\n".join([f"  {i+1}) {c['name']} <{c['email']}>" for i, c in enumerate(found_contacts)])
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data={
                            "contact": contact,
                            "found_emails": found_contacts,
                            "needs_selection": True
                        },
                        message=f"Found {len(found_contacts)} emails associated with '{contact}':\n{options}\n\nWhich one to use? (e.g., '1' or '1,3' for multiple)"
                    )
            else:
                emails_to_search = [contact]

            # Now search for the actual emails
            all_messages = []
            for email in emails_to_search:
                base_query = f"from:{email} OR to:{email}"

                if search_all_history:
                    date_from = "2020-01-01"
                    query = f"{base_query} after:2020/01/01"
                    warning = "⚠️ WARNING: Full history search (from 2020). This operation may cost many tokens!"
                else:
                    one_year_ago = datetime.now() - timedelta(days=365)
                    date_from = one_year_ago.strftime("%Y-%m-%d")
                    query = f"{base_query} after:{one_year_ago.strftime('%Y/%m/%d')}"
                    warning = None

                messages = self.gmail.search_messages(query, max_results)
                all_messages.extend(messages)

            # Deduplicate by message id
            seen_ids = set()
            unique_messages = []
            for msg in all_messages:
                msg_id = msg.get('id', msg.get('subject', '') + msg.get('date', ''))
                if msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    unique_messages.append(msg)

            result_data = {
                "contact": contact,
                "emails_searched": emails_to_search,
                "message_count": len(unique_messages),
                "search_scope": "all_history_from_2020" if search_all_history else "last_year",
                "messages": [{
                    "from": msg["from"],
                    "to": msg["to"],
                    "subject": msg["subject"],
                    "date": msg["date"],
                    "snippet": msg["snippet"]
                } for msg in unique_messages]
            }

            date_to = datetime.now().strftime("%Y-%m-%d")
            message = f"Found {len(unique_messages)} email exchanges (from {date_from} to {date_to})"
            if len(emails_to_search) > 1:
                message += f" [searched {len(emails_to_search)} email addresses]"
            if warning:
                message = f"{warning}\n{message}"
            if not search_all_history and len(unique_messages) == 0:
                message += "\n💡 No results in last year. Use search_all_history=true to search from 2020 (more expensive)."

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=result_data,
                message=message
            )
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Search Gmail history for emails from or to a contact. Can accept email address OR name. If name is provided, will find associated emails first. By default searches last year only. Use search_all_history=true to search from 2020 (WARNING: expensive).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": "Email address OR person name to search for"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results (default 20)",
                        "default": 20
                    },
                    "search_all_history": {
                        "type": "boolean",
                        "description": "If true, search from 2020 instead of last year. WARNING: expensive operation!",
                        "default": False
                    },
                    "selected_emails": {
                        "type": "string",
                        "description": "When multiple emails found for a name, specify which to use (e.g. '1' or '1,3')"
                    }
                },
                "required": ["contact"]
            }
        }


class _CreateDraftTool(Tool):
    """Create a draft email in Supabase."""
    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="create_draft",
            description="Create a draft email that the user can review and send later"
        )
        self.storage = storage
        self.owner_id = owner_id

    async def execute(self, to: str, subject: str, body: str, in_reply_to: str = None, references: str = None, thread_id: str = None):
        try:
            # Convert references string to list if needed
            refs_list = None
            if references:
                refs_list = [r.strip() for r in references.split()] if isinstance(references, str) else references

            draft = self.storage.create_draft(
                owner_id=self.owner_id,
                to=to,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
                references=refs_list,
                thread_id=thread_id
            )

            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Failed to create draft in database"
                )

            thread_info = " (in reply to thread)" if in_reply_to else ""
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": draft.get('id')},
                message=f"✅ Draft created successfully{thread_info}!\n"
                        f"📧 To: {to}\n"
                        f"📝 Subject: {subject}\n\n"
                        f"📄 Message body:\n"
                        f"{'─' * 70}\n"
                        f"{body}\n"
                        f"{'─' * 70}\n\n"
                        f"Draft saved. Say 'send it' when ready to send."
            )
        except Exception as e:
            logger.error(f"Failed to create draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error creating draft: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Create a draft email. The draft is saved locally and can be sent later. If this is a REPLY to an existing email, provide the in_reply_to and references headers from the original message.",
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
                        "description": "Message-ID of the email being replied to (for replies)"
                    },
                    "references": {
                        "type": "string",
                        "description": "References header from the original message (for replies)"
                    },
                    "thread_id": {
                        "type": "string",
                        "description": "Gmail thread ID (for replies to keep in conversation)"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        }


class _ListDraftsTool(Tool):
    """List all drafts from Supabase."""
    def __init__(self, storage, owner_id: str):
        super().__init__(
            name="list_drafts",
            description="List all draft emails"
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
                    message="📭 No drafts found."
                )

            # Format draft details
            draft_details = []
            for draft in drafts:
                to_addresses = draft.get('to_addresses', [])
                to_str = ', '.join(to_addresses) if to_addresses else 'Unknown'
                body = draft.get('body', '')
                draft_details.append({
                    'id': draft['id'],
                    'to': to_str,
                    'subject': draft.get('subject', '(no subject)'),
                    'body_preview': body,
                    'created_at': draft.get('created_at')
                })

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"drafts": draft_details},
                message=f"📧 Found {len(draft_details)} drafts:\n\n" +
                       "\n".join([
                           f"**Draft {i+1}** (ID: {d['id']})\n"
                           f"📧 To: {d['to']}\n"
                           f"📝 Subject: {d['subject']}\n"
                           f"Preview: {d['body_preview']}\n"
                           for i, d in enumerate(draft_details)
                       ])
            )

        except Exception as e:
            logger.error(f"Failed to list drafts: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error retrieving drafts: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "List all draft emails. Returns draft IDs, recipients, subjects, and previews.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }


class _EditDraftTool(Tool):
    """Edit a draft interactively with nano editor."""
    def __init__(self, gmail_client):
        super().__init__(
            name="edit_draft",
            description="Open a draft in nano editor for manual editing"
        )
        self.gmail = gmail_client

    async def execute(self, draft_id: str):
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
                message=f"✅ Draft manually edited and saved!\n"
                        f"📧 To: {draft['to']}\n"
                        f"📝 Subject: {draft['subject']}"
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
                error=f"Error editing draft: {str(e)}"
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


class _UpdateDraftTool(Tool):
    """Update an existing draft."""
    def __init__(self, gmail_client):
        super().__init__(
            name="update_draft",
            description="Update an existing draft with new content"
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
                updates.append(f"📧 To: {to}")
            if subject:
                updates.append(f"📝 Subject: {subject}")
            if body:
                updates.append(f"✍️  Body: updated")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"draft_id": updated_draft.get('id')},
                message=f"✅ Draft updated successfully!\n" + "\n".join(updates) + "\n\n"
                        f"The updated draft is available in Gmail Drafts folder."
            )
        except Exception as e:
            logger.error(f"Failed to update draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error updating draft: {str(e)}"
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


class _SendDraftTool(Tool):
    """Send a draft from Supabase via Gmail/Outlook API."""
    def __init__(self, gmail_client, storage, owner_id: str):
        super().__init__(
            name="send_draft",
            description="Send a draft email. When user says 'send it', 'inviala', 'spedisci', call this tool. If no draft_id provided, sends the most recent draft."
        )
        self.gmail = gmail_client
        self.storage = storage
        self.owner_id = owner_id

    async def execute(self, draft_id: str = None):
        try:
            # If no draft_id, get the most recent draft
            if not draft_id:
                drafts = self.storage.list_drafts(self.owner_id)
                if not drafts:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        data=None,
                        error="No drafts found. Create a draft first."
                    )
                draft = drafts[0]  # Most recent
                draft_id = draft['id']
            else:
                # Get draft from Supabase
                draft = self.storage.get_draft(self.owner_id, draft_id)

            if not draft:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Draft not found: {draft_id}"
                )

            # Extract email details
            to_addresses = draft.get('to_addresses', [])
            to = ', '.join(to_addresses) if to_addresses else None
            subject = draft.get('subject', '')
            body = draft.get('body', '')
            in_reply_to = draft.get('in_reply_to')
            references = draft.get('references')
            thread_id = draft.get('thread_id')

            if not to:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error="Draft has no recipient address"
                )

            # Send via Gmail API
            sent_message = self.gmail.send_message(
                to=to,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
                references=' '.join(references) if references else None,
                thread_id=thread_id
            )

            # Mark draft as sent in Supabase
            self.storage.mark_draft_sent(
                self.owner_id,
                draft_id,
                sent_message.get('id', '')
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"message_id": sent_message.get('id')},
                message=f"📧 Email sent successfully!\n"
                        f"✉️  To: {to}\n"
                        f"📝 Subject: {subject}\n\n"
                        f"Email sent and draft marked as sent."
            )
        except Exception as e:
            logger.error(f"Failed to send draft: {e}")
            # Mark as failed if we have a draft_id
            if draft_id:
                try:
                    self.storage.update_draft(self.owner_id, draft_id, {
                        'status': 'failed',
                        'error_message': str(e)
                    })
                except Exception:
                    pass
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error sending email: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Send a draft email. If no draft_id provided, sends the most recent draft. IMPORTANT: Always confirm with the user before sending.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": "Draft ID to send (optional - uses most recent if not provided)"
                    }
                },
                "required": []
            }
        }


class _RefreshGoogleAuthTool(Tool):
    """Refresh Google OAuth authentication."""
    def __init__(self, gmail_client, calendar_client):
        super().__init__(
            name="refresh_google_auth",
            description="Refresh Google OAuth permissions for Gmail and Calendar"
        )
        self.gmail = gmail_client
        self.calendar = calendar_client

    async def execute(self):
        # In Supabase-only mode, we cannot start OAuth flows from the backend.
        # Users must use the CLI or dashboard to re-authenticate.
        return ToolResult(
            status=ToolStatus.ERROR,
            data=None,
            error="To refresh Google authentication, please use: /connect google reset\n"
                  "Then reconnect with: /connect google"
        )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Rinnova i permessi Google (Gmail e Calendar). Guida l'utente a usare /connect google per riautenticarsi.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }


class _SyncEmailsTool(Tool):
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
                error=f"Error during synchronization: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Sync emails from Gmail in BATCH mode (long operation, ~15-30 minutes). Analyzes with AI (summary, open/closed status, required actions) and saves to local cache. First sync: fixed 30 days (1 month). NOTE: In the future we'll use Gmail real-time notifications.",
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


class _SearchEmailsTool(Tool):
    """Search emails using Supabase hybrid search (FTS + semantic)."""
    def __init__(self, email_sync_manager, storage, owner_id: str):
        super().__init__(
            name="search_emails",
            description="Search emails with hybrid FTS + semantic search"
        )
        self.email_sync = email_sync_manager
        self.storage = storage
        self.owner_id = owner_id

    async def execute(
        self,
        query: Optional[str] = None,
        open_only: bool = False,
        expected_action: Optional[str] = None
    ):
        try:
            # Use Supabase hybrid search (FTS + semantic + exact pattern)
            if self.storage and query:
                emails = self.storage.search_emails(self.owner_id, query, limit=20)

                # Format results for LLM consumption
                results = []
                for email in emails:
                    results.append({
                        "subject": email.get("subject"),
                        "from": email.get("sender"),
                        "to": email.get("recipient"),
                        "cc": email.get("cc"),
                        "date": email.get("date"),
                        "body": email.get("body_text", ""),
                        # CRITICAL: Threading headers for replies
                        "message_id": email.get("message_id"),
                        "in_reply_to": email.get("in_reply_to"),
                        "references": email.get("references"),
                        "thread_id": email.get("thread_id"),
                        "gmail_id": email.get("gmail_id"),
                        # Search score for ranking info
                        "score": email.get("combined_score", email.get("score", 0))
                    })

                message = f"Found {len(emails)} emails matching '{query}'"
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"threads": results, "total": len(emails)},
                    message=message
                )

            # Fallback: no query provided
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"threads": [], "total": 0},
                message="No search query provided. Use 'query' parameter to search emails."
            )

        except Exception as e:
            logger.error(f"Email search failed: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Search failed: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Search emails using hybrid FTS + semantic search. Finds emails by keywords, names, or topics. IMPORTANT: Results include threading headers (message_id, in_reply_to, references, thread_id) needed to create draft replies that stay in the conversation thread.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - keywords, names, or topics to find in emails"
                    }
                },
                "required": ["query"]
            }
        }


class _CloseEmailThreadTool(Tool):
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
                    message="No conversations found with these subjects"
                )

            # Format message
            threads_list = '\n'.join([
                f"  - {t['subject']}"
                for t in results['threads']
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


class _EmailStatsTool(Tool):
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
            "description": "Shows statistics on cached emails: how many conversations, how many open, how many require response/reminder. Use when user asks 'what do I need to do today?' or 'do I have emails to read?'",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }


class _GetTasksTool(Tool):
    """Get open tasks from task_items table.

    Returns formatted task list from Supabase task_items.
    """

    def __init__(self, session_state: SessionState):
        super().__init__(
            name="get_tasks",
            description="ALWAYS use this tool when user asks about tasks, to-dos, what they need to do, pending actions, what needs attention, or anything related to their task list. Returns task data instantly. Do NOT answer from memory - ALWAYS call this tool for task queries."
        )
        self.session_state = session_state

    async def execute(self, days_back: int = 7):
        from zylch.storage.supabase_client import SupabaseStorage

        owner_id = self.session_state.get_owner_id()
        if not owner_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={},
                message="No owner_id available. Please log in first."
            )

        try:
            supabase = SupabaseStorage()

            result = supabase.client.table('task_items')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('action_required', True)\
                .order('analyzed_at', desc=True)\
                .execute()

            tasks = result.data or []

            # Sort by urgency: high -> medium -> low
            urgency_order = {'high': 0, 'medium': 1, 'low': 2}
            tasks = sorted(tasks, key=lambda t: urgency_order.get(t.get('urgency'), 9))

            # Group by urgency: high -> medium -> low (no limits)
            high_medium = [t for t in tasks if t.get('urgency') in ('high', 'medium')]
            low = [t for t in tasks if t.get('urgency') == 'low']
            tasks = high_medium + low

            if not tasks:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={'count': 0},
                    message="No pending tasks found."
                )

            # Format task list
            lines = []
            for i, task in enumerate(tasks, 1):
                urgency = task.get('urgency', 'medium')
                icon = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(urgency, '⚪')
                contact = task.get('contact_email') or task.get('contact_name') or 'Unknown'
                action = task.get('suggested_action', 'Review')
                lines.append(f"{i}. {icon} **{contact}** - {action}")

            message = f"**Tasks requiring action ({len(tasks)}):**\n\n" + "\n".join(lines)
            message += "\n\nUse 'more on #N' to see details for a specific task."

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={'count': len(tasks)},
                message=message
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Failed to get tasks: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "ALWAYS use this tool when user asks about tasks, to-dos, what they need to do, pending actions, what needs attention, or anything related to their task list. Do NOT answer task queries from conversation history - ALWAYS call this tool.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "Days to look back (default 7)",
                        "default": 7
                    }
                },
                "required": []
            }
        }


class _SearchLocalMemoryTool(Tool):
    """Search local memory (blobs) for person info using hybrid FTS + semantic search.

    ZYLCH IS PERSON-CENTRIC: A person can have multiple emails/phones.
    This tool uses hybrid search (FTS + semantic) for better recall and precision.

    Flow:
    1. User asks "info su Luigi"
    2. Hybrid search combines FTS and semantic search for best results
    3. Returns top results ranked by hybrid_score (FTS + semantic)
    """

    def __init__(
        self,
        search_engine: Optional[HybridSearchEngine] = None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant"
    ):
        super().__init__(
            name="search_local_memory",
            description="Search local memory for person/contact info using hybrid FTS + semantic search. ALWAYS call this FIRST before remote searches (Gmail, StarChat, web). Returns ranked results by relevance."
        )
        self.search_engine = search_engine
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

    async def execute(self, query: str) -> ToolResult:
        """Search for a person in local memory using hybrid FTS + semantic search.

        Args:
            query: Search query - can be email, phone, or name

        Returns:
            ToolResult with ranked person data or not_found status
        """
        if not query or not query.strip():
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="Query cannot be empty"
            )

        query = query.strip()

        try:
            # Use hybrid search if available for better results
            if self.search_engine:
                contacts_namespace = f"{self.owner_id}:{self.zylch_assistant_id}:contacts"

                results = self.search_engine.search(
                    owner_id=self.owner_id,
                    query=query,
                    namespace=contacts_namespace,
                    limit=5
                )

                if not results:
                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        data={"not_found": True, "query": query},
                        message=f"No contacts found for '{query}'. Proceed with remote searches."
                    )

                # Format results with hybrid scores
                output = [f"Found {len(results)} contacts:"]
                formatted_results = []

                for r in results:
                    # Extract person data from result
                    person_data = {
                        "namespace": r.namespace,
                        "content": r.content,
                        "hybrid_score": round(r.hybrid_score, 2),
                        "fts_score": round(r.fts_score, 2) if r.fts_score else None,
                        "semantic_score": round(r.semantic_score, 2) if r.semantic_score else None,
                    }

                    formatted_results.append(person_data)
                    output.append(f"\n**{r.namespace}** (score: {r.hybrid_score:.2f})")
                    output.append(person_data["content"])

                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={
                        "found": True,
                        "results": formatted_results,
                        "count": len(results),
                        "query": query
                    },
                    message="\n".join(output)
                )

            # No search engine available
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"not_found": True},
                message="Search engine not initialized. Proceed with remote searches."
            )

        except Exception as e:
            logger.error(f"Error searching local memory: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data={"not_found": True},
                error=f"Error searching local memory: {e}. Proceed with remote searches."
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Search local memory (blobs) for person/contact info. CRITICAL: ALWAYS call this FIRST when user asks about a person (e.g., 'info on Luigi', 'who is Mario?', 'tell me about Connecto'). This avoids expensive 10+ second remote API calls if data is already cached.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query: email address, phone number, or person name"
                    }
                },
                "required": ["query"]
            }
        }


class _GetContactTool(Tool):
    """Tool to retrieve saved contact from MrCall assistant."""
    def __init__(self, starchat_client, session_state: SessionState):
        super().__init__(
            name="get_contact",
            description="Retrieve a saved contact from the selected MrCall assistant's contact list"
        )
        self.starchat = starchat_client
        self.session_state = session_state

    async def execute(
        self,
        email: Optional[str] = None,
        contact_id: Optional[str] = None,
    ):
        # Check if business is selected
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No MrCall assistant selected. Use /mrcall <id> to select one."
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
                logger.info(f"🔍 Calling search_contacts with business_id={business_id}")
                contacts = await self.starchat.search_contacts(
                    email=email,
                    business_id=business_id
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


class _GetWhatsAppContactsTool(Tool):
    """Get contacts from WhatsApp messages via StarChat."""
    def __init__(self, starchat_client, session_state: SessionState):
        super().__init__(
            name="get_whatsapp_contacts",
            description="Get contacts from WhatsApp messages to identify people by phone number"
        )
        self.starchat = starchat_client
        self.session_state = session_state

    async def execute(self, days_back: int = 30):
        """Get WhatsApp contacts for the selected business.

        Args:
            days_back: Number of days to look back for messages
        """
        # Check if business is selected
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No MrCall assistant selected. Use /mrcall <id> to select one."
            )

        try:
            whatsapp_contacts = await self.starchat.get_whatsapp_contacts(
                business_id=business_id,
                days_back=days_back
            )

            if not whatsapp_contacts:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"contacts": []},
                    message="⚠️  WhatsApp integration requires StarChat REST API endpoint for WhatsApp messages. "
                            "This feature is pending StarChat API implementation. See STARCHAT_REQUESTS.md Request #3."
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"contacts": whatsapp_contacts, "total": len(whatsapp_contacts)},
                message=f"✅ Found {len(whatsapp_contacts)} WhatsApp contacts in the last {days_back} days"
            )

        except Exception as e:
            logger.error(f"Failed to get WhatsApp contacts: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error retrieving WhatsApp contacts: {str(e)}"
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": "Get contacts from WhatsApp messages via StarChat PostgreSQL database. Extracts phone numbers from whatsapp_messages table and matches them against StarChat contacts. Use this to identify contacts by phone number from WhatsApp conversations.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days to look back for WhatsApp messages (default: 30)",
                        "default": 30
                    }
                },
                "required": []
            }
        }


class _SearchPipedrivePersonTool(Tool):
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
                    message=f"No person found in Pipedrive for: {email}"
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
                error=f"Pipedrive search error: {str(e)}"
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


class _GetPipedrivePersonDealsTool(Tool):
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
                    message="No deals found with specified filters"
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
                error=f"Error retrieving deals: {str(e)}"
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


class _ComposeEmailTool(Tool):
    """Write an email with full context from memory and hybrid search.

    Gathers context using:
    - PERSON, COMPANY, TEMPLATE blobs from hybrid search
    - Task sources if task_num is provided
    - Recipient info if provided

    The emailer agent uses LLM to generate contextual emails.
    """

    def __init__(
        self,
        session_state: SessionState,
        api_key: str,
        provider: str = "anthropic"
    ):
        super().__init__(
            name="compose_email",
            description="Write an email with full context from memory and email history. Use this to compose emails about a person, company, or topic - the tool will gather relevant context automatically."
        )
        self.session_state = session_state
        self.api_key = api_key
        self.provider = provider
        self._agent = None  # Lazy initialization

    def _get_agent(self):
        """Lazily initialize EmailerAgent."""
        if self._agent is None:
            from zylch.agents.emailer_agent import EmailerAgent
            from zylch.storage.supabase_client import SupabaseStorage

            owner_id = self.session_state.get_owner_id()
            if not owner_id:
                raise ValueError("No owner_id available. Please log in first.")

            storage = SupabaseStorage.get_instance()
            self._agent = EmailerAgent(
                storage=storage,
                owner_id=owner_id,
                api_key=self.api_key,
                provider=self.provider
            )
        return self._agent

    async def execute(
        self,
        request: str,
        recipient_email: Optional[str] = None,
        task_num: Optional[int] = None,
    ) -> ToolResult:
        """Compose an email based on request and context.

        Args:
            request: What to write (e.g., "scrivi a Mario un'offerta")
            recipient_email: Optional email extracted from conversation
            task_num: Optional 1-indexed task number from /tasks

        Returns:
            ToolResult with composed email and auto-saved draft
        """
        try:
            agent = self._get_agent()

            result = await agent.compose(
                user_request=request,
                recipient_email=recipient_email,
                task_num=task_num
            )

            subject = result.get('subject', '(no subject)')
            body = result.get('body', '')

            # Auto-save draft in Supabase
            owner_id = self.session_state.get_owner_id()
            from zylch.storage.supabase_client import SupabaseStorage
            storage = SupabaseStorage.get_instance()

            # Use recipient from result if not provided (extracted from thread)
            to_email = recipient_email or result.get('recipient_email')
            to_addresses = [to_email] if to_email else []

            # Create draft with threading headers (for replies to stay in thread)
            draft = storage.create_draft(
                owner_id=owner_id,
                to=to_addresses,
                subject=subject,
                body=body,
                in_reply_to=result.get('in_reply_to'),
                references=result.get('references'),
                thread_id=result.get('thread_id'),
            )

            draft_id = draft.get('id', '') if draft else ''
            to_display = to_email or '(not specified)'

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={**result, "draft_id": draft_id},
                message=f"""**📝 Draft Saved** (ID: `{draft_id}`)

**To:** {to_display}
**Subject:** {subject}

{body}

---
Say "send it" when ready - I'll send it for you."""
            )
        except Exception as e:
            logger.error(f"Failed to compose email: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error composing email: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Write an email with full context from memory and email history. Gathers PERSON, COMPANY, TEMPLATE blobs via hybrid search. If task_num is provided, includes task sources. Use for: replies, new emails to contacts, formal proposals, etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "What to write (e.g., 'reply to Mario about the proposal', 'scrivi un'offerta per Acme Corp')"
                    },
                    "recipient_email": {
                        "type": "string",
                        "description": "Recipient email address (optional - extracted from conversation if replying)"
                    },
                    "task_num": {
                        "type": "integer",
                        "description": "Task number from /tasks output (optional - includes task context)"
                    }
                },
                "required": ["request"]
            }
        }
