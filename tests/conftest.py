"""Shared test fixtures for pytest."""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from unittest.mock import Mock, MagicMock

from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_owner_id():
    """Test user owner_id."""
    return "test_owner_von_neumann"


@pytest.fixture
def storage():
    """Get SupabaseStorage instance for tests."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        pytest.skip("Supabase not configured")
    return SupabaseStorage.get_instance()


@pytest.fixture
def test_email_data():
    """Generate test email data."""
    def _create_email(
        gmail_id: str,
        from_email: str,
        to_email: str,
        subject: str,
        body: str,
        date_offset_days: int = 0
    ) -> Dict[str, Any]:
        date = datetime.now(timezone.utc) - timedelta(days=date_offset_days)
        return {
            'id': gmail_id,
            'thread_id': f'thread_{gmail_id}',
            'from_email': from_email,
            'from_name': from_email.split('@')[0].replace('.', ' ').title(),
            'to_email': to_email,
            'cc_email': '',
            'subject': subject,
            'date': date.isoformat(),
            'date_timestamp': int(date.timestamp()),
            'snippet': body[:100],
            'body_plain': body,
            'body_html': f'<p>{body}</p>',
            'labels': ['INBOX'],
            'message_id_header': f'<{gmail_id}@mail.gmail.com>',
            'in_reply_to': None,
            'references': None
        }
    return _create_email


@pytest.fixture
def test_contact_data():
    """Generate test contact data."""
    return {
        'john': {
            'email': 'john.doe@example.com',
            'name': 'John Doe',
            'phone': '+1-234-567-8900',
            'linkedin': 'https://linkedin.com/in/johndoe'
        },
        'jane': {
            'email': 'jane.smith@company.com',
            'name': 'Jane Smith',
            'phone': '+1-234-567-8901',
            'linkedin': 'https://linkedin.com/in/janesmith'
        },
        'bob': {
            'email': 'bob.wilson@startup.io',
            'name': 'Bob Wilson',
            'phone': '+1-234-567-8902',
            'linkedin': None
        },
        'alice': {
            'email': 'alice.brown@corp.com',
            'name': 'Alice Brown',
            'phone': None,
            'linkedin': 'https://linkedin.com/in/alicebrown'
        },
        'charlie': {
            'email': 'charlie.davis@firm.net',
            'name': 'Charlie Davis',
            'phone': '+1-234-567-8904',
            'linkedin': 'https://linkedin.com/in/charliedavis'
        }
    }


@pytest.fixture
def mock_gmail_client():
    """Mock Gmail client for testing."""
    mock = MagicMock()
    mock.list_messages = MagicMock(return_value=[])
    mock.get_message = MagicMock(return_value={})
    mock.authenticate = MagicMock()
    return mock


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client for testing."""
    mock = MagicMock()

    # Mock message creation
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"status": "success"}')]
    mock.messages.create = MagicMock(return_value=mock_response)

    return mock


@pytest.fixture(autouse=True)
def cleanup_test_data(storage, test_owner_id):
    """Clean up test data after each test."""
    yield

    # Note: In production tests, you might want to clean up test data
    # For now, we leave it to avoid accidental deletion
    # Uncomment if you want automatic cleanup:
    # try:
    #     # Clean up emails
    #     storage.client.table('emails').delete().eq('owner_id', test_owner_id).execute()
    #     # Clean up avatars
    #     storage.client.table('avatars').delete().eq('owner_id', test_owner_id).execute()
    # except Exception:
    #     pass


@pytest.fixture
def sample_emails_with_contact_info(test_email_data, test_contact_data):
    """Generate sample emails with contact information embedded."""
    emails = []

    # Email 1: Inbound from John with phone in body
    emails.append(test_email_data(
        gmail_id='test_email_001',
        from_email=f"{test_contact_data['john']['name']} <{test_contact_data['john']['email']}>",
        to_email='owner@example.com',
        subject='Partnership Discussion',
        body=f"""Hi,

I'd love to discuss the partnership opportunity. Feel free to call me at {test_contact_data['john']['phone']}.

Best regards,
{test_contact_data['john']['name']}
LinkedIn: {test_contact_data['john']['linkedin']}""",
        date_offset_days=1
    ))

    # Email 2: Inbound from Jane with LinkedIn
    emails.append(test_email_data(
        gmail_id='test_email_002',
        from_email=f"{test_contact_data['jane']['name']} <{test_contact_data['jane']['email']}>",
        to_email='owner@example.com',
        subject='Follow-up Meeting',
        body=f"""Hello,

Thanks for meeting yesterday. Connect with me on LinkedIn: {test_contact_data['jane']['linkedin']}

Regards,
{test_contact_data['jane']['name']}""",
        date_offset_days=2
    ))

    # Email 3: Outbound to Bob (no response expected)
    emails.append(test_email_data(
        gmail_id='test_email_003',
        from_email='owner@example.com',
        to_email=f"{test_contact_data['bob']['name']} <{test_contact_data['bob']['email']}>",
        subject='Project Update',
        body='Just wanted to update you on the project status.',
        date_offset_days=3
    ))

    # Email 4: Inbound from Alice
    emails.append(test_email_data(
        gmail_id='test_email_004',
        from_email=f"{test_contact_data['alice']['name']} <{test_contact_data['alice']['email']}>",
        to_email='owner@example.com',
        subject='Quick Question',
        body=f"""Hi,

I have a quick question about the proposal.

{test_contact_data['alice']['name']}
{test_contact_data['alice']['linkedin']}""",
        date_offset_days=4
    ))

    # Email 5: Inbound from Charlie with phone
    emails.append(test_email_data(
        gmail_id='test_email_005',
        from_email=f"{test_contact_data['charlie']['name']} <{test_contact_data['charlie']['email']}>",
        to_email='owner@example.com',
        subject='Contract Review',
        body=f"""Hello,

Please review the attached contract. You can reach me at {test_contact_data['charlie']['phone']}.

Best,
{test_contact_data['charlie']['name']}""",
        date_offset_days=5
    ))

    return emails
