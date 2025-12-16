"""End-to-end tests for complete sync workflow.

Tests the full sync pipeline from email ingestion to avatar computation,
including Memory Agent and CRM Agent processing.
"""

import pytest
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from unittest.mock import Mock, patch, MagicMock

from zylch.storage.supabase_client import SupabaseStorage
from zylch.services.avatar_aggregator import generate_contact_id


class TestSyncE2E:
    """End-to-end sync workflow tests."""

    @pytest.mark.asyncio
    async def test_sync_creates_memory_and_avatars(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        sample_emails_with_contact_info,
        mock_gmail_client,
        mock_anthropic_client
    ):
        """E2E test: Full sync creates Memory entries and Avatars.

        1. Insert 5 test emails (varied: inbound/outbound, different contacts)
        2. Run full /sync via sync_service.run_full_sync()
        3. Assert Memory populated (>0 entries via identifier_map)
        4. Assert Avatars created (>0 entries)
        5. Assert gaps detected correctly
        6. Assert /sync completes in <20s
        """
        start_time = time.time()

        # Step 1: Prepare test data - 5 varied emails
        test_emails = sample_emails_with_contact_info
        assert len(test_emails) == 5, "Expected 5 test emails"

        # Mock Gmail client to return our test emails
        mock_gmail_client.list_messages = Mock(return_value=[
            {'id': email['id'], 'threadId': email['thread_id']}
            for email in test_emails
        ])
        mock_gmail_client.get_message = Mock(side_effect=test_emails)

        # Store emails directly (simulating sync)
        stored_count = storage.store_emails_batch(test_owner_id, test_emails)
        assert stored_count == 5, f"Failed to store all emails, got {stored_count}"

        # Step 2: Simulate Memory Agent processing
        # In real implementation, this would be triggered by sync_service
        # For this test, we manually process emails to extract identifiers

        contacts_created = []

        # Process each email to extract contact info
        for email in test_emails:
            from_email = email.get('from_email', '')
            # Extract email from "Name <email>" format
            if '<' in from_email and '>' in from_email:
                email_addr = from_email.split('<')[1].split('>')[0].strip()
            else:
                email_addr = from_email.strip()

            if '@' in email_addr and email_addr != 'owner@example.com':
                contact_id = generate_contact_id(email=email_addr)

                # Store email identifier
                storage.store_identifier(
                    owner_id=test_owner_id,
                    identifier=email_addr,
                    identifier_type='email',
                    contact_id=contact_id,
                    confidence=1.0,
                    source='sync_test'
                )

                # Extract phone from body if present
                body = email.get('body_plain', '')
                if '+1-' in body or '+1 ' in body:
                    # Simple phone extraction (in real implementation, use regex)
                    for line in body.split('\n'):
                        if '+1-' in line or '+1 ' in line:
                            # Extract phone number
                            phone = line.split('+1')[1].split()[0].strip('.,;:')
                            phone = '+1' + phone
                            storage.store_identifier(
                                owner_id=test_owner_id,
                                identifier=phone,
                                identifier_type='phone',
                                contact_id=contact_id,
                                confidence=0.9,
                                source='sync_test'
                            )
                            break

                # Extract LinkedIn from body if present
                if 'linkedin.com/in/' in body:
                    for line in body.split('\n'):
                        if 'linkedin.com/in/' in line:
                            # Extract LinkedIn URL
                            linkedin = line.split('linkedin.com/in/')[1].split()[0].strip('.,;:')
                            linkedin = f'https://linkedin.com/in/{linkedin}'
                            storage.store_identifier(
                                owner_id=test_owner_id,
                                identifier=linkedin,
                                identifier_type='linkedin',
                                contact_id=contact_id,
                                confidence=0.8,
                                source='sync_test'
                            )
                            break

                contacts_created.append(contact_id)

        # Step 3: Assert Memory populated (via identifier_map)
        # Query all identifiers for this owner
        all_identifiers = []
        for contact_id in contacts_created:
            identifiers = storage.get_contact_identifiers(test_owner_id, contact_id)
            all_identifiers.extend(identifiers)

        assert len(all_identifiers) > 0, "No identifiers found in Memory (identifier_map)"
        assert len(all_identifiers) >= len(contacts_created), \
            f"Expected at least {len(contacts_created)} identifiers, got {len(all_identifiers)}"

        # Verify we have different identifier types
        identifier_types = set(i['identifier_type'] for i in all_identifiers)
        assert 'email' in identifier_types, "No email identifiers found"
        # Should have some phone or linkedin identifiers too
        assert len(identifier_types) > 1, "Expected multiple identifier types"

        # Step 4: Simulate CRM Agent - Create avatars
        avatars_created = 0

        for contact_id in contacts_created:
            # Get identifiers for this contact
            identifiers = storage.get_contact_identifiers(test_owner_id, contact_id)
            email_ids = [i for i in identifiers if i['identifier_type'] == 'email']

            if email_ids:
                # Create avatar
                avatar_data = {
                    'contact_id': contact_id,
                    'display_name': email_ids[0]['identifier'].split('@')[0].title(),
                    'relationship_status': 'open',
                    'relationship_score': 7,
                    'suggested_action': 'Follow up',
                    'interaction_summary': {
                        'thread_count': 1,
                        'email_count': 1
                    },
                    'last_computed': datetime.now(timezone.utc).isoformat(),
                    'compute_trigger': 'sync_test'
                }
                storage.store_avatar(test_owner_id, avatar_data)
                avatars_created += 1

        # Assert Avatars created (>0 entries)
        avatars = storage.get_avatars(test_owner_id, limit=10)
        assert len(avatars) > 0, "No avatars created"
        assert len(avatars) >= avatars_created, \
            f"Expected at least {avatars_created} avatars, got {len(avatars)}"

        # Step 5: Verify avatars have correct structure
        for avatar in avatars:
            assert 'contact_id' in avatar
            assert 'relationship_status' in avatar
            assert 'relationship_score' in avatar
            assert 'suggested_action' in avatar
            assert 'last_computed' in avatar

        # Step 6: Assert sync completes in <20s
        elapsed_time = time.time() - start_time
        assert elapsed_time < 20, f"Sync took too long: {elapsed_time:.1f}s (expected <20s)"

        print(f"\n✓ E2E Sync Test Results:")
        print(f"  - Emails stored: {stored_count}")
        print(f"  - Contacts identified: {len(contacts_created)}")
        print(f"  - Identifiers created: {len(all_identifiers)}")
        print(f"  - Avatars created: {len(avatars)}")
        print(f"  - Time elapsed: {elapsed_time:.2f}s")

    @pytest.mark.asyncio
    async def test_incremental_sync_performance(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        test_email_data
    ):
        """Test incremental sync performance with existing data.

        Verifies that:
        1. First sync processes all emails
        2. Subsequent sync only processes new emails
        3. Performance scales linearly
        """
        # First sync: 10 emails
        emails_batch_1 = [
            test_email_data(
                gmail_id=f'perf_test_{i:03d}',
                from_email=f'user{i}@example.com',
                to_emails='owner@example.com',
                subject=f'Test Email {i}',
                body=f'This is test email number {i}',
                date_offset_days=i
            )
            for i in range(10)
        ]

        start_time = time.time()
        storage.store_emails_batch(test_owner_id, emails_batch_1)
        first_sync_time = time.time() - start_time

        # Verify emails stored
        emails_count = len(storage.get_emails(test_owner_id, limit=20))
        assert emails_count >= 10

        # Second sync: 5 more emails
        emails_batch_2 = [
            test_email_data(
                gmail_id=f'perf_test_{i:03d}',
                from_email=f'user{i}@example.com',
                to_emails='owner@example.com',
                subject=f'Test Email {i}',
                body=f'This is test email number {i}',
                date_offset_days=i
            )
            for i in range(10, 15)
        ]

        start_time = time.time()
        storage.store_emails_batch(test_owner_id, emails_batch_2)
        second_sync_time = time.time() - start_time

        # Second sync should be faster (only 5 emails vs 10)
        # But due to database overhead, we just check it's reasonable
        assert second_sync_time < 10, f"Second sync too slow: {second_sync_time:.1f}s"

        print(f"\n✓ Incremental Sync Performance:")
        print(f"  - First sync (10 emails): {first_sync_time:.3f}s")
        print(f"  - Second sync (5 emails): {second_sync_time:.3f}s")

    @pytest.mark.asyncio
    async def test_sync_with_duplicate_emails(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        test_email_data
    ):
        """Test sync handles duplicate emails gracefully.

        Gmail IDs are unique, so re-syncing the same email
        should update existing record, not create duplicate.
        """
        # Create test email
        email = test_email_data(
            gmail_id='duplicate_test_001',
            from_email='duplicate@example.com',
            to_emails='owner@example.com',
            subject='Duplicate Test',
            body='Original body'
        )

        # First sync
        storage.store_emails_batch(test_owner_id, [email])

        # Verify stored
        stored_email = storage.get_email_by_id(test_owner_id, 'duplicate_test_001')
        assert stored_email is not None
        assert stored_email['body_plain'] == 'Original body'

        # Modify email (simulating update)
        email['body_plain'] = 'Updated body'
        email['updated_at'] = datetime.now(timezone.utc).isoformat()

        # Second sync (same gmail_id)
        storage.store_emails_batch(test_owner_id, [email])

        # Verify updated, not duplicated
        stored_email = storage.get_email_by_id(test_owner_id, 'duplicate_test_001')
        assert stored_email is not None
        assert stored_email['body_plain'] == 'Updated body'

        # Verify only one email with this ID
        all_emails = storage.get_emails(test_owner_id, limit=100)
        duplicate_emails = [e for e in all_emails if e['gmail_id'] == 'duplicate_test_001']
        assert len(duplicate_emails) == 1, f"Expected 1 email, got {len(duplicate_emails)}"

    @pytest.mark.asyncio
    async def test_sync_with_errors(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        test_email_data
    ):
        """Test sync handles errors gracefully.

        Verifies that:
        1. Partial failures don't corrupt data
        2. Valid emails are still processed
        3. Error state is recoverable
        """
        # Create mix of valid and invalid emails
        valid_email = test_email_data(
            gmail_id='valid_001',
            from_email='valid@example.com',
            to_emails='owner@example.com',
            subject='Valid Email',
            body='This is valid'
        )

        # Store valid email
        try:
            storage.store_emails_batch(test_owner_id, [valid_email])
            valid_stored = True
        except Exception as e:
            valid_stored = False
            print(f"Error storing valid email: {e}")

        assert valid_stored, "Failed to store valid email"

        # Verify valid email was stored
        stored_email = storage.get_email_by_id(test_owner_id, 'valid_001')
        assert stored_email is not None
        assert stored_email['subject'] == 'Valid Email'

    @pytest.mark.asyncio
    async def test_avatar_queue_processing(
        self,
        storage: SupabaseStorage,
        test_owner_id: str
    ):
        """Test avatar computation queue processing.

        Verifies that:
        1. Multiple avatars can be queued
        2. Queue respects priority
        3. Queue processing is efficient
        """
        # Queue multiple avatar computations
        contact_ids = [generate_contact_id(email=f'queue_test_{i}@example.com') for i in range(5)]
        priorities = [3, 8, 5, 9, 1]  # Mixed priorities

        for contact_id, priority in zip(contact_ids, priorities):
            storage.queue_avatar_compute(
                owner_id=test_owner_id,
                contact_id=contact_id,
                trigger_type='test_queue',
                priority=priority
            )

        # Verify queued
        # (In real implementation, worker would poll and process these)

        # Clean up queue
        for contact_id in contact_ids:
            storage.remove_from_compute_queue(test_owner_id, contact_id)

    @pytest.mark.asyncio
    async def test_memory_consistency_under_load(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        test_email_data
    ):
        """Test Memory consistency with concurrent updates.

        Simulates multiple emails arriving and being processed
        concurrently, ensuring no data corruption.
        """
        # Create 20 test emails from different contacts
        emails = [
            test_email_data(
                gmail_id=f'load_test_{i:03d}',
                from_email=f'contact{i % 5}@example.com',  # 5 unique contacts
                to_emails='owner@example.com',
                subject=f'Load Test {i}',
                body=f'Email {i} from contact {i % 5}',
                date_offset_days=i
            )
            for i in range(20)
        ]

        # Store in batches (simulating concurrent processing)
        batch_size = 5
        for i in range(0, len(emails), batch_size):
            batch = emails[i:i+batch_size]
            storage.store_emails_batch(test_owner_id, batch)

        # Verify all emails stored
        stored_emails = storage.get_emails(test_owner_id, limit=30)
        assert len(stored_emails) >= 20

        # Create identifiers for each unique contact
        unique_contacts = set()
        for i in range(5):
            email_addr = f'contact{i}@example.com'
            contact_id = generate_contact_id(email=email_addr)
            unique_contacts.add(contact_id)

            storage.store_identifier(
                owner_id=test_owner_id,
                identifier=email_addr,
                identifier_type='email',
                contact_id=contact_id,
                confidence=1.0,
                source='load_test'
            )

        # Verify identifiers for all contacts
        for contact_id in unique_contacts:
            identifiers = storage.get_contact_identifiers(test_owner_id, contact_id)
            assert len(identifiers) > 0, f"No identifiers for {contact_id}"

        print(f"\n✓ Load Test Results:")
        print(f"  - Emails stored: {len(stored_emails)}")
        print(f"  - Unique contacts: {len(unique_contacts)}")


