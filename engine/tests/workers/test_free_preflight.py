"""The update pipeline's preflight is free, and a refusal still skips the paid stages (brief D3).

The pipeline used to ping the model with a paid one-token call before its
LLM-bound stages. It now runs ``LLMClient.check_transport`` — free reads only
— and a refused key or an empty balance is still recorded once, under the
``llm`` stage that ``humanize_error`` reads, with memory and task detection
skipped. Storage is real (a per-test SQLite file); the provider is a fake.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

OWNER = "o-free-preflight"


@pytest.fixture
def pending(tmp_path, monkeypatch):
    """A profile whose only work is one WhatsApp message awaiting task detection."""
    from zylch.storage import database
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.storage.worker_state import set_state
    from zylch.workers.task_gating import (
        WS_KEY_DEDUP_FINGERPRINT,
        WS_KEY_LAST_FULL_SWEEP,
        open_tasks_fingerprint,
    )

    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "pipeline.db"))
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    database.dispose_engine()
    database.init_db()
    now = datetime.now(timezone.utc)
    set_state(OWNER, WS_KEY_DEDUP_FINGERPRINT, open_tasks_fingerprint([]))
    set_state(OWNER, WS_KEY_LAST_FULL_SWEEP, now.isoformat())
    with get_session() as session:
        mid = str(uuid.uuid4())
        session.add(
            WhatsAppMessage(
                id=mid,
                owner_id=OWNER,
                message_id=mid,
                chat_jid="391112223334@s.whatsapp.net",
                sender_jid="391112223334@s.whatsapp.net",
                text="hi",
                timestamp=now,
                is_from_me=False,
                is_group=False,
                memory_processed_at=now,
            )
        )
    yield
    database.dispose_engine()


def _router(status, balance=None):
    from zylch.llm.client import LLMClient
    from zylch.llm.openrouter_client import OpenRouterClient

    paths = []

    def handler(request):
        paths.append((request.method, request.url.path))
        if balance is not None and request.url.path == "/api/v1/credits":
            return httpx.Response(200, json={"data": balance})
        return httpx.Response(status, json={"data": {"limit_remaining": None}})

    client = LLMClient("openrouter", api_key="synthetic", model="z-ai/glm-5.3-flash")
    client._client = OpenRouterClient(
        "synthetic", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, paths


async def _run(client):
    from zylch.services import process_pipeline as pp

    errors, tasks = [], AsyncMock(return_value="detection ran")
    with (
        patch.object(pp, "_run_sync", AsyncMock(return_value={"success": True, "new_messages": 0})),
        patch.object(pp, "_run_whatsapp_sync", return_value={"skipped": True, "reason": "test"}),
        patch("zylch.llm.client.make_llm_client", lambda *a, **k: client),
        patch.object(pp, "_run_tasks", tasks),
        patch.object(pp, "_run_memory", AsyncMock(return_value=(0, 0))),
        patch("zylch.services.command_handlers.handle_tasks", AsyncMock(return_value="no tasks")),
    ):
        await pp.handle_process([], None, OWNER, errors_out=errors)
    return errors, tasks


@pytest.mark.asyncio
async def test_a_refused_key_is_recorded_once_and_skips_the_paid_stages(pending):
    from zylch.services.error_messages import humanize_error

    client, paths = _router(401)
    errors, tasks = await _run(client)
    assert paths == [("GET", "/api/v1/key")]  # a free read: no request to /messages
    llm = [e for e in errors if e["stage"] == "llm"]
    assert len(llm) == 1 and "HTTP 401" in str(llm[0]["error"])
    assert humanize_error(llm[0]["error"], "llm")["kind"] == "llm_budget"
    tasks.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_accepted_key_lets_the_paid_stages_run(pending):
    client, paths = _router(200)
    errors, tasks = await _run(client)
    # The key's record, then the account's balance (IR1 m2): free reads only.
    assert paths == [("GET", "/api/v1/key"), ("GET", "/api/v1/credits")]
    assert not [e for e in errors if e["stage"] == "llm"]
    tasks.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_exhausted_account_balance_is_recorded_once_and_skips_the_paid_stages(pending):
    from zylch.services.error_messages import humanize_error

    client, paths = _router(200, balance={"total_credits": 25, "total_usage": 25.0004})
    errors, tasks = await _run(client)
    assert paths == [("GET", "/api/v1/key"), ("GET", "/api/v1/credits")]
    llm = [e for e in errors if e["stage"] == "llm"]
    assert len(llm) == 1 and "account has no credit left" in str(llm[0]["error"])
    assert humanize_error(llm[0]["error"], "llm")["kind"] == "llm_budget"
    tasks.assert_not_awaited()
