"""Zylch Storage - PostgreSQL storage backend via SQLAlchemy.

All data stored in PostgreSQL (NO local filesystem per ARCHITECTURE.md).
"""

from .storage import Storage

# Backward-compat alias: all existing code importing SupabaseStorage still works
SupabaseStorage = Storage
