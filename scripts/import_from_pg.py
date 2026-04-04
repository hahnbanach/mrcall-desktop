#!/usr/bin/env python3
"""Import data from old Railway PostgreSQL into local SQLite.

Usage:
    /tmp/pg_import_venv/bin/python3 scripts/import_from_pg.py

Imports: emails, blobs, blob_sentences, task_items, agent_prompts,
         oauth_tokens, user_notifications, drafts, contacts.
Embeddings are converted from pgvector text to numpy float32 bytes.
"""

import json
import sqlite3
import struct
import sys
from datetime import datetime

import psycopg2

PG_URL = "postgresql://postgres:TlQDBrYmtfvFWbDpZaEVcihQoKMjjKog@metro.proxy.rlwy.net:24308/railway"
SQLITE_PATH = "/home/mal/.zylch/zylch.db"


def pgvector_to_blob(pgvector_text: str) -> bytes:
    """Convert pgvector text '[0.1,0.2,...]' to float32 bytes for SQLite BLOB."""
    if not pgvector_text:
        return None
    # Strip brackets and parse
    values = [float(x) for x in pgvector_text.strip("[]").split(",")]
    return struct.pack(f"{len(values)}f", *values)


def ts_to_str(ts) -> str:
    """Convert timestamp to ISO string or None."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


def json_dumps(val):
    """Serialize JSON value for SQLite."""
    if val is None:
        return None
    return json.dumps(val)


def import_emails(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT id::text, owner_id, gmail_id, thread_id, from_email, from_name,
               to_email, cc_email, subject, date, date_timestamp, snippet,
               body_plain, body_html, labels, message_id_header, in_reply_to,
               "references", created_at, updated_at, read_events,
               memory_processed_at, embedding::text, task_processed_at, is_auto_reply
        FROM emails ORDER BY date
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        sl_cur.execute("""
            INSERT OR IGNORE INTO emails
            (id, owner_id, gmail_id, thread_id, from_email, from_name,
             to_email, cc_email, subject, date, date_timestamp, snippet,
             body_plain, body_html, labels, message_id_header, in_reply_to,
             "references", created_at, updated_at, read_events,
             memory_processed_at, embedding, task_processed_at, is_auto_reply)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(r[0]), r[1], r[2], r[3], r[4], r[5],
            r[6], r[7], r[8], ts_to_str(r[9]), r[10], r[11],
            r[12], r[13], r[14], r[15], r[16],
            r[17], ts_to_str(r[18]), ts_to_str(r[19]), json_dumps(r[20]),
            ts_to_str(r[21]), pgvector_to_blob(r[22]), ts_to_str(r[23]), r[24],
        ))
        count += 1
    sl_conn.commit()
    print(f"  emails: {count} imported")


def import_blobs(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT id::text, owner_id, namespace, content, embedding::text,
               events, created_at, updated_at
        FROM blobs ORDER BY created_at
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        sl_cur.execute("""
            INSERT OR IGNORE INTO blobs
            (id, owner_id, namespace, content, embedding, events, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            str(r[0]), r[1], r[2], r[3], pgvector_to_blob(r[4]),
            json_dumps(r[5]), ts_to_str(r[6]), ts_to_str(r[7]),
        ))
        count += 1
    sl_conn.commit()
    print(f"  blobs: {count} imported")


def import_blob_sentences(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT id::text, blob_id::text, owner_id, sentence_text,
               embedding::text, created_at
        FROM blob_sentences ORDER BY created_at
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        emb = pgvector_to_blob(r[4])
        if emb is None:
            continue  # sentence without embedding is useless
        sl_cur.execute("""
            INSERT OR IGNORE INTO blob_sentences
            (id, blob_id, owner_id, sentence_text, embedding, created_at)
            VALUES (?,?,?,?,?,?)
        """, (
            str(r[0]), str(r[1]), r[2], r[3], emb, ts_to_str(r[5]),
        ))
        count += 1
    sl_conn.commit()
    print(f"  blob_sentences: {count} imported")


def import_task_items(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT id::text, owner_id, event_type, event_id, contact_email,
               contact_name, action_required, urgency, reason, suggested_action,
               created_at, analyzed_at, completed_at, sources
        FROM task_items ORDER BY created_at
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        sl_cur.execute("""
            INSERT OR IGNORE INTO task_items
            (id, owner_id, event_type, event_id, contact_email,
             contact_name, action_required, urgency, reason, suggested_action,
             created_at, analyzed_at, completed_at, sources)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(r[0]), r[1], r[2], r[3], r[4],
            r[5], r[6], r[7], r[8], r[9],
            ts_to_str(r[10]), ts_to_str(r[11]), ts_to_str(r[12]), json_dumps(r[13]),
        ))
        count += 1
    sl_conn.commit()
    print(f"  task_items: {count} imported")


