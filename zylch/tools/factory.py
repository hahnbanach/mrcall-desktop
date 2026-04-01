"""Tool factory for centralizing tool initialization."""

import logging
from typing import List, Optional

from zylch.config import settings
from .base import Tool, ToolResult, ToolStatus
from .config import ToolConfig

# Re-export SessionState for backward compatibility:
# from zylch.tools.factory import SessionState
from .session_state import SessionState

from zylch.memory import (
    EmbeddingEngine,
    HybridSearchEngine,
    MemoryConfig,
)
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

# Tool classes from split modules
from .gmail_tools import (
    GmailSearchTool,
    CreateDraftTool,
    ListDraftsTool,
    EditDraftTool,
    UpdateDraftTool,
    SendDraftTool,
    RefreshGoogleAuthTool,
)
from .email_sync_tools import (
    SyncEmailsTool,
    SearchEmailsTool,
    CloseEmailThreadTool,
    EmailStatsTool,
)
from .contact_tools import (
    GetTasksTool,
    SearchLocalMemoryTool,
    GetContactTool,
    GetWhatsAppContactsTool,
)
from .crm_tools import (
    SearchPipedrivePersonTool,
    GetPipedrivePersonDealsTool,
    ComposeEmailTool,
)

logger = logging.getLogger(__name__)


