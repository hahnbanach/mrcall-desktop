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
                        user_email="user@example.com",
                    )
    return w


class TestIsUserEmail:
    """Bug #2: _is_user_email must NOT match same-domain colleagues."""

    def test_exact_match_returns_true(self, worker):
        assert worker._is_user_email("user@example.com") is True

    def test_exact_match_case_insensitive(self, worker):
        assert worker._is_user_email("User@Example.com") is True

    def test_colleague_same_domain_returns_false(self, worker):
        """colleague@example.com must NOT be treated as user."""
        assert worker._is_user_email("colleague@example.com") is False

    def test_external_contact_returns_false(self, worker):
        assert worker._is_user_email("customer@otherco.com") is False

    def test_empty_string_returns_false(self, worker):
        assert worker._is_user_email("") is False

    def test_subdomain_not_matched(self, worker):
        """user@notexample.com must NOT match example.com domain."""
        assert worker._is_user_email("someone@notexample.com") is False


class TestGetTasksNoDelete:
    """Bug #1: get_tasks(refresh=True) must NOT call clear_task_items."""

    @pytest.mark.asyncio
    async def test_refresh_does_not_clear_tasks(self, worker, mock_storage):
        """Existing tasks must survive a refresh."""
        existing_task = {
            "id": "task-1",
            "contact_email": "customer@otherco.com",
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
        assert tasks[0]["contact_email"] == "customer@otherco.com"


class TestUserReplyClosesTask:
    """Bug #3: User replies must close tasks, parsing multi-recipient to_email."""

    @pytest.mark.asyncio
    async def test_reply_to_single_recipient_closes_task(self, worker, mock_storage):
        """When user replies to john@ex.com, the task for john@ex.com closes."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-reply",
                "from_email": "user@example.com",
                "to_email": "customer@otherco.com",
                "subject": "Re: Contract",
                "body_plain": "Here's my answer",
                "snippet": "Here's my answer",
                "date_timestamp": 1712700000,
                "thread_id": "thread-1",
            },
        ]
        mock_storage.get_task_by_contact.return_value = {
            "id": "task-customer",
            "contact_email": "customer@otherco.com",
        }

        await worker.get_tasks(refresh=True)

        mock_storage.complete_task_item.assert_called_with(
            "test_owner",
            "task-customer",
        )

    @pytest.mark.asyncio
    async def test_reply_to_multi_recipient_closes_task(self, worker, mock_storage):
        """When user replies to 'john@ex.com, cc@ex.com', task for john closes."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-reply-multi",
                "from_email": "user@example.com",
                "to_email": "customer@otherco.com, someone.else@firm.com",
                "subject": "Re: Contract",
                "body_plain": "Done",
                "snippet": "Done",
                "date_timestamp": 1712700000,
                "thread_id": "thread-2",
            },
        ]

        # Return task for first call (mapostoli), None for second (someone.else)
        mock_storage.get_task_by_contact.side_effect = [
            {"id": "task-customer", "contact_email": "customer@otherco.com"},
            None,
        ]

        await worker.get_tasks(refresh=True)

        mock_storage.complete_task_item.assert_called_with(
            "test_owner",
            "task-customer",
        )


