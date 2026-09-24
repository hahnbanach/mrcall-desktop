"""Direct GPT-6 Responses adapter for the explicitly isolated voice experiment.

The common LLMClient owns reservations and settlement. No StarChat fallback.
GPT-6 Sol supports reasoning=none and function calling on Responses. Keeping
reasoning off avoids introducing hidden state into the existing text/tool loop.
Official model/pricing and function-calling docs checked 2026-09-24.
"""

import json
from decimal import Decimal, ROUND_CEILING
from types import SimpleNamespace

import httpx

from .budget_pricing import BudgetError, _content

MODEL = "gpt-6-sol"
MAX_OUTPUT_TOKENS = 128000  # Provider capacity, not a conversation limit.


def text_content(content):
    _content(content)
    if isinstance(content, str):
        return content
    if any(b.get("type") != "text" for b in content):
        raise BudgetError("OpenAI voice accepts text and selected function results only.")
    return "\n".join(b["text"] for b in content)


def responses_request(request):
    """Translate the existing agent's text/tool history without provider storage."""
    if request.get("model") != MODEL:
        raise BudgetError("OpenAI voice model has no verified price.")
    if set(request) - {
        "model",
        "messages",
        "system",
        "tools",
        "max_tokens",
        "temperature",
        "service_tier",
    }:
        raise BudgetError("Unsupported OpenAI voice request option.")
    if request.get("service_tier", "standard_only") != "standard_only":
        raise BudgetError("Only standard OpenAI pricing is supported.")
    if request.get("temperature", 1) != 1:
        raise BudgetError("Custom sampling is not configured for GPT-6 voice.")
    output = request.get("max_tokens")
    if type(output) is not int or not 1 <= output <= MAX_OUTPUT_TOKENS:
        raise BudgetError("OpenAI output exceeds the model capacity.")
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BudgetError("OpenAI voice requires conversation messages.")
    items = []
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise BudgetError("Unsupported OpenAI voice message options.")
        role, content = message["role"], message["content"]
        if role not in ("user", "assistant"):
            raise BudgetError("Unsupported OpenAI voice message role.")
        _content(content)
        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue
        for block in content:
            kind = block["type"]
            if kind == "text":
                items.append({"role": role, "content": block["text"]})
            elif kind == "tool_use" and role == "assistant":
                if block.get("name") != "caller_memory" or not isinstance(block.get("input"), dict):
                    raise BudgetError("Only selected caller memory is available to OpenAI voice.")
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block["id"],
                        "name": block["name"],
                        "arguments": json.dumps(block["input"], allow_nan=False),
                    }
                )
            elif kind == "tool_result" and role == "user":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": text_content(block.get("content", "")),
                    }
                )
            else:
                raise BudgetError("Unsupported OpenAI voice message block.")
    tools = request.get("tools") or []
    if not isinstance(tools, list) or any(
        not isinstance(t, dict)
        or t.get("name") != "caller_memory"
        or set(t) - {"name", "description", "input_schema", "cache_control"}
        for t in tools
    ):
        raise BudgetError("Only selected caller memory is available to OpenAI voice.")
    body = {
        "model": MODEL,
        "input": items,
        "instructions": text_content(request.get("system", "")),
        "store": False,
        "reasoning": {"effort": "none"},
        "max_output_tokens": output,
        "service_tier": "default",
    }
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
                "strict": False,
            }
            for t in tools
        ]
        body["parallel_tool_calls"] = False
    return body


def request_bound(request):
    body = responses_request(request)
    try:
        payload = len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode())
    except (TypeError, ValueError):
        raise BudgetError("OpenAI request cannot be priced safely.") from None
    tokens = payload + 4096 + 1024 * (len(body["input"]) + len(body.get("tools") or []))
    # Reserve long-context rates and all input as cache writes. No local context
    # ceiling: the provider enforces its physical window. USD/MTok = microUSD/token.
    return tokens * 5 + body["max_output_tokens"] * 15


