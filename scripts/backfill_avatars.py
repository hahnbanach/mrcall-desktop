"""Backfill avatars for all existing contacts in the database.

This script:
1. Queries all emails from the database
2. Extracts unique contact emails
3. Generates stable contact_ids
4. Queues avatar computation for all contacts

Usage:
    python scripts/backfill_avatars.py --owner-id <firebase_uid>

Options:
    --owner-id: Firebase UID of the user (required)
    --limit: Max contacts to process (default: no limit)
    --priority: Priority for queued avatars (default: 5)
    --batch-size: Number of contacts to process per batch (default: 50)

Example:
    # Backfill all avatars for user
    python scripts/backfill_avatars.py --owner-id abc123xyz

    # Backfill with high priority
    python scripts/backfill_avatars.py --owner-id abc123xyz --priority 8

    # Test with limited batch
    python scripts/backfill_avatars.py --owner-id abc123xyz --limit 10
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Set

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from zylch.config import settings
from zylch.services.avatar_aggregator import generate_contact_id
from zylch.storage.supabase_client import SupabaseStorage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_contacts_from_emails(storage: SupabaseStorage, owner_id: str) -> Set[str]:
    """Extract all unique contact emails from email archive.

    Args:
        storage: SupabaseStorage instance
        owner_id: User's Firebase UID

    Returns:
        Set of unique email addresses
    """
    logger.info("Extracting contacts from email archive...")

    # Get all emails for user
    # Note: This queries in batches to avoid memory issues
    contacts = set()
    offset = 0
    batch_size = 1000

    while True:
        emails = storage.get_emails(owner_id=owner_id, limit=batch_size, offset=offset)

        if not emails:
            break

        logger.info(f"Processing batch {offset // batch_size + 1} ({len(emails)} emails)")

        for email in emails:
            # Add from_email
            from_email = email.get('from_email')
            if from_email and '@' in from_email:
                contacts.add(from_email.lower())

            # Add to_emails
            to_emails = email.get('to_emails', [])
            if isinstance(to_emails, str):
                to_emails = [to_emails]
            for to_email in to_emails:
                if to_email and '@' in to_email:
                    contacts.add(to_email.lower())

            # Add cc_emails
            cc_emails = email.get('cc_emails', [])
            if isinstance(cc_emails, str):
                cc_emails = [cc_emails]
            for cc_email in cc_emails:
                if cc_email and '@' in cc_email:
                    contacts.add(cc_email.lower())

        offset += batch_size

        # Progress update
        if offset % 5000 == 0:
            logger.info(f"Processed {offset} emails, found {len(contacts)} unique contacts so far...")

    logger.info(f"Extracted {len(contacts)} unique contacts from emails")
    return contacts


def backfill_avatars(
    owner_id: str,
    limit: int = None,
    priority: int = 5,
    batch_size: int = 50
) -> dict:
    """Backfill avatars for all existing contacts.

    Args:
        owner_id: User's Firebase UID
        limit: Optional limit on number of contacts to process
        priority: Priority for queued avatars (1-10)
        batch_size: Number of contacts to process per batch

    Returns:
        Stats dict with results
    """
    logger.info("="*60)
    logger.info("Avatar Backfill Starting")
    logger.info("="*60)
    logger.info(f"Owner ID: {owner_id}")
    logger.info(f"Priority: {priority}")
    logger.info(f"Batch size: {batch_size}")
    if limit:
        logger.info(f"Limit: {limit} contacts")

    # Initialize storage
    storage = SupabaseStorage.get_instance()

    # Extract contacts from emails
    contacts = extract_contacts_from_emails(storage, owner_id)

    if limit:
        contacts = set(list(contacts)[:limit])
        logger.info(f"Limited to {len(contacts)} contacts")

    # Queue avatar computation for each contact
    queued = 0
    failed = 0
    skipped = 0
    batch_count = 0

    contact_list = list(contacts)
    total_contacts = len(contact_list)

    for i, email in enumerate(contact_list):
        try:
            # Generate stable contact_id
            contact_id = generate_contact_id(email=email)

            # Check if avatar already exists and is recent
            existing_avatar = storage.get_avatar(owner_id, contact_id)
            if existing_avatar:
                # Skip if computed in last 7 days
                last_computed = existing_avatar.get('last_computed')
                if last_computed:
                    last_computed_dt = datetime.fromisoformat(last_computed.replace('Z', '+00:00'))
                    age_days = (datetime.now(timezone.utc) - last_computed_dt).days
                    if age_days < 7:
                        logger.debug(f"Skipping {email} (avatar computed {age_days} days ago)")
                        skipped += 1
                        continue

            # Store identifier mapping
            storage.store_identifier(
                owner_id=owner_id,
                identifier=email,
                identifier_type='email',
                contact_id=contact_id,
                confidence=1.0,
                source='backfill'
            )

            # Queue avatar computation
            storage.queue_avatar_compute(
                owner_id=owner_id,
                contact_id=contact_id,
                trigger_type='scheduled',
                priority=priority
            )

            queued += 1

            # Progress logging
            if (i + 1) % batch_size == 0:
                batch_count += 1
                progress = (i + 1) / total_contacts * 100
                logger.info(
                    f"Progress: {i + 1}/{total_contacts} ({progress:.1f}%) - "
                    f"Queued: {queued}, Skipped: {skipped}, Failed: {failed}"
                )

        except Exception as e:
            logger.error(f"Failed to queue avatar for {email}: {e}")
            failed += 1
            continue

    # Final summary
    logger.info("="*60)
    logger.info("Avatar Backfill Complete")
    logger.info("="*60)
    logger.info(f"Total contacts: {total_contacts}")
    logger.info(f"Queued: {queued}")
    logger.info(f"Skipped (recent): {skipped}")
    logger.info(f"Failed: {failed}")
    logger.info("="*60)

    return {
        "total_contacts": total_contacts,
        "queued": queued,
        "skipped": skipped,
        "failed": failed,
        "owner_id": owner_id,
        "priority": priority
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill avatars for all existing contacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--owner-id',
        required=True,
        help='Firebase UID of the user'
    )

    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Max contacts to process (default: no limit)'
    )

    parser.add_argument(
        '--priority',
        type=int,
        default=5,
        choices=range(1, 11),
        help='Priority for queued avatars (1-10, default: 5)'
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of contacts to process per batch (default: 50)'
    )

    args = parser.parse_args()

    # Run backfill
    try:
        stats = backfill_avatars(
            owner_id=args.owner_id,
            limit=args.limit,
            priority=args.priority,
            batch_size=args.batch_size
        )

        # Exit with appropriate code
        if stats['failed'] > 0:
            logger.warning(f"{stats['failed']} contacts failed to queue")
            sys.exit(1)
        else:
            logger.info("Backfill completed successfully")
            sys.exit(0)

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