class TestUserReplyClosesCcRecipientTask:
    """F1 (RealStep / cafe124 case): user reply with contact in Cc must close
    that contact's task, not just To recipients."""

    @pytest.mark.asyncio
    async def test_reply_with_contact_in_cc_closes_cc_task(self, worker, mock_storage):
        """to=A, cc=B,C — tasks for A AND B AND C must all be closed via the
        per-recipient fallback (when get_tasks_by_thread returns empty)."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-reply-cc",
                "from_email": "user@example.com",
                "to_email": "e.argento@realstep.it",
                "cc_email": "ivan.marchese@cafe124milan.com, m.scacciati@realstep.it",
                "subject": "Re: RealStep meeting",
                "body_plain": "Confermo per il 5 maggio.",
                "snippet": "Confermo per il 5 maggio.",
                "date_timestamp": 1712700000,
                "thread_id": "thread-realstep",
            },
        ]
        # Per-thread close returns empty (RC-1 condition).
        mock_storage.get_tasks_by_thread.return_value = []
        # Per-recipient lookups: each contact has its own task.
        tasks_by_addr = {
            "e.argento@realstep.it": {"id": "task-argento"},
            "ivan.marchese@cafe124milan.com": {"id": "task-ivan"},
            "m.scacciati@realstep.it": {"id": "task-michele"},
        }
        mock_storage.get_task_by_contact.side_effect = lambda owner, addr: tasks_by_addr.get(addr)

        # `_collect` re-imports `get_session` lazily, so the fixture-level
        # patch has already exited. Re-patch for the test body. Same for
        # build_thread_history (the LLM analyze path is short-circuited via
        # the per-thread close → analyze branch).
        with (
            patch("zylch.storage.database.get_session"),
            patch(
                "zylch.workers.task_creation.build_thread_history",
                return_value="",
            ),
        ):
            await worker.get_tasks(refresh=True)

        completed_ids = {call.args[1] for call in mock_storage.complete_task_item.call_args_list}
        assert completed_ids == {"task-argento", "task-ivan", "task-michele"}

    @pytest.mark.asyncio
    async def test_reply_with_user_self_in_cc_skipped(self, worker, mock_storage):
        """User's own address in Cc (BCC-to-self pattern) must be ignored."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-reply-self-cc",
                "from_email": "user@example.com",
                "to_email": "contact@ex.com",
                "cc_email": "user@example.com",
                "subject": "Re: x",
                "body_plain": "ok",
                "snippet": "ok",
                "date_timestamp": 1712700000,
                "thread_id": "thread-self-cc",
            },
        ]
        mock_storage.get_tasks_by_thread.return_value = []
        mock_storage.get_task_by_contact.side_effect = lambda owner, addr: (
            {"id": "task-contact"} if addr == "contact@ex.com" else None
        )

        with (
            patch("zylch.storage.database.get_session"),
            patch(
                "zylch.workers.task_creation.build_thread_history",
                return_value="",
            ),
        ):
            await worker.get_tasks(refresh=True)

        completed_ids = {call.args[1] for call in mock_storage.complete_task_item.call_args_list}
        assert completed_ids == {"task-contact"}

    @pytest.mark.asyncio
    async def test_reply_dedup_recipients_no_double_close(self, worker, mock_storage):
        """Same address listed in both To and Cc must trigger only one close."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-reply-dup",
                "from_email": "user@example.com",
                "to_email": "dup@ex.com",
                "cc_email": "dup@ex.com",
                "subject": "Re: y",
                "body_plain": "ok",
                "snippet": "ok",
                "date_timestamp": 1712700000,
                "thread_id": "thread-dup",
            },
        ]
        mock_storage.get_tasks_by_thread.return_value = []
        mock_storage.get_task_by_contact.return_value = {"id": "task-dup"}

        with (
            patch("zylch.storage.database.get_session"),
            patch(
                "zylch.workers.task_creation.build_thread_history",
                return_value="",
            ),
        ):
            await worker.get_tasks(refresh=True)

        # complete_task_item called exactly once for task-dup
        dup_calls = [
            c for c in mock_storage.complete_task_item.call_args_list if c.args[1] == "task-dup"
        ]
        assert len(dup_calls) == 1


class TestForcingUpdateBranchDoesNotCorruptTask:
    """F2 (RealStep case): when LLM returns task_action='none' with a
    non-empty suggested_action ("Keep existing task as-is: …"), the worker
    must NOT overwrite the existing task's fields. The advisory text is
    not a task description."""

    @pytest.mark.asyncio
    async def test_none_with_advisory_does_not_update_existing_task(self, worker, mock_storage):
        existing = {
            "id": "task-existing",
            "contact_email": "m.scacciati@realstep.it",
            "suggested_action": "Original action: confirm date",
            "urgency": "high",
            "reason": "Original reason",
            "sources": {"emails": ["e1"]},
        }
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-from-michele",
                "from_email": "m.scacciati@realstep.it",
                "to_email": "mario.alemi@cafe124.it",
                "cc_email": "",
                "subject": "Re: meeting",
                "body_plain": "ack",
                "snippet": "ack",
                "date_timestamp": 1712700000,
                "thread_id": "thread-realstep",
            }
        ]
        mock_storage.get_tasks_by_thread.return_value = [existing]
        mock_storage.get_task_by_contact.return_value = None

        # _collect imports get_session lazily at call time via
        # `from zylch.storage.database import get_session as _gs`, so the
        # fixture-level patch has already exited. Re-patch for the test body.
        with (
            patch("zylch.storage.database.get_session"),
            patch(
                "zylch.workers.task_creation.build_thread_history",
                return_value="",
            ),
        ):
            with patch.object(worker, "_analyze_event", new_callable=AsyncMock) as mock_analyze:
                mock_analyze.return_value = {
                    "action_required": True,
                    "task_action": "none",
                    "suggested_action": ("Keep existing task as-is: Coordinate with Ivan to reply"),
                    "reason": "This email is just an ack",
                    "urgency": "high",
                }
                with patch.object(worker, "_get_blob_for_contact", return_value=("", None)):
                    await worker.get_tasks(refresh=True)

        # The existing task must NOT be updated by the "Forcing update" branch.
        mock_storage.update_task_item.assert_not_called()
        # The email must still be marked processed (so we don't loop forever).
        mock_storage.mark_email_task_processed.assert_called()


class TestColleagueEmailCreatesTask:
    """Bug #2 extended: Emails from same-domain colleagues must create tasks."""

    @pytest.mark.asyncio
    async def test_colleague_email_not_skipped(self, worker, mock_storage):
        """Email from colleague@example.com must NOT be skipped."""
        mock_storage.get_unprocessed_emails_for_task.return_value = [
            {
                "id": "email-riccardo",
                "from_email": "colleague@example.com",
                "to_email": "user@example.com",
                "subject": "Aggiorna il pitch",
                "body_plain": "quando puoi riesci ad aggiornare il pitch con il brevetto",
                "snippet": "quando puoi riesci ad aggiornare il pitch con il brevetto",
                "date_timestamp": 1712700000,
                "thread_id": "thread-riccardo",
            },
        ]

        # Mock the LLM analysis to return a task. `_collect` re-imports
        # `get_session` lazily, so the fixture-level patch has already
        # exited; re-patch for the test body. Same for build_thread_history.
        with (
            patch("zylch.storage.database.get_session"),
            patch(
                "zylch.workers.task_creation.build_thread_history",
                return_value="",
            ),
        ):
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
