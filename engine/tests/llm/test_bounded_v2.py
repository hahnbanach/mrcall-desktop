"""The credits protocol v2 on the engine's side (`roles/contract/protocol-v2.md`; brief D6).

The engine marks its quote and execute bodies with ``"protocol":
"mrcall-bounded-v2"`` beside ``request`` (so ``payload_hash`` stays the
digest of ``request``), checks that the server answers v2 — a quote naming
the snapshot version it priced with, a receipt repeating it — and pauses with
"update the billing server" when a marked call is answered as v1, never
falling back. A reservation quoted in v1 before an upgrade still settles
against its stored v1 quote. Synthetic server over `httpx.MockTransport`, real
SQLite ledger; no paid endpoint.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm.bounded_proxy import V1, BoundedProxyClient, PROTOCOL, digest, validate_receipt
from zylch.llm.budget import BudgetError, budget_snapshot
from zylch.llm.client import LLMClient
from zylch.storage import database
from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

SNAPSHOT = hashlib.sha256(b"priced with").hexdigest()
ARGS = dict(messages=[{"role": "user", "content": "synthetic"}], max_tokens=20)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "account")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(),
        tables=[LlmReservation.__table__, LlmUsage.__table__, LlmBillingAuthorization.__table__],
    )
    yield
    database.dispose_engine()


def server(*, quote_edit=None, receipt_edit=None):
    """A v2 billing server; `quote_edit` / `receipt_edit` doctor its answers."""
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append((request.url.path.rsplit("/", 1)[1], body))
        if request.url.path.endswith("/quote"):
            quote = dict(
                protocol=body.get("protocol", V1),
                currency="USD",
                account_id="account",
                business_id="business",
                payload_hash=digest(body["request"]),
                tariff_version="test-tariff",
                model=body["request"]["model"],
                credit_value_micro_usd=11000,
                markup_factor="1.5",
                max_credits=2,
                max_debit_micro_usd=22000,
                snapshot_version=SNAPSHOT,
            )
            if quote_edit:
                quote_edit(quote)
            quote["quote_hash"] = digest({k: v for k, v in quote.items() if k != "quote_hash"})
            return httpx.Response(200, json=quote)
        receipt = {
            **body["quote"],
            "request_id": body["request_id"],
            "authorized_max_debit_micro_usd": body["max_debit_micro_usd"],
            "credits": 1,
            "debit_micro_usd": 11000,
        }
        if receipt_edit:
            receipt_edit(receipt)
        message = {
            "model": body["request"]["model"],
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 1},
        }
        return httpx.Response(
            200, json={"state": "settled", "receipt": receipt, "message": message}
        )

    session = SimpleNamespace(id_token="synthetic")
    client = LLMClient("proxy", firebase_session=session, model="claude-sonnet-5")
    client._client = BoundedProxyClient(
        "https://synthetic.test",
        session,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return client, bodies


def test_quote_and_execute_carry_the_v2_marker_beside_the_request(ledger):
    client, bodies = server()
    assert client.create_message_sync(**ARGS).content[0].text == "OK"
    assert [name for name, _ in bodies] == ["quote", "execute"]
    for _, body in bodies:
        assert body["protocol"] == PROTOCOL == "mrcall-bounded-v2"
        assert "protocol" not in body["request"]
    quote_body, execute_body = bodies[0][1], bodies[1][1]
    assert execute_body["quote"]["snapshot_version"] == SNAPSHOT
    assert execute_body["quote"]["payload_hash"] == digest(quote_body["request"])
    assert budget_snapshot("account")["spent_usd"] == 0.011


def test_a_quote_answered_as_v1_pauses_with_update_the_billing_server(ledger):
    client, bodies = server(quote_edit=lambda quote: quote.update(protocol=V1))
    with pytest.raises(BudgetError, match="update the billing server"):
        client.create_message_sync(**ARGS)
    assert [name for name, _ in bodies] == ["quote"]  # never falls back, never executes
    assert budget_snapshot("account")["reserved_usd"] == 0


@pytest.mark.parametrize(
    "edit",
    [
        lambda quote: quote.pop("snapshot_version"),
        lambda quote: quote.update(snapshot_version=None),
        lambda quote: quote.update(snapshot_version="F" * 64),
        lambda quote: quote.update(snapshot_version=SNAPSHOT[:63]),
    ],
    ids=["missing", "null", "uppercase", "short"],
)
def test_a_v2_quote_must_name_the_snapshot_it_priced_with(ledger, edit):
    client, bodies = server(quote_edit=edit)
    with pytest.raises(BudgetError, match="invalid debit quote"):
        client.create_message_sync(**ARGS)
    assert [name for name, _ in bodies] == ["quote"]
    assert budget_snapshot("account")["reserved_usd"] == 0


@pytest.mark.parametrize(
    "edit",
    [
        lambda receipt: receipt.update(snapshot_version="0" * 64),
        lambda receipt: receipt.pop("snapshot_version"),
        lambda receipt: receipt.update(protocol=V1),
    ],
    ids=["another-snapshot", "no-snapshot", "v1-receipt"],
)
def test_a_receipt_must_repeat_the_quote_s_protocol_and_snapshot(ledger, edit):
    client, _ = server(receipt_edit=edit)
    with pytest.raises(BudgetError, match="charge is unconfirmed; reservation retained"):
        client.create_message_sync(**ARGS)
    assert budget_snapshot("account")["reserved_usd"] == 0.022  # the hold stays


def test_a_reservation_quoted_in_v1_before_an_upgrade_still_settles():
    quote = dict(
        protocol=V1,
        currency="USD",
        account_id="account",
        business_id="business",
        payload_hash="p",
        tariff_version="t",
        model="claude-sonnet-5",
        credit_value_micro_usd=11000,
        max_credits=2,
        max_debit_micro_usd=22000,
    )
    quote["quote_hash"] = digest(quote)
    reservation = SimpleNamespace(id="r-1", reserved_micro_usd=22000)
    receipt = {
        **quote,
        "request_id": "r-1",
        "authorized_max_debit_micro_usd": 22000,
        "credits": 1,
        "debit_micro_usd": 11000,
    }
    assert validate_receipt(reservation, quote, receipt) == 11000
