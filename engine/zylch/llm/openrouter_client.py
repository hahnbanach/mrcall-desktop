"""Single-attempt Anthropic-wire adapter with server-enforced price ceilings.

Protocol: https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-a-message.md
Only GLM text/functions are enabled; quality on memory tasks is not benchmarked.
"""

from copy import deepcopy
from types import SimpleNamespace

import httpx

from .budget_pricing import BudgetError
from .openrouter_pricing import provider_policy, request_bound


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
        body = _without_cache(deepcopy(request))
        body.pop("service_tier", None)
        body.update(
            provider=provider_policy(body["model"]), thinking={"type": "disabled"}, stream=False
        )

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
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise BudgetError("OpenRouter returned an incomplete response; reservation retained.")
        if data.get("model") != request["model"]:
            raise BudgetError("OpenRouter returned a different model; reservation retained.")
        blocks = []
        for block in data["content"]:
            if not isinstance(block, dict) or block.get("type") not in ("text", "tool_use"):
                raise BudgetError("OpenRouter returned unsupported content; reservation retained.")
            blocks.append(SimpleNamespace(**block))
        return SimpleNamespace(
            content=blocks,
            usage=data.get("usage"),
            stop_reason=data.get("stop_reason"),
            model=data.get("model"),
            id=data.get("id"),
        )
