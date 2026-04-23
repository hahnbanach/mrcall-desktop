"""Tests for task worker bug fixes.

Tests the critical bugs:
1. get_tasks(refresh=True) must NOT delete existing tasks
2. _is_user_email must use exact match only (not domain match)
3. User replies must close tasks even with multi-recipient to_email
4. Same-domain colleagues must NOT be treated as "the user"
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from zylch.workers.task_creation import TaskWorker


@pytest.fixture
def mock_storage():
    """Storage mock with all methods needed by TaskWorker."""
    s = MagicMock()
    s.get_agent_prompt.return_value = "You are a task detection agent."
    s.get_task_items.return_value = []
    s.get_unprocessed_emails_for_task.return_value = []
    s.clear_task_items.return_value = 0
    s.get_task_by_contact.return_value = None
    return s


@pytest.fixture
def worker(mock_storage):
    """TaskWorker with mocked LLM and storage."""
    with patch("zylch.workers.task_creation.LLMClient"):
        with patch("zylch.workers.task_creation.EmbeddingEngine"):
            with patch("zylch.workers.task_creation.HybridSearchEngine"):
                with patch("zylch.storage.database.get_session"):
                    w = TaskWorker(
                        storage=mock_storage,
                        owner_id="test_owner",
                        api_key="fake-key",
                        provider="anthropic",
                        user_email="mario.alemi@cafe124.it",
                    )
    return w


class TestIsUserEmail:
    """Bug #2: _is_user_email must NOT match same-domain colleagues."""

    def test_exact_match_returns_true(self, worker):
        assert worker._is_user_email("mario.alemi@cafe124.it") is True

    def test_exact_match_case_insensitive(self, worker):
        assert worker._is_user_email("Mario.Alemi@Cafe124.it") is True

    def test_colleague_same_domain_returns_false(self, worker):
        """riccardo.cargnel@cafe124.it must NOT be treated as user."""
        assert worker._is_user_email("riccardo.cargnel@cafe124.it") is False

    def test_external_contact_returns_false(self, worker):
        assert worker._is_user_email("mapostoli@jacobacci.com") is False

    def test_empty_string_returns_false(self, worker):
        assert worker._is_user_email("") is False

    def test_subdomain_not_matched(self, worker):
        """user@notcafe124.it must NOT match cafe124.it domain."""
        assert worker._is_user_email("someone@notcafe124.it") is False


class TestGetTasksNoDelete:
    """Bug #1: get_tasks(refresh=True) must NOT call clear_task_items."""

    @pytest.mark.asyncio
    async def test_refresh_does_not_clear_tasks(self, worker, mock_storage):
        """Existing tasks must survive a refresh."""
        existing_task = {
            "id": "task-1",
            "contact_email": "mapostoli@jacobacci.com",
            "suggested_action": "Reply to contract question",
            "urgency": "high",
            "action_required": True,
        }
        mock_storage.get_task_items.return_value = [existing_task]
        mock_storage.get_unprocessed_emails_for_task.return_value = []

        tasks, _ = await worker.get_tasks(refresh=True)

        # clear_task_items must NEVER be called
        mock_storage.clear_task_items.assert_not_called()
        assert len(tasks) == 1
        assert tasks[0]["contact_email"] == "mapostoli@jacobacci.com"


class TestUserReplyClosesTask:
    """Bug #3: User replies must close tasks, parsing multi-recipient to_email."""

    @pytest.mark.asyncio
    async def test_reply_to_single_recipient_closes_task(self, worker, mock_storage):
        """When user replies to john@ex.com, the task for john@ex.com closes."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-reply",
                "from_email": "mario.alemi@cafe124.it",
                "to_email": "mapostoli@jacobacci.com",
                "subject": "Re: Contract",
                "body_plain": "Here's my answer",
                "snippet": "Here's my answer",
                "date_timestamp": 1712700000,
                "thread_id": "thread-1",
            },
        ]
        mock_storage.get_task_by_contact.return_value = {
            "id": "task-mapostoli",
            "contact_email": "mapostoli@jacobacci.com",
        }

        await worker.get_tasks(refresh=True)

        mock_storage.complete_task_item.assert_called_with(
            "test_owner",
            "task-mapostoli",
        )

    @pytest.mark.asyncio
    async def test_reply_to_multi_recipient_closes_task(self, worker, mock_storage):
        """When user replies to 'john@ex.com, cc@ex.com', task for john closes."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-reply-multi",
                "from_email": "mario.alemi@cafe124.it",
                "to_email": "mapostoli@jacobacci.com, someone.else@firm.com",
                "subject": "Re: Contract",
                "body_plain": "Done",
                "snippet": "Done",
                "date_timestamp": 1712700000,
                "thread_id": "thread-2",
            },
        ]

        # Return task for first call (mapostoli), None for second (someone.else)
        mock_storage.get_task_by_contact.side_effect = [
            {"id": "task-mapostoli", "contact_email": "mapostoli@jacobacci.com"},
            None,
        ]

        await worker.get_tasks(refresh=True)

        mock_storage.complete_task_item.assert_called_with(
            "test_owner",
            "task-mapostoli",
        )


class TestColleagueEmailCreatesTask:
    """Bug #2 extended: Emails from same-domain colleagues must create tasks."""

    @pytest.mark.asyncio
    async def test_colleague_email_not_skipped(self, worker, mock_storage):
        """Email from riccardo.cargnel@cafe124.it must NOT be skipped."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-riccardo",
                "from_email": "riccardo.cargnel@cafe124.it",
                "to_email": "mario.alemi@cafe124.it",
                "subject": "Aggiorna il pitch",
                "body_plain": "quando puoi riesci ad aggiornare il pitch con il brevetto",
                "snippet": "quando puoi riesci ad aggiornare il pitch con il brevetto",
                "date_timestamp": 1712700000,
                "thread_id": "thread-riccardo",
            },
        ]

        # Mock the LLM analysis to return a task
        with patch.object(worker, "_analyze_event", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = {
                "action_required": True,
                "task_action": "create",
                "urgency": "medium",
                "suggested_action": "Update pitch deck with patent info",
                "reason": "Colleague needs updated pitch for potential investors",
            }
            with patch.object(worker, "_get_blob_for_contact", return_value=("", None)):
                await worker.get_tasks(refresh=True)

        # The email must have been analyzed (not skipped)
        mock_analyze.assert_called_once()
        # And mark_email_task_processed must be called (email was processed)
        mock_storage.mark_email_task_processed.assert_called()
