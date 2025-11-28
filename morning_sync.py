#!/usr/bin/env python3
"""Morning sync workflow for Zylch AI.

Run this at 5am via cron to:
1. Sync email threads
2. Sync calendar events
3. Analyze relationship gaps
4. Build relationship-aware tasks

Usage:
    python morning_sync.py

Or add to crontab:
    0 5 * * * cd /path/to/zylch && python morning_sync.py >> logs/morning_sync.log 2>&1
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Add zylch to path
sys.path.insert(0, str(Path(__file__).parent))

from zylch.config import settings
from zylch.tools.gmail import GmailClient
from zylch.tools.gcalendar import GoogleCalendarClient
from zylch.tools.email_archive import EmailArchiveManager
from zylch.tools.email_sync import EmailSyncManager
from zylch.tools.calendar_sync import CalendarSyncManager
from zylch.tools.relationship_analyzer import RelationshipAnalyzer
from zylch.memory import ZylchMemory, ZylchMemoryConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/morning_sync.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Run morning sync workflow."""
    logger.info("=" * 80)
    logger.info("🌅 MORNING SYNC STARTED")
    logger.info("=" * 80)

    start_time = datetime.now()

    try:
        # Step 1: Sync email archive (incremental)
        logger.info("\n📧 STEP 1: Syncing email archive...")
        gmail = GmailClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path
        )
        gmail.authenticate()

        # NEW: Use email archive with incremental sync
        archive = EmailArchiveManager(gmail_client=gmail)

        # Run incremental sync (fast - only fetches changes)
        archive_results = archive.incremental_sync()
        logger.info(
            f"✅ Archive sync complete: "
            f"+{archive_results.get('messages_added', 0)} "
            f"-{archive_results.get('messages_deleted', 0)} messages"
        )

        # Step 2: Build intelligence cache from archive
        logger.info("\n🧠 STEP 2: Building intelligence cache...")
        email_sync = EmailSyncManager(
            email_archive=archive,  # CHANGED: pass archive instead of gmail
            anthropic_api_key=settings.anthropic_api_key
        )

        email_results = email_sync.sync_emails()
        logger.info(
            f"✅ Intelligence cache complete: "
            f"{email_results.get('new_threads', 0)} new threads, "
            f"{email_results.get('updated_threads', 0)} updated"
        )

    except Exception as e:
        logger.error(f"❌ Email sync failed: {e}", exc_info=True)
        email_results = {"success": False, "error": str(e)}

    try:
        # Step 3: Sync calendar events
        logger.info("\n📅 STEP 3: Syncing calendar events...")
        calendar = GoogleCalendarClient(
            credentials_path=settings.google_credentials_path,
            token_dir=settings.google_token_path,
            calendar_id=settings.calendar_id
        )
        calendar.authenticate()

        calendar_sync = CalendarSyncManager(
            calendar_client=calendar,
            anthropic_api_key=settings.anthropic_api_key
        )

        calendar_results = calendar_sync.sync_events()
        logger.info(
            f"✅ Calendar sync complete: "
            f"{calendar_results.get('new_events', 0)} new events, "
            f"{calendar_results.get('updated_events', 0)} updated"
        )

    except Exception as e:
        logger.error(f"❌ Calendar sync failed: {e}", exc_info=True)
        calendar_results = {"success": False, "error": str(e)}

    try:
        # Step 4: Analyze relationship gaps
        logger.info("\n🔍 STEP 4: Analyzing relationship gaps...")

        # Initialize ZylchMemory for personalized filtering
        memory_config = ZylchMemoryConfig(
            db_path=Path(settings.cache_dir) / "zylch_memory.db",
            index_dir=Path(settings.cache_dir) / "indices"
        )
        memory = ZylchMemory(config=memory_config)

        analyzer = RelationshipAnalyzer(
            anthropic_api_key=settings.anthropic_api_key,
            memory_bank=memory
        )

        gap_results = analyzer.analyze_all_gaps(days_back=7)

        # Log summary
        meetings_no_followup = len(gap_results.get('meetings_no_followup', []))
        urgent_no_meeting = len(gap_results.get('urgent_emails_no_meeting', []))
        silent_contacts = len(gap_results.get('silent_contacts', []))

        logger.info(f"📊 Gap Analysis Results:")
        logger.info(f"   - Meetings without follow-up: {meetings_no_followup}")
        logger.info(f"   - Urgent emails without meeting: {urgent_no_meeting}")
        logger.info(f"   - Silent contacts: {silent_contacts}")

        # Save gap analysis results
        output_path = Path("cache/relationship_gaps.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(gap_results, f, indent=2, default=str)

        logger.info(f"✅ Gap analysis saved to {output_path}")

    except Exception as e:
        logger.error(f"❌ Gap analysis failed: {e}", exc_info=True)
        gap_results = {"success": False, "error": str(e)}

    # Final summary
    duration = (datetime.now() - start_time).total_seconds()

    logger.info("\n" + "=" * 80)
    logger.info("🌅 MORNING SYNC COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Duration: {duration:.1f}s")
    logger.info(f"Email sync: {'✅' if email_results.get('success') else '❌'}")
    logger.info(f"Calendar sync: {'✅' if calendar_results.get('success') else '❌'}")
    logger.info(f"Gap analysis: {'✅' if 'analyzed_at' in gap_results else '❌'}")
    logger.info("=" * 80)

    # Return exit code
    if (email_results.get('success') and
        calendar_results.get('success') and
        'analyzed_at' in gap_results):
        return 0
    else:
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n⚠️  Morning sync interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Morning sync crashed: {e}", exc_info=True)
        sys.exit(1)