def usage_cost(model, usage):
    if model != MODEL or not isinstance(usage, dict):
        raise BudgetError("OpenAI usage unavailable; reservation retained.")
    if usage.get("service_tier") not in (None, "default"):
        raise BudgetError("Unexpected OpenAI service tier; reservation retained.")
    counts = {}
    for name in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        value = usage.get(name, 0 if name.startswith("cache_") else None)
        if type(value) is not int or value < 0:
            raise BudgetError("Invalid OpenAI usage; reservation retained.")
        counts[name] = value
    long = (
        sum(
            counts[k]
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        > 272000
    )
    cost = (
        counts["input_tokens"] * (4 if long else 2)
        + counts["output_tokens"] * (15 if long else 10)
        + Decimal("0.4" if long else "0.2") * counts["cache_read_input_tokens"]
        + Decimal("5" if long else "2.5") * counts["cache_creation_input_tokens"]
    )
    return int(cost.to_integral_value(rounding=ROUND_CEILING)), counts


def decode_response(data):
    try:
        if data["model"] != MODEL or data["status"] != "completed" or data.get("error"):
            raise ValueError
        blocks, ids = [], set()
        for item in data["output"]:
            if item["type"] == "message":
                if item["role"] != "assistant" or item["status"] != "completed":
                    raise ValueError
                for block in item["content"]:
                    if block["type"] != "output_text" or not isinstance(block["text"], str):
                        raise ValueError
                    blocks.append(SimpleNamespace(type="text", text=block["text"]))
            elif item["type"] == "function_call":
                name, identifier = item["name"], item["call_id"]
                args = json.loads(item["arguments"])
                if (
                    name != "caller_memory"
                    or item.get("status") != "completed"
                    or not isinstance(identifier, str)
                    or not identifier
                    or identifier in ids
                    or not isinstance(args, dict)
                ):
                    raise ValueError
                ids.add(identifier)
                blocks.append(
                    SimpleNamespace(type="tool_use", name=name, id=identifier, input=args)
                )
            else:
                # reasoning=none: never silently discard reasoning or accept a
                # paid hosted tool that this selected-memory adapter did not admit.
                raise ValueError
        if not blocks:
            raise ValueError
        u = data["usage"]
        total, output = u["input_tokens"], u["output_tokens"]
        details = u["input_tokens_details"]
        if not isinstance(details, dict):
            raise ValueError
        cached, written = details["cached_tokens"], details["cache_write_tokens"]
        if (
            any(type(v) is not int or v < 0 for v in (total, output, cached, written))
            or cached + written > total
        ):
            raise ValueError
        usage = {
            "input_tokens": total - cached - written,
            "output_tokens": output,
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": written,
            "service_tier": data.get("service_tier"),
        }
        usage_cost(MODEL, usage)
        return SimpleNamespace(
            model=MODEL, content=blocks, usage=usage, stop_reason="tool_use" if ids else "end_turn"
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BudgetError("OpenAI response incomplete; reservation retained.") from None


class OpenAIVoiceClient:
    def __init__(self, api_key, project, *, http_client=None):
        if not api_key or not project:
            raise BudgetError("Dedicated OpenAI key and project required.")
        self._key, self._project, self._http = api_key, project, http_client
        self.messages = self

    def _request(self, method, path, body=None):
        def dispatch(client):
            return client.request(
                method,
                "https://api.openai.com/v1/" + path,
                json=body,
                headers={"Authorization": "Bearer " + self._key, "OpenAI-Project": self._project},
            )

        try:
            if self._http is not None:
                response = dispatch(self._http)
            else:
                with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
                    response = dispatch(client)
            if response.status_code != 200:
                # No provider body/headers (which may contain credentials) escape.
                error = BudgetError(
                    f"OpenAI voice HTTP {response.status_code}; no automatic retry."
                )
                error.status_code = response.status_code
                raise error
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise BudgetError("OpenAI voice request unconfirmed; reservation retained.") from None

    def ready(self):
        if self._request("GET", "models/" + MODEL).get("id") != MODEL:
            raise BudgetError("OpenAI voice model unavailable.")

    def create(self, **request):
        return decode_response(self._request("POST", "responses", responses_request(request)))
