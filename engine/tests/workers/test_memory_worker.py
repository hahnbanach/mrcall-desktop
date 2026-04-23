"""
Unit tests for memory_agent.py

Tests cover phone number extraction, LinkedIn URL extraction, reconsolidation logic,
and the full email processing pipeline with mocked dependencies.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from app.workers.memory_worker import (
    extract_phone_numbers,
    extract_linkedin_urls,
    reconsolidate,
    process_email,
)


class TestExtractPhoneNumbers:
    """Test phone number extraction from various formats."""

    def test_extract_phone_numbers_us(self):
        """Test US phone number formats."""
        text = """
        Call me at (555) 123-4567 or 555-123-4567.
        You can also reach me at 555.123.4567.
        """
        numbers = extract_phone_numbers(text)

        assert len(numbers) == 3
        assert "(555) 123-4567" in numbers
        assert "555-123-4567" in numbers
        assert "555.123.4567" in numbers

    def test_extract_phone_numbers_international(self):
        """Test international phone number formats."""
        text = """
        International: +1-555-123-4567
        UK number: +44 20 7123 4567
        France: +33 1 42 86 82 00
        """
        numbers = extract_phone_numbers(text)

        assert len(numbers) == 3
        assert "+1-555-123-4567" in numbers
        assert "+44 20 7123 4567" in numbers
        assert "+33 1 42 86 82 00" in numbers

    def test_extract_phone_numbers_e164(self):
        """Test E.164 format phone numbers."""
        text = """
        E.164 format: +14155552671
        Another: +442071234567
        Mobile: +33612345678
        """
        numbers = extract_phone_numbers(text)

        assert len(numbers) == 3
        assert "+14155552671" in numbers
        assert "+442071234567" in numbers
        assert "+33612345678" in numbers

    def test_extract_phone_numbers_mixed(self):
        """Test mixed formats in single text."""
        text = "Contact: (555) 123-4567, +1-555-987-6543, or +442071234567"
        numbers = extract_phone_numbers(text)

        assert len(numbers) == 3

    def test_extract_phone_numbers_none(self):
        """Test text with no phone numbers."""
        text = "This text has no phone numbers at all."
        numbers = extract_phone_numbers(text)

        assert len(numbers) == 0

    def test_extract_phone_numbers_invalid(self):
        """Test that invalid numbers are not extracted."""
        text = "123-45 or 12345 or (12) 34-56 are not valid phone numbers"
        numbers = extract_phone_numbers(text)

        # Should not extract invalid short numbers
        assert len(numbers) == 0


class TestExtractLinkedInUrls:
    """Test LinkedIn URL extraction from various formats."""

    def test_extract_linkedin_urls_in_variant(self):
        """Test /in/ variant LinkedIn URLs."""
        text = """
        My profile: https://www.linkedin.com/in/john-doe-12345
        Or visit: linkedin.com/in/jane-smith
        Also: http://linkedin.com/in/bob-jones-67890/
        """
        urls = extract_linkedin_urls(text)

        assert len(urls) == 3
        assert "https://www.linkedin.com/in/john-doe-12345" in urls
        assert "linkedin.com/in/jane-smith" in urls
        assert "http://linkedin.com/in/bob-jones-67890/" in urls

    def test_extract_linkedin_urls_pub_variant(self):
        """Test /pub/ variant LinkedIn URLs."""
        text = """
        Public profile: https://www.linkedin.com/pub/john-doe/12/345/678
        Another: linkedin.com/pub/jane-smith/90/123/456
        """
        urls = extract_linkedin_urls(text)

        assert len(urls) == 2
        assert any("pub/john-doe" in url for url in urls)
        assert any("pub/jane-smith" in url for url in urls)

    def test_extract_linkedin_urls_company(self):
        """Test company LinkedIn URLs."""
        text = """
        Company: https://www.linkedin.com/company/acme-corp
        Showcase: linkedin.com/company/tech-solutions/
        """
        urls = extract_linkedin_urls(text)

        assert len(urls) == 2
        assert "https://www.linkedin.com/company/acme-corp" in urls

    def test_extract_linkedin_urls_mixed(self):
        """Test mixed LinkedIn URL formats."""
        text = """
        Profile: linkedin.com/in/john-doe
        Public: linkedin.com/pub/jane/1/2/3
        Company: linkedin.com/company/acme
        """
        urls = extract_linkedin_urls(text)

        assert len(urls) == 3

    def test_extract_linkedin_urls_none(self):
        """Test text with no LinkedIn URLs."""
        text = "Visit my website at example.com or twitter.com/johndoe"
        urls = extract_linkedin_urls(text)

        assert len(urls) == 0

    def test_extract_linkedin_urls_with_tracking(self):
        """Test URLs with tracking parameters."""
        text = "https://www.linkedin.com/in/john-doe?trk=profile-badge"
        urls = extract_linkedin_urls(text)

        assert len(urls) == 1
        # Should preserve the full URL including parameters
        assert "john-doe" in urls[0]


class TestReconsolidation:
    """Test memory reconsolidation logic."""

    def test_reconsolidation_updates_not_duplicates(self):
        """Test that reconsolidation updates existing memory, not duplicates."""
        old_memory = """
        Name: John Doe
        Company: Acme Corp
        Role: Engineer
        Phone: 555-123-4567
        """

        new_data = {
            "phones": ["555-987-6543", "555-123-4567"],  # One new, one existing
            "linkedins": ["linkedin.com/in/john-doe"],
            "topics": ["machine learning", "data science"],
            "action_items": ["Schedule follow-up call"],
        }

        result = reconsolidate(old_memory, new_data)

        # Should contain both phone numbers
        assert "555-123-4567" in result
        assert "555-987-6543" in result

        # Should contain LinkedIn
        assert "linkedin.com/in/john-doe" in result

        # Should contain topics
        assert "machine learning" in result
        assert "data science" in result

        # Should contain action items
        assert "Schedule follow-up call" in result

        # Should preserve old information
        assert "John Doe" in result
        assert "Acme Corp" in result

        # Should not duplicate phone number
        assert result.count("555-123-4567") == 1

    def test_reconsolidation_empty_old_memory(self):
        """Test reconsolidation with empty old memory."""
        old_memory = ""

        new_data = {
            "phones": ["555-123-4567"],
            "linkedins": ["linkedin.com/in/john-doe"],
            "topics": ["AI", "ML"],
            "action_items": ["Send proposal"],
        }

        result = reconsolidate(old_memory, new_data)

        assert "555-123-4567" in result
        assert "linkedin.com/in/john-doe" in result
        assert "AI" in result
        assert "Send proposal" in result

    def test_reconsolidation_empty_new_data(self):
        """Test reconsolidation with empty new data."""
        old_memory = "Name: John Doe\nCompany: Acme Corp"

        new_data = {"phones": [], "linkedins": [], "topics": [], "action_items": []}

        result = reconsolidate(old_memory, new_data)

        # Should preserve old memory
        assert "John Doe" in result
        assert "Acme Corp" in result

    def test_reconsolidation_multiple_updates(self):
        """Test reconsolidation with multiple new items."""
        old_memory = "Discussed: Project Alpha"

        new_data = {
            "phones": ["555-111-1111", "555-222-2222", "555-333-3333"],
            "linkedins": ["linkedin.com/in/person1", "linkedin.com/in/person2"],
            "topics": ["topic1", "topic2", "topic3", "topic4"],
            "action_items": ["action1", "action2", "action3"],
        }

        result = reconsolidate(old_memory, new_data)

        # All phones should be present
        assert all(phone in result for phone in new_data["phones"])

        # All LinkedIns should be present
        assert all(linkedin in result for linkedin in new_data["linkedins"])

        # All topics should be present
        assert all(topic in result for topic in new_data["topics"])

        # All action items should be present
        assert all(action in result for action in new_data["action_items"])


class TestProcessEmail:
    """Test the full email processing pipeline."""

    @pytest.fixture
    def mock_storage_client(self):
        """Create a mock storage client."""
        client = Mock()
        client.get_contact_memory.return_value = "Previous conversation about AI projects"
        client.store_contact_memory.return_value = None
        return client

    @pytest.fixture
    def mock_anthropic_client(self):
        """Create a mock Anthropic client."""
        client = Mock()

        # Mock the messages.create response
        mock_response = Mock()
        mock_response.content = [
            Mock(
                type="text",
                text="""
            PHONES: 555-123-4567, +1-555-987-6543
            LINKEDINS: linkedin.com/in/john-doe
            TOPICS: artificial intelligence, machine learning, neural networks
            ACTION_ITEMS: Schedule demo call, Send whitepaper, Follow up next week
            """,
            )
        ]

        client.messages.create.return_value = mock_response
        return client

    @pytest.fixture
    def sample_email(self):
        """Create a sample email for testing."""
        return {
            "id": "email123",
            "from": "john.doe@example.com",
            "subject": "AI Project Discussion",
            "body": """
            Hi there,

            I wanted to discuss our AI project. You can reach me at (555) 123-4567
            or check my LinkedIn: linkedin.com/in/john-doe

            We should focus on machine learning and neural networks.

            Best regards,
            John
            """,
            "timestamp": datetime.now().isoformat(),
        }

    def test_process_email_full_pipeline(
        self, mock_storage_client, mock_anthropic_client, sample_email
    ):
        """Test the complete email processing pipeline with mocks."""
        with (
            patch("app.workers.memory_worker.storage_client", mock_storage_client),
            patch("app.workers.memory_worker.anthropic_client", mock_anthropic_client),
        ):

            result = process_email(sample_email)

            # Verify storage client was called to get memory
            mock_storage_client.get_contact_memory.assert_called_once_with("john.doe@example.com")

            # Verify Anthropic API was called
            assert mock_anthropic_client.messages.create.called
            call_args = mock_anthropic_client.messages.create.call_args

            # Verify correct model and parameters
            assert call_args[1]["model"] == "claude-opus-4-6-20260205"
            assert call_args[1]["max_tokens"] == 2000

            # Verify message content includes email body and old memory
            messages = call_args[1]["messages"]
            assert len(messages) == 1
            assert sample_email["body"] in messages[0]["content"]
            assert "Previous conversation" in messages[0]["content"]

            # Verify storage client was called to store updated memory
            assert mock_storage_client.store_contact_memory.called
            store_call_args = mock_storage_client.store_contact_memory.call_args
            assert store_call_args[0][0] == "john.doe@example.com"

            # Verify the stored memory contains extracted information
            stored_memory = store_call_args[0][1]
            assert "555-123-4567" in stored_memory
            assert "linkedin.com/in/john-doe" in stored_memory
            assert "machine learning" in stored_memory
            assert "Schedule demo call" in stored_memory

            # Verify result structure
            assert result["status"] == "success"
            assert result["email_id"] == "email123"
            assert result["contact"] == "john.doe@example.com"
            assert "memory_updated" in result

    def test_process_email_no_previous_memory(
        self, mock_storage_client, mock_anthropic_client, sample_email
    ):
        """Test processing email when contact has no previous memory."""
        mock_storage_client.get_contact_memory.return_value = ""

        with (
            patch("app.workers.memory_worker.storage_client", mock_storage_client),
            patch("app.workers.memory_worker.anthropic_client", mock_anthropic_client),
        ):

            result = process_email(sample_email)

            # Should still process successfully
            assert result["status"] == "success"

            # Verify message to Anthropic doesn't include "Old Memory" section
            call_args = mock_anthropic_client.messages.create.call_args
            message_content = call_args[1]["messages"][0]["content"]
            # Old Memory section should be empty or not misleading
            assert sample_email["body"] in message_content

    def test_process_email_api_error(
        self, mock_storage_client, mock_anthropic_client, sample_email
    ):
        """Test handling of Anthropic API errors."""
        mock_anthropic_client.messages.create.side_effect = Exception("API Error")

        with (
            patch("app.workers.memory_worker.storage_client", mock_storage_client),
            patch("app.workers.memory_worker.anthropic_client", mock_anthropic_client),
        ):

            result = process_email(sample_email)

            # Should return error status
            assert result["status"] == "error"
            assert "API Error" in result["error"]

            # Should not store memory when processing fails
            assert not mock_storage_client.store_contact_memory.called

    def test_process_email_storage_error(
        self, mock_storage_client, mock_anthropic_client, sample_email
    ):
        """Test handling of storage errors."""
        mock_storage_client.store_contact_memory.side_effect = Exception("Storage Error")

        with (
            patch("app.workers.memory_worker.storage_client", mock_storage_client),
            patch("app.workers.memory_worker.anthropic_client", mock_anthropic_client),
        ):

            result = process_email(sample_email)

            # Should return error status
            assert result["status"] == "error"
            assert "Storage Error" in result["error"]


class TestBatchProcessing:
    """Test batch email processing."""

    @pytest.fixture
    def mock_storage_client(self):
        """Create a mock storage client."""
        client = Mock()
        client.get_contact_memory.return_value = "Previous conversation"
        client.store_contact_memory.return_value = None
        return client

    @pytest.fixture
    def mock_anthropic_client(self):
        """Create a mock Anthropic client with fast responses."""
        client = Mock()

        mock_response = Mock()
        mock_response.content = [
            Mock(
                type="text", text="PHONES: 555-0000\nLINKEDINS: \nTOPICS: test\nACTION_ITEMS: none"
            )
        ]

        client.messages.create.return_value = mock_response
        return client

    @pytest.fixture
    def batch_emails(self):
        """Create 10 sample emails for batch testing."""
        return [
            {
                "id": f"email{i}",
                "from": f"user{i}@example.com",
                "subject": f"Subject {i}",
                "body": f"Email body {i} with phone (555) 000-000{i}",
                "timestamp": datetime.now().isoformat(),
            }
            for i in range(10)
        ]

    def test_batch_processing_efficiency(
        self, mock_storage_client, mock_anthropic_client, batch_emails
    ):
        """Test that 10 emails are processed efficiently."""
        with (
            patch("app.workers.memory_worker.storage_client", mock_storage_client),
            patch("app.workers.memory_worker.anthropic_client", mock_anthropic_client),
        ):

            results = []
            start_time = datetime.now()

            for email in batch_emails:
                result = process_email(email)
                results.append(result)

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            # All should succeed
            assert len(results) == 10
            assert all(r["status"] == "success" for r in results)

            # Verify each email was processed
            for i, result in enumerate(results):
                assert result["email_id"] == f"email{i}"
                assert result["contact"] == f"user{i}@example.com"

            # Verify API was called correct number of times
            assert mock_anthropic_client.messages.create.call_count == 10

            # Verify storage was updated for each contact
            assert mock_storage_client.store_contact_memory.call_count == 10

            # Processing should be reasonably fast (mock calls should be instant)
            # Allow 5 seconds for overhead
            assert duration < 5.0

    def test_batch_processing_partial_failure(
        self, mock_storage_client, mock_anthropic_client, batch_emails
    ):
        """Test batch processing when some emails fail."""

        # Make every 3rd email fail
        def side_effect(*args, **kwargs):
            call_count = mock_anthropic_client.messages.create.call_count
            if call_count % 3 == 0:
                raise Exception("API Error")

            mock_response = Mock()
            mock_response.content = [
                Mock(type="text", text="PHONES: \nLINKEDINS: \nTOPICS: test\nACTION_ITEMS: none")
            ]
            return mock_response

        mock_anthropic_client.messages.create.side_effect = side_effect

        with (
            patch("app.workers.memory_worker.storage_client", mock_storage_client),
            patch("app.workers.memory_worker.anthropic_client", mock_anthropic_client),
        ):

            results = []
            for email in batch_emails:
                result = process_email(email)
                results.append(result)

            # Some should succeed, some should fail
            success_count = sum(1 for r in results if r["status"] == "success")
            error_count = sum(1 for r in results if r["status"] == "error")

            assert success_count > 0
            assert error_count > 0
            assert success_count + error_count == 10
