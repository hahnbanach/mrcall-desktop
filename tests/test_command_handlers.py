"""Test command handlers for slash commands.

Tests the new /trigger, /mrcall, /share, /revoke, /sharing handlers.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Test the command handlers
from zylch.services.command_handlers import (
    handle_trigger,
    handle_mrcall,
    handle_share,
    handle_revoke,
    handle_sharing,
    handle_help,
)


class TestTriggerHandler:
    """Tests for /trigger command handler."""

    @pytest.mark.asyncio
    async def test_trigger_help(self):
        """Test /trigger --help returns help text."""
        result = await handle_trigger(['--help'], 'test_owner', 'test@example.com')
        assert '**Usage:**' in result
        assert 'session_start' in result
        assert 'email_received' in result

    @pytest.mark.asyncio
    async def test_trigger_types(self):
        """Test /trigger --types returns available types."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_trigger(['--types'], 'test_owner', 'test@example.com')
            assert 'session_start' in result
            assert 'email_received' in result
            assert 'sms_received' in result
            assert 'call_received' in result

    @pytest.mark.asyncio
    async def test_trigger_list_empty(self):
        """Test /trigger --list with no triggers."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.list_triggers.return_value = []
            mock_client.return_value = mock_instance

            result = await handle_trigger(['--list'], 'test_owner', 'test@example.com')
            assert 'No Triggers' in result

    @pytest.mark.asyncio
    async def test_trigger_list_with_triggers(self):
        """Test /trigger --list with existing triggers."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.list_triggers.return_value = [
                {
                    'id': 'abc12345-1234-1234-1234-123456789012',
                    'trigger_type': 'session_start',
                    'instruction': 'Say good morning',
                    'active': True
                }
            ]
            mock_client.return_value = mock_instance

            result = await handle_trigger(['--list'], 'test_owner', 'test@example.com')
            assert 'Your Triggers' in result
            assert 'session_start' in result
            assert 'abc12345' in result

    @pytest.mark.asyncio
    async def test_trigger_add_missing_args(self):
        """Test /trigger --add with missing arguments."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_trigger(['--add'], 'test_owner', 'test@example.com')
            assert 'Error' in result
            assert 'Missing arguments' in result

    @pytest.mark.asyncio
    async def test_trigger_add_invalid_type(self):
        """Test /trigger --add with invalid trigger type."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_trigger(['--add', 'invalid_type', 'instruction'], 'test_owner', 'test@example.com')
            assert 'Error' in result
            assert 'Invalid trigger type' in result

    @pytest.mark.asyncio
    async def test_trigger_add_success(self):
        """Test /trigger --add with valid arguments."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.add_trigger.return_value = {'id': 'new-trigger-id'}
            mock_client.return_value = mock_instance

            result = await handle_trigger(
                ['--add', 'session_start', 'Say', 'good', 'morning'],
                'test_owner',
                'test@example.com'
            )
            assert 'Trigger Created' in result
            assert 'session_start' in result

    @pytest.mark.asyncio
    async def test_trigger_remove_missing_id(self):
        """Test /trigger --remove without ID."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_trigger(['--remove'], 'test_owner', 'test@example.com')
            assert 'Error' in result
            assert 'Missing trigger ID' in result

    @pytest.mark.asyncio
    async def test_trigger_remove_success(self):
        """Test /trigger --remove with valid ID."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.remove_trigger.return_value = True
            mock_client.return_value = mock_instance

            result = await handle_trigger(['--remove', 'abc123'], 'test_owner', 'test@example.com')
            assert 'Trigger Removed' in result


class TestMrCallHandler:
    """Tests for /mrcall command handler."""

    @pytest.mark.asyncio
    async def test_mrcall_help(self):
        """Test /mrcall --help returns help text."""
        result = await handle_mrcall(['--help'], 'test_owner', 'test@example.com')
        assert '**Usage:**' in result
        assert 'business_id' in result

    @pytest.mark.asyncio
    async def test_mrcall_status_not_linked(self):
        """Test /mrcall with no link."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.get_mrcall_link.return_value = None
            mock_client.return_value = mock_instance

            result = await handle_mrcall([], 'test_owner', 'test@example.com')
            assert 'Not linked' in result

    @pytest.mark.asyncio
    async def test_mrcall_status_linked(self):
        """Test /mrcall with existing link."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.get_mrcall_link.return_value = {
                'mrcall_business_id': '123456',
                'created_at': '2024-01-01T00:00:00'
            }
            mock_client.return_value = mock_instance

            result = await handle_mrcall([], 'test_owner', 'test@example.com')
            assert '123456' in result
            assert 'Linked Business' in result

    @pytest.mark.asyncio
    async def test_mrcall_link_success(self):
        """Test /mrcall <business_id> linking."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.set_mrcall_link.return_value = {'id': 'link-id'}
            mock_client.return_value = mock_instance

            result = await handle_mrcall(['987654'], 'test_owner', 'test@example.com')
            assert 'MrCall Linked' in result
            assert '987654' in result

    @pytest.mark.asyncio
    async def test_mrcall_unlink(self):
        """Test /mrcall --unlink."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.remove_mrcall_link.return_value = True
            mock_client.return_value = mock_instance

            result = await handle_mrcall(['--unlink'], 'test_owner', 'test@example.com')
            assert 'Unlinked' in result


class TestShareHandler:
    """Tests for /share command handler."""

    @pytest.mark.asyncio
    async def test_share_help(self):
        """Test /share --help returns help text."""
        result = await handle_share(['--help'], 'test_owner', 'test@example.com')
        assert '**Usage:**' in result
        assert 'email' in result.lower()

    @pytest.mark.asyncio
    async def test_share_invalid_email(self):
        """Test /share with invalid email."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_share(['not-an-email'], 'test_owner', 'test@example.com')
            assert 'Error' in result
            assert 'Invalid email' in result

    @pytest.mark.asyncio
    async def test_share_self(self):
        """Test /share with own email."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_share(['test@example.com'], 'test_owner', 'test@example.com')
            assert 'Error' in result
            assert "can't share with yourself" in result.lower()

    @pytest.mark.asyncio
    async def test_share_no_user_email(self):
        """Test /share without user email context."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_share(['other@example.com'], 'test_owner', None)
            assert 'Error' in result
            assert 'email is not available' in result

    @pytest.mark.asyncio
    async def test_share_success(self):
        """Test /share with valid email."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.register_share_recipient.return_value = {'status': 'pending'}
            mock_client.return_value = mock_instance

            result = await handle_share(['colleague@example.com'], 'test_owner', 'test@example.com')
            assert 'Share Request Sent' in result
            assert 'colleague@example.com' in result


class TestRevokeHandler:
    """Tests for /revoke command handler."""

    @pytest.mark.asyncio
    async def test_revoke_help(self):
        """Test /revoke --help returns help text."""
        result = await handle_revoke(['--help'], 'test_owner', 'test@example.com')
        assert '**Usage:**' in result

    @pytest.mark.asyncio
    async def test_revoke_invalid_email(self):
        """Test /revoke with invalid email."""
        with patch('zylch.storage.supabase_client.SupabaseStorage'):
            result = await handle_revoke(['not-an-email'], 'test_owner', 'test@example.com')
            assert 'Error' in result
            assert 'Invalid email' in result

    @pytest.mark.asyncio
    async def test_revoke_success(self):
        """Test /revoke with valid email."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.revoke_sharing.return_value = True
            mock_client.return_value = mock_instance

            result = await handle_revoke(['colleague@example.com'], 'test_owner', 'test@example.com')
            assert 'Sharing Revoked' in result

    @pytest.mark.asyncio
    async def test_revoke_not_found(self):
        """Test /revoke when no sharing exists."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.revoke_sharing.return_value = False
            mock_client.return_value = mock_instance

            result = await handle_revoke(['unknown@example.com'], 'test_owner', 'test@example.com')
            assert 'Error' in result
            assert 'No active sharing' in result


class TestSharingHandler:
    """Tests for /sharing command handler."""

    @pytest.mark.asyncio
    async def test_sharing_help(self):
        """Test /sharing --help returns help text."""
        result = await handle_sharing(['--help'], 'test_owner', 'test@example.com')
        assert '**Usage:**' in result

    @pytest.mark.asyncio
    async def test_sharing_empty(self):
        """Test /sharing with no connections."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.get_sharing_status.return_value = None
            mock_client.return_value = mock_instance

            result = await handle_sharing([], 'test_owner', 'test@example.com')
            assert 'No sharing connections' in result

    @pytest.mark.asyncio
    async def test_sharing_with_connections(self):
        """Test /sharing with existing connections."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.get_sharing_status.return_value = {
                'outgoing': [
                    {'recipient_email': 'colleague@example.com', 'status': 'authorized'}
                ],
                'incoming': [
                    {'sender_email': 'boss@example.com', 'status': 'pending'}
                ]
            }
            mock_client.return_value = mock_instance

            result = await handle_sharing([], 'test_owner', 'test@example.com')
            assert 'colleague@example.com' in result
            assert 'boss@example.com' in result
            assert 'authorized' in result
            assert 'pending' in result.lower()

    @pytest.mark.asyncio
    async def test_sharing_authorize(self):
        """Test /sharing --authorize."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_client:
            mock_instance = Mock()
            mock_instance.authorize_sender.return_value = True
            mock_client.return_value = mock_instance

            result = await handle_sharing(['--authorize', 'sender@example.com'], 'test_owner', 'test@example.com')
            assert 'Sharing Authorized' in result


class TestHelpHandler:
    """Tests for /help command handler."""

    @pytest.mark.asyncio
    async def test_help_content(self):
        """Test /help returns comprehensive help."""
        result = await handle_help()

        # Check all major command categories are present
        assert 'Data Management' in result
        assert 'Memory & Automation' in result
        assert 'Integrations' in result
        assert 'Sharing' in result
        assert 'Configuration' in result

        # Check specific commands
        assert '/sync' in result
        assert '/trigger' in result
        assert '/mrcall' in result
        assert '/share' in result
        assert '/memory' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
