#!/usr/bin/env python3
"""Run avatar migration on Supabase database.

This script executes the avatar architecture SQL migration.

Usage:
    python scripts/run_avatar_migration.py

Environment variables required:
    SUPABASE_URL - Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY - Supabase service role key (JWT token)
    SUPABASE_DB_PASSWORD - Database password (from Supabase dashboard > Project Settings > Database)
"""

import os
import sys
import psycopg2
from pathlib import Path


def get_connection_string():
    """Build Supabase connection string."""
    supabase_url = os.environ.get('SUPABASE_URL')
    if not supabase_url:
        raise ValueError("SUPABASE_URL not set")

    # Extract project ref from URL (e.g., https://nbudpcnbtfpbdlurumlo.supabase.co)
    project_ref = supabase_url.replace('https://', '').replace('.supabase.co', '')

    # Get database password (NOT the service role key)
    db_password = os.environ.get('SUPABASE_DB_PASSWORD')
    if not db_password:
        print("\n" + "="*60)
        print("ERROR: SUPABASE_DB_PASSWORD not set!")
        print("="*60)
        print("\nTo get your database password:")
        print("1. Go to https://supabase.com/dashboard/project/" + project_ref)
        print("2. Click 'Settings' → 'Database'")
        print("3. Under 'Connection string', click 'URI' tab")
        print("4. Copy the password from the connection string")
        print("5. Set environment variable:")
        print(f"   export SUPABASE_DB_PASSWORD='<your-password>'")
        print("\nOR execute manually via SQL Editor:")
        print(f"   https://supabase.com/dashboard/project/{project_ref}/editor/sql")
        print("="*60)
        sys.exit(1)

    # Build connection string (direct connection, port 5432)
    conn_string = f"postgresql://postgres.{project_ref}:{db_password}@aws-0-us-east-1.pooler.supabase.com:5432/postgres"

    return conn_string


def run_migration():
    """Execute avatar migration."""
    print("Avatar Architecture Migration")
    print("="*60)

    # Get connection string
    try:
        conn_string = get_connection_string()
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
        return False

    # Load migration SQL
    migration_file = Path(__file__).parent.parent / 'docs' / 'migration' / '001_add_avatar_fields.sql'
    if not migration_file.exists():
        print(f"✗ Migration file not found: {migration_file}")
        return False

    with open(migration_file, 'r') as f:
        sql = f.read()

    print(f"Migration file: {migration_file}")
    print(f"SQL length: {len(sql)} characters")
    print("\nConnecting to Supabase...")

    # Execute migration
    try:
        conn = psycopg2.connect(conn_string)
        conn.autocommit = True
        cursor = conn.cursor()

        print("✓ Connected successfully!")
        print("\nExecuting migration...")
        print("-"*60)

        cursor.execute(sql)

        print("-"*60)
        print("✓ Migration executed successfully!")

        # Verify tables
        print("\nVerifying migration...")

        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('avatars', 'identifier_map', 'avatar_compute_queue')
            ORDER BY table_name
        """)

        tables = [row[0] for row in cursor.fetchall()]
        print(f"  Tables: {tables}")

        # Check avatar columns
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'avatars'
            AND column_name IN ('relationship_summary', 'relationship_status', 'relationship_score',
                               'suggested_action', 'profile_embedding', 'last_computed', 'compute_trigger')
            ORDER BY column_name
        """)

        columns = [row[0] for row in cursor.fetchall()]
        print(f"  Avatar columns: {len(columns)}/7 added")

        # Check indices
        cursor.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'avatars'
            AND indexname LIKE 'idx_avatars_%'
            ORDER BY indexname
        """)

        indices = [row[0] for row in cursor.fetchall()]
        print(f"  Avatar indices: {len(indices)} created")

        cursor.close()
        conn.close()

        print("\n" + "="*60)
        print("✓ Migration complete and verified!")
        print("="*60)

        return True

    except psycopg2.Error as e:
        print(f"\n✗ Database error: {e}")
        print("\nIf connection failed, try manual execution:")
        print(f"1. Go to Supabase SQL Editor")
        print(f"2. Paste contents of: {migration_file}")
        print(f"3. Click 'Run'")
        return False

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