class ToolFactory:
    """Factory for creating and initializing Zylch AI tools.

    Centralizes all tool initialization logic previously scattered
    in CLI. Both API services and CLI can use this factory to get
    identical tool sets.
    """

    # Class attributes for storing service client references
    # These are set during create_all_tools() and accessed by CLI
    _starchat_client = None
    _email_client = None  # GmailClient or OutlookClient
    _calendar_client = None  # Google or Outlook calendar
    _email_archive = None
    _session_state = None  # Shared session state

    @staticmethod
    async def create_all_tools(
        config: ToolConfig,
        current_business_id: Optional[str] = None,
    ) -> tuple:
        """Create and initialize all Zylch AI tools.

        Args:
            config: Tool configuration
            current_business_id: Current StarChat business ID

        Returns:
            Tuple of (tools, session_state):
            - tools: List of initialized tool instances
            - session_state: SessionState for runtime updates

        Raises:
            Exception: If required services fail to initialize
        """
        logger.info("Initializing Zylch AI tools...")

        # Create shared session state
        session_state = SessionState(
            business_id=current_business_id,
            owner_id=config.owner_id,
        )
        ToolFactory._session_state = session_state

        # Initialize external service clients
        try:
            from zylch.storage.supabase_client import (
                SupabaseStorage,
            )

            supabase_storage = SupabaseStorage()

            # StarChat client - DISABLED pending OAuth2.0
            starchat = None
            logger.info(
                "StarChat disabled"
                " - pending OAuth2.0 implementation"
            )

            # Email client - choose based on auth provider
            if config.auth_provider == "microsoft":
                email_client = OutlookClient(
                    graph_token=config.graph_token,
                    account=config.user_email,
                )
                logger.info("Using Microsoft Outlook for email")

                try:
                    if config.graph_token:
                        email_client.authenticate()
                        logger.info(
                            "Microsoft Graph API authenticated"
                        )
                    else:
                        logger.warning(
                            "Microsoft Graph token not found"
                        )
                except Exception as e:
                    logger.warning(
                        f"Microsoft authentication needed: {e}"
                    )

            else:
                # Gmail client (default)
                owner_id = (
                    config.owner_id
                    if config.owner_id != "owner_default"
                    else None
                )
                if not owner_id:
                    raise ValueError(
                        "owner_id is required for Gmail client"
                        " - Zylch uses Supabase for all"
                        " token storage"
                    )

                email_client = GmailClient(
                    account=config.user_email,
                    owner_id=owner_id,
                )
                logger.info("Using Gmail for email")

                try:
                    from ..api import token_storage

                    if token_storage.has_google_credentials(
                        owner_id
                    ):
                        email_client.authenticate()
                        logger.info(
                            "Google services authenticated"
                            " (Gmail)"
                        )
                    else:
                        logger.warning(
                            "Google authentication needed"
                            " - tokens not found in Supabase"
                        )
                except Exception as e:
                    logger.warning(
                        f"Google authentication needed: {e}"
                    )

            # Calendar client (conditional based on provider)
            calendar = None
            if config.auth_provider == "google":
                calendar = GoogleCalendarClient(
                    calendar_id="primary",
                    account=config.user_email,
                    owner_id=owner_id,
                )
                logger.info(
                    "Google Calendar initialized"
                    " for Gmail user"
                )
            elif config.auth_provider == "microsoft":
                if (
                    isinstance(email_client, OutlookClient)
                    and email_client.graph_token
                ):
                    calendar = OutlookCalendarClient(
                        graph_token=email_client.graph_token,
                        calendar_id="primary",
                    )
                    logger.info(
                        "Outlook Calendar initialized"
                        " for Microsoft user"
                    )
                else:
                    logger.warning(
                        "Outlook Calendar not available"
                        " - email client not authenticated"
                    )
            else:
                logger.info("No calendar provider configured")

            # Save clients to class variables
            ToolFactory._email_client = email_client
            ToolFactory._calendar_client = calendar

            # Email archive manager (lazy auth)
            email_archive = None
            try:
                email_archive = EmailArchiveManager(
                    gmail_client=email_client
                )
            except Exception as e:
                logger.warning(
                    "EmailArchiveManager initialization"
                    f" skipped: {e}"
                )

            # Email sync manager
            email_sync = None
            if (
                email_archive
                and config.anthropic_api_key
                and config.llm_provider
            ):
                email_sync = EmailSyncManager(
                    email_archive=email_archive,
                    api_key=config.anthropic_api_key,
                    provider=config.llm_provider,
                    days_back=30,
                    owner_id=config.owner_id,
                    supabase_storage=supabase_storage,
                )

            # Pipedrive CRM client (optional)
            pipedrive = None
            if config.pipedrive_api_token:
                try:
                    pipedrive = PipedriveClient(
                        api_token=config.pipedrive_api_token
                    )
                    logger.info("Pipedrive CRM connected")
                except Exception as e:
                    logger.warning(
                        f"Pipedrive connection failed: {e}"
                    )
                    pipedrive = None

            # Initialize hybrid search engine for blob search
            from zylch.storage.database import get_session

            mem_config = MemoryConfig()
            embedding_engine = EmbeddingEngine(mem_config)
            search_engine = HybridSearchEngine(
                get_session=get_session,
                embedding_engine=embedding_engine,
                default_alpha=0.3,
            )
            logger.info("Hybrid search engine initialized")

        except Exception as e:
            logger.error(
                f"Failed to initialize service clients: {e}"
            )
            raise

        # Initialize tools list
        tools = []

        # Email tools (7 tools) - Gmail or Outlook
        tools.extend(ToolFactory._create_gmail_tools(
            email_client,
            calendar,
            supabase_storage,
            email_sync,
            config.owner_id,
            config.zylch_assistant_id,
        ))

        # Email sync tools (4 tools)
        tools.extend(ToolFactory._create_email_sync_tools(
            email_sync, supabase_storage, config.owner_id
        ))

        # Memory search tools
        tools.extend(ToolFactory._create_contact_tools(
            starchat,
            session_state,
            search_engine,
            config.owner_id,
            config.zylch_assistant_id,
        ))

        # Calendar tools (4 tools)
        tools.extend(
            ToolFactory._create_calendar_tools(calendar)
        )

        # Web search tool (1 tool)
        tools.append(WebSearchTool(
            api_key=config.anthropic_api_key,
            provider=getattr(
                config, "llm_provider", "anthropic"
            ),
        ))

        # Pipedrive tools (2 tools) - optional
        if pipedrive:
            tools.extend(
                ToolFactory._create_pipedrive_tools(pipedrive)
            )

        # MrCall configuration tools (3 tools)
        if starchat:
            tools.extend(ToolFactory._create_mrcall_tools(
                starchat_client=starchat,
                session_state=session_state,
                storage=supabase_storage,
                owner_id=config.owner_id,
                api_key=config.anthropic_api_key,
                provider=getattr(
                    config, "llm_provider", "anthropic"
                ),
            ))

        # SMS tools (always available)
        tools.extend(ToolFactory._create_sms_tools(
            session_state=session_state,
            owner_id=config.owner_id,
            zylch_assistant_id=config.zylch_assistant_id,
        ))
        logger.info(
            "SMS tools initialized"
            " (credentials loaded per-user)"
        )

        # Call tools (1 tool)
        if starchat:
            tools.append(InitiateCallTool(
                starchat_client=starchat,
                session_state=session_state,
            ))
            logger.info(
                "Call tool initialized (StarChat/MrCall)"
            )

        # Get Tasks tool
        tools.append(GetTasksTool(session_state=session_state))
        logger.info("Get Tasks tool initialized")

        # Compose Email tool
        tools.append(ComposeEmailTool(
            session_state=session_state,
            api_key=config.anthropic_api_key,
            provider=getattr(
                config, "llm_provider", "anthropic"
            ),
        ))
        logger.info("Compose Email tool initialized")

        # Store service client references for CLI access
        ToolFactory._starchat_client = starchat
        ToolFactory._email_archive = email_archive

        logger.info(f"Initialized {len(tools)} tools")
        return tools, session_state

    @staticmethod
    def create_model_selector(
        config: ToolConfig,
    ) -> ModelSelector:
        """Create model selector with configuration.

        Args:
            config: Tool configuration

        Returns:
            Configured ModelSelector instance
        """
        return ModelSelector(
            default_model=config.default_model,
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
            GmailSearchTool(
                gmail_client, owner_id, zylch_assistant_id
            ),
            CreateDraftTool(storage, owner_id),
            ListDraftsTool(storage, owner_id),
            EditDraftTool(gmail_client),
            UpdateDraftTool(gmail_client),
            SendDraftTool(gmail_client, storage, owner_id),
            RefreshGoogleAuthTool(
                gmail_client, calendar_client
            ),
        ]

    @staticmethod
    def _create_email_sync_tools(
        email_sync_manager, storage, owner_id: str
    ) -> List[Tool]:
        """Create email sync tools."""
        return [
            SyncEmailsTool(email_sync_manager),
            SearchEmailsTool(
                email_sync_manager, storage, owner_id
            ),
            CloseEmailThreadTool(email_sync_manager),
            EmailStatsTool(email_sync_manager),
        ]

    @staticmethod
    def _create_contact_tools(
        starchat_client,
        session_state: SessionState,
        search_engine: Optional[HybridSearchEngine] = None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
    ) -> List[Tool]:
        """Create memory search tools.

        ZYLCH IS PERSON-CENTRIC: A person can have multiple
        emails/phones. search_local_memory provides hybrid
        FTS + semantic search.
        """
        return [
            SearchLocalMemoryTool(
                search_engine, owner_id, zylch_assistant_id
            ),
            GetContactTool(starchat_client, session_state),
            GetWhatsAppContactsTool(
                starchat_client, session_state
            ),
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
    def _create_pipedrive_tools(
        pipedrive_client,
    ) -> List[Tool]:
        """Create Pipedrive CRM tools."""
        return [
            SearchPipedrivePersonTool(pipedrive_client),
            GetPipedrivePersonDealsTool(pipedrive_client),
        ]

    @staticmethod
    def _create_mrcall_tools(
        starchat_client,
        session_state: SessionState,
        storage,
        owner_id: str,
        api_key: str,
        provider: str,
    ) -> List[Tool]:
        """Create MrCall assistant configuration tools.

        These tools enable natural language configuration of
        MrCall assistants. Features:
        - Preview + confirm workflow for all changes
        - Variable preservation during prompt modifications
        - Dynamic sub-prompt generation
        """
        from .mrcall import (
            GetAssistantCatalogTool,
            ConfigureAssistantTool,
        )
        from .mrcall.feature_context_tool import (
            GetMrCallFeatureContextTool,
        )
        from zylch.agents.trainers import (
            MrCallConfiguratorTrainer,
        )

        trainer = MrCallConfiguratorTrainer(
            storage=storage,
            starchat_client=starchat_client,
            owner_id=owner_id,
            api_key=api_key,
            provider=provider,
        )

        return [
            GetAssistantCatalogTool(
                starchat_client, session_state
            ),
            GetMrCallFeatureContextTool(
                trainer, session_state
            ),
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
        user_display_name: Optional[str] = None,
    ) -> List[Tool]:
        """Create intelligence sharing tools.

        TODO: Disabled - need migration from legacy memory
        system to Supabase blobs.
        """
        return []

    @staticmethod
    def _create_sms_tools(
        session_state,
        owner_id: str,
        zylch_assistant_id: str,
    ) -> List[Tool]:
        """Create SMS tools for sending messages via Vonage.

        Credentials are loaded per-user at execution time.

        Tools:
        - send_sms: Send a text message
        - send_verification_code: Send a 6-digit code
        - verify_sms_code: Verify a code that was sent via SMS
        """
        return [
            SendSMSTool(session_state=session_state),
            SendVerificationCodeTool(
                session_state=session_state,
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id,
            ),
            VerifyCodeTool(
                owner_id=owner_id,
                zylch_assistant_id=zylch_assistant_id,
            ),
        ]
