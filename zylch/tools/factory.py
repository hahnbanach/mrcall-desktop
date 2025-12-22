"""Tool factory for centralizing tool initialization."""

import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import anthropic

from .base import Tool, ToolResult, ToolStatus


class SessionState:
    """Shared session state that can be updated at runtime.

    This allows tools to access current values (like business_id, owner_id) that may
    change during the session (e.g., when user runs /mrcall <id>).
    """
    def __init__(self, business_id: Optional[str] = None, owner_id: Optional[str] = None):
        self.business_id = business_id
        self.owner_id = owner_id

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


from .config import ToolConfig
from ..config import settings
from zylch_memory import HybridSearchEngine
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
from ..cache.json_cache import JSONCache
from ..cache.identifier_map import IdentifierMapCache, normalize_phone, normalize_name
from .email_archive import EmailArchiveManager
from .email_sync import EmailSyncManager
# TaskManager removed - legacy file-based system replaced by Supabase avatars
from ..memory import ZylchMemory, ZylchMemoryConfig
from ..assistant.models import ModelSelector
from .instruction_tools import (
    AddTriggeredInstructionTool,
    ListTriggeredInstructionsTool,
    RemoveTriggeredInstructionTool,
)
from .sms_tools import (
    SendSMSTool,
    SendVerificationCodeTool,
    VerifyCodeTool,
)
from .call_tools import InitiateCallTool
from .scheduler_tools import (
    ScheduleReminderTool,
    ScheduleConditionalTool,
    CancelConditionalTool,
    ListScheduledJobsTool,
    CancelJobTool,
)
from ..services.scheduler import ZylchScheduler

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
                # Pass owner_id to enable Supabase token storage
                # Note: credentials_path is not used when owner_id is provided (uses Supabase)
                email_client = GmailClient(
                    credentials_path="credentials/gmail_oauth.json",  # Not used with owner_id
                    token_dir=config.google_token_path,
                    account=config.user_email,  # Isolate tokens per user account
                    owner_id=config.owner_id if config.owner_id != "owner_default" else None,
                )
                logger.info("Using Gmail for email")

                # Try to authenticate Google services silently
                try:
                    # Check Supabase first if owner_id is set, then fallback to local
                    from ..api import token_storage
                    has_creds = False
                    if config.owner_id and config.owner_id != "owner_default":
                        has_creds = token_storage.has_google_credentials(config.owner_id)
                    if not has_creds:
                        # Fallback to local token file
                        token_path = Path(config.google_token_path) / "token.pickle"
                        has_creds = token_path.exists()

                    if has_creds:
                        email_client.authenticate()
                        logger.info("Google services authenticated (Gmail)")
                    else:
                        logger.warning("Google authentication needed - tokens not found")
                except Exception as e:
                    logger.warning(f"Google authentication needed: {e}")

            # Calendar client (conditional based on provider)
            calendar = None
            if config.auth_provider == "google":
                # Gmail users get Google Calendar automatically
                # Pass owner_id to enable Supabase token storage
                # Note: credentials_path is not used when owner_id is provided (uses Supabase)
                calendar = GoogleCalendarClient(
                    credentials_path="credentials/gmail_oauth.json",  # Not used with owner_id
                    token_dir=config.google_token_path,
                    calendar_id=config.calendar_id,
                    account=config.user_email,
                    owner_id=config.owner_id if config.owner_id != "owner_default" else None,
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

            # Cache
            cache = JSONCache(
                cache_dir=config.cache_dir,
                ttl_days=config.cache_ttl_days,
            )

            # Identifier map cache for person-centric lookups (7-day TTL)
            identifier_cache = IdentifierMapCache(
                cache_dir=config.cache_dir,
                ttl_days=7  # Freshness TTL for contacts
            )

            # Email archive manager (lazy auth - won't fail if Gmail not configured)
            email_archive = None
            try:
                email_archive = EmailArchiveManager(gmail_client=email_client)
            except Exception as e:
                logger.warning(f"EmailArchiveManager initialization skipped: {e}")

            # Email sync manager
            email_sync = None
            if email_archive:
                email_sync = EmailSyncManager(
                    email_archive=email_archive,
                    cache_dir=config.cache_dir + "/emails",
                    anthropic_api_key=config.anthropic_api_key,
                    days_back=30,
                )

            # Pipedrive CRM client (optional)
            pipedrive = None
            if config.pipedrive_enabled and config.pipedrive_api_token:
                try:
                    pipedrive = PipedriveClient(api_token=config.pipedrive_api_token)
                    logger.info("Pipedrive CRM connected")
                except Exception as e:
                    logger.warning(f"Pipedrive connection failed: {e}")
                    pipedrive = None

            # Vonage SMS: credentials are loaded dynamically per-user in SendSMSTool.execute()
            # No client initialization needed here - tool is always available

            # Initialize zylch_memory for person-centric memory
            zylch_memory = await ToolFactory.create_memory_system(config)

            # Initialize hybrid search engine for better memory search
            search_engine = None
            if zylch_memory:
                from zylch.storage.supabase_client import SupabaseStorage
                supabase_storage = SupabaseStorage.get_instance()
                search_engine = HybridSearchEngine(
                    supabase_client=supabase_storage.client,
                    embedding_engine=zylch_memory.embedding_engine,
                    default_alpha=0.3  # FTS weight (0.3 = 70% semantic, 30% FTS)
                )
                logger.info("Hybrid search engine initialized")

            # TaskManager removed - legacy file-based system replaced by Supabase avatars
            # Tasks are now served by get_tasks tool which queries pre-computed avatars

        except Exception as e:
            logger.error(f"Failed to initialize service clients: {e}")
            raise

        # Initialize tools list
        tools = []

        # Email tools (7-8 tools, +1 if zylch_memory) - Gmail or Outlook
        tools.extend(ToolFactory._create_gmail_tools(
            email_client, calendar, email_sync, zylch_memory,
            starchat, identifier_cache, config.owner_id, config.zylch_assistant_id,
            anthropic_api_key=config.anthropic_api_key
        ))

        # Email sync tools (4 tools)
        tools.extend(ToolFactory._create_email_sync_tools(email_sync))

        # Task management tools removed - legacy file-based system
        # Tasks now served by get_tasks tool (line ~380) which queries Supabase avatars

        # Contact tools (5 tools) - use session_state for dynamic business_id
        # Includes search_local_memory with hybrid FTS + semantic search
        tools.extend(ToolFactory._create_contact_tools(
            starchat,
            session_state,
            zylch_memory,
            identifier_cache,
            search_engine,
            config.owner_id,
            config.zylch_assistant_id
        ))

        # Calendar tools (4 tools)
        tools.extend(ToolFactory._create_calendar_tools(calendar))

        # Web search tool (1 tool)
        tools.append(WebSearchTool(anthropic_api_key=config.anthropic_api_key))

        # Pipedrive tools (2 tools) - optional
        if pipedrive:
            tools.extend(ToolFactory._create_pipedrive_tools(pipedrive))

        # MrCall configuration tools (3 tools) - requires StarChat
        if starchat:
            tools.extend(ToolFactory._create_mrcall_tools(
                starchat_client=starchat,
                session_state=session_state,
                zylch_memory=zylch_memory,
                anthropic_api_key=config.anthropic_api_key
            ))

        # Sharing tools (4 tools) - for intelligence sharing between users
        if config.user_email:
            sharing_tools = ToolFactory._create_sharing_tools(
                zylch_memory=zylch_memory,
                cache_dir=config.cache_dir,
                owner_id=config.owner_id,
                user_email=config.user_email,
                user_display_name=config.user_display_name if hasattr(config, 'user_display_name') else None
            )
            tools.extend(sharing_tools)
            logger.info(f"Sharing tools initialized ({len(sharing_tools)} tools)")

        # Triggered instruction tools (3 tools) - for event-driven automation
        tools.extend(ToolFactory._create_trigger_tools(
            zylch_memory=zylch_memory,
            owner_id=config.owner_id,
            zylch_assistant_id=config.zylch_assistant_id
        ))
        logger.info("Triggered instruction tools initialized")

        # SMS tools (always available - credentials loaded per-user at execution time)
        tools.extend(ToolFactory._create_sms_tools(
            session_state=session_state,
            zylch_memory=zylch_memory,
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

        # Scheduler tools (5 tools) - for reminders and timed actions
        scheduler_db_path = Path(config.cache_dir) / "scheduler.db"
        scheduler = ZylchScheduler(
            db_path=scheduler_db_path,
            owner_id=config.owner_id,
            zylch_assistant_id=config.zylch_assistant_id
        )
        scheduler.start()
        tools.extend(ToolFactory._create_scheduler_tools(scheduler))
        logger.info("Scheduler tools initialized (APScheduler)")

        # Get Tasks tool - returns pre-formatted task list from avatars
        # Much faster than having Claude format the list (~5s vs 27s)
        tools.append(_GetTasksTool(session_state=session_state))
        logger.info("Get Tasks tool initialized (pre-computed avatars)")

        # Store service client references for CLI access
        ToolFactory._starchat_client = starchat
        ToolFactory._email_archive = email_archive

        logger.info(f"Initialized {len(tools)} tools")
        return tools, session_state

    @staticmethod
    async def create_memory_system(config: ToolConfig) -> ZylchMemory:
        """Create and initialize memory system.

        Args:
            config: Tool configuration

        Returns:
            Initialized ZylchMemory instance
        """
        memory_config = ZylchMemoryConfig(
            db_path=Path(config.cache_dir) / "zylch_memory.db",
            index_dir=Path(config.cache_dir) / "indices"
        )
        memory = ZylchMemory(config=memory_config)
        logger.info("ZylchMemory system initialized (semantic search enabled)")
        return memory

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
        email_sync_manager=None,
        zylch_memory=None,
        starchat_client=None,
        identifier_cache=None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
        anthropic_api_key: str = ""
    ) -> List[Tool]:
        """Create Gmail-related tools."""
        tools = [
            _GmailSearchTool(gmail_client, zylch_memory, identifier_cache, owner_id, zylch_assistant_id),
            _CreateDraftTool(gmail_client),
            _ListDraftsTool(gmail_client),
            _EditDraftTool(gmail_client),
            _UpdateDraftTool(gmail_client),
            _SendDraftTool(gmail_client, email_sync_manager),
            _RefreshGoogleAuthTool(gmail_client, calendar_client),
        ]

        # Add memory-based draft tool if zylch_memory available and API key present
        if zylch_memory and starchat_client and anthropic_api_key:
            tools.append(_DraftEmailFromMemoryTool(
                gmail_client,
                zylch_memory,
                starchat_client,
                owner_id,
                zylch_assistant_id,
                anthropic_api_key=anthropic_api_key
            ))

        return tools

    @staticmethod
    def _create_email_sync_tools(email_sync_manager) -> List[Tool]:
        """Create email sync tools."""
        return [
            _SyncEmailsTool(email_sync_manager),
            _SearchEmailsTool(email_sync_manager),
            _CloseEmailThreadTool(email_sync_manager),
            _EmailStatsTool(email_sync_manager),
        ]

    # _create_task_tools removed - legacy file-based system replaced by Supabase avatars
    # Tasks are now served by get_tasks tool which queries pre-computed avatars

    @staticmethod
    def _create_contact_tools(
        starchat_client,
        session_state: SessionState,
        zylch_memory=None,
        identifier_cache: IdentifierMapCache = None,
        search_engine: Optional[HybridSearchEngine] = None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant"
    ) -> List[Tool]:
        """Create contact management tools.

        ZYLCH IS PERSON-CENTRIC: A person can have multiple emails/phones.
        search_local_memory provides fast O(1) lookup before expensive remote calls.
        """
        return [
            _SearchLocalMemoryTool(zylch_memory, identifier_cache, search_engine, owner_id, zylch_assistant_id),
            _SaveContactTool(starchat_client, session_state, zylch_memory, identifier_cache, owner_id, zylch_assistant_id),
            _GetContactTool(starchat_client, session_state),
            _ListContactsTool(starchat_client, session_state),
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
        zylch_memory,
        anthropic_api_key: str
    ) -> List[Tool]:
        """Create MrCall assistant configuration tools.

        These tools enable natural language configuration of MrCall assistants.
        Features:
        - Two-level memory: Admin (global rules) + Business (per-assistant)
        - Preview + confirm workflow for all changes
        - Variable preservation during prompt modifications
        """
        from .mrcall import (
            GetAssistantCatalogTool,
            ConfigureAssistantTool,
            SaveMrCallAdminRuleTool,
        )

        return [
            GetAssistantCatalogTool(starchat_client, session_state),
            ConfigureAssistantTool(
                starchat_client,
                session_state,
                zylch_memory,
                anthropic_api_key
            ),
            SaveMrCallAdminRuleTool(starchat_client, session_state, zylch_memory),
        ]

    @staticmethod
    def _create_sharing_tools(
        zylch_memory,
        cache_dir: str,
        owner_id: str,
        user_email: str,
        user_display_name: Optional[str] = None
    ) -> List[Tool]:
        """Create intelligence sharing tools.

        These tools enable sharing contact intelligence between Zylch users.
        Features:
        - Share intel with authorized recipients
        - Retrieve shared intel when looking up contacts
        - Accept/reject share requests
        """
        from .sharing_tools import (
            ShareContactIntelTool,
            GetSharedIntelTool,
            AcceptShareRequestTool,
            RejectShareRequestTool,
        )
        from ..sharing import SharingAuthorizationManager, IntelShareManager

        # Initialize sharing managers
        sharing_db_path = Path(cache_dir) / "sharing.db"
        auth_manager = SharingAuthorizationManager(db_path=sharing_db_path)
        intel_share_manager = IntelShareManager(
            zylch_memory=zylch_memory,
            auth_manager=auth_manager
        )

        # Register current user
        if user_email:
            auth_manager.register_user(
                owner_id=owner_id,
                email=user_email,
                display_name=user_display_name
            )

        return [
            ShareContactIntelTool(
                intel_share_manager=intel_share_manager,
                auth_manager=auth_manager,
                owner_id=owner_id,
                user_email=user_email,
                user_display_name=user_display_name
            ),
            GetSharedIntelTool(
                intel_share_manager=intel_share_manager,
                owner_id=owner_id,
                user_email=user_email
            ),
            AcceptShareRequestTool(
                intel_share_manager=intel_share_manager,
                auth_manager=auth_manager,
                owner_id=owner_id,
                user_email=user_email
            ),
            RejectShareRequestTool(
                auth_manager=auth_manager,
                user_email=user_email
            ),
        ]

    @staticmethod
    def _create_trigger_tools(
        zylch_memory,
        owner_id: str,
        zylch_assistant_id: str
    ) -> List[Tool]:
        """Create triggered instruction tools.

        These tools allow users to create event-driven automation that executes
        when specific triggers occur. For example:
        - "All'inizio di ogni sessione devi dirmi Buongiorno Mario..." (session_start)
        - "When a new email arrives from someone I don't know, create a contact" (email_received)
        - "When a prospect replies, invite them to call the demo number" (email_received)
        """
        return [
            AddTriggeredInstructionTool(
                zylch_memory=zylch_memory,
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id
            ),
            ListTriggeredInstructionsTool(
                zylch_memory=zylch_memory,
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id
            ),
            RemoveTriggeredInstructionTool(
                zylch_memory=zylch_memory,
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id
            ),
        ]

    @staticmethod
    def _create_sms_tools(
        session_state,
        zylch_memory,
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
                zylch_memory=zylch_memory,
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id
            ),
            VerifyCodeTool(
                zylch_memory=zylch_memory,
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id
            ),
        ]

    @staticmethod
    def _create_scheduler_tools(scheduler) -> List[Tool]:
        """Create scheduler tools for reminders and timed actions.

        Tools:
        - schedule_reminder: Schedule a one-time reminder
        - schedule_conditional: Schedule action if condition not met in time
        - cancel_conditional: Cancel a conditional timeout
        - list_scheduled_jobs: List all pending jobs
        - cancel_scheduled_job: Cancel a job by ID
        """
        return [
            ScheduleReminderTool(scheduler=scheduler),
            ScheduleConditionalTool(scheduler=scheduler),
            CancelConditionalTool(scheduler=scheduler),
            ListScheduledJobsTool(scheduler=scheduler),
            CancelJobTool(scheduler=scheduler),
        ]


# ============================================================================
# INLINE TOOL DEFINITIONS
# These are extracted from CLI but kept as private classes in this module
# ============================================================================

class _GmailSearchTool(Tool):
    """Gmail search tool for contact enrichment with auto-caching."""
    def __init__(
        self,
        gmail_client,
        zylch_memory=None,
        identifier_cache=None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant"
    ):
        super().__init__(
            name="search_gmail",
            description="Search Gmail for emails from or to a contact to understand relationship"
        )
        self.gmail = gmail_client
        self.zylch_memory = zylch_memory
        self.identifier_cache = identifier_cache
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

    def _auto_cache_contact(self, contact_name: str, email: str, message_count: int) -> Optional[int]:
        """Auto-cache contact in ZylchMemory after successful Gmail search.

        This saves the contact locally so future searches are instant (no Gmail API call needed).

        Args:
            contact_name: Name of the contact (if known)
            email: Email address
            message_count: Number of email exchanges found

        Returns:
            Memory ID if saved, None otherwise
        """
        if not self.zylch_memory or not self.identifier_cache:
            return None

        try:
            contacts_namespace = f"{self.owner_id}:{self.zylch_assistant_id}:contacts"

            # Build a minimal memory entry from Gmail search results
            memory_parts = []
            if contact_name:
                memory_parts.append(f"Name: {contact_name}")
            if email:
                memory_parts.append(f"Email: {email}")
            memory_parts.append(f"Gmail exchanges: {message_count}")
            memory_parts.append(f"Source: Gmail search auto-cache")

            memory_content = " | ".join(memory_parts)
            display_name = contact_name or email

            # Store in ZylchMemory (with reconsolidation - will update if similar exists)
            memory_id_str = self.zylch_memory.store_memory(
                namespace=contacts_namespace,
                category="person",
                context=f"Contact discovered via Gmail search: {display_name}",
                pattern=memory_content,
                examples=[],
                confidence=0.6  # Lower confidence for auto-cached (not explicitly saved)
            )
            memory_id = int(memory_id_str) if memory_id_str else None

            # Register identifiers for O(1) lookup
            if memory_id:
                identifiers = []
                if email:
                    identifiers.append(("email", email))
                if contact_name:
                    identifiers.append(("name", contact_name))

                self.identifier_cache.register(
                    identifiers=identifiers,
                    memory_id=memory_id,
                    owner_id=self.owner_id,
                    assistant_id=self.zylch_assistant_id
                )
                logger.info(f"Auto-cached contact from Gmail search: {display_name} (memory_id={memory_id})")

            return memory_id

        except Exception as e:
            logger.warning(f"Failed to auto-cache contact (non-fatal): {e}")
            return None

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
                    "snippet": msg["snippet"][:200]
                } for msg in unique_messages[:10]]
            }

            date_to = datetime.now().strftime("%Y-%m-%d")
            message = f"Found {len(unique_messages)} email exchanges (from {date_from} to {date_to})"
            if len(emails_to_search) > 1:
                message += f" [searched {len(emails_to_search)} email addresses]"
            if warning:
                message = f"{warning}\n{message}"
            if not search_all_history and len(unique_messages) == 0:
                message += "\n💡 No results in last year. Use search_all_history=true to search from 2020 (more expensive)."

            # AUTO-CACHE: Save contact to local memory for instant future lookups
            # This means next time user asks about this contact, no Gmail API call needed!
            if len(unique_messages) > 0:
                # Determine contact name (original query if it's a name, or extract from messages)
                contact_name = contact if not self._is_email(contact) else None

                # Try to extract name from message headers if we only have email
                if not contact_name and unique_messages:
                    for msg in unique_messages[:3]:
                        from_email, from_name = self._extract_email_from_header(msg.get('from', ''))
                        if from_name and from_email in emails_to_search:
                            contact_name = from_name
                            break

                # Cache each email found
                for email_addr in emails_to_search:
                    self._auto_cache_contact(
                        contact_name=contact_name,
                        email=email_addr,
                        message_count=len(unique_messages)
                    )

                message += "\n✅ Contact auto-cached for instant future lookups."

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
                        f"The draft is now available in Gmail Drafts folder. "
                        f"You can review and send it anytime."
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


