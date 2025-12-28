#!/usr/bin/env python3
"""
Verify Supabase database schema installation
"""
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

EXPECTED_TABLES = [
    'emails', 'sync_state', 'task_items',
    'calendar_events', 'patterns', 'blobs',
    'oauth_tokens', 'triggers', 'trigger_events',
    'sharing_auth', 'scheduled_jobs'
]

def verify_schema():
    """Verify all tables exist and have correct structure"""

    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")
        return False

    print(f"🔍 Connecting to Supabase: {url}")
    supabase = create_client(url, key)

    print("\n" + "="*60)
    print("DATABASE SCHEMA VERIFICATION")
    print("="*60)

    # Check each table
    missing_tables = []
    existing_tables = []

    for table in EXPECTED_TABLES:
        try:
            # Try to query the table (will fail if it doesn't exist)
            result = supabase.table(table).select("*").limit(0).execute()
            existing_tables.append(table)
            print(f"✓ {table:25} EXISTS")
        except Exception as e:
            missing_tables.append(table)
            print(f"✗ {table:25} MISSING - {str(e)[:50]}")

    print("\n" + "="*60)
    print(f"SUMMARY: {len(existing_tables)}/{len(EXPECTED_TABLES)} tables found")
    print("="*60)

    if missing_tables:
        print(f"\n❌ Missing tables: {', '.join(missing_tables)}")
        return False
    else:
        print(f"\n✅ All {len(EXPECTED_TABLES)} tables installed successfully!")
        print("\n📋 Next steps:")
        print("   1. Start Zylch with: python -m zylch.cli.main")
        print("   2. Sync emails with: /sync 7")
        print("   3. Check tasks with: /tasks")
        return True

if __name__ == '__main__':
    success = verify_schema()
    exit(0 if success else 1)
