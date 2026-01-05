"""Test command handlers for slash commands.

Tests the new /trigger, /mrcall, /share, /revoke handlers.
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
        assert '📞 MrCall Integration' in result
        assert 'list' in result
        assert 'link' in result

    @pytest.mark.asyncio
    async def test_mrcall_status_not_connected(self):
        """Test /mrcall with no OAuth credentials."""
        with patch('zylch.services.command_handlers.SupabaseClient') as mock_client, \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds:
            mock_instance = Mock()
            mock_client.return_value = mock_instance
            mock_creds.return_value = None

            result = await handle_mrcall([], 'test_owner', 'test@example.com')
            assert 'Not connected' in result

    @pytest.mark.asyncio
    async def test_mrcall_status_connected_linked(self):
        """Test /mrcall with OAuth credentials and linked business."""
        with patch('zylch.services.command_handlers.SupabaseClient') as mock_client, \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds:
            mock_instance = Mock()
            mock_client.return_value = mock_instance
            mock_creds.return_value = {
                'access_token': 'test_token',
                'business_id': '123456',
                'metadata': {'email': 'test@mrcall.com'}
            }

            result = await handle_mrcall([], 'test_owner', 'test@example.com')
            assert '123456' in result
            assert 'Connected and linked' in result

    @pytest.mark.asyncio
    async def test_mrcall_status_connected_not_linked(self):
        """Test /mrcall with OAuth credentials but no linked business."""
        with patch('zylch.services.command_handlers.SupabaseClient') as mock_client, \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds:
            mock_instance = Mock()
            mock_client.return_value = mock_instance
            mock_creds.return_value = {
                'access_token': 'test_token',
                'business_id': None,
                'metadata': {'email': 'test@mrcall.com'}
            }

            result = await handle_mrcall([], 'test_owner', 'test@example.com')
            assert 'Connected' in result
            assert 'not linked' in result

    @pytest.mark.asyncio
    async def test_mrcall_list_not_connected(self):
        """Test /mrcall list without OAuth credentials."""
        with patch('zylch.services.command_handlers.SupabaseClient'), \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds:
            mock_creds.return_value = None

            result = await handle_mrcall(['list'], 'test_owner', 'test@example.com')
            assert 'Not connected to MrCall' in result
            assert '/connect mrcall' in result

    @pytest.mark.asyncio
    async def test_mrcall_list_success(self):
        """Test /mrcall list with OAuth credentials."""
        with patch('zylch.services.command_handlers.SupabaseClient'), \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds, \
             patch('httpx.AsyncClient') as mock_httpx:
            mock_creds.return_value = {
                'access_token': 'test_token',
                'business_id': None
            }

            # Mock httpx response
            mock_response = AsyncMock()
            mock_response.json.return_value = [
                {'businessId': 'biz_001', 'nickname': 'Test Assistant', 'companyName': 'Acme Corp'},
                {'businessId': 'biz_002', 'nickname': 'Support Bot', 'serviceNumber': '+1234567890'}
            ]
            mock_response.raise_for_status = Mock()

            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__.return_value = mock_client_instance
            mock_client_instance.__aexit__.return_value = None
            mock_client_instance.post.return_value = mock_response
            mock_httpx.return_value = mock_client_instance

            result = await handle_mrcall(['list'], 'test_owner', 'test@example.com')
            assert 'Your MrCall Assistants' in result
            assert 'Test Assistant' in result
            assert 'Support Bot' in result

    @pytest.mark.asyncio
    async def test_mrcall_link_success(self):
        """Test /mrcall link N linking."""
        with patch('zylch.services.command_handlers.SupabaseClient') as mock_client, \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds, \
             patch('httpx.AsyncClient') as mock_httpx:
            mock_instance = Mock()
            mock_instance.set_mrcall_link.return_value = True
            mock_client.return_value = mock_instance

            mock_creds.return_value = {
                'access_token': 'test_token',
                'business_id': None
            }

            # Mock httpx response for business list
            mock_response = AsyncMock()
            mock_response.json.return_value = [
                {'businessId': 'biz_001', 'nickname': 'Test Assistant'},
            ]
            mock_response.raise_for_status = Mock()

            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__.return_value = mock_client_instance
            mock_client_instance.__aexit__.return_value = None
            mock_client_instance.post.return_value = mock_response
            mock_httpx.return_value = mock_client_instance

            result = await handle_mrcall(['link', '1'], 'test_owner', 'test@example.com')
            assert 'MrCall Linked' in result
            assert 'Test Assistant' in result

    @pytest.mark.asyncio
    async def test_mrcall_unlink(self):
        """Test /mrcall unlink."""
        with patch('zylch.services.command_handlers.SupabaseClient') as mock_client:
            mock_instance = Mock()
            mock_instance.remove_mrcall_link.return_value = True
            mock_client.return_value = mock_instance

            result = await handle_mrcall(['unlink'], 'test_owner', 'test@example.com')
            assert 'Unlinked' in result

    @pytest.mark.asyncio
    async def test_mrcall_variables_not_linked(self):
        """Test /mrcall variables without linked business."""
        with patch('zylch.services.command_handlers.SupabaseClient') as mock_client, \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds:
            mock_instance = Mock()
            mock_instance.get_mrcall_link.return_value = None
            mock_client.return_value = mock_instance
            mock_creds.return_value = {'access_token': 'token', 'business_id': None}

            result = await handle_mrcall(['variables'], 'test_owner', 'test@example.com')
            assert 'No assistant linked' in result

    @pytest.mark.asyncio
    async def test_mrcall_variables_get(self):
        """Test /mrcall variables get with linked business."""
        with patch('zylch.services.command_handlers.SupabaseClient'), \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds, \
             patch('zylch.tools.starchat.create_starchat_client') as mock_create:
            mock_creds.return_value = {
                'access_token': 'test_token',
                'business_id': 'biz_001'
            }

            mock_sc_client = AsyncMock()
            mock_sc_client.get_all_variables.return_value = [
                {'name': 'GREETING', 'description': 'Welcome message', 'value': 'Hello!'},
                {'name': 'OBJECTIVE', 'description': 'Main goal', 'value': 'Schedule appointments'}
            ]
            mock_create.return_value = mock_sc_client

            result = await handle_mrcall(['variables'], 'test_owner', 'test@example.com')
            assert 'MrCall Variables' in result
            assert 'GREETING' in result
            assert 'Hello!' in result

    @pytest.mark.asyncio
    async def test_mrcall_variables_set(self):
        """Test /mrcall variables set."""
        with patch('zylch.services.command_handlers.SupabaseClient'), \
             patch('zylch.services.command_handlers.get_mrcall_credentials') as mock_creds, \
             patch('zylch.tools.starchat.create_starchat_client') as mock_create:
            mock_creds.return_value = {
                'access_token': 'test_token',
                'business_id': 'biz_001'
            }

            mock_sc_client = AsyncMock()
            mock_sc_client.update_business_variable.return_value = None
            mock_create.return_value = mock_sc_client

            result = await handle_mrcall(['variables', 'set', 'GREETING', 'New greeting!'], 'test_owner', 'test@example.com')
            assert 'Variable Updated' in result
            assert 'GREETING' in result


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
