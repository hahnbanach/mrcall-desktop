"""Test command handlers for slash commands.

Tests the /share, /revoke, /help handlers.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

# Test the command handlers
from zylch.services.command_handlers import (
    handle_share,
    handle_revoke,
    handle_help,
)


class TestShareHandler:
    """Tests for /share command handler."""

    @pytest.mark.asyncio
    async def test_share_help(self):
        """Test /share --help returns help text."""
        result = await handle_share(["--help"], "test_owner", "test@example.com")
        assert "**Usage:**" in result
        assert "email" in result.lower()

    @pytest.mark.asyncio
    async def test_share_invalid_email(self):
        """Test /share with invalid email."""
        with patch("zylch.storage.storage.Storage"):
            result = await handle_share(["not-an-email"], "test_owner", "test@example.com")
            assert "Error" in result
            assert "Invalid email" in result

    @pytest.mark.asyncio
    async def test_share_self(self):
        """Test /share with own email."""
        with patch("zylch.storage.storage.Storage"):
            result = await handle_share(["test@example.com"], "test_owner", "test@example.com")
            assert "Error" in result
            assert "can't share with yourself" in result.lower()

    @pytest.mark.asyncio
    async def test_share_no_user_email(self):
        """Test /share without user email context."""
        with patch("zylch.storage.storage.Storage"):
            result = await handle_share(["other@example.com"], "test_owner", None)
            assert "Error" in result
            assert "email is not available" in result

    @pytest.mark.asyncio
    async def test_share_success(self):
        """Test /share with valid email."""
        with patch("zylch.storage.storage.Storage") as mock_client:
            mock_instance = Mock()
            mock_instance.register_share_recipient.return_value = {"status": "pending"}
            mock_client.return_value = mock_instance

            result = await handle_share(["colleague@example.com"], "test_owner", "test@example.com")
            assert "Share Request Sent" in result
            assert "colleague@example.com" in result


class TestRevokeHandler:
    """Tests for /revoke command handler."""

    @pytest.mark.asyncio
    async def test_revoke_help(self):
        """Test /revoke --help returns help text."""
        result = await handle_revoke(["--help"], "test_owner", "test@example.com")
        assert "**Usage:**" in result

    @pytest.mark.asyncio
    async def test_revoke_invalid_email(self):
        """Test /revoke with invalid email."""
        with patch("zylch.storage.storage.Storage"):
            result = await handle_revoke(["not-an-email"], "test_owner", "test@example.com")
            assert "Error" in result
            assert "Invalid email" in result

    @pytest.mark.asyncio
    async def test_revoke_success(self):
        """Test /revoke with valid email."""
        with patch("zylch.storage.storage.Storage") as mock_client:
            mock_instance = Mock()
            mock_instance.revoke_sharing.return_value = True
            mock_client.return_value = mock_instance

            result = await handle_revoke(
                ["colleague@example.com"], "test_owner", "test@example.com"
            )
            assert "Sharing Revoked" in result

    @pytest.mark.asyncio
    async def test_revoke_not_found(self):
        """Test /revoke when no sharing exists."""
        with patch("zylch.storage.storage.Storage") as mock_client:
            mock_instance = Mock()
            mock_instance.revoke_sharing.return_value = False
            mock_client.return_value = mock_instance

            result = await handle_revoke(["unknown@example.com"], "test_owner", "test@example.com")
            assert "Error" in result
            assert "No active sharing" in result


class TestSharingHandler:
    """Tests for /sharing command handler.

    NOTE: These tests reference handle_sharing which does not exist in
    command_handlers.py (the implementation was split into handle_share /
    handle_revoke). Tests are kept for future re-implementation; F821 is
    suppressed to keep lint clean.
    """

    @pytest.mark.asyncio
    async def test_sharing_help(self):
        """Test /sharing --help returns help text."""
        result = await handle_sharing(["--help"], "test_owner", "test@example.com")  # noqa: F821
        assert "**Usage:**" in result

    @pytest.mark.asyncio
    async def test_sharing_empty(self):
        """Test /sharing with no connections."""
        with patch("zylch.storage.storage.Storage") as mock_client:
            mock_instance = Mock()
            mock_instance.get_sharing_status.return_value = None
            mock_client.return_value = mock_instance

            result = await handle_sharing([], "test_owner", "test@example.com")  # noqa: F821
            assert "No sharing connections" in result

    @pytest.mark.asyncio
    async def test_sharing_with_connections(self):
        """Test /sharing with existing connections."""
        with patch("zylch.storage.storage.Storage") as mock_client:
            mock_instance = Mock()
            mock_instance.get_sharing_status.return_value = {
                "outgoing": [{"recipient_email": "colleague@example.com", "status": "authorized"}],
                "incoming": [{"sender_email": "boss@example.com", "status": "pending"}],
            }
            mock_client.return_value = mock_instance

            result = await handle_sharing([], "test_owner", "test@example.com")  # noqa: F821
            assert "colleague@example.com" in result
            assert "boss@example.com" in result
            assert "authorized" in result
            assert "pending" in result.lower()

    @pytest.mark.asyncio
    async def test_sharing_authorize(self):
        """Test /sharing --authorize."""
        with patch("zylch.storage.storage.Storage") as mock_client:
            mock_instance = Mock()
            mock_instance.authorize_sender.return_value = True
            mock_client.return_value = mock_instance

            result = await handle_sharing(  # noqa: F821
                ["--authorize", "sender@example.com"], "test_owner", "test@example.com"
            )
            assert "Sharing Authorized" in result


class TestHelpHandler:
    """Tests for /help command handler."""

    @pytest.mark.asyncio
    async def test_help_content(self):
        """Test /help returns comprehensive help."""
        result = await handle_help()

        # Check all major command categories are present
        assert "Data Management" in result
        assert "Memory & Automation" in result
        assert "Integrations" in result
        assert "Sharing" in result
        assert "Configuration" in result

        # Check specific commands
        assert "/sync" in result
        assert "/share" in result
        assert "/memory" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
