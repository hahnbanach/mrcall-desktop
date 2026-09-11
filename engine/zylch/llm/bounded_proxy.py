"""Single-attempt MrCall debit contract; never replay inference to recover billing."""
import hashlib
import json
from types import SimpleNamespace

import httpx

from .budget_pricing import BudgetError

PROTOCOL = 'mrcall-bounded-v1'
PREFIX = '/api/desktop/llm/bounded'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def wire_request(request):
    if request.get('service_tier', 'standard_only') != 'standard_only':
        raise BudgetError('MrCall credits support standard pricing only.')
    # The server injects standard_only. All other features are validated there;
    # never silently drop caller options from the quoted/authorized payload.
    return {key: value for key, value in request.items() if key != 'service_tier' and value is not None}


def validate_quote(request, quote, owner):
    try:
        if not isinstance(quote, dict):
            raise ValueError()
        if (quote['protocol'] != PROTOCOL or quote['currency'] != 'USD'
                or quote['account_id'] != owner or quote['model'] != request['model']
                or quote['payload_hash'] != digest(wire_request(request))
                or not isinstance(quote['business_id'], str) or not quote['business_id']
                or not isinstance(quote['tariff_version'], str) or not quote['tariff_version']):
            raise ValueError()
        for key in ('credit_value_micro_usd', 'max_credits', 'max_debit_micro_usd'):
            if type(quote[key]) is not int or quote[key] <= 0:
                raise ValueError()
        if quote['max_debit_micro_usd'] != quote['max_credits'] * quote['credit_value_micro_usd']:
            raise ValueError()
        if quote['quote_hash'] != digest({k: v for k, v in quote.items() if k != 'quote_hash'}):
            raise ValueError()
        return quote['max_debit_micro_usd']
    except (KeyError, ValueError, TypeError):
        raise BudgetError('AI paused: MrCall returned an invalid debit quote.') from None


def validate_receipt(reservation, quote, receipt):
    try:
        if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in quote.items()):
            raise ValueError()
        if (receipt['request_id'] != reservation.id
                or receipt['authorized_max_debit_micro_usd'] != reservation.reserved_micro_usd):
            raise ValueError()
        units, amount = receipt['credits'], receipt['debit_micro_usd']
        if (type(units) is not int or type(amount) is not int or units < 0 or amount < 0
                or units > quote['max_credits'] or amount > reservation.reserved_micro_usd
                or amount != units * quote['credit_value_micro_usd']):
            raise ValueError()
        return amount
    except (KeyError, ValueError, TypeError):
        raise BudgetError('AI paused: MrCall charge is unconfirmed; reservation retained.') from None


class BoundedProxyClient:
    def __init__(self, proxy_base_url, firebase_session, *, http_client=None):
        self.base = proxy_base_url.rstrip('/')
        self.session = firebase_session
        self.http = http_client

    def _call(self, method, path, body=None):
        token = getattr(self.session, 'id_token', None)
        if not isinstance(token, str) or not token:
            raise BudgetError('Sign in again to check MrCall billing.')
        def send(client):
            response = client.request(method, self.base + PREFIX + path, json=body,
                                      headers={'auth': token})
            if response.status_code != 200:
                hints = {401: 'Sign in again.', 402: 'Top up at dashboard.mrcall.ai/plan.',
                         404: 'Update the billing server to support bounded credits.',
                         409: 'Pricing or request state changed; check reservations before retrying.'}
                raise BudgetError(f'MrCall billing HTTP {response.status_code}. ' +
                                  hints.get(response.status_code, 'Request unconfirmed; check reservations.'))
            return response.json()
        try:
            if self.http is not None:
                return send(self.http)
            with httpx.Client(timeout=5 if method == 'GET' else 180, follow_redirects=False) as client:
                return send(client)
        except (httpx.HTTPError, ValueError):
            raise BudgetError('MrCall request unconfirmed; any existing reservation remains.') from None

    def capabilities(self):
        result = self._call('GET', '/capabilities')
        if not isinstance(result, dict) or result.get('protocol') != PROTOCOL or result.get('currency') != 'USD':
            raise BudgetError('Update the billing server to support bounded credits.')
        return result

    def quote(self, request):
        return self._call('POST', '/quote', {'request': wire_request(request)})

    def execute(self, request, quote, reservation):
        result = self._call('POST', '/execute', {
            'request': wire_request(request), 'quote': quote, 'request_id': reservation.id,
            'max_debit_micro_usd': reservation.reserved_micro_usd,
        })
        if not isinstance(result, dict) or result.get('state') != 'settled':
            raise BudgetError('MrCall request unresolved; reservation retained. Check its status.')
        message = result.get('message')
        if not isinstance(message, dict) or not isinstance(message.get('content'), list):
            raise BudgetError('MrCall response unavailable; check billing status without repeating the request.')
        blocks = message['content']
        if any(not isinstance(b, dict) or b.get('type') not in ('text', 'tool_use') for b in blocks):
            raise BudgetError('MrCall response incomplete; reservation retained.')
        return SimpleNamespace(content=[SimpleNamespace(**b) for b in blocks],
                               model=message.get('model'), stop_reason=message.get('stop_reason'),
                               usage=message.get('usage')), result.get('receipt')

    def status(self, request_id):
        return self._call('GET', '/status/' + request_id)