class _ListDraftsTool(Tool):
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
                    message="📭 No drafts found in Gmail."
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
            "description": "List all draft emails currently saved in Gmail. Returns draft IDs, recipients, subjects, and previews.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }


class _EditDraftTool(Tool):
    """Edit a Gmail draft interactively with nano editor."""
    def __init__(self, gmail_client):
        super().__init__(
            name="edit_gmail_draft",
            description="Open a Gmail draft in nano editor for manual editing"
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
    """Send a Gmail draft."""
    def __init__(self, gmail_client, email_sync_manager=None):
        super().__init__(
            name="send_gmail_draft",
            description="Send a Gmail draft email"
        )
        self.gmail = gmail_client
        self.email_sync = email_sync_manager

    async def execute(self, draft_id: str):
        try:
            # Get draft details before sending
            draft = self.gmail.get_draft(draft_id)

            # Send the draft
            sent_message = self.gmail.send_draft(draft_id)

            # Auto-sync email cache after send (updates threads.json and gap analysis)
            if self.email_sync:
                logger.info("🔄 Syncing email cache after send...")
                try:
                    sync_result = self.email_sync.sync_emails(
                        days_back=1,  # Only last 24 hours (fast incremental)
                        force_full=False
                    )
                    updated = sync_result.get('updated_threads', 0)
                    logger.info(f"✅ Cache updated: {updated} threads refreshed")
                except Exception as e:
                    # Non-critical - user can manually run /sync if needed
                    logger.warning(f"Post-send cache sync failed (non-critical): {e}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"message_id": sent_message.get('id')},
                message=f"📧 Email sent successfully!\n"
                        f"✉️  To: {draft['to']}\n"
                        f"📝 Subject: {draft['subject']}\n\n"
                        f"Email sent and draft removed from Drafts folder."
            )
        except Exception as e:
            logger.error(f"Failed to send draft: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error sending email: {str(e)}"
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
        try:
            # Delete existing tokens to force re-authentication
            import shutil

            token_dir = Path(settings.google_token_path)
            if token_dir.exists():
                shutil.rmtree(token_dir)
                token_dir.mkdir(parents=True, exist_ok=True)

            # Re-authenticate
            logger.info("🔐 Opening browser for Google authentication...")
            print("\n🔐 Opening browser window for Google authentication...")
            print("   Authorize access to Gmail and Calendar in the browser window that opens.\n")

            self.gmail.authenticate()

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={"authenticated": True},
                message="Google authentication completed successfully! Now have access to Gmail and Calendar."
            )
        except Exception as e:
            logger.error(f"Failed to refresh Google auth: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error during authentication: {str(e)}"
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


class _DraftEmailFromMemoryTool(Tool):
    """Draft email using person-centric memory (relationship + business context)."""
    def __init__(
        self,
        gmail_client,
        zylch_memory,
        starchat_client,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
        anthropic_api_key: str = ""
    ):
        super().__init__(
            name="draft_email_from_memory",
            description="Draft personalized email using relationship memory, business info, and user style"
        )
        self.gmail = gmail_client
        self.zylch_memory = zylch_memory
        self.starchat = starchat_client
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)

    async def execute(
        self,
        contact_email: str,
        topic: str,
        user_id: str = "mario"
    ):
        """Draft email using multi-namespace memory retrieval.

        Args:
            contact_email: Recipient email address
            topic: Email topic/purpose (e.g., "offerta servizi outbound")
            user_id: User identifier (default: "mario")
        """
        try:
            # Get contact_id from StarChat (async context - use await)
            contact = None
            try:
                contact = await self.starchat.get_contact_by_email(contact_email)
            except Exception as e:
                logger.debug(f"Contact not found in StarChat for {contact_email}: {e}")

            contact_id = contact.get('id') if contact else f"email_{contact_email.replace('@', '_at_')}"

            # 1. Retrieve person memory (multi-tenant namespace)
            person_namespace = f"{self.owner_id}:{self.zylch_assistant_id}:{contact_id}"
            person_memories = self.zylch_memory.retrieve_memories(
                query=f"relationship communication style preferences {topic}",
                namespace=person_namespace,
                category="person",
                limit=3
            )

            # 2. Retrieve user style memory (assistant-level namespace)
            assistant_namespace = f"{self.owner_id}:{self.zylch_assistant_id}"
            user_memories = self.zylch_memory.retrieve_memories(
                query=f"email writing style {topic}",
                namespace=assistant_namespace,
                category="style",
                limit=2
            )

            # 3. Retrieve business memory (ALWAYS, as "reference text")
            # First: get core identity (mission, values, what we do)
            business_identity = self.zylch_memory.retrieve_memories(
                query="company mission values services core business identity",
                namespace=assistant_namespace,
                category="business",
                limit=5
            )

            # Second: get topic-specific info (services, pricing, policies)
            business_specific = self.zylch_memory.retrieve_memories(
                query=f"business services products pricing policies {topic}",
                namespace=assistant_namespace,
                category="business",
                limit=3
            )

            # Build context sections
            person_context = "\n".join([
                f"- {m['pattern']}" for m in person_memories
            ]) if person_memories else "No relationship information available."

            user_context = "\n".join([
                f"- {m['pattern']}" for m in user_memories
            ]) if user_memories else "Use standard professional style."

            # Business identity: always remember what we do
            business_identity_text = "\n".join([
                f"- {m['pattern']}" for m in business_identity
            ]) if business_identity else "We sell AI phone assistants and business communication services, NOTHING else."

            # Topic-specific business info
            business_specific_text = "\n".join([
                f"- {m['pattern']}" for m in business_specific
            ]) if business_specific else ""

            # Compose prompt for Claude
            prompt = f"""Write a professional email draft for {contact_email} on topic: {topic}

╔═══════════════════════════════════════════════════════════════╗
║  BUSINESS IDENTITY (ALWAYS REMEMBER - REFERENCE TEXT)         ║
╚═══════════════════════════════════════════════════════════════╝

{business_identity_text}

⚠️  IMPORTANT: This is our business identity. ALWAYS keep in mind what
we sell (AI phone assistants, not fried chicken!), our values, and our
policies. DO NOT make up services or prices not mentioned above.

───────────────────────────────────────────────────────────────

RELATIONSHIP CONTEXT WITH THIS CLIENT:
{person_context}

USER'S WRITING STYLE ({user_id}):
{user_context}

RELEVANT BUSINESS DETAILS FOR THIS TOPIC:
{business_specific_text if business_specific_text else "Use the general business identity info above."}

───────────────────────────────────────────────────────────────

INSTRUCTIONS:
1. Use appropriate tone based on relationship (formal/informal)
2. Follow the user's writing style
3. Include ONLY documented business info above (DO NOT make things up!)
4. Be specific and actionable
5. ALWAYS respect company policies (e.g., no spam, GDPR compliance)
6. Sign as "Mario" (or the user's name)

Write ONLY the email body (no subject), ready to be copied into a draft."""

            # Generate draft with Claude Sonnet
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            draft_body = response.content[0].text.strip()

            # Extract suggested subject if Claude provided one
            subject = f"Re: {topic}"  # Default
            if draft_body.startswith("Subject:"):
                lines = draft_body.split("\n", 1)
                subject = lines[0].replace("Subject:", "").strip()
                draft_body = lines[1].strip() if len(lines) > 1 else draft_body

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "subject": subject,
                    "body": draft_body,
                    "to": contact_email,
                    "person_memories_used": len(person_memories),
                    "user_memories_used": len(user_memories),
                    "business_identity_used": len(business_identity),
                    "business_specific_used": len(business_specific)
                },
                message=f"✅ Email draft created for {contact_email}\n\n"
                        f"📧 Subject: {subject}\n\n"
                        f"📄 Body:\n"
                        f"{'─' * 70}\n"
                        f"{draft_body}\n"
                        f"{'─' * 70}\n\n"
                        f"📊 Memories used:\n"
                        f"   👤 Person: {len(person_memories)}\n"
                        f"   ✍️  User style: {len(user_memories)}\n"
                        f"   🏢 Business identity: {len(business_identity)} (always loaded)\n"
                        f"   📋 Business topic-specific: {len(business_specific)}\n\n"
                        f"Do you want me to create a Gmail draft with this text?"
            )

        except Exception as e:
            logger.error(f"Failed to draft email from memory: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Error creating draft: {str(e)}"
            )

    def get_schema(self):
        return {
            "name": self.name,
            "description": "Create a personalized email draft using relationship memory, business info, and user's style. Uses semantic search on 3 namespaces (person, user, business) to compose a contextually rich email. ALWAYS use this tool when user asks to write emails/offers to known contacts.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_email": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "topic": {
                        "type": "string",
                        "description": "Email topic/purpose (e.g., 'outbound services offer', 'follow-up meeting', 'pricing question reply')"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID (default: 'mario')",
                        "default": "mario"
                    }
                },
                "required": ["contact_email", "topic"]
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

            # Get date range from cache metadata
            cache_info = self.email_sync.get_cache_info() if hasattr(self.email_sync, 'get_cache_info') else {}
            date_from = cache_info.get('oldest_email', 'unknown')
            date_to = cache_info.get('newest_email', 'unknown')

            message = f"Found {len(threads)} conversations"
            if date_from != 'unknown' and date_to != 'unknown':
                message += f" (from {date_from} to {date_to})"
            if open_only:
                message += " [open only]"
            if expected_action:
                message += f" [requires {expected_action}]"

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
                error=f"Search failed: {str(e)}"
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


