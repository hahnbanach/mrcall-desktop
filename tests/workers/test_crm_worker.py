"""
Unit tests for crm_worker.py

Tests cover status computation, priority calculation, action generation,
and avatar computation with mocked dependencies.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from app.workers.crm_worker import (
    compute_status,
    compute_priority,
    generate_action,
    compute_avatar
)


class TestComputeStatus:
    """Test CRM status computation based on last interaction."""

    def test_compute_status_open(self):
        """Test status is 'open' when contact sent the last message."""
        thread = [
            {"from": "owner@example.com", "timestamp": "2025-01-01T10:00:00Z"},
            {"from": "contact@example.com", "timestamp": "2025-01-01T10:05:00Z"}
        ]
        memory = "Discussed project timeline"

        status = compute_status(thread, memory, "owner@example.com")

        assert status == "open"

    def test_compute_status_waiting(self):
        """Test status is 'waiting' when owner sent the last message."""
        thread = [
            {"from": "contact@example.com", "timestamp": "2025-01-01T10:00:00Z"},
            {"from": "owner@example.com", "timestamp": "2025-01-01T10:05:00Z"}
        ]
        memory = "Awaiting response on proposal"

        status = compute_status(thread, memory, "owner@example.com")

        assert status == "waiting"

    def test_compute_status_closed_no_response_memory(self):
        """Test status is 'closed' when memory contains 'no response'."""
        thread = [
            {"from": "owner@example.com", "timestamp": "2025-01-01T10:00:00Z"},
            {"from": "owner@example.com", "timestamp": "2025-01-02T10:00:00Z"}
        ]
        memory = "Sent multiple follow-ups but received no response. Moving on."

        status = compute_status(thread, memory, "owner@example.com")

        assert status == "closed"

    def test_compute_status_closed_not_interested_memory(self):
        """Test status is 'closed' when memory indicates lack of interest."""
        thread = [
            {"from": "contact@example.com", "timestamp": "2025-01-01T10:00:00Z"}
        ]
        memory = "Contact said they are not interested in our services"

        status = compute_status(thread, memory, "owner@example.com")

        assert status == "closed"

    def test_compute_status_closed_deal_done_memory(self):
        """Test status is 'closed' when deal is completed."""
        thread = [
            {"from": "owner@example.com", "timestamp": "2025-01-01T10:00:00Z"}
        ]
        memory = "Deal closed successfully. Contract signed."

        status = compute_status(thread, memory, "owner@example.com")

        assert status == "closed"

    def test_compute_status_empty_thread(self):
        """Test status computation with empty thread."""
        thread = []
        memory = "No communication yet"

        status = compute_status(thread, memory, "owner@example.com")

        # Should default to 'open' or handle gracefully
        assert status in ["open", "waiting", "closed"]

    def test_compute_status_single_message_from_contact(self):
        """Test status with single message from contact."""
        thread = [
            {"from": "contact@example.com", "timestamp": "2025-01-01T10:00:00Z"}
        ]
        memory = "Initial inquiry about services"

        status = compute_status(thread, memory, "owner@example.com")

        assert status == "open"

    def test_compute_status_case_insensitive_memory(self):
        """Test that memory matching is case-insensitive."""
        thread = [
            {"from": "owner@example.com", "timestamp": "2025-01-01T10:00:00Z"}
        ]
        memory = "NO RESPONSE after three attempts"

        status = compute_status(thread, memory, "owner@example.com")

        assert status == "closed"


class TestComputePriority:
    """Test priority computation based on urgency and importance."""

    def test_compute_priority_high_urgency_high_importance(self):
        """Test priority calculation with high urgency and importance."""
        memory = "URGENT: Need immediate response. CEO is waiting. Critical deal."
        last_interaction = (datetime.now() - timedelta(hours=1)).isoformat()

        priority = compute_priority(memory, last_interaction)

        # Should be high priority (8-10)
        assert 8 <= priority <= 10

    def test_compute_priority_low_urgency_low_importance(self):
        """Test priority calculation with low urgency and importance."""
        memory = "General inquiry about services. No rush."
        last_interaction = (datetime.now() - timedelta(days=30)).isoformat()

        priority = compute_priority(memory, last_interaction)

        # Should be low priority (1-3)
        assert 1 <= priority <= 3

    def test_compute_priority_medium_urgency_medium_importance(self):
        """Test priority calculation with medium urgency and importance."""
        memory = "Discussed project timeline. Follow up needed next week."
        last_interaction = (datetime.now() - timedelta(days=3)).isoformat()

        priority = compute_priority(memory, last_interaction)

        # Should be medium priority (4-7)
        assert 4 <= priority <= 7

    def test_compute_priority_bounds(self):
        """Test that priority is always between 1 and 10."""
        test_cases = [
            ("URGENT URGENT URGENT CEO VIP CRITICAL ASAP", (datetime.now() - timedelta(minutes=1)).isoformat()),
            ("No urgency at all", (datetime.now() - timedelta(days=365)).isoformat()),
            ("", (datetime.now() - timedelta(days=100)).isoformat()),
            ("Some random text without urgency markers", datetime.now().isoformat())
        ]

        for memory, last_interaction in test_cases:
            priority = compute_priority(memory, last_interaction)

            assert 1 <= priority <= 10, f"Priority {priority} out of bounds for memory: {memory}"

    def test_compute_priority_urgency_keywords(self):
        """Test that urgency keywords affect priority."""
        base_time = (datetime.now() - timedelta(days=1)).isoformat()

        # Test various urgency levels
        urgent_memory = "URGENT: Response needed ASAP"
        important_memory = "Important project for VIP client"
        normal_memory = "Regular follow-up needed"

        urgent_priority = compute_priority(urgent_memory, base_time)
        important_priority = compute_priority(important_memory, base_time)
        normal_priority = compute_priority(normal_memory, base_time)

        # Urgent should be higher than important, important higher than normal
        assert urgent_priority > normal_priority
        assert important_priority > normal_priority

    def test_compute_priority_time_decay(self):
        """Test that older interactions have lower priority."""
        memory = "Follow up on proposal"

        recent_time = (datetime.now() - timedelta(hours=1)).isoformat()
        old_time = (datetime.now() - timedelta(days=30)).isoformat()

        recent_priority = compute_priority(memory, recent_time)
        old_priority = compute_priority(memory, old_time)

        # Recent interaction should have higher priority
        assert recent_priority >= old_priority

    def test_compute_priority_empty_memory(self):
        """Test priority computation with empty memory."""
        priority = compute_priority("", datetime.now().isoformat())

        # Should return valid priority even with empty memory
        assert 1 <= priority <= 10

    def test_compute_priority_invalid_timestamp(self):
        """Test priority computation with invalid timestamp."""
        memory = "Test memory"
        invalid_timestamp = "not-a-timestamp"

        # Should handle gracefully and return valid priority
        priority = compute_priority(memory, invalid_timestamp)

        assert 1 <= priority <= 10


class TestGenerateAction:
    """Test action generation using Claude Haiku."""

    @pytest.fixture
    def mock_anthropic_client(self):
        """Create a mock Anthropic client."""
        client = Mock()

        mock_response = Mock()
        mock_response.content = [
            Mock(type="text", text="Send follow-up email with pricing proposal")
        ]

        client.messages.create.return_value = mock_response
        return client

    def test_generate_action_specific_action(self, mock_anthropic_client):
        """Test that specific action is generated from Haiku."""
        memory = "Discussed pricing for enterprise plan. Waiting for budget approval."
        status = "waiting"
        priority = 8

        with patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):
            action = generate_action(memory, status, priority)

        # Should return specific action
        assert isinstance(action, str)
        assert len(action) > 0
        assert "follow-up" in action.lower() or "pricing" in action.lower()

        # Verify API was called with correct parameters
        assert mock_anthropic_client.messages.create.called
        call_args = mock_anthropic_client.messages.create.call_args

        # Verify model
        assert call_args[1]["model"] == "claude-3-5-haiku-20241022"

        # Verify message includes context
        messages = call_args[1]["messages"]
        assert len(messages) == 1
        assert memory in messages[0]["content"]
        assert str(priority) in messages[0]["content"]
        assert status in messages[0]["content"]

    def test_generate_action_open_status(self, mock_anthropic_client):
        """Test action generation for 'open' status."""
        mock_response = Mock()
        mock_response.content = [
            Mock(type="text", text="Review their inquiry and respond with initial proposal")
        ]
        mock_anthropic_client.messages.create.return_value = mock_response

        memory = "New inquiry about AI consulting services"
        status = "open"
        priority = 9

        with patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):
            action = generate_action(memory, status, priority)

        assert "respond" in action.lower() or "reply" in action.lower()

    def test_generate_action_waiting_status(self, mock_anthropic_client):
        """Test action generation for 'waiting' status."""
        mock_response = Mock()
        mock_response.content = [
            Mock(type="text", text="Check in gently after 2 days if no response")
        ]
        mock_anthropic_client.messages.create.return_value = mock_response

        memory = "Sent proposal 3 days ago. Awaiting decision."
        status = "waiting"
        priority = 6

        with patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):
            action = generate_action(memory, status, priority)

        assert "check" in action.lower() or "follow" in action.lower()

    def test_generate_action_closed_status(self, mock_anthropic_client):
        """Test action generation for 'closed' status."""
        mock_response = Mock()
        mock_response.content = [
            Mock(type="text", text="Archive conversation. No action needed.")
        ]
        mock_anthropic_client.messages.create.return_value = mock_response

        memory = "Deal closed. Contract signed. Implementation team assigned."
        status = "closed"
        priority = 2

        with patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):
            action = generate_action(memory, status, priority)

        assert "archive" in action.lower() or "no action" in action.lower()

    def test_generate_action_high_priority(self, mock_anthropic_client):
        """Test action generation with high priority."""
        mock_response = Mock()
        mock_response.content = [
            Mock(type="text", text="URGENT: Call immediately to discuss critical issue")
        ]
        mock_anthropic_client.messages.create.return_value = mock_response

        memory = "URGENT: Production system down. Client escalated to CEO."
        status = "open"
        priority = 10

        with patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):
            action = generate_action(memory, status, priority)

        assert len(action) > 0
        # High priority actions should be more specific/urgent

    def test_generate_action_api_error(self, mock_anthropic_client):
        """Test handling of API errors during action generation."""
        mock_anthropic_client.messages.create.side_effect = Exception("API Error")

        memory = "Test memory"
        status = "open"
        priority = 5

        with patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):
            action = generate_action(memory, status, priority)

        # Should return fallback action
        assert isinstance(action, str)
        assert len(action) > 0
        assert "error" in action.lower() or "review" in action.lower()

    def test_generate_action_empty_memory(self, mock_anthropic_client):
        """Test action generation with empty memory."""
        mock_response = Mock()
        mock_response.content = [
            Mock(type="text", text="Review contact history and initiate conversation")
        ]
        mock_anthropic_client.messages.create.return_value = mock_response

        memory = ""
        status = "open"
        priority = 5

        with patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):
            action = generate_action(memory, status, priority)

        # Should still generate valid action
        assert isinstance(action, str)
        assert len(action) > 0


class TestComputeAvatar:
    """Test the full avatar computation pipeline."""

    @pytest.fixture
    def mock_storage_client(self):
        """Create a mock storage client."""
        client = Mock()
        client.get_contact_memory.return_value = """
        Name: Jane Smith
        Company: Tech Innovations Inc.
        Role: VP of Engineering
        Discussed: AI/ML infrastructure, scaling challenges
        Recent topics: Kubernetes, microservices, team growth
        """
        client.get_thread.return_value = [
            {
                "from": "owner@example.com",
                "subject": "Following up on our discussion",
                "timestamp": (datetime.now() - timedelta(days=2)).isoformat()
            },
            {
                "from": "jane.smith@techinnovations.com",
                "subject": "Re: Following up on our discussion",
                "timestamp": (datetime.now() - timedelta(days=1)).isoformat()
            }
        ]
        return client

    @pytest.fixture
    def mock_anthropic_client(self):
        """Create a mock Anthropic client for action generation."""
        client = Mock()

        mock_response = Mock()
        mock_response.content = [
            Mock(type="text", text="Send detailed proposal addressing their scaling challenges")
        ]

        client.messages.create.return_value = mock_response
        return client

    def test_compute_avatar_full_pipeline(self, mock_storage_client, mock_anthropic_client):
        """Test the complete avatar computation pipeline with mocks."""
        contact_email = "jane.smith@techinnovations.com"
        owner_email = "owner@example.com"

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            avatar = compute_avatar(contact_email, owner_email)

        # Verify storage client was called
        mock_storage_client.get_contact_memory.assert_called_once_with(contact_email)
        mock_storage_client.get_thread.assert_called_once_with(contact_email)

        # Verify avatar structure
        assert isinstance(avatar, dict)
        assert "email" in avatar
        assert "status" in avatar
        assert "priority" in avatar
        assert "next_action" in avatar
        assert "last_interaction" in avatar
        assert "memory_summary" in avatar

        # Verify values
        assert avatar["email"] == contact_email
        assert avatar["status"] in ["open", "waiting", "closed"]
        assert 1 <= avatar["priority"] <= 10
        assert isinstance(avatar["next_action"], str)
        assert len(avatar["next_action"]) > 0

        # Last interaction should be from the thread
        assert avatar["last_interaction"] is not None

        # Memory summary should contain key info
        assert len(avatar["memory_summary"]) > 0

    def test_compute_avatar_open_status(self, mock_storage_client, mock_anthropic_client):
        """Test avatar computation with 'open' status."""
        # Set up thread where contact sent last message
        mock_storage_client.get_thread.return_value = [
            {
                "from": "owner@example.com",
                "timestamp": (datetime.now() - timedelta(days=2)).isoformat()
            },
            {
                "from": "contact@example.com",
                "timestamp": (datetime.now() - timedelta(days=1)).isoformat()
            }
        ]

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            avatar = compute_avatar("contact@example.com", "owner@example.com")

        assert avatar["status"] == "open"

    def test_compute_avatar_waiting_status(self, mock_storage_client, mock_anthropic_client):
        """Test avatar computation with 'waiting' status."""
        # Set up thread where owner sent last message
        mock_storage_client.get_thread.return_value = [
            {
                "from": "contact@example.com",
                "timestamp": (datetime.now() - timedelta(days=2)).isoformat()
            },
            {
                "from": "owner@example.com",
                "timestamp": (datetime.now() - timedelta(days=1)).isoformat()
            }
        ]

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            avatar = compute_avatar("contact@example.com", "owner@example.com")

        assert avatar["status"] == "waiting"

    def test_compute_avatar_closed_status(self, mock_storage_client, mock_anthropic_client):
        """Test avatar computation with 'closed' status."""
        mock_storage_client.get_contact_memory.return_value = "Deal closed. No further action needed."

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            avatar = compute_avatar("contact@example.com", "owner@example.com")

        assert avatar["status"] == "closed"

    def test_compute_avatar_high_priority(self, mock_storage_client, mock_anthropic_client):
        """Test avatar computation with high priority."""
        mock_storage_client.get_contact_memory.return_value = "URGENT: CEO escalation. Critical issue needs immediate attention."
        mock_storage_client.get_thread.return_value = [
            {
                "from": "contact@example.com",
                "timestamp": (datetime.now() - timedelta(hours=1)).isoformat()
            }
        ]

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            avatar = compute_avatar("contact@example.com", "owner@example.com")

        # Should have high priority
        assert avatar["priority"] >= 8

    def test_compute_avatar_no_memory(self, mock_storage_client, mock_anthropic_client):
        """Test avatar computation when no memory exists."""
        mock_storage_client.get_contact_memory.return_value = ""
        mock_storage_client.get_thread.return_value = []

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            avatar = compute_avatar("new-contact@example.com", "owner@example.com")

        # Should still return valid avatar
        assert isinstance(avatar, dict)
        assert avatar["email"] == "new-contact@example.com"
        assert "status" in avatar
        assert "priority" in avatar

    def test_compute_avatar_storage_error(self, mock_storage_client, mock_anthropic_client):
        """Test handling of storage errors."""
        mock_storage_client.get_contact_memory.side_effect = Exception("Storage Error")

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            with pytest.raises(Exception) as exc_info:
                compute_avatar("contact@example.com", "owner@example.com")

            assert "Storage Error" in str(exc_info.value)

    def test_compute_avatar_action_generation_error(self, mock_storage_client, mock_anthropic_client):
        """Test handling of action generation errors."""
        mock_anthropic_client.messages.create.side_effect = Exception("API Error")

        with patch('app.workers.crm_worker.storage_client', mock_storage_client), \
             patch('app.workers.crm_worker.anthropic_client', mock_anthropic_client):

            avatar = compute_avatar("contact@example.com", "owner@example.com")

        # Should return avatar with fallback action
        assert isinstance(avatar, dict)
        assert "next_action" in avatar
        assert isinstance(avatar["next_action"], str)
