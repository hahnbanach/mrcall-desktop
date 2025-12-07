"""Test trigger service - background worker for event-driven automation.

Tests the TriggerService for processing queued trigger events.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from zylch.services.trigger_service import (
    TriggerService,
    queue_trigger_event,
    process_trigger_queue,
)


class TestTriggerService:
    """Tests for TriggerService class."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database client."""
        return Mock()

    @pytest.fixture
    def service(self, mock_db):
        """Create a TriggerService with mocked db."""
        with patch('zylch.storage.supabase_client.SupabaseStorage') as mock_storage:
            mock_storage.return_value = mock_db
            svc = TriggerService()
            svc.db = mock_db
            return svc

    # queue_event tests

    @pytest.mark.asyncio
    async def test_queue_event_no_triggers(self, service, mock_db):
        """Test queueing event when user has no triggers for that type."""
        mock_db.get_triggers_by_type.return_value = []

        result = await service.queue_event('owner123', 'email_received', {'from': 'test@example.com'})

        assert result is None
        mock_db.queue_trigger_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_queue_event_success(self, service, mock_db):
        """Test queueing event when user has triggers."""
        mock_db.get_triggers_by_type.return_value = [{'id': 'trigger1', 'instruction': 'test'}]
        mock_db.queue_trigger_event.return_value = {'id': 'event123', 'status': 'pending'}

        result = await service.queue_event('owner123', 'email_received', {'from': 'test@example.com'})

        assert result is not None
        assert result['id'] == 'event123'
        mock_db.queue_trigger_event.assert_called_once_with(
            'owner123', 'email_received', {'from': 'test@example.com'}
        )

    # process_pending_events tests

    @pytest.mark.asyncio
    async def test_process_no_pending_events(self, service, mock_db):
        """Test processing when no events are pending."""
        mock_db.get_pending_events.return_value = []

        stats = await service.process_pending_events()

        assert stats['processed'] == 0
        assert stats['succeeded'] == 0
        assert stats['failed'] == 0

    @pytest.mark.asyncio
    async def test_process_event_already_processing(self, service, mock_db):
        """Test handling event that's already being processed."""
        mock_db.get_pending_events.return_value = [
            {'id': 'event1', 'owner_id': 'owner1', 'event_type': 'call_received', 'event_data': {}}
        ]
        mock_db.mark_event_processing.return_value = False  # Already processing

        stats = await service.process_pending_events()

        assert stats['processed'] == 1
        assert stats['succeeded'] == 0
        assert stats['failed'] == 0

    @pytest.mark.asyncio
    async def test_process_event_no_triggers(self, service, mock_db):
        """Test processing event when triggers were deleted."""
        mock_db.get_pending_events.return_value = [
            {'id': 'event1', 'owner_id': 'owner1', 'event_type': 'call_received', 'event_data': {}}
        ]
        mock_db.mark_event_processing.return_value = True
        mock_db.get_triggers_by_type.return_value = []  # No triggers found

        stats = await service.process_pending_events()

        assert stats['processed'] == 1
        assert stats['succeeded'] == 1  # Considered success (no-op)
        mock_db.mark_event_completed.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_event_success(self, service, mock_db):
        """Test successful event processing."""
        mock_db.get_pending_events.return_value = [
            {
                'id': 'event1',
                'owner_id': 'owner1',
                'event_type': 'call_received',
                'event_data': {'caller': '+123456', 'transcript': 'Hello'}
            }
        ]
        mock_db.mark_event_processing.return_value = True
        mock_db.get_triggers_by_type.return_value = [
            {'id': 'trigger1', 'instruction': 'Send a thank you email'}
        ]

        # Mock the agent execution
        with patch.object(service, '_execute_with_agent', new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = 'Email sent successfully'

            stats = await service.process_pending_events()

        assert stats['processed'] == 1
        assert stats['succeeded'] == 1
        assert stats['failed'] == 0
        mock_db.mark_event_completed.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_event_agent_failure(self, service, mock_db):
        """Test event processing when agent execution fails."""
        mock_db.get_pending_events.return_value = [
            {
                'id': 'event1',
                'owner_id': 'owner1',
                'event_type': 'sms_received',
                'event_data': {'from': '+123456', 'body': 'Test message'}
            }
        ]
        mock_db.mark_event_processing.return_value = True
        mock_db.get_triggers_by_type.return_value = [
            {'id': 'trigger1', 'instruction': 'Reply to SMS'}
        ]

        # Mock agent execution to raise an exception
        with patch.object(service, '_execute_with_agent', new_callable=AsyncMock) as mock_agent:
            mock_agent.side_effect = Exception('Agent execution failed')

            stats = await service.process_pending_events()

        assert stats['processed'] == 1
        assert stats['succeeded'] == 0
        assert stats['failed'] == 1
        mock_db.mark_event_failed.assert_called()

    # _build_context_message tests

    def test_build_context_email(self, service):
        """Test building context message for email_received."""
        event_data = {
            'from': 'sender@example.com',
            'subject': 'Meeting Tomorrow',
            'snippet': 'Hi, just confirming our meeting...'
        }
        instruction = 'Add to calendar'

        result = service._build_context_message('email_received', event_data, instruction)

        assert 'sender@example.com' in result
        assert 'Meeting Tomorrow' in result
        assert 'confirming our meeting' in result
        assert 'Add to calendar' in result

    def test_build_context_sms(self, service):
        """Test building context message for sms_received."""
        event_data = {
            'from': '+1234567890',
            'body': 'Running 10 minutes late'
        }
        instruction = 'Log the delay'

        result = service._build_context_message('sms_received', event_data, instruction)

        assert '+1234567890' in result
        assert 'Running 10 minutes late' in result
        assert 'Log the delay' in result

    def test_build_context_call(self, service):
        """Test building context message for call_received."""
        event_data = {
            'caller': '+39123456789',
            'duration_seconds': 180,
            'transcript': 'Discussion about project timeline'
        }
        instruction = 'Summarize call and send email'

        result = service._build_context_message('call_received', event_data, instruction)

        assert '+39123456789' in result
        assert '180' in result
        assert 'project timeline' in result
        assert 'Summarize call' in result

    def test_build_context_unknown_type(self, service):
        """Test building context message for unknown event type."""
        event_data = {'custom': 'data'}
        instruction = 'Process this'

        result = service._build_context_message('custom_event', event_data, instruction)

        assert 'custom_event' in result
        assert 'Process this' in result

    # get_event_history tests

    @pytest.mark.asyncio
    async def test_get_event_history(self, service, mock_db):
        """Test getting event history for a user."""
        mock_db.get_event_history.return_value = [
            {'id': 'event1', 'event_type': 'call_received', 'status': 'completed'},
            {'id': 'event2', 'event_type': 'email_received', 'status': 'failed'}
        ]

        history = await service.get_event_history('owner123', limit=10)

        assert len(history) == 2
        mock_db.get_event_history.assert_called_once_with('owner123', 10)


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_queue_trigger_event(self):
        """Test the queue_trigger_event convenience function."""
        with patch('zylch.services.trigger_service.TriggerService') as MockService:
            mock_instance = MockService.return_value
            mock_instance.queue_event = AsyncMock(return_value={'id': 'event1'})

            result = await queue_trigger_event('owner1', 'call_received', {'caller': '+123'})

            mock_instance.queue_event.assert_called_once_with('owner1', 'call_received', {'caller': '+123'})
            assert result['id'] == 'event1'

    @pytest.mark.asyncio
    async def test_process_trigger_queue(self):
        """Test the process_trigger_queue convenience function."""
        with patch('zylch.services.trigger_service.TriggerService') as MockService:
            mock_instance = MockService.return_value
            mock_instance.process_pending_events = AsyncMock(return_value={'processed': 5, 'succeeded': 4, 'failed': 1})

            stats = await process_trigger_queue(limit=20)

            mock_instance.process_pending_events.assert_called_once_with(limit=20)
            assert stats['processed'] == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