# Legacy task tools removed (_BuildTasksTool, _GetContactTaskTool, _SearchTasksTool, _TaskStatsTool)
# These used the old file-based tasks.json system which has been replaced by Supabase avatars
# The get_tasks tool below queries pre-computed avatars for instant task retrieval


class _GetTasksTool(Tool):
    """Get open tasks from pre-computed avatars.

    Returns formatted task list instantly from Supabase avatars.
    Much faster than having Claude format the list (~5s vs 27s).
    """

    def __init__(self, session_state: SessionState):
        super().__init__(
            name="get_tasks",
            description="ALWAYS use this tool when user asks about tasks, to-dos, what they need to do, pending actions, what needs attention, or anything related to their task list. Returns pre-computed task data instantly. Do NOT answer from memory - ALWAYS call this tool for task queries."
        )
        self.session_state = session_state

    async def execute(self, days_back: int = 7):
        from zylch.storage.supabase_client import SupabaseStorage
        from zylch.services.task_formatter import filter_own_emails, format_task_list

        # Get owner_id from session state (runtime value)
        owner_id = self.session_state.get_owner_id()
        if not owner_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data={},
                message="❌ No owner_id available. Please log in first."
            )

        try:
            supabase = SupabaseStorage()

            result = supabase.client.table('avatars')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .or_('relationship_status.eq.open,relationship_status.eq.waiting')\
                .gte('relationship_score', 3)\
                .order('relationship_score', desc=True)\
                .execute()

            avatars = result.data or []
            avatars = filter_own_emails(avatars)

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={'count': len(avatars)},
                message=format_task_list(avatars, include_stale_warning=False)
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
            "description": "ALWAYS use this tool when user asks about tasks, to-dos, what they need to do, pending actions, what needs attention, or anything related to their task list. Returns current pre-computed task data. Do NOT answer task queries from conversation history - ALWAYS call this tool.",
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
    """Search local ZylchMemory for person info using hybrid FTS + semantic search.

    ZYLCH IS PERSON-CENTRIC: A person can have multiple emails/phones.
    This tool uses hybrid search (FTS + semantic) for better recall and precision.

    Flow:
    1. User asks "info su Luigi"
    2. Hybrid search combines FTS and semantic search for best results
    3. Returns top results ranked by hybrid_score (FTS + semantic)
    4. Falls back to identifier_cache for O(1) lookup if needed
    """

    def __init__(
        self,
        zylch_memory,
        identifier_cache: IdentifierMapCache,
        search_engine: Optional[HybridSearchEngine] = None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant"
    ):
        super().__init__(
            name="search_local_memory",
            description="Search local memory for person/contact info using hybrid FTS + semantic search. ALWAYS call this FIRST before remote searches (Gmail, StarChat, web). Returns ranked results by relevance."
        )
        self.zylch_memory = zylch_memory
        self.identifier_cache = identifier_cache
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
                        "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
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

            # Fallback to identifier_cache if hybrid search not available
            if not self.identifier_cache:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"not_found": True},
                    message="Search engines not initialized. Proceed with remote searches."
                )

            # Legacy O(1) lookup in identifier_map
            match = self.identifier_cache.lookup(
                query=query,
                owner_id=self.owner_id,
                assistant_id=self.zylch_assistant_id
            )

            if not match:
                logger.info(f"No local match for query: {query}")
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={"not_found": True, "query": query},
                    message=f"Contact '{query}' not found in local memory. Proceed with remote searches."
                )

            memory_id = match.get("memory_id")
            is_fresh = self.identifier_cache.is_fresh(
                query=query,
                owner_id=self.owner_id,
                assistant_id=self.zylch_assistant_id
            )

            # Retrieve full data from ZylchMemory
            person_data = None
            if self.zylch_memory:
                contacts_namespace = f"{self.owner_id}:{self.zylch_assistant_id}:contacts"
                memories = self.zylch_memory.retrieve_memories(
                    query=query,
                    category="person",
                    namespace=contacts_namespace,
                    limit=1
                )

                if memories:
                    person_data = {
                        "pattern": memories[0].get("pattern", ""),
                        "context": memories[0].get("context", ""),
                        "confidence": memories[0].get("confidence", 0),
                        "updated_at": match.get("updated_at"),
                    }

            all_identifiers = self.identifier_cache.get_all_for_memory(
                memory_id=memory_id,
                owner_id=self.owner_id,
                assistant_id=self.zylch_assistant_id
            )

            result_data = {
                "found": True,
                "fresh": is_fresh,
                "needs_refresh": not is_fresh,
                "memory_id": memory_id,
                "query": query,
                "identifiers": [{"type": t, "value": v} for t, v in all_identifiers],
                "person_data": person_data
            }

            if is_fresh:
                message = f"Found fresh contact data for '{query}' in local memory."
            else:
                message = f"Found contact data for '{query}' but it may be stale."

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=result_data,
                message=message
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
            "description": "Search local ZylchMemory for person/contact info. CRITICAL: ALWAYS call this FIRST when user asks about a person (e.g., 'info on Luigi', 'who is Mario?', 'tell me about Connecto'). This avoids expensive 10+ second remote API calls if data is already cached.",
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


