"""Tests for ToolFactory - centralized tool creation and initialization."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from pathlib import Path

from zylch.tools.factory import ToolFactory
from zylch.tools.config import ToolConfig
from zylch.tools.base import Tool
from zylch.assistant.models import ModelSelector


@pytest.fixture
def mock_config():
    """Create a mock ToolConfig for testing."""
    return ToolConfig(
        # LLM Provider
        llm_provider="anthropic",
        anthropic_api_key="test_anthropic_key",

        # Optional services
        pipedrive_api_token="",
        sendgrid_api_key="",
        sendgrid_from_email="",

        # My emails
        my_emails="test@example.com",

        # Multi-tenant (required for Google clients)
        owner_id="test_owner_123",
        user_email="test@example.com",
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
         patch('zylch.tools.factory.EmailSyncManager', return_value=mock_email_sync):

        result = await ToolFactory.create_all_tools(mock_config, current_business_id="test_business_123")
        tools, session_state = result

        # Verify we got tools (number may vary based on available services)
        assert len(tools) > 0, "Should create some tools"

        # Verify all tools are Tool instances
        for tool in tools:
            assert isinstance(tool, Tool)

        # Verify session_state is returned
        assert session_state is not None


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
         patch('zylch.tools.factory.PipedriveClient', return_value=mock_pipedrive):

        result = await ToolFactory.create_all_tools(mock_config, current_business_id="test_business_123")
        tools, session_state = result

        # Verify we got tools (with Pipedrive enabled, should have more tools)
        assert len(tools) > 0, "Should create some tools"

        # Verify session_state is returned
        assert session_state is not None


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
         patch('zylch.tools.factory.EmailSyncManager', return_value=mock_email_sync):

        result = await ToolFactory.create_all_tools(mock_config, current_business_id=None)
        tools, session_state = result

        # Should still create tools successfully
        assert len(tools) > 0, "Should create some tools"
        assert session_state is not None


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
         patch('zylch.tools.factory.EmailSyncManager', return_value=mock_email_sync):

        result = await ToolFactory.create_all_tools(mock_config)
        tools, session_state = result

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

        # Task tool (1) - queries task_items from Supabase
        assert "get_tasks" in tool_names

        # Memory/contact tools (2) - search_local_memory, get_contact
        assert "get_contact" in tool_names

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
    """Test creating ToolConfig from global settings.

    BYOK credentials (anthropic_api_key, pipedrive_api_token, etc.) are NOT
    populated from settings - they're fetched from Supabase via from_settings_with_owner().
    """

    with patch('zylch.tools.config.settings') as mock_settings:
        # Set up mock settings (only non-BYOK fields that ToolConfig reads)
        mock_settings.my_emails = "me@example.com"
        mock_settings.owner_id = "test_owner"
        mock_settings.zylch_assistant_id = "test_assistant"
        mock_settings.user_email = "user@example.com"
        mock_settings.user_display_name = "Test User"

        config = ToolConfig.from_settings()

        # Verify non-BYOK fields are populated from settings
        assert config.my_emails == "me@example.com"
        assert config.owner_id == "test_owner"
        assert config.zylch_assistant_id == "test_assistant"
        assert config.user_email == "user@example.com"
        assert config.user_display_name == "Test User"

        # Verify BYOK credentials are empty (must use from_settings_with_owner)
        assert config.anthropic_api_key == ""
        assert config.pipedrive_api_token == ""
        assert config.sendgrid_api_key == ""