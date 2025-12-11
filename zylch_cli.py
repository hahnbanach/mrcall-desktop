#!/usr/bin/env python3
"""Zylch CLI - Command line interface for email archive and sync."""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

from zylch.config import settings

# Get Anthropic API key from environment (local dev CLI)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
from zylch.tools.gmail import GmailClient
from zylch.tools.email_archive import EmailArchiveManager
from zylch.tools.email_sync import EmailSyncManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def print_help():
    """Print CLI help."""
    print("""
Zylch CLI - Email Archive & Intelligence System

COMMANDS:

  archive init [--months N]
      Initialize email archive with full sync
      --months: Number of months to sync (default: 1)

  archive sync
      Run incremental sync (fetch new emails only)

  archive stats
      Show archive statistics

  archive search <query> [--limit N]
      Search archived emails
      --limit: Max results (default: 10)

  sync
      Run full morning sync workflow:
        1. Archive incremental sync
        2. Build intelligence cache
        3. Calendar sync (if configured)
        4. Relationship gap analysis

  cache rebuild [--days N]
      Rebuild intelligence cache from archive
      --days: Days back for intelligence window (default: 30)

  help
      Show this help message

EXAMPLES:

  # First time setup - sync 1 month of emails
  python zylch_cli.py archive init

  # Daily sync - fetch only new emails
  python zylch_cli.py archive sync

  # Search for emails about "project"
  python zylch_cli.py archive search "project" --limit 20

  # Full morning sync
  python zylch_cli.py sync

  # Rebuild intelligence cache
  python zylch_cli.py cache rebuild
""")


def cmd_archive_init(args):
    """Initialize email archive."""
    months = 1
    if '--months' in args:
        try:
            idx = args.index('--months')
            months = int(args[idx + 1])
        except (IndexError, ValueError):
            print("❌ Invalid --months value")
            return 1

    print(f"\n📦 Initializing email archive ({months} months)...")
    print("This may take a few minutes...\n")

    try:
        # Initialize Gmail
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()

        # Initialize archive
        archive = EmailArchiveManager(gmail_client=gmail)

        # Run initial sync
        result = archive.initial_full_sync(months_back=months)

        if result['success']:
            print(f"\n✅ Archive initialized successfully!")
            print(f"   Messages: {result['total_stored']}")
            print(f"   Date range: {result['date_range']}")
            print(f"   Location: {settings.get_email_archive_path()}")
            return 0
        else:
            print(f"\n❌ Initialization failed: {result.get('error')}")
            return 1

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Archive init failed: {e}", exc_info=True)
        return 1


def cmd_archive_sync(args):
    """Run incremental archive sync."""
    print("\n🔄 Running incremental sync...")

    try:
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()

        archive = EmailArchiveManager(gmail_client=gmail)
        result = archive.incremental_sync()

        if result['success']:
            print(f"\n✅ Sync complete!")
            print(f"   Messages added: {result['messages_added']}")
            print(f"   Messages deleted: {result['messages_deleted']}")

            if result['messages_added'] == 0 and result['messages_deleted'] == 0:
                print("   No changes since last sync")

            return 0
        else:
            print(f"\n❌ Sync failed: {result.get('error')}")
            return 1

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Archive sync failed: {e}", exc_info=True)
        return 1


def cmd_archive_stats(args):
    """Show archive statistics."""
    try:
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()

        archive = EmailArchiveManager(gmail_client=gmail)
        stats = archive.get_stats()

        print("\n📊 ARCHIVE STATISTICS")
        print("=" * 60)
        print(f"Backend: {stats['backend'].upper()}")
        print(f"Location: {stats['db_path']}")
        print(f"\nMessages: {stats['total_messages']:,}")
        print(f"Threads: {stats['total_threads']:,}")
        print(f"\nDate Range:")
        print(f"  Earliest: {stats['earliest_message']}")
        print(f"  Latest: {stats['latest_message']}")
        print(f"\nLast Sync: {stats.get('last_sync', 'Never')}")
        print(f"Database Size: {stats['db_size_mb']:.2f} MB")
        print("=" * 60)

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Stats failed: {e}", exc_info=True)
        return 1


def cmd_archive_search(args):
    """Search archived emails."""
    if len(args) < 1:
        print("❌ Usage: archive search <query> [--limit N]")
        return 1

    query = args[0]
    limit = 10

    if '--limit' in args:
        try:
            idx = args.index('--limit')
            limit = int(args[idx + 1])
        except (IndexError, ValueError):
            print("❌ Invalid --limit value")
            return 1

    print(f"\n🔍 Searching for: '{query}'")
    print(f"Limit: {limit} results\n")

    try:
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()

        archive = EmailArchiveManager(gmail_client=gmail)
        results = archive.search_messages(query=query, limit=limit)

        if results:
            print(f"Found {len(results)} results:\n")
            for i, msg in enumerate(results, 1):
                print(f"{i}. {msg.get('subject', '(no subject)')}")
                print(f"   From: {msg.get('from_email', 'unknown')}")
                print(f"   Date: {msg.get('date', 'unknown')}")
                print()
        else:
            print("No results found")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Search failed: {e}", exc_info=True)
        return 1


def cmd_sync(args):
    """Run full sync workflow."""
    print("\n🌅 Running full sync workflow...")
    print("This will:")
    print("  1. Sync email archive (incremental)")
    print("  2. Build intelligence cache")
    print("\n")

    try:
        # Step 1: Archive sync
        print("📧 Step 1: Syncing archive...")
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()

        archive = EmailArchiveManager(gmail_client=gmail)
        archive_result = archive.incremental_sync()

        if not archive_result['success']:
            print(f"❌ Archive sync failed: {archive_result.get('error')}")
            return 1

        print(f"✅ Archive: +{archive_result['messages_added']} -{archive_result['messages_deleted']}")

        # Step 2: Intelligence cache
        print("\n🧠 Step 2: Building intelligence cache...")
        email_sync = EmailSyncManager(
            email_archive=archive,
            anthropic_api_key=ANTHROPIC_API_KEY
        )

        cache_result = email_sync.sync_emails()
        print(f"✅ Cache: {cache_result['total_threads']} threads analyzed")

        print("\n✅ Sync complete!")
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


def cmd_cache_rebuild(args):
    """Rebuild intelligence cache."""
    days = 30
    if '--days' in args:
        try:
            idx = args.index('--days')
            days = int(args[idx + 1])
        except (IndexError, ValueError):
            print("❌ Invalid --days value")
            return 1

    print(f"\n🧠 Rebuilding intelligence cache ({days} days)...")

    try:
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()

        archive = EmailArchiveManager(gmail_client=gmail)
        email_sync = EmailSyncManager(
            email_archive=archive,
            anthropic_api_key=ANTHROPIC_API_KEY
        )

        result = email_sync.sync_emails(days_back=days)
        print(f"\n✅ Cache rebuilt!")
        print(f"   Threads: {result['total_threads']}")
        print(f"   New: {result['new_threads']}")
        print(f"   Updated: {result['updated_threads']}")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Cache rebuild failed: {e}", exc_info=True)
        return 1


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print_help()
        return 1

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    commands = {
        'help': lambda _: print_help() or 0,
        'archive': lambda a: handle_archive(a),
        'sync': cmd_sync,
        'cache': lambda a: handle_cache(a),
    }

    handler = commands.get(command)
    if not handler:
        print(f"❌ Unknown command: {command}")
        print("\nUse 'python zylch_cli.py help' for usage")
        return 1

    return handler(args)


def handle_archive(args):
    """Handle archive subcommands."""
    if not args:
        print("❌ Missing archive subcommand")
        print("Usage: archive [init|sync|stats|search]")
        return 1

    subcommand = args[0].lower()
    subargs = args[1:]

    subcommands = {
        'init': cmd_archive_init,
        'sync': cmd_archive_sync,
        'stats': cmd_archive_stats,
        'search': cmd_archive_search,
    }

    handler = subcommands.get(subcommand)
    if not handler:
        print(f"❌ Unknown archive subcommand: {subcommand}")
        return 1

    return handler(subargs)


def handle_cache(args):
    """Handle cache subcommands."""
    if not args:
        print("❌ Missing cache subcommand")
        print("Usage: cache [rebuild]")
        return 1

    subcommand = args[0].lower()
    subargs = args[1:]

    if subcommand == 'rebuild':
        return cmd_cache_rebuild(subargs)
    else:
        print(f"❌ Unknown cache subcommand: {subcommand}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        logger.error(f"CLI crashed: {e}", exc_info=True)
        sys.exit(1)