class _SaveContactTool(Tool):
    """Tool to save enriched contact to MrCall assistant and ZylchMemory."""
    def __init__(self, starchat_client, session_state: SessionState, zylch_memory=None, identifier_cache: IdentifierMapCache = None, owner_id="owner_default", zylch_assistant_id="default_assistant"):
        super().__init__(
            name="save_contact",
            description="Save enriched contact data to BOTH StarChat (structured contact) AND ZylchMemory (semantic person-centric namespace). Single call saves to both locations."
        )
        self.starchat = starchat_client
        self.identifier_cache = identifier_cache
        self.session_state = session_state
        self.zylch_memory = zylch_memory
        self.owner_id = owner_id
        self.zylch_assistant_id = zylch_assistant_id

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
        # Check if business is selected (get current value from session state)
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No MrCall assistant selected. Use /mrcall <id> to select one."
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
                "ENRICHMENT_SOURCES": json.dumps(["gmail", "web_search", "zylch"]),
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
            logger.info(f"Checking for existing contact with email={email}, business_id={business_id}")
            existing_contacts = await self.starchat.search_contacts(
                email=email,
                business_id=business_id
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
                business_id=business_id
            )

            # ALSO save to ZylchMemory (person-centric, SINGLE namespace for all contacts)
            # ZYLCH IS PERSON-CENTRIC: One namespace for all contacts, identifier_map for fast lookup
            memory_id = None
            if self.zylch_memory:
                try:
                    # TODO: STARCHAT_REQUEST - When available, use contact_id from StarChat
                    # instead of generating email-based fallback
                    # contact_id = await self.starchat.lookup_by_email(email)["contact_id"]

                    # Use SINGLE namespace for all contacts (enables cross-contact semantic search)
                    contacts_namespace = f"{self.owner_id}:{self.zylch_assistant_id}:contacts"

                    # Build semantic summary for memory
                    memory_parts = []
                    if name:
                        memory_parts.append(f"Name: {name}")
                    if email:
                        memory_parts.append(f"Email: {email}")
                    if phone:
                        memory_parts.append(f"Phone: {phone}")
                    if company:
                        memory_parts.append(f"Company: {company}")
                    if relationship_type and relationship_type != "unknown":
                        memory_parts.append(f"Relationship: {relationship_type}")
                    if notes:
                        memory_parts.append(f"Notes: {notes}")

                    memory_content = " | ".join(memory_parts)

                    # Store in zylch_memory (single namespace for semantic search)
                    memory_id_str = self.zylch_memory.store_memory(
                        namespace=contacts_namespace,
                        category="person",
                        context=f"Contact profile for {name or email}",
                        pattern=memory_content,
                        examples=[],
                        confidence=0.9  # High confidence for explicitly saved contacts
                    )
                    memory_id = int(memory_id_str) if memory_id_str else None

                    logger.info(f"✅ Saved contact to ZylchMemory: namespace={contacts_namespace}, memory_id={memory_id}")
                except Exception as e:
                    # Don't fail the whole operation if zylch_memory save fails
                    logger.warning(f"Failed to save to ZylchMemory (non-fatal): {e}")

            # Register ALL identifiers in the identifier_map for O(1) lookup
            # PERSON-CENTRIC: Multiple emails/phones can point to the same person
            if self.identifier_cache and memory_id:
                try:
                    identifiers = []
                    if email:
                        identifiers.append(("email", email))
                    if phone:
                        identifiers.append(("phone", phone))
                    if name:
                        identifiers.append(("name", name))

                    self.identifier_cache.register(
                        identifiers=identifiers,
                        memory_id=memory_id,
                        owner_id=self.owner_id,
                        assistant_id=self.zylch_assistant_id
                    )
                    logger.info(f"✅ Registered {len(identifiers)} identifiers in cache for memory_id={memory_id}")
                except Exception as e:
                    logger.warning(f"Failed to register identifiers (non-fatal): {e}")

            action = "updated" if existing_contacts else "created"
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=result,
                message=f"Contact {action} in assistant: {business_id} (also saved to ZylchMemory)"
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


class _ListContactsTool(Tool):
    """Wrapper for ListAllContactsTool that uses current business_id."""
    def __init__(self, starchat_client, session_state: SessionState):
        super().__init__(
            name="list_all_contacts",
            description="List all contacts associated with your selected business in StarChat"
        )
        self.starchat = starchat_client
        self.session_state = session_state

    async def execute(self, limit: Optional[int] = None) -> ToolResult:
        """Execute contact listing using current business_id."""
        # Check if business is selected
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No MrCall assistant selected. Use /mrcall <id> to select one."
            )

        try:
            logger.info(f"Listing all contacts for business: {business_id}")

            contacts = await self.starchat.search_contacts_paginated(
                business_id=business_id,
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