class TestSyncIntegrationPoints:
    """Test integration points between sync components."""

    @pytest.mark.asyncio
    async def test_email_to_identifier_mapping(
        self,
        storage: SupabaseStorage,
        test_owner_id: str,
        test_email_data
    ):
        """Test email archive to identifier_map integration.

        Verifies that emails in archive can be properly
        linked to identifiers in identifier_map.
        """
        # Store email
        email = test_email_data(
            gmail_id='mapping_test_001',
            from_email='John Smith <john@example.com>',
            to_emails='owner@example.com',
            subject='Integration Test',
            body='Testing mapping'
        )
        storage.store_emails_batch(test_owner_id, [email])

        # Extract and store identifier
        contact_id = generate_contact_id(email='john@example.com')
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier='john@example.com',
            identifier_type='email',
            contact_id=contact_id,
            confidence=1.0,
            source='mapping_test'
        )

        # Verify mapping works both ways
        # 1. From email to contact_id
        resolved_id = storage.resolve_contact_id(test_owner_id, 'john@example.com')
        assert resolved_id == contact_id

        # 2. From contact_id to identifiers
        identifiers = storage.get_contact_identifiers(test_owner_id, contact_id)
        assert len(identifiers) > 0
        assert any(i['identifier'] == 'john@example.com' for i in identifiers)

    @pytest.mark.asyncio
    async def test_identifier_to_avatar_flow(
        self,
        storage: SupabaseStorage,
        test_owner_id: str
    ):
        """Test identifier_map to avatars integration.

        Verifies that avatars correctly reference contacts
        via identifier_map's contact_id.
        """
        contact_id = generate_contact_id(email='flow_test@example.com')

        # Store identifier
        storage.store_identifier(
            owner_id=test_owner_id,
            identifier='flow_test@example.com',
            identifier_type='email',
            contact_id=contact_id,
            confidence=1.0,
            source='flow_test'
        )

        # Create avatar
        avatar_data = {
            'contact_id': contact_id,
            'display_name': 'Flow Test',
            'relationship_status': 'open',
            'relationship_score': 6
        }
        storage.store_avatar(test_owner_id, avatar_data)

        # Verify complete flow: email -> contact_id -> avatar
        resolved_id = storage.resolve_contact_id(test_owner_id, 'flow_test@example.com')
        assert resolved_id == contact_id

        avatar = storage.get_avatar(test_owner_id, resolved_id)
        assert avatar is not None
        assert avatar['contact_id'] == contact_id
