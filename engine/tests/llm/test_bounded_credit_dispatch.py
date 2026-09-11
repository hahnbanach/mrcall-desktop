"""HTTP debit protocol plus real SQLite. Synthetic receipts; no paid endpoints."""
import json
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm.bounded_proxy import BoundedProxyClient, PROTOCOL, digest
from zylch.llm.budget import BudgetError, budget_snapshot
from zylch.llm.billing_reconciliation import reconcile
from zylch.llm.client import LLMClient
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage, LlmBillingAuthorization


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYLCH_DB_PATH', str(tmp_path/'profile.db'))
    monkeypatch.setenv('OWNER_ID', 'account')
    monkeypatch.setenv('LLM_DAILY_BUDGET_USD', '5')
    monkeypatch.delenv('ZYLCH_PROFILE_DIR', raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(database.get_engine(), tables=[
        LlmReservation.__table__, LlmUsage.__table__, LlmBillingAuthorization.__table__])
    yield
    database.dispose_engine()


def protocol(*, lose_response=False, corrupt=None):
    requests, receipts = [], {}
    def handler(http_request):
        requests.append(http_request.url.path)
        if '/status/' in http_request.url.path:
            receipt = receipts[http_request.url.path.rsplit('/', 1)[1]]
            return httpx.Response(200, json={'state': 'settled', 'receipt': receipt})
        body = json.loads(http_request.content)
        if http_request.url.path.endswith('/quote'):
            quote = dict(protocol=PROTOCOL, currency='USD', account_id='account', business_id='business',
                payload_hash=digest(body['request']), tariff_version='test-tariff', model=body['request']['model'],
                credit_value_micro_usd=11000, markup_factor='1.5', max_credits=2, max_debit_micro_usd=22000)
            if corrupt == 'quote_account':
                quote['account_id'] = 'other'
            quote['quote_hash'] = digest(quote)
            return httpx.Response(200, json=quote)
        assert budget_snapshot('account')['reserved_usd'] == 0.022
        receipt = {**body['quote'], 'request_id': body['request_id'],
                   'authorized_max_debit_micro_usd': body['max_debit_micro_usd'],
                   'credits': 1, 'debit_micro_usd': 11000}
        if corrupt == 'receipt_amount':
            receipt['debit_micro_usd'] = 1
        receipts[body['request_id']] = receipt
        if lose_response:
            raise httpx.ReadTimeout('lost response after debit')
        return httpx.Response(200, json={'state': 'settled', 'receipt': receipt,
            'message': {'model': body['request']['model'], 'content': [{'type':'text','text':'SKIP'}],
                        'stop_reason':'end_turn','usage':{'input_tokens':10,'output_tokens':1}}})
    transport = BoundedProxyClient('https://synthetic.test', SimpleNamespace(id_token='fake'),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client = LLMClient('proxy', firebase_session=SimpleNamespace(id_token='fake'), model='claude-haiku-4-5')
    client._client = transport
    return client, requests


ARGS = dict(messages=[{'role':'user','content':'synthetic'}], max_tokens=20)


def test_receipt_settles_customer_debit_including_markup_and_rounding(ledger):
    c, calls = protocol()
    assert c.create_message_sync(**ARGS).content[0].text == 'SKIP'
    snapshot = budget_snapshot('account')
    assert snapshot['spent_usd'] == 0.011
    assert snapshot['reserved_usd'] == 0
    assert len(calls) == 2


def test_lost_response_recovers_only_receipt_after_store_reopen(ledger):
    c, calls = protocol(lose_response=True)
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS)
    assert budget_snapshot('account')['reserved_usd'] == 0.022
    database.dispose_engine()
    assert reconcile(c._client)['recovered'] == 1
    assert reconcile(c._client)['recovered'] == 0
    assert budget_snapshot('account')['spent_usd'] == 0.011
    assert len([path for path in calls if path.endswith('/execute')]) == 1


@pytest.mark.parametrize('corrupt,held,execute', [('quote_account',0,0),('receipt_amount',.022,1)])
def test_invalid_binding_cannot_release_liability(ledger, corrupt, held, execute):
    c, calls = protocol(corrupt=corrupt)
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS)
    assert budget_snapshot('account')['reserved_usd'] == held
    assert len([path for path in calls if path.endswith('/execute')]) == execute


def test_daily_cap_stops_before_paid_execute(ledger, monkeypatch):
    monkeypatch.setenv('LLM_DAILY_BUDGET_USD', '0')
    c, calls = protocol()
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS)
    assert all(not path.endswith('/execute') for path in calls)


def test_factory_and_status_use_saved_proxy_endpoint(ledger, tmp_path, monkeypatch):
    from zylch import auth
    from zylch.config import settings
    from zylch.llm.client import make_llm_client
    from zylch.rpc.usage_queries import _credit_client
    tmp_path.joinpath('.env').write_text('LLM_PROVIDER=mrcall\nMRCALL_PROXY_URL=https://saved.example.test\n')
    monkeypatch.setenv('ZYLCH_PROFILE_DIR', str(tmp_path))
    monkeypatch.setenv('MRCALL_PROXY_URL', 'https://ambient.example.test')
    monkeypatch.setattr(settings, 'mrcall_proxy_url', 'https://startup.example.test')
    monkeypatch.setattr(auth, 'get_session', lambda: SimpleNamespace(id_token='fake'))
    assert make_llm_client()._client.base == 'https://saved.example.test'
    assert _credit_client().base == 'https://saved.example.test'


def test_reconciliation_can_advance_past_permanent_holds(ledger, monkeypatch):
    from zylch.llm import budget
    from uuid import UUID
    ids = iter(UUID(int=i) for i in range(1, 12))
    monkeypatch.setattr(budget, 'uuid4', lambda: next(ids))
    c, _ = protocol(lose_response=True)
    # Handler's reservation assertion is for the first call only; each request
    # obtains its quote and hold; emulate dispatch ambiguity before execute.
    for i in range(1,12):
        request = {'model':'claude-haiku-4-5', **ARGS}
        quote = c._client.quote(request)
        budget.reserve(request, 'proxy', quote=quote)
    def status(request_id):
        if UUID(request_id).int < 11:
            return {'state':'dispatched','receipt':None}
        from sqlalchemy import select
        with database.get_engine().connect() as conn:
            quote = conn.execute(select(LlmBillingAuthorization.quote).where(
                LlmBillingAuthorization.reservation_id == request_id)).scalar_one()
        return {'state':'settled','receipt': {**quote,'request_id':request_id,
            'authorized_max_debit_micro_usd':22000,'credits':1,'debit_micro_usd':11000}}
    c._client.status = status
    first = reconcile(c._client)
    assert first['unresolved'] == 10 and first['next_cursor']
    second = reconcile(c._client, cursor=first['next_cursor'])
    assert second['recovered'] == 1 and second['next_cursor'] is None
