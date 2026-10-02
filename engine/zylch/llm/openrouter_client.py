"""Single-attempt Anthropic-wire adapter with server-enforced price ceilings.

Protocol: https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-a-message.md
Only explicitly priced text/function models are enabled; task quality is unmeasured.
The body is the request ``LLMClient`` shaped (``request_shape.py``): its reasoning
fields are the model's, and reasoning blocks come back in the response to be
replayed in the next request's history.
"""

import logging
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import httpx

from .budget_pricing import BudgetError
from .openrouter_pricing import provider_policy, request_bound
from .response import REASONING

logger = logging.getLogger(__name__)

# Anthropic-wire block types a response may carry; anything else is refused.
BLOCKS = ("text", "tool_use") + REASONING


def _without_cache(request):
    # Only protocol cache hints are removed. Tool arguments and JSON schemas
    # belong to the user and may legitimately have a "cache_control" property.
    body = deepcopy(request)

    def content(blocks):
        if not isinstance(blocks, list):
            return
        for block in blocks:
            block.pop("cache_control", None)
            if block.get("type") == "tool_result":
                content(block.get("content"))

    content(body.get("system"))
    for message in body.get("messages", []):
        content(message.get("content"))
    for tool in body.get("tools") or []:
        tool.pop("cache_control", None)
    return body


class OpenRouterClient:
    def __init__(self, api_key, *, http_client=None):
        if not api_key or not api_key.strip():
            raise BudgetError("Configure the selected OpenRouter account's API key.")
        self._key = api_key
        self._http = http_client
        self.messages = self

    def create(self, **request):
        request_bound(request)
        if request.get("model") == "moonshotai/kimi-k3" and "thinking" in request:
            return self._create_k3(request)
        body = _without_cache(deepcopy(request))
        body.pop("service_tier", None)
        body.update(provider=provider_policy(body["model"]), stream=False)

        def dispatch(client):
            return client.post(
                "https://openrouter.ai/api/v1/messages",
                json=body,
                headers={"Authorization": f"Bearer {self._key}", "anthropic-version": "2023-06-01"},
            )

        if self._http is not None:
            response = dispatch(self._http)
        else:
            with httpx.Client(timeout=180, follow_redirects=False) as client:
                response = dispatch(client)
        if response.status_code != 200:
            raise BudgetError(
                f"OpenRouter request failed (HTTP {response.status_code}); no automatic retry."
            )
        # Keep normal JSON types in tool arguments/public responses, but never
        # pass monetary literals through binary float before micro-USD rounding.
        exact = response.json(parse_float=Decimal)
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("usage"), dict):
            exact_cost = exact["usage"].get("cost")
            if isinstance(exact_cost, Decimal):
                data["usage"]["cost"] = str(exact_cost)
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise BudgetError("OpenRouter returned an incomplete response; reservation retained.")
        if data.get("model") != request["model"]:
            raise BudgetError("OpenRouter returned a different model; reservation retained.")
        blocks = []
        for block in data["content"]:
            if not isinstance(block, dict) or block.get("type") not in BLOCKS:
                raise BudgetError("OpenRouter returned unsupported content; reservation retained.")
            blocks.append(SimpleNamespace(**block))
        return SimpleNamespace(
            content=blocks,
            usage=data.get("usage"),
            stop_reason=data.get("stop_reason"),
            model=data.get("model"),
            id=data.get("id"),
        )

    def check_account(self):
        """A free read of the key's record (``GET /api/v1/key``): no inference.

        A refused key raises as a refused request does; a key whose credit
        limit is spent raises before a paid call would be refused for it.
        The key's record reflects only its own cap, so the account's balance
        is read too (``GET /api/v1/credits``): an exhausted one — the 402 a
        paid call would get with ``limit_source: openrouter_credits`` —
        raises the same way. OpenRouter documents that read for management
        keys; an inference key read it on 2026-10-02, and a key it refuses
        (403) leaves only the key's own limit checked.
        """

        def read(path):
            def dispatch(client):
                return client.get(
                    f"https://openrouter.ai/api/v1/{path}",
                    headers={"Authorization": f"Bearer {self._key}"},
                )

            if self._http is not None:
                return dispatch(self._http)
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                return dispatch(client)

        response = read("key")
        if response.status_code != 200:
            raise BudgetError(
                f"OpenRouter request failed (HTTP {response.status_code}); no automatic retry."
            )
        data = response.json().get("data")
        left = data.get("limit_remaining") if isinstance(data, dict) else None
        if type(left) in (int, float) and left <= 0:
            raise BudgetError("OpenRouter key has no credit left: its limit is spent.")
        response = read("credits")
        if response.status_code == 403:
            logger.debug("[openrouter] check_account: balance not readable with this key (403)")
            return
        if response.status_code != 200:
            raise BudgetError(
                f"OpenRouter request failed (HTTP {response.status_code}); no automatic retry."
            )
        data = response.json().get("data")
        data = data if isinstance(data, dict) else {}
        total, used = data.get("total_credits"), data.get("total_usage")
        if type(total) in (int, float) and type(used) in (int, float) and total - used <= 0:
            raise BudgetError(
                "OpenRouter account has no credit left: its balance is spent. "
                "Add credits at https://openrouter.ai/settings/credits."
            )

    def _create_k3(self, request):
        from .k3_reasoning import chat_request, decode_chat_response

        body = chat_request(request)

        def dispatch(client):
            return client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._key}"},
            )

        if self._http is not None:
            response = dispatch(self._http)
        else:
            with httpx.Client(timeout=600, follow_redirects=False) as client:
                response = dispatch(client)
        if response.status_code != 200:
            raise BudgetError(
                f"K3 request failed (HTTP {response.status_code}); no automatic retry."
            )
        return decode_chat_response(response)