def import_agent_prompts(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT id::text, owner_id, agent_type, agent_prompt, metadata,
               created_at, updated_at
        FROM agent_prompts ORDER BY created_at
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        sl_cur.execute("""
            INSERT OR IGNORE INTO agent_prompts
            (id, owner_id, agent_type, agent_prompt, metadata,
             created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            str(r[0]), r[1], r[2], r[3], json_dumps(r[4]),
            ts_to_str(r[5]), ts_to_str(r[6]),
        ))
        count += 1
    sl_conn.commit()
    print(f"  agent_prompts: {count} imported")


def import_oauth_tokens(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'oauth_tokens' ORDER BY ordinal_position
    """)
    pg_cols = [r[0] for r in pg_cur.fetchall()]

    # Build select for columns that exist in both PG and SQLite
    sqlite_cols = [
        'id', 'owner_id', 'provider', 'email', 'scopes',
        'created_at', 'updated_at', 'connection_status', 'last_sync',
        'error_message', 'display_name', 'credentials',
    ]
    select_cols = []
    insert_cols = []
    for col in sqlite_cols:
        if col in pg_cols:
            if col == 'id':
                select_cols.append('id::text')
            elif col == 'credentials':
                select_cols.append('credentials::text')
            else:
                select_cols.append(f'"{col}"')
            insert_cols.append(col)

    pg_cur.execute(f"SELECT {', '.join(select_cols)} FROM oauth_tokens")
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    placeholders = ','.join(['?'] * len(insert_cols))
    cols_str = ','.join(insert_cols)
    for r in rows:
        values = []
        for i, col in enumerate(insert_cols):
            val = r[i]
            if col in ('created_at', 'updated_at', 'last_sync'):
                val = ts_to_str(val)
            elif col == 'credentials' and isinstance(val, str):
                val = val  # already text/json
            values.append(val)
        sl_cur.execute(
            f"INSERT OR IGNORE INTO oauth_tokens ({cols_str}) VALUES ({placeholders})",
            values,
        )
        count += 1
    sl_conn.commit()
    print(f"  oauth_tokens: {count} imported")


def import_user_notifications(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT id::text, owner_id, message, notification_type, read, created_at
        FROM user_notifications ORDER BY created_at
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        sl_cur.execute("""
            INSERT OR IGNORE INTO user_notifications
            (id, owner_id, message, notification_type, read, created_at)
            VALUES (?,?,?,?,?,?)
        """, (str(r[0]), r[1], r[2], r[3], r[4], ts_to_str(r[5])))
        count += 1
    sl_conn.commit()
    print(f"  user_notifications: {count} imported")


def import_drafts(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT id::text, owner_id, to_addresses, cc_addresses, bcc_addresses,
               subject, body, body_format, in_reply_to, "references", thread_id,
               original_message_id, status, provider, sent_at, sent_message_id,
               error_message, created_at, updated_at
        FROM drafts ORDER BY created_at
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        sl_cur.execute("""
            INSERT OR IGNORE INTO drafts
            (id, owner_id, to_addresses, cc_addresses, bcc_addresses,
             subject, body, body_format, in_reply_to, "references", thread_id,
             original_message_id, status, provider, sent_at, sent_message_id,
             error_message, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(r[0]), r[1], json_dumps(r[2]), json_dumps(r[3]), json_dumps(r[4]),
            r[5], r[6], r[7], r[8], json_dumps(r[9]), r[10],
            r[11], r[12], r[13], ts_to_str(r[14]), r[15],
            r[16], ts_to_str(r[17]), ts_to_str(r[18]),
        ))
        count += 1
    sl_conn.commit()
    print(f"  drafts: {count} imported")


def import_contacts(pg_cur, sl_conn):
    pg_cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'contacts' ORDER BY ordinal_position
    """)
    pg_cols = [r[0] for r in pg_cur.fetchall()]
    if not pg_cols:
        print("  contacts: table not found, skipping")
        return

    pg_cur.execute("SELECT COUNT(*) FROM contacts")
    cnt = pg_cur.fetchone()[0]
    if cnt == 0:
        print("  contacts: 0 rows, skipping")
        return

    pg_cur.execute("""
        SELECT id::text, owner_id, email, name, phone, metadata,
               created_at, updated_at
        FROM contacts ORDER BY created_at
    """)
    rows = pg_cur.fetchall()
    sl_cur = sl_conn.cursor()
    count = 0
    for r in rows:
        sl_cur.execute("""
            INSERT OR IGNORE INTO contacts
            (id, owner_id, email, name, phone, metadata, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            str(r[0]), r[1], r[2], r[3], r[4], json_dumps(r[5]),
            ts_to_str(r[6]), ts_to_str(r[7]),
        ))
        count += 1
    sl_conn.commit()
    print(f"  contacts: {count} imported")


def ensure_sqlite_tables(sl_conn):
    """Create tables if they don't exist (minimal DDL matching models.py)."""
    sl_cur = sl_conn.cursor()

    sl_cur.executescript("""
        CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            gmail_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            from_email TEXT,
            from_name TEXT,
            to_email TEXT,
            cc_email TEXT,
            subject TEXT,
            date TEXT NOT NULL,
            date_timestamp INTEGER,
            snippet TEXT,
            body_plain TEXT,
            body_html TEXT,
            labels TEXT,
            message_id_header TEXT,
            in_reply_to TEXT,
            "references" TEXT,
            created_at TEXT,
            updated_at TEXT,
            read_events TEXT,
            memory_processed_at TEXT,
            embedding BLOB,
            task_processed_at TEXT,
            is_auto_reply INTEGER DEFAULT 0,
            UNIQUE(owner_id, gmail_id)
        );

        CREATE TABLE IF NOT EXISTS blobs (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding BLOB,
            events TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS blob_sentences (
            id TEXT PRIMARY KEY,
            blob_id TEXT NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL,
            sentence_text TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS task_items (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_id TEXT NOT NULL,
            contact_email TEXT,
            contact_name TEXT,
            action_required INTEGER DEFAULT 0,
            urgency TEXT,
            reason TEXT,
            suggested_action TEXT,
            created_at TEXT,
            analyzed_at TEXT,
            completed_at TEXT,
            sources TEXT,
            UNIQUE(owner_id, event_type, event_id)
        );

        CREATE TABLE IF NOT EXISTS agent_prompts (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            agent_prompt TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(owner_id, agent_type)
        );

        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            email TEXT NOT NULL,
            scopes TEXT,
            created_at TEXT,
            updated_at TEXT,
            connection_status TEXT DEFAULT 'connected',
            last_sync TEXT,
            error_message TEXT,
            display_name TEXT,
            credentials TEXT,
            UNIQUE(owner_id, provider)
        );

        CREATE TABLE IF NOT EXISTS user_notifications (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            message TEXT NOT NULL,
            notification_type TEXT DEFAULT 'warning',
            read INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS drafts (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            to_addresses TEXT,
            cc_addresses TEXT,
            bcc_addresses TEXT,
            subject TEXT,
            body TEXT,
            body_format TEXT DEFAULT 'html',
            in_reply_to TEXT,
            "references" TEXT,
            thread_id TEXT,
            original_message_id TEXT,
            status TEXT DEFAULT 'draft',
            provider TEXT,
            sent_at TEXT,
            sent_message_id TEXT,
            error_message TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            email TEXT,
            name TEXT,
            phone TEXT,
            metadata TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL UNIQUE,
            history_id TEXT,
            last_sync TEXT,
            full_sync_completed TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            google_event_id TEXT NOT NULL,
            summary TEXT,
            description TEXT,
            start_time TEXT,
            end_time TEXT,
            location TEXT,
            attendees TEXT,
            organizer_email TEXT,
            is_external INTEGER DEFAULT 0,
            meet_link TEXT,
            calendar_id TEXT DEFAULT 'primary',
            created_at TEXT,
            updated_at TEXT,
            memory_processed_at TEXT,
            task_processed_at TEXT,
            UNIQUE(owner_id, google_event_id)
        );

        CREATE TABLE IF NOT EXISTS mrcall_conversations (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            contact_phone TEXT,
            contact_name TEXT,
            call_duration_ms INTEGER,
            call_started_at TEXT,
            subject TEXT,
            body TEXT,
            custom_values TEXT,
            memory_processed_at TEXT,
            raw_data TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS background_jobs (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            business_id TEXT,
            job_type TEXT NOT NULL,
            channel TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            progress_pct INTEGER DEFAULT 0,
            items_processed INTEGER DEFAULT 0,
            total_items INTEGER,
            status_message TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            last_error TEXT,
            retry_count INTEGER DEFAULT 0,
            result TEXT,
            params TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_emails_owner ON emails(owner_id);
        CREATE INDEX IF NOT EXISTS idx_blobs_owner ON blobs(owner_id);
        CREATE INDEX IF NOT EXISTS idx_blob_sentences_owner ON blob_sentences(owner_id);
        CREATE INDEX IF NOT EXISTS idx_blob_sentences_blob ON blob_sentences(blob_id);
    """)
    sl_conn.commit()


def main():
    import os

    # Ensure ~/.zylch/ exists
    zylch_dir = os.path.expanduser("~/.zylch")
    os.makedirs(zylch_dir, exist_ok=True)

    print(f"Connecting to PostgreSQL...")
    pg_conn = psycopg2.connect(PG_URL)
    pg_cur = pg_conn.cursor()

    print(f"Opening SQLite at {SQLITE_PATH}...")
    sl_conn = sqlite3.connect(SQLITE_PATH)
    sl_conn.execute("PRAGMA journal_mode=WAL")
    sl_conn.execute("PRAGMA foreign_keys=ON")

    print("Ensuring SQLite tables exist...")
    ensure_sqlite_tables(sl_conn)

    print("\nImporting data:")
    import_emails(pg_cur, sl_conn)
    import_blobs(pg_cur, sl_conn)
    import_blob_sentences(pg_cur, sl_conn)
    import_task_items(pg_cur, sl_conn)
    import_agent_prompts(pg_cur, sl_conn)
    import_oauth_tokens(pg_cur, sl_conn)
    import_user_notifications(pg_cur, sl_conn)
    import_drafts(pg_cur, sl_conn)
    import_contacts(pg_cur, sl_conn)

    # Fix namespaces (PG uses Firebase UIDs, standalone uses email)
    sl_cur = sl_conn.cursor()
    sl_cur.execute(
        "UPDATE blobs SET namespace = REPLACE(namespace, 'EWy1peBy8WdiV1AED2e1Qv0hdcM2', 'support@mrcall.ai')"
        " WHERE namespace LIKE '%EWy1peBy%'"
    )
    if sl_cur.rowcount:
        print(f"  namespaces: {sl_cur.rowcount} blobs fixed")
    sl_conn.commit()

    # Summary
    print("\n--- SQLite summary ---")
    for table in [
        'emails', 'blobs', 'blob_sentences', 'task_items',
        'agent_prompts', 'oauth_tokens', 'user_notifications',
        'drafts', 'contacts',
    ]:
        sl_cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {sl_cur.fetchone()[0]} rows")

    pg_conn.close()
    sl_conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
