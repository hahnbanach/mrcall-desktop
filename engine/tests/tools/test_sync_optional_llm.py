"""Email and calendar sync keep working without an LLM (review 2, M1).

Both managers resolve their role (`MODEL_SYNC_ANALYSIS`) when they are
built; unreadable AI settings make `routed_model` raise BudgetError, which
must leave `llm_client` None ("LLM is optional here") as the bare
`try_make_llm_client()` did before the roster, not abort the sync.
"""

import pytest

from zylch.llm import routed_model
from zylch.llm.budget_pricing import BudgetError
from zylch.tools.calendar_sync import CalendarSyncManager
from zylch.tools.email_sync import EmailSyncManager


@pytest.fixture
def broken_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("LLM_PROVIDER='unterminated\n")
    with pytest.raises(BudgetError):
        routed_model("MODEL_SYNC_ANALYSIS")


def test_email_sync_builds_without_an_llm_on_a_broken_policy(broken_policy):
    manager = EmailSyncManager(object(), owner_id="owner", supabase_storage=object())
    assert manager.llm_client is None


def test_calendar_sync_builds_without_an_llm_on_a_broken_policy(broken_policy):
    manager = CalendarSyncManager(object(), owner_id="owner", supabase_storage=object())
    assert manager.llm_client is None


def test_email_sync_still_routes_its_role(tmp_path, monkeypatch):
    import zylch.tools.email_sync as email_sync

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("MODEL_SYNC_ANALYSIS=saved-sync-model\n")
    monkeypatch.setattr(email_sync, "try_make_llm_client", lambda model=None: model)
    manager = EmailSyncManager(object(), owner_id="owner", supabase_storage=object())
    assert manager.llm_client == "saved-sync-model"
