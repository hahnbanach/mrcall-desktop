#!/usr/bin/env python3
"""
Migration script: Convert legacy credential columns to unified JSONB format.

This script migrates existing credentials from provider-specific columns
(google_token_data, graph_access_token, anthropic_api_key, etc.) to the
unified 'credentials' JSONB column.

Usage:
    python scripts/migrate_to_unified_credentials.py [--dry-run] [--batch-size 100]

Options:
    --dry-run       Show what would be migrated without making changes
    --batch-size N  Process N rows at a time (default: 100)
    --verbose       Show detailed progress

Safety:
    - Preserves legacy columns (dual-storage for backward compatibility)
    - Validates decryption before migrating
    - Logs all changes for audit trail
    - Can be run multiple times safely (idempotent)
"""

import sys
import logging
import argparse
from typing import Dict, Any, List, Optional
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, '/Users/mal/hb/zylch')

from zylch.storage.supabase_client import SupabaseStorage
from zylch.utils.encryption import encrypt, decrypt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_google_credentials(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract Google OAuth credentials from legacy column."""
    google_token_data = row.get('google_token_data')
    if not google_token_data:
        return None

    try:
        # Decrypt legacy token data
        decrypted_data = decrypt(google_token_data)

        # Google stores as base64-encoded pickle - we'll keep it as-is
        # but move it into the unified structure
        return {
            'token_data': decrypted_data,
            'type': 'oauth'
        }
    except Exception as e:
        logger.error(f"Failed to decrypt Google token for owner {row['owner_id']}: {e}")
        return None


def migrate_microsoft_credentials(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract Microsoft Graph credentials from legacy columns."""
    access_token = row.get('graph_access_token')
    if not access_token:
        return None

    try:
        credentials = {
            'access_token': decrypt(access_token),
            'type': 'oauth'
        }

        refresh_token = row.get('graph_refresh_token')
        if refresh_token:
            credentials['refresh_token'] = decrypt(refresh_token)

        expires_at = row.get('graph_expires_at')
        if expires_at:
            credentials['expires_at'] = expires_at

        return credentials
    except Exception as e:
        logger.error(f"Failed to decrypt Microsoft token for owner {row['owner_id']}: {e}")
        return None


def migrate_anthropic_credentials(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract Anthropic API key from legacy column."""
    api_key = row.get('anthropic_api_key')
    if not api_key:
        return None

    try:
        return {
            'api_key': decrypt(api_key),
            'type': 'api_key'
        }
    except Exception as e:
        logger.error(f"Failed to decrypt Anthropic key for owner {row['owner_id']}: {e}")
        return None


def migrate_pipedrive_credentials(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract Pipedrive API token from legacy column."""
    api_token = row.get('pipedrive_api_token')
    if not api_token:
        return None

    try:
        return {
            'api_token': decrypt(api_token),
            'type': 'api_key'
        }
    except Exception as e:
        logger.error(f"Failed to decrypt Pipedrive token for owner {row['owner_id']}: {e}")
        return None


def migrate_vonage_credentials(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract Vonage API credentials from legacy columns."""
    api_key = row.get('vonage_api_key')
    api_secret = row.get('vonage_api_secret')

    if not (api_key and api_secret):
        return None

    try:
        credentials = {
            'api_key': decrypt(api_key),
            'api_secret': decrypt(api_secret),
            'type': 'api_key'
        }

        from_number = row.get('vonage_from_number')
        if from_number:
            credentials['from_number'] = from_number  # Not encrypted

        return credentials
    except Exception as e:
        logger.error(f"Failed to decrypt Vonage keys for owner {row['owner_id']}: {e}")
        return None


def build_unified_credentials(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build unified credentials JSONB from legacy columns."""
    provider = row['provider']
    credentials = {}

    # Map provider to migration function
    if provider == 'google.com':
        creds = migrate_google_credentials(row)
        if creds:
            credentials['google'] = creds
    elif provider == 'microsoft.com':
        creds = migrate_microsoft_credentials(row)
        if creds:
            credentials['microsoft'] = creds
    elif provider == 'anthropic':
        creds = migrate_anthropic_credentials(row)
        if creds:
            credentials['anthropic'] = creds
    elif provider == 'pipedrive':
        creds = migrate_pipedrive_credentials(row)
        if creds:
            credentials['pipedrive'] = creds
    elif provider == 'vonage':
        creds = migrate_vonage_credentials(row)
        if creds:
            credentials['vonage'] = creds
    else:
        logger.warning(f"Unknown provider: {provider}")
        return None

    if not credentials:
        return None

    return credentials


def migrate_rows(storage: SupabaseStorage, rows: List[Dict[str, Any]], dry_run: bool = False) -> tuple:
    """Migrate a batch of rows."""
    migrated_count = 0
    skipped_count = 0
    error_count = 0

    for row in rows:
        owner_id = row['owner_id']
        provider = row['provider']
        row_id = row['id']

        # Check if already migrated
        if row.get('credentials'):
            logger.debug(f"Skipping {provider} for {owner_id} - already migrated")
            skipped_count += 1
            continue

        # Build unified credentials
        unified_creds = build_unified_credentials(row)
        if not unified_creds:
            logger.warning(f"No credentials to migrate for {provider} for owner {owner_id}")
            skipped_count += 1
            continue

        # Re-encrypt for unified storage
        try:
            import json
            credentials_json = encrypt(json.dumps(unified_creds))

            if dry_run:
                logger.info(f"[DRY RUN] Would migrate {provider} for owner {owner_id}")
                logger.debug(f"[DRY RUN] Credentials structure: {list(unified_creds.keys())}")
                migrated_count += 1
            else:
                # Update row with unified credentials
                # DUAL-WRITE: Keep legacy columns for backward compatibility
                storage.client.table('oauth_tokens').update({
                    'credentials': credentials_json,
                    'updated_at': datetime.utcnow().isoformat()
                }).eq('id', row_id).execute()

                logger.info(f"Migrated {provider} for owner {owner_id}")
                migrated_count += 1

        except Exception as e:
            logger.error(f"Failed to migrate {provider} for owner {owner_id}: {e}")
            error_count += 1

    return migrated_count, skipped_count, error_count


def main():
    parser = argparse.ArgumentParser(description='Migrate credentials to unified JSONB format')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated')
    parser.add_argument('--batch-size', type=int, default=100, help='Rows per batch')
    parser.add_argument('--verbose', action='store_true', help='Show detailed progress')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 70)
    logger.info("UNIFIED CREDENTIALS MIGRATION")
    logger.info("=" * 70)
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE MIGRATION'}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info("")

    try:
        # Initialize storage
        storage = SupabaseStorage()

        # Count total rows to migrate
        result = storage.client.table('oauth_tokens')\
            .select('id', count='exact')\
            .is_('credentials', 'null')\
            .execute()

        total_rows = result.count if hasattr(result, 'count') else len(result.data)
        logger.info(f"Found {total_rows} rows to migrate")

        if total_rows == 0:
            logger.info("No rows need migration. Exiting.")
            return

        # Process in batches
        offset = 0
        total_migrated = 0
        total_skipped = 0
        total_errors = 0

        while offset < total_rows:
            logger.info(f"\nProcessing batch {offset // args.batch_size + 1} (rows {offset + 1}-{min(offset + args.batch_size, total_rows)})...")

            # Fetch batch
            result = storage.client.table('oauth_tokens')\
                .select('*')\
                .is_('credentials', 'null')\
                .range(offset, offset + args.batch_size - 1)\
                .execute()

            if not result.data:
                break

            # Migrate batch
            migrated, skipped, errors = migrate_rows(storage, result.data, args.dry_run)

            total_migrated += migrated
            total_skipped += skipped
            total_errors += errors

            offset += args.batch_size

        # Summary
        logger.info("")
        logger.info("=" * 70)
        logger.info("MIGRATION SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total rows:     {total_rows}")
        logger.info(f"Migrated:       {total_migrated}")
        logger.info(f"Skipped:        {total_skipped}")
        logger.info(f"Errors:         {total_errors}")
        logger.info("")

        if args.dry_run:
            logger.info("This was a DRY RUN - no changes were made.")
            logger.info("Run without --dry-run to perform the actual migration.")
        else:
            logger.info("Migration complete!")
            logger.info("Legacy columns have been preserved for backward compatibility.")

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
