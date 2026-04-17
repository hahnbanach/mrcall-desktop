"""Tool factory for centralizing tool initialization."""

import logging
from typing import List, Optional

from .base import Tool
from .config import ToolConfig

# Re-export SessionState for backward compatibility:
# from zylch.tools.factory import SessionState
from .session_state import SessionState

from zylch.memory import (
    EmbeddingEngine,
    HybridSearchEngine,
    MemoryConfig,
)
from .web_search import WebSearchTool

# IMAP client replaces Gmail/Outlook OAuth
from zylch.email.imap_client import IMAPClient

# External service imports (non-OAuth)
from .pipedrive import PipedriveClient
from .email_archive import EmailArchiveManager
from .email_sync import EmailSyncManager
from ..assistant.models import ModelSelector

from .sms_tools import SendSMSTool
from .call_tools import InitiateCallTool
from .whatsapp_tools import (
    SearchWhatsAppTool,
    GetWhatsAppConversationTool,
    SendWhatsAppMessageTool,
    WhatsAppGapAnalysisTool,
    GetContactTimelineTool,
)

# Tool classes from split modules
from .gmail_tools import (
    GmailSearchTool,
    CreateDraftTool,
    ListDraftsTool,
    EditDraftTool,
    UpdateDraftTool,
    SendDraftTool,
    DeleteDraftTool,
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
)
from .crm_tools import (
    SearchPipedrivePersonTool,
    GetPipedrivePersonDealsTool,
    ComposeEmailTool,
)
from .download_attachment_tool import DownloadAttachmentTool  # Phase A
from .read_document_tool import ReadDocumentTool  # Phase A
from .read_email_tool import ReadEmailTool
from .run_python_tool import RunPythonTool  # Phase A
from .update_memory_tool import UpdateMemoryTool  # Phase A

logger = logging.getLogger(__name__)


