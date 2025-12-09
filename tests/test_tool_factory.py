"""Tests for ToolFactory - centralized tool creation and initialization."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from pathlib import Path

from zylch.tools.factory import ToolFactory
from zylch.tools.config import ToolConfig
from zylch.tools.base import Tool
from zylch.agent.models import ModelSelector
from zylch.memory import ZylchMemory


@pytest.fixture
def mock_config():
    """Create a mock ToolConfig for testing."""
    return ToolConfig(
        # Anthropic
        anthropic_api_key="test_anthropic_key",
        default_model="claude-3-5-sonnet-20241022",
        classification_model="claude-3-5-haiku-20241022",
        executive_model="claude-3-opus-20240229",

        # Google OAuth
        google_credentials_path="/tmp/test_credentials.json",
        google_token_path="/tmp/test_token.json",
        gmail_accounts=["test@example.com"],
        calendar_id="primary",

        # StarChat
        starchat_api_url="http://test-starchat.com",
        starchat_api_key="test_starchat_key",
        starchat_username="test_user",
        starchat_password="test_pass",
        starchat_business_id="test_business_123",
        starchat_auth_method="basic",

        # Cache
        cache_dir="/tmp/test_cache",
        cache_ttl_days=30,

        # Email Archive
        email_archive_backend="sqlite",
        email_archive_sqlite_path="/tmp/test_emails.db",
        email_archive_postgres_url="",
        email_archive_initial_months=6,
        email_archive_batch_size=50,
        email_archive_enable_fts=True,

        # Optional services
        pipedrive_api_token="",
        pipedrive_enabled=False,
        sendgrid_api_key="",
        sendgrid_from_email="",

        # Email style
        email_style_prompt="Test style prompt",

        # My emails
        my_emails="test@example.com",
        bot_emails="bot@example.com",
    )


@pytest.fixture
def mock_starchat_client():
    """Mock StarChatClient."""
    mock_client = MagicMock()
    mock_client.ensure_authenticated = AsyncMock()
    mock_client.get_contact = AsyncMock(return_value={"name": "Test Contact"})
    mock_client.save_contact = AsyncMock(return_value={"id": "123"})
    return mock_client


@pytest.fixture
def mock_gmail_client():
    """Mock GmailClient."""
    mock_client = MagicMock()
    mock_client.search_messages = AsyncMock(return_value=[])
    mock_client.create_draft = AsyncMock(return_value="draft_123")
    return mock_client


@pytest.fixture
def mock_calendar_client():
    """Mock GoogleCalendarClient."""
    mock_client = MagicMock()
    mock_client.list_events = AsyncMock(return_value=[])
    mock_client.create_event = AsyncMock(return_value={"id": "event_123"})
    return mock_client


@pytest.fixture
def mock_email_archive():
    """Mock EmailArchiveManager."""
    mock_archive = MagicMock()
    mock_archive.initialize = AsyncMock()
    mock_archive.search_emails = AsyncMock(return_value=[])
    return mock_archive


@pytest.fixture
def mock_email_sync():
    """Mock EmailSyncManager."""
    mock_sync = MagicMock()
    mock_sync.sync_all_emails = AsyncMock(return_value={"synced": 10})
    return mock_sync


@pytest.mark.asyncio
async def test_create_all_tools_success(
    mock_config,
    mock_starchat_client,
    mock_gmail_client,
    mock_calendar_client,
    mock_email_archive,
    mock_email_sync
):
    """Test successful creation of all tools."""

    with patch('zylch.tools.factory.StarChatClient', return_value=mock_starchat_client), \
         patch('zylch.tools.factory.GmailClient', return_value=mock_gmail_client), \
         patch('zylch.tools.factory.GoogleCalendarClient', return_value=mock_calendar_client), \
         patch('zylch.tools.factory.EmailArchiveManager', return_value=mock_email_archive), \
         patch('zylch.tools.factory.EmailSyncManager', return_value=mock_email_sync), \
         patch('zylch.tools.factory.JSONCache'):

        result = await ToolFactory.create_all_tools(mock_config, current_business_id="test_business_123")
        tools, session_state, persona_analyzer = result

        # Verify we got tools (number may vary based on available services)
        assert len(tools) > 0, "Should create some tools"

        # Verify all tools are Tool instances
        for tool in tools:
            assert isinstance(tool, Tool)

        # Verify session_state and persona_analyzer are returned
        assert session_state is not None
        assert persona_analyzer is not None


@pytest.mark.asyncio
async def test_create_all_tools_with_pipedrive(
    mock_config,
    mock_starchat_client,
    mock_gmail_client,
    mock_calendar_client,
    mock_email_archive,
    mock_email_sync
):
    """Test tool creation with Pipedrive enabled."""

    # Enable Pipedrive in config
    mock_config.pipedrive_enabled = True
    mock_config.pipedrive_api_token = "test_pipedrive_token"

    mock_pipedrive = MagicMock()
    mock_pipedrive.search_person = AsyncMock(return_value=[])

    with patch('zylch.tools.factory.StarChatClient', return_value=mock_starchat_client), \
         patch('zylch.tools.factory.GmailClient', return_value=mock_gmail_client), \
         patch('zylch.tools.factory.GoogleCalendarClient', return_value=mock_calendar_client), \
         patch('zylch.tools.factory.EmailArchiveManager', return_value=mock_email_archive), \
         patch('zylch.tools.factory.EmailSyncManager', return_value=mock_email_sync), \
         patch('zylch.tools.factory.PipedriveClient', return_value=mock_pipedrive), \
         patch('zylch.tools.factory.JSONCache'):

        result = await ToolFactory.create_all_tools(mock_config, current_business_id="test_business_123")
        tools, session_state, persona_analyzer = result

        # Verify we got tools (with Pipedrive enabled, should have more tools)
        assert len(tools) > 0, "Should create some tools"

        # Verify session_state and persona_analyzer are returned
        assert session_state is not None
        assert persona_analyzer is not None


@pytest.mark.asyncio
async def test_create_all_tools_without_business_id(
    mock_config,
    mock_starchat_client,
    mock_gmail_client,
    mock_calendar_client,
    mock_email_archive,
    mock_email_sync
):
    """Test tool creation without current_business_id (should use config default)."""

    with patch('zylch.tools.factory.StarChatClient', return_value=mock_starchat_client), \
         patch('zylch.tools.factory.GmailClient', return_value=mock_gmail_client), \
         patch('zylch.tools.factory.GoogleCalendarClient', return_value=mock_calendar_client), \
         patch('zylch.tools.factory.EmailArchiveManager', return_value=mock_email_archive), \
         patch('zylch.tools.factory.EmailSyncManager', return_value=mock_email_sync), \
         patch('zylch.tools.factory.JSONCache'):

        result = await ToolFactory.create_all_tools(mock_config, current_business_id=None)
        tools, session_state, persona_analyzer = result

        # Should still create tools successfully
        assert len(tools) > 0, "Should create some tools"
        assert session_state is not None
        assert persona_analyzer is not None


@pytest.mark.asyncio
async def test_create_memory_system(mock_config):
    """Test memory system creation."""

    with patch('zylch.tools.factory.ZylchMemory') as mock_memory_class:
        mock_memory_instance = MagicMock(spec=ZylchMemory)
        mock_memory_class.return_value = mock_memory_instance

        memory = await ToolFactory.create_memory_system(mock_config)

        # Verify ZylchMemory was instantiated
        mock_memory_class.assert_called_once()

        # Verify the config passed to memory system
        call_args = mock_memory_class.call_args
        memory_config = call_args[1]['config']

        assert memory_config.db_path == Path(mock_config.cache_dir) / "zylch_memory.db"
        assert memory_config.index_dir == Path(mock_config.cache_dir) / "indices"

        assert memory is mock_memory_instance


def test_create_model_selector(mock_config):
    """Test model selector creation."""

    model_selector = ToolFactory.create_model_selector(mock_config)

    # Verify model selector was created
    assert isinstance(model_selector, ModelSelector)

    # Verify models are configured correctly
    assert model_selector.default_model == "claude-3-5-sonnet-20241022"
    assert model_selector.classification_model == "claude-3-5-haiku-20241022"
    assert model_selector.executive_model == "claude-3-opus-20240229"


@pytest.mark.asyncio
async def test_tool_categories(
    mock_config,
    mock_starchat_client,
    mock_gmail_client,
    mock_calendar_client,
    mock_email_archive,
    mock_email_sync
):
    """Test that tools are created in the correct categories."""

    with patch('zylch.tools.factory.StarChatClient', return_value=mock_starchat_client), \
         patch('zylch.tools.factory.GmailClient', return_value=mock_gmail_client), \
         patch('zylch.tools.factory.GoogleCalendarClient', return_value=mock_calendar_client), \
         patch('zylch.tools.factory.EmailArchiveManager', return_value=mock_email_archive), \
         patch('zylch.tools.factory.EmailSyncManager', return_value=mock_email_sync), \
         patch('zylch.tools.factory.JSONCache'):

        result = await ToolFactory.create_all_tools(mock_config)
        tools, session_state, persona_analyzer = result

        tool_names = [tool.name for tool in tools]

        # Gmail tools (7)
        assert "search_gmail" in tool_names
        assert "create_gmail_draft" in tool_names
        assert "list_gmail_drafts" in tool_names
        assert "edit_gmail_draft" in tool_names
        assert "update_gmail_draft" in tool_names
        assert "send_gmail_draft" in tool_names
        assert "refresh_google_auth" in tool_names

        # Email Sync tools (4)
        assert "sync_emails" in tool_names
        assert "search_emails" in tool_names
        assert "close_email_threads" in tool_names
        assert "email_stats" in tool_names

        # Task tool (1) - uses pre-computed avatars from Supabase
        assert "get_tasks" in tool_names

        # Contact tools (3)
        assert "save_contact" in tool_names
        assert "get_contact" in tool_names
        assert "list_all_contacts" in tool_names

        # Calendar tools (4)
        assert "list_calendar_events" in tool_names
        assert "search_calendar_events" in tool_names
        assert "create_calendar_event" in tool_names
        assert "update_calendar_event" in tool_names

        # Other tools (1)
        assert "web_search_contact" in tool_names


@pytest.mark.asyncio
async def test_error_handling_starchat_failure(mock_config):
    """Test error handling when StarChat client fails to initialize."""

    with patch('zylch.tools.factory.StarChatClient', side_effect=Exception("StarChat connection failed")):

        with pytest.raises(Exception) as exc_info:
            await ToolFactory.create_all_tools(mock_config)

        assert "StarChat connection failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_error_handling_gmail_failure(mock_config, mock_starchat_client):
    """Test error handling when Gmail client fails to initialize."""

    with patch('zylch.tools.factory.StarChatClient', return_value=mock_starchat_client), \
         patch('zylch.tools.factory.GmailClient', side_effect=Exception("Gmail auth failed")):

        with pytest.raises(Exception) as exc_info:
            await ToolFactory.create_all_tools(mock_config)

        assert "Gmail auth failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_config_from_settings():
    """Test creating ToolConfig from global settings."""

    with patch('zylch.tools.config.settings') as mock_settings:
        # Set up mock settings
        mock_settings.anthropic_api_key = "test_key"
        mock_settings.default_model = "test_model"
        mock_settings.classification_model = "test_classification"
        mock_settings.executive_model = "test_executive"
        mock_settings.google_credentials_path = "/test/creds.json"
        mock_settings.google_token_path = "/test/token.json"
        mock_settings.gmail_accounts = ["test@example.com"]
        mock_settings.calendar_id = "primary"
        mock_settings.starchat_api_url = "http://test.com"
        mock_settings.starchat_api_key = "test_sc_key"
        mock_settings.starchat_username = "test_user"
        mock_settings.starchat_password = "test_pass"
        mock_settings.starchat_business_id = "test_biz"
        mock_settings.starchat_auth_method = "basic"
        mock_settings.cache_dir = "/test/cache"
        mock_settings.cache_ttl_days = 30
        mock_settings.email_archive_backend = "sqlite"
        mock_settings.email_archive_sqlite_path = "/test/emails.db"
        mock_settings.email_archive_postgres_url = ""
        mock_settings.email_archive_initial_months = 6
        mock_settings.email_archive_batch_size = 50
        mock_settings.email_archive_enable_fts = True
        mock_settings.pipedrive_api_token = ""
        mock_settings.pipedrive_enabled = False
        mock_settings.sendgrid_api_key = ""
        mock_settings.sendgrid_from_email = ""
        mock_settings.email_style_prompt = ""
        mock_settings.my_emails = "me@example.com"
        mock_settings.bot_emails = "bot@example.com"

        config = ToolConfig.from_settings()

        assert config.anthropic_api_key == "test_key"
        assert config.default_model == "test_model"
        assert config.starchat_api_url == "http://test.com"
        assert config.gmail_accounts == ["test@example.com"]


def test_get_cache_path(mock_config):
    """Test cache path creation."""

    with patch('pathlib.Path.mkdir') as mock_mkdir:
        cache_path = mock_config.get_cache_path()

        assert cache_path == Path(mock_config.cache_dir)
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


def test_get_email_archive_path(mock_config):
    """Test email archive path creation."""

    with patch('pathlib.Path.mkdir') as mock_mkdir:
        archive_path = mock_config.get_email_archive_path()

        assert archive_path == Path(mock_config.email_archive_sqlite_path)
        # Parent directory should be created
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
