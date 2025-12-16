"""Integration tests for Von Neumann Memory Architecture.

Tests the complete pipeline:
1. Email sync → Email archive
2. Memory Agent → Extract contact info → Memory table
3. CRM Agent → Compute avatars → Avatar table
4. Verify consistency and data flow
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
import hashlib

from zylch.storage.supabase_client import SupabaseStorage
from zylch.services.avatar_aggregator import generate_contact_id


class TestVonNeumannFlow:
    """Test complete Von Neumann data flow."""

    @pytest.mark.asyncio
    async def test_full_pipeline(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        sample_emails_with_contact_info
    ):
        """Integration test: Complete Von Neumann pipeline.

        1. Insert test email with phone/LinkedIn in body
        2. Run Memory Agent (simulated)
        3. Assert Memory table has contact info
        4. Assert identifier_map has phone
        5. Run CRM Agent (simulated)
        6. Assert Avatar has correct status/priority/action
        7. Verify consistency: Memory timestamp ≈ Avatar timestamp (within 1 min)
        """
        # Step 1: Insert test emails into email archive
        emails = sample_emails_with_contact_info[:2]  # Use first 2 emails
        stored_count = storage.store_emails_batch(test_owner_id, emails)
        assert stored_count == 2, "Failed to store test emails"

        # Verify emails are in archive
        archived_emails = storage.get_emails(test_owner_id, limit=10)
        assert len(archived_emails) >= 2, "Emails not found in archive"

        # Step 2: Simulate Memory Agent - Extract contact info
        # In real implementation, this would be done by MemoryWorker
        # For now, we manually extract and store identifiers

        # Extract John's contact info from first email
        john_email = 'john.doe@example.com'
        john_phone = '+1-234-567-8900'
        john_linkedin = 'https://linkedin.com/in/johndoe'
        john_contact_id = generate_contact_id(email=john_email)

        # Store email identifier
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier=john_email,
            identifier_type='email',
            contact_id=john_contact_id,
            confidence=1.0,
            source='memory_agent'
        )

        # Store phone identifier
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier=john_phone,
            identifier_type='phone',
            contact_id=john_contact_id,
            confidence=0.9,
            source='memory_agent'
        )

        # Store LinkedIn identifier
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier=john_linkedin,
            identifier_type='linkedin',
            contact_id=john_contact_id,
            confidence=0.8,
            source='memory_agent'
        )

        # Step 3: Assert Memory table has contact info (via identifier_map)
        john_identifiers = storage.get_contact_identifiers(test_owner_id, john_contact_id)
        assert len(john_identifiers) == 3, f"Expected 3 identifiers, got {len(john_identifiers)}"

        # Verify phone is in identifier_map
        phone_identifiers = [i for i in john_identifiers if i['identifier_type'] == 'phone']
        assert len(phone_identifiers) == 1, "Phone identifier not found"
        assert phone_identifiers[0]['identifier'] == john_phone.lower().replace('-', '').replace('+', '').replace(' ', '')

        # Verify LinkedIn is in identifier_map
        linkedin_identifiers = [i for i in john_identifiers if i['identifier_type'] == 'linkedin']
        assert len(linkedin_identifiers) == 1, "LinkedIn identifier not found"

        # Step 4: Simulate CRM Agent - Compute avatar
        # In real implementation, this would be done by AvatarComputeWorker

        # Get email data for John
        john_emails = [e for e in archived_emails if john_email in e.get('from_email', '').lower()]
        assert len(john_emails) > 0, "No emails found from John"

        latest_email = john_emails[0]
        last_interaction = datetime.fromisoformat(latest_email['date'].replace('Z', '+00:00'))

        # Create avatar
        avatar_data = {
            'contact_id': john_contact_id,
            'display_name': 'John Doe',
            'identifiers': {
                'emails': [john_email],
                'phones': [john_phone],
                'linkedin': [john_linkedin]
            },
            'relationship_summary': 'Discussing partnership opportunity',
            'relationship_status': 'open',
            'relationship_score': 8,
            'suggested_action': 'Follow up on partnership discussion',
            'interaction_summary': {
                'thread_count': 1,
                'email_count': 1,
                'last_direction': 'inbound'
            },
            'preferred_tone': 'professional',
            'response_latency': {'median_hours': 24.0},
            'relationship_strength': 0.75,
            'last_computed': datetime.now(timezone.utc).isoformat(),
            'compute_trigger': 'test_integration'
        }

        storage.store_avatar(test_owner_id, avatar_data)

        # Step 5: Assert Avatar has correct status/priority/action
        retrieved_avatar = storage.get_avatar(test_owner_id, john_contact_id)
        assert retrieved_avatar is not None, "Avatar not found"
        assert retrieved_avatar['relationship_status'] == 'open'
        assert retrieved_avatar['relationship_score'] == 8
        assert 'partnership' in retrieved_avatar['suggested_action'].lower()

        # Step 6: Verify consistency - timestamps should be recent and close
        avatar_computed_time = datetime.fromisoformat(
            retrieved_avatar['last_computed'].replace('Z', '+00:00')
        )
        now = datetime.now(timezone.utc)

        # Avatar should have been computed recently (within 1 minute)
        time_diff = (now - avatar_computed_time).total_seconds()
        assert time_diff < 60, f"Avatar computation timestamp too old: {time_diff}s ago"

        # Verify identifier map entries have recent timestamps
        for identifier in john_identifiers:
            updated_at = datetime.fromisoformat(identifier['updated_at'].replace('Z', '+00:00'))
            identifier_age = (now - updated_at).total_seconds()
            assert identifier_age < 60, f"Identifier timestamp too old: {identifier_age}s ago"

    @pytest.mark.asyncio
    async def test_memory_to_avatar_flow(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        test_email_data,
        test_contact_data
    ):
        """Test data flow from Memory Agent output to CRM Agent input.

        Verifies that:
        1. Memory Agent stores contact info in identifier_map
        2. CRM Agent can resolve contact_id from email
        3. Avatar uses the same contact_id
        """
        # Setup: Create email and extract contact
        jane_data = test_contact_data['jane']
        jane_email = jane_data['email']
        jane_contact_id = generate_contact_id(email=jane_email)

        # Memory Agent: Store identifier
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier=jane_email,
            identifier_type='email',
            contact_id=jane_contact_id,
            confidence=1.0,
            source='memory_agent_test'
        )

        # CRM Agent: Resolve contact_id from email
        resolved_id = storage.resolve_contact_id(test_owner_id, jane_email)
        assert resolved_id == jane_contact_id, "Contact ID resolution failed"

        # CRM Agent: Create avatar with resolved contact_id
        avatar_data = {
            'contact_id': jane_contact_id,
            'display_name': jane_data['name'],
            'relationship_status': 'open',
            'relationship_score': 7,
            'suggested_action': 'Schedule follow-up meeting'
        }
        storage.store_avatar(test_owner_id, avatar_data)

        # Verify avatar uses same contact_id
        avatar = storage.get_avatar(test_owner_id, jane_contact_id)
        assert avatar is not None
        assert avatar['contact_id'] == jane_contact_id

    @pytest.mark.asyncio
    async def test_identifier_deduplication(
        self,
        storage: SupabaseStorage,
        test_owner_id: str
    ):
        """Test that duplicate identifiers are properly deduplicated.

        Memory Agent might extract the same phone number multiple times
        from different emails. The system should handle this gracefully.
        """
        contact_id = generate_contact_id(email='test@example.com')
        phone = '+1-234-567-8900'

        # Store phone identifier twice (simulating extraction from 2 emails)
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier=phone,
            identifier_type='phone',
            contact_id=contact_id,
            confidence=0.9,
            source='email_1'
        )

        storage.store_identifier(
            owner_id=test_owner_id,
            identifier=phone,
            identifier_type='phone',
            contact_id=contact_id,
            confidence=0.95,  # Higher confidence
            source='email_2'
        )

        # Should have only one phone identifier (upsert behavior)
        identifiers = storage.get_contact_identifiers(test_owner_id, contact_id)
        phone_ids = [i for i in identifiers if i['identifier_type'] == 'phone']

        assert len(phone_ids) == 1, f"Expected 1 phone identifier, got {len(phone_ids)}"
        # Should keep the higher confidence value
        assert phone_ids[0]['confidence'] == 0.95

    @pytest.mark.asyncio
    async def test_avatar_computation_triggers(
        self,
        storage: SupabaseStorage,
        test_owner_id: str
    ):
        """Test avatar computation queue and trigger system.

        Verifies that:
        1. Avatar computation can be queued
        2. Queue entries have correct priority
        3. Queue can be processed
        """
        contact_id = generate_contact_id(email='priority_test@example.com')

        # Queue avatar computation
        queue_entry = storage.queue_avatar_compute(
            owner_id=test_owner_id,
            contact_id=contact_id,
            trigger_type='email_sync',
            priority=8
        )

        assert queue_entry is not None
        assert queue_entry['contact_id'] == contact_id
        assert queue_entry['priority'] == 8
        assert queue_entry['trigger_type'] == 'email_sync'

        # Verify queue entry can be retrieved
        # (In real implementation, worker would poll this queue)

        # Clean up: Remove from queue
        removed = storage.remove_from_compute_queue(test_owner_id, contact_id)
        assert removed is True

    @pytest.mark.asyncio
    async def test_timestamp_consistency(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        test_email_data
    ):
        """Test timestamp consistency across Memory and Avatar layers.

        The Avatar's last_computed should be >= identifier's updated_at,
        since Avatar is computed AFTER identifiers are stored.
        """
        # Create email
        email = test_email_data(
            gmail_id='timestamp_test_001',
            from_email='timestamp@example.com',
            to_emails='owner@example.com',
            subject='Timestamp Test',
            body='Testing timestamp consistency'
        )
        storage.store_emails_batch(test_owner_id, [email])

        contact_id = generate_contact_id(email='timestamp@example.com')

        # Memory Agent: Store identifier
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier='timestamp@example.com',
            identifier_type='email',
            contact_id=contact_id,
            confidence=1.0,
            source='timestamp_test'
        )

        # Wait 1 second to ensure different timestamps
        await asyncio.sleep(1)

        # CRM Agent: Create avatar
        avatar_data = {
            'contact_id': contact_id,
            'display_name': 'Timestamp Test',
            'relationship_status': 'open',
            'relationship_score': 5,
            'last_computed': datetime.now(timezone.utc).isoformat()
        }
        storage.store_avatar(test_owner_id, avatar_data)

        # Verify timestamps
        identifiers = storage.get_contact_identifiers(test_owner_id, contact_id)
        avatar = storage.get_avatar(test_owner_id, contact_id)

        assert len(identifiers) > 0
        identifier_time = datetime.fromisoformat(identifiers[0]['updated_at'].replace('Z', '+00:00'))
        avatar_time = datetime.fromisoformat(avatar['last_computed'].replace('Z', '+00:00'))

        # Avatar should be computed after identifiers are stored
        assert avatar_time >= identifier_time, "Avatar timestamp should be >= identifier timestamp"

    @pytest.mark.asyncio
    async def test_multi_contact_flow(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        sample_emails_with_contact_info,
        test_contact_data
    ):
        """Test Von Neumann flow with multiple contacts.

        Simulates real-world scenario with multiple contacts,
        ensuring data isolation and correct aggregation.
        """
        # Store all sample emails
        emails = sample_emails_with_contact_info
        storage.store_emails_batch(test_owner_id, emails)

        # Process each contact
        contacts_processed = []

        for contact_key, contact_info in test_contact_data.items():
            email = contact_info['email']
            contact_id = generate_contact_id(email=email)

            # Memory Agent: Store identifiers
            storage.store_identifier(
                owner_id=test_owner_id,
                identifier=email,
                identifier_type='email',
                contact_id=contact_id,
                confidence=1.0,
                source='multi_contact_test'
            )

            if contact_info.get('phone'):
                storage.store_identifier(
                    owner_id=test_owner_id,
                    identifier=contact_info['phone'],
                    identifier_type='phone',
                    contact_id=contact_id,
                    confidence=0.9,
                    source='multi_contact_test'
                )

            # CRM Agent: Create avatar
            avatar_data = {
                'contact_id': contact_id,
                'display_name': contact_info['name'],
                'relationship_status': 'open',
                'relationship_score': 7,
                'suggested_action': f'Follow up with {contact_info["name"]}'
            }
            storage.store_avatar(test_owner_id, avatar_data)

            contacts_processed.append(contact_id)

        # Verify all avatars were created
        avatars = storage.get_avatars(test_owner_id, limit=10)
        avatar_ids = [a['contact_id'] for a in avatars]

        for contact_id in contacts_processed:
            assert contact_id in avatar_ids, f"Avatar for {contact_id} not found"

        # Verify data isolation - each contact has separate identifiers
        for contact_id in contacts_processed:
            identifiers = storage.get_contact_identifiers(test_owner_id, contact_id)
            # Each contact should have at least email identifier
            assert len(identifiers) >= 1, f"No identifiers found for {contact_id}"
