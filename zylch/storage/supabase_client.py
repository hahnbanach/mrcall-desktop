"""Backward-compat shim — redirects to the new SQLAlchemy-based Storage class.

All 40+ files that do ``from zylch.storage.supabase_client import SupabaseStorage``
will keep working unchanged.  Remove this file in Phase 4 cleanup.
"""

from zylch.storage.storage import Storage as SupabaseStorage  # noqa: F401
