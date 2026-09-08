"""`chat.send` reports a refused prompt and a cut tool result in its metadata.

A caller — the desktop, the `cs` operator, a cron tick — reads
`metadata.error` to tell an answer from an outage. A prompt refused for
size is an outage of the grounding step, so it is reported as
`PROMPT_TOO_LARGE` with the estimate and the budget, and any tool result
cut earlier in the turn is listed under `truncated_tool_results` on every
outcome, so a reply built on a partial lookup is never indistinguishable
from a grounded one.
"""

from __future__ import annotations

import asyncio

import pytest

from zylch.llm.exceptions import LLMPromptTooLargeError

OWNER = "owner-prompt-budget-test"
CUT = {"tool": "search_local_emails", "original_chars": 1_130_883, "shown_chars": 80_000}


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "prompt_budget_test.db"))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield
    db_mod.dispose_engine()


class _Agent:
    def __init__(self, outcome, truncations):
        self.outcome = outcome
        self.last_truncations = list(truncations)
        self.tools = []

    def clear_history(self):
        pass

    def set_history(self, history):
        pass

    async def process_message(self, user_message, context=None, approval_callback=None):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _send(monkeypatch, agent):
    from zylch.services.chat_service import ChatService

    async def _init(self, owner_id=None):
        self.agent = agent
        self._initialized = True

    monkeypatch.setattr(ChatService, "_initialize_agent", _init)
    monkeypatch.setattr(ChatService, "_match_semantic_command", lambda self, m: None)
    return asyncio.run(
        ChatService().process_message(
            user_message="what have we quoted for private label?",
            user_id=OWNER,
            context={"user_id": OWNER},
        )
    )


def test_a_refused_prompt_is_a_structured_error(fresh_storage, monkeypatch):
    result = _send(monkeypatch, _Agent(LLMPromptTooLargeError(300_000, 150_000), [CUT]))

    meta = result["metadata"]
    assert meta["error"] == "PROMPT_TOO_LARGE"
    assert meta["estimated_tokens"] == 300_000
    assert meta["budget_tokens"] == 150_000
    assert meta["truncated_tool_results"] == [CUT]
    assert "150,000" in result["response"] or "150000" in result["response"]


def test_a_cut_result_is_reported_on_success(fresh_storage, monkeypatch):
    result = _send(monkeypatch, _Agent("grounded answer", [CUT]))

    assert result["response"].endswith("grounded answer")
    assert "error" not in result["metadata"]
    assert result["metadata"]["truncated_tool_results"] == [CUT]


def test_no_cut_means_no_key(fresh_storage, monkeypatch):
    result = _send(monkeypatch, _Agent("grounded answer", []))

    assert "truncated_tool_results" not in result["metadata"]