class ToolFactory:
    """Factory for creating and initializing tools.

    Centralizes all tool initialization logic.
    Uses IMAPClient for email (no OAuth APIs).
    """

    # Class attributes for storing service clients
    _starchat_client = None
    _email_client = None  # IMAPClient
    _email_archive = None
    _session_state = None

    @staticmethod
    async def create_all_tools(
        config: ToolConfig,
        current_business_id: Optional[str] = None,
    ) -> tuple:
        """Create and initialize all Zylch AI tools.

        Args:
            config: Tool configuration
            current_business_id: Current business ID

        Returns:
            Tuple of (tools, session_state)
        """
        logger.info("Initializing Zylch AI tools...")

        session_state = SessionState(
            business_id=current_business_id,
            owner_id=config.owner_id,
        )
        ToolFactory._session_state = session_state

        try:
            from zylch.storage import Storage

            supabase_storage = Storage()

            # StarChat client - DISABLED pending OAuth2.0
            starchat = None
            logger.info("StarChat disabled" " - pending OAuth2.0 implementation")

            # Email client via IMAP
            email_client = ToolFactory._create_imap_client(config)

            # Save client reference
            ToolFactory._email_client = email_client

            # Email archive manager (lazy auth)
            email_archive = None
            if email_client:
                try:
                    email_archive = EmailArchiveManager(
                        gmail_client=email_client,
                        owner_id=config.owner_id,
                        supabase_storage=(supabase_storage),
                    )
                except Exception as e:
                    logger.warning("EmailArchiveManager init" f" skipped: {e}")

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

            # Pipedrive CRM client (optional)
            pipedrive = None
            if config.pipedrive_api_token:
                try:
                    pipedrive = PipedriveClient(api_token=(config.pipedrive_api_token))
                    logger.info("Pipedrive CRM connected")
                except Exception as e:
                    logger.warning(f"Pipedrive failed: {e}")
                    pipedrive = None

            # Initialize hybrid search engine
            from zylch.storage.database import (
                get_session,
            )

            mem_config = MemoryConfig()
            embedding_engine = EmbeddingEngine(mem_config)
            search_engine = HybridSearchEngine(
                get_session=get_session,
                embedding_engine=embedding_engine,
                default_alpha=0.3,
            )
            logger.info("Hybrid search engine initialized")

        except Exception as e:
            logger.error(f"Failed to init service clients: {e}")
            raise

        # Initialize tools list
        tools = []

        # Email tools - using IMAP client
        tools.extend(
            ToolFactory._create_email_tools(
                email_client,
                supabase_storage,
                email_sync,
                config.owner_id,
                config.zylch_assistant_id,
            )
        )

        # Email sync tools (4 tools)
        tools.extend(
            ToolFactory._create_email_sync_tools(
                email_sync,
                supabase_storage,
                config.owner_id,
            )
        )

        # Memory search tools
        tools.extend(
            ToolFactory._create_contact_tools(
                starchat,
                session_state,
                search_engine,
                config.owner_id,
                config.zylch_assistant_id,
            )
        )

        # Calendar tools removed (pending CalDAV)
        # TODO: Re-add when CalDAV is implemented

        # Web search tool (1 tool)
        tools.append(
            WebSearchTool(
                api_key=config.anthropic_api_key,
                provider=getattr(config, "llm_provider", "anthropic"),
            )
        )

        # Pipedrive tools (2 tools) - optional
        if pipedrive:
            tools.extend(ToolFactory._create_pipedrive_tools(pipedrive))

        # MrCall configuration tools (3 tools)
        if starchat:
            tools.extend(
                ToolFactory._create_mrcall_tools(
                    starchat_client=starchat,
                    session_state=session_state,
                    storage=supabase_storage,
                    owner_id=config.owner_id,
                    api_key=config.anthropic_api_key,
                    provider=getattr(
                        config,
                        "llm_provider",
                        "anthropic",
                    ),
                )
            )

        # SMS tool (send only - verification removed)
        tools.append(SendSMSTool(session_state=session_state))
        logger.info("SMS tool initialized" " (credentials loaded per-user)")

        # Call tools (1 tool)
        if starchat:
            tools.append(
                InitiateCallTool(
                    starchat_client=starchat,
                    session_state=session_state,
                )
            )
            logger.info("Call tool initialized" " (StarChat/MrCall)")

        # WhatsApp tools (4 tools) — local neonize
        tools.extend(
            [
                SearchWhatsAppTool(
                    session_state=session_state,
                ),
                GetWhatsAppConversationTool(
                    session_state=session_state,
                ),
                SendWhatsAppMessageTool(
                    session_state=session_state,
                ),
                WhatsAppGapAnalysisTool(
                    session_state=session_state,
                ),
                GetContactTimelineTool(
                    session_state=session_state,
                ),
            ]
        )
        logger.info("WhatsApp tools initialized (5)")

        # Get Tasks tool
        tools.append(GetTasksTool(session_state=session_state))
        logger.info("Get Tasks tool initialized")

        # Phase A tools (attachment, document, python, memory) + read_email
        tools.extend(
            [
                DownloadAttachmentTool(
                    storage=supabase_storage, session_state=session_state, owner_id=config.owner_id
                ),
                ReadDocumentTool(),
                ReadEmailTool(
                    storage=supabase_storage,
                    session_state=session_state,
                    owner_id=config.owner_id,
                ),
                RunPythonTool(),
                UpdateMemoryTool(session_state=session_state, owner_id=config.owner_id),
            ]
        )
        logger.info("Phase A tools initialized (5: +read_email)")

        # Compose Email tool
        tools.append(
            ComposeEmailTool(
                session_state=session_state,
                api_key=config.anthropic_api_key,
                provider=getattr(
                    config,
                    "llm_provider",
                    "anthropic",
                ),
            )
        )
        logger.info("Compose Email tool initialized")

        # Store service client references
        ToolFactory._starchat_client = starchat
        ToolFactory._email_archive = email_archive

        logger.info(f"Initialized {len(tools)} tools")
        return tools, session_state

    @staticmethod
    def _create_imap_client(
        config: ToolConfig,
    ) -> Optional[IMAPClient]:
        """Create IMAPClient from config/env.

        Reads EMAIL_ADDRESS, EMAIL_PASSWORD from env.
        Optionally IMAP_HOST, IMAP_PORT, SMTP_HOST,
        SMTP_PORT.

        Args:
            config: Tool configuration

        Returns:
            IMAPClient or None if not configured
        """
        import os

        email_addr = os.environ.get(
            "EMAIL_ADDRESS",
            config.user_email or "",
        )
        email_pass = os.environ.get("EMAIL_PASSWORD", "")

        if not email_addr or not email_pass:
            logger.warning(
                "IMAP not configured:" " EMAIL_ADDRESS or EMAIL_PASSWORD" " missing. Set in .env."
            )
            return None

        imap_host = os.environ.get("IMAP_HOST")
        imap_port_str = os.environ.get("IMAP_PORT")
        smtp_host = os.environ.get("SMTP_HOST")
        smtp_port_str = os.environ.get("SMTP_PORT")

        imap_port = int(imap_port_str) if imap_port_str else None
        smtp_port = int(smtp_port_str) if smtp_port_str else None

        client = IMAPClient(
            email_addr=email_addr,
            password=email_pass,
            imap_host=imap_host,
            imap_port=imap_port,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
        )

        try:
            client.connect()
            logger.info(f"IMAP connected as {email_addr}")
        except Exception as e:
            logger.warning(f"IMAP connection failed: {e}." " Will retry on first use.")

        return client

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
    def _create_email_tools(
        imap_client,
        storage,
        email_sync_manager=None,
        owner_id: str = "owner_default",
        zylch_assistant_id: str = "default_assistant",
    ) -> List[Tool]:
        """Create email tools using IMAP client."""
        return [
            GmailSearchTool(
                imap_client,
                owner_id,
                zylch_assistant_id,
            ),
            CreateDraftTool(storage, owner_id),
            ListDraftsTool(storage, owner_id),
            EditDraftTool(storage, owner_id),
            UpdateDraftTool(storage, owner_id),
            SendDraftTool(imap_client, storage, owner_id),
            DeleteDraftTool(storage, owner_id),
        ]

    @staticmethod
    def _create_email_sync_tools(email_sync_manager, storage, owner_id: str) -> List[Tool]:
        """Create email sync tools."""
        return [
            SyncEmailsTool(email_sync_manager),
            SearchEmailsTool(
                email_sync_manager,
                storage,
                owner_id,
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
        """Create memory search tools."""
        return [
            SearchLocalMemoryTool(
                search_engine,
                owner_id,
                zylch_assistant_id,
            ),
            GetContactTool(starchat_client, session_state),
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
        """Create MrCall assistant config tools."""
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
        user_display_name: Optional[str] = None,
    ) -> List[Tool]:
        """Create intelligence sharing tools.

        TODO: Disabled - pending migration.
        """
        return []
