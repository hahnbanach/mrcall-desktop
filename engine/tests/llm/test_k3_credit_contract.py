"""Optional cross-repository contract regression, synthetic paid services only.

Add the mrcall-agent checkout to PYTHONPATH and set BOUNDED_TEST_DATABASE_URL
for a disposable PostgreSQL database. Never uses a production database URL.
"""

import os
from types import SimpleNamespace
import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

pytest.importorskip("mrcall_agent")
from mrcall_agent.api.routes import desktop_bounded_llm as route
from mrcall_agent.api.routes.desktop_auth import get_current_user_either_header
from mrcall_agent.storage.bounded_billing import BillingLedger, admissions
from zylch.llm.bounded_proxy import BoundedProxyClient
from zylch.llm.billing_reconciliation import reconcile
from zylch.llm.budget import BudgetError, budget_snapshot
from zylch.llm.client import LLMClient
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage, LlmBillingAuthorization


@pytest.mark.parametrize("mode", ["normal", "lost", "zero", "partial"])
def test_actual_crossrepo(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "crossrepo-review-account")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0" if mode == "zero" else "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(),
        tables=[LlmReservation.__table__, LlmUsage.__table__, LlmBillingAuthorization.__table__],
    )
    test_url = os.environ.get("BOUNDED_TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("Dedicated disposable PostgreSQL required")
    assert test_url.startswith("postgresql") and "bounded_test" in test_url
    pg = create_engine(test_url)
    admissions.create(pg, checkfirst=True)
    monkeypatch.setattr(route, "ledger", lambda: BillingLedger(pg))
    monkeypatch.setattr(route.settings, "anthropic_api_key", "synthetic-key")
    monkeypatch.setattr(route.settings, "openrouter_api_key", "synthetic-key")
    counts = {"dispatch": 0, "consume": 0, "execute": 0}

    class Credit:
        async def resolve_business_id(self, *a):
            return "synthetic-business"

        async def balance(self, *a):
            return 10000

        async def consume(self, *a, **kw):
            counts["consume"] += 1
            return 0 if mode == "partial" else a[2]

        async def aclose(self):
            pass

    async def upstream(request):
        counts["dispatch"] += 1
        assert request["thinking"] == {"type": "adaptive"}
        assert request["output_config"] == {"effort": "max"}
        assert request["max_tokens"] == 8192
        return {
            "model": "moonshotai/kimi-k3",
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
            "type": "message",
            "id": "gen-synthetic",
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost": "0.000001"},
        }

    monkeypatch.setattr(route, "StarChatCreditClient", Credit)
    monkeypatch.setattr(route, "upstream", upstream)
    app = FastAPI()
    app.include_router(route.router, prefix="/api/desktop/llm/bounded")
    app.dependency_overrides[get_current_user_either_header] = lambda: {
        "uid": "crossrepo-review-account"
    }
    api = TestClient(app)

    def forward(req):
        response = api.request(
            req.method,
            req.url.path,
            content=req.content,
            headers={"auth": "synthetic-token", "content-type": "application/json"},
        )
        if req.url.path.endswith("/execute"):
            counts["execute"] += 1
            assert budget_snapshot("crossrepo-review-account")["reserved_usd"] > 0
            if mode == "lost":
                assert response.status_code == 200, response.text
                raise httpx.ReadTimeout("synthetic lost settled response")
        assert response.status_code == 200, response.text
        return httpx.Response(response.status_code, content=response.content)

    transport = BoundedProxyClient(
        "https://synthetic.test",
        SimpleNamespace(id_token="synthetic-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(forward)),
    )
    client = LLMClient(
        "proxy",
        firebase_session=SimpleNamespace(id_token="synthetic-token"),
        model="moonshotai/kimi-k3",
    )
    client._client = transport
    args = {"messages": [{"role": "user", "content": "synthetic review"}], "max_tokens": 20}
    if mode in ["zero", "lost"]:
        with pytest.raises(BudgetError):
            client.create_message_sync(**args)
    else:
        assert client.create_message_sync(**args).content[0].text == "OK"
    if mode == "lost":
        database.dispose_engine()
        assert reconcile(transport)["recovered"] == 1
        assert reconcile(transport)["recovered"] == 0
    expected = 0 if mode == "zero" else 1
    assert counts == dict(dispatch=expected, consume=expected, execute=expected)
    state = budget_snapshot("crossrepo-review-account")
    assert state["reserved_usd"] == 0
    assert state["spent_usd"] == (0 if mode in ["zero", "partial"] else 0.011)
    database.dispose_engine()
    pg.dispose()
