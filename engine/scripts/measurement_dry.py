"""The scripted transport of ``measure_roles.py --dry-run`` and of its tests: no network.

It stands where ``httpx`` stands inside the engine's ``OpenRouterClient``
(``client._client._http``), so everything above the wire runs for real: the
one request shape, the engine's reservation, the provider policy, K3's Chat
adapter and its response decoding, the ledger guard. Each dispatch is
answered by an ``answerer(cell, body)`` returning ``{"text", "tool": (name,
input) | None, "stop": "end_turn" | "tool_use" | "max_tokens"}``; the
scripted HTTP turns it into OpenRouter's Messages response, or into a Chat
Completions response for K3, with a receipt (``usage.cost``) priced from the
snapshot at four bytes per input token and the scripted output tokens.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Callable

import httpx

OUTPUT_TOKENS = 64


def placeholder(schema: Any) -> Any:
    """A minimal value that satisfies ``schema`` (required properties only)."""
    if not isinstance(schema, dict):
        return None
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    kind = next((k for k in kind if k != "null"), "null") if isinstance(kind, list) else kind
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        return {key: placeholder(properties.get(key)) for key in schema.get("required") or []}
    return {"array": [], "string": "dry run", "boolean": False, "integer": 0, "number": 0}.get(kind)


def _tools(body: dict) -> list[tuple[str, dict]]:
    out = []
    for tool in body.get("tools") or []:
        function = tool.get("function") if tool.get("type") == "function" else None
        if function:
            out.append((function["name"], function.get("parameters") or {}))
        else:
            out.append((tool["name"], tool.get("input_schema") or {}))
    return out


def continuing(body: dict) -> bool:
    """Whether the request answers a tool result (the turn goes on after a call)."""
    last = (body.get("messages") or [{}])[-1]
    if last.get("role") == "tool":
        return True
    content = last.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def default_answer(cell: Any, body: dict) -> dict:
    """The dry run's answer: the first tool with a minimal valid input, text after a result."""
    tools = _tools(body)
    if tools and not continuing(body):
        name, schema = tools[0]
        return {"text": None, "tool": (name, placeholder(schema)), "stop": "tool_use"}
    return {
        "text": "Risposta di prova del dry run, nessuna rete.",
        "tool": None,
        "stop": "end_turn",
    }


def _cost(model: str, body: dict, output_tokens: int) -> tuple[int, str]:
    from zylch.llm.roles import catalogue

    input_tokens = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) // 4
    rates = catalogue.rates(model, "openrouter") or (Decimal("1"), Decimal("1"))
    cost = (input_tokens * rates[0] + output_tokens * rates[1]) / Decimal(1_000_000)
    return input_tokens, format(cost.quantize(Decimal("0.000000001")), "f")


def messages_payload(body: dict, scripted: dict) -> dict:
    content = []
    if scripted.get("text") is not None:
        content.append({"type": "text", "text": scripted["text"]})
    if scripted.get("tool"):
        name, given = scripted["tool"]
        content.append({"type": "tool_use", "id": "toolu_dry_1", "name": name, "input": given})
    output = scripted.get("output_tokens", OUTPUT_TOKENS)
    input_tokens, cost = _cost(body["model"], body, output)
    return {
        "id": "msg_dry",
        "type": "message",
        "role": "assistant",
        "model": scripted.get("model", body["model"]),
        "content": content,
        "stop_reason": scripted.get("stop", "end_turn"),
        "usage": {"input_tokens": input_tokens, "output_tokens": output, "cost": cost},
    }


def chat_payload(body: dict, scripted: dict) -> dict:
    """K3's Chat Completions response (``k3_reasoning.decode_chat_response`` reads it)."""
    message: dict[str, Any] = {"role": "assistant", "content": scripted.get("text")}
    if scripted.get("tool"):
        name, given = scripted["tool"]
        message["tool_calls"] = [
            {
                "id": "call_dry_1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(given)},
            }
        ]
    finish = {"tool_use": "tool_calls", "max_tokens": "length"}.get(scripted.get("stop"), "stop")
    output = scripted.get("output_tokens", OUTPUT_TOKENS)
    input_tokens, cost = _cost(body["model"], body, output)
    return {
        "id": "gen_dry",
        "model": body["model"],
        "choices": [{"finish_reason": finish, "message": message}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output,
            "cost": cost,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": output // 2},
        },
    }


class ScriptedHTTP:
    """``post(url, json=, headers=)`` answering from the script; records every body."""

    def __init__(self, cell: Any, answerer: Callable[[Any, dict], dict]):
        self.cell, self.answerer, self.bodies = cell, answerer, []

    def post(self, url: str, *, json: dict, headers: dict):  # noqa: A002 - httpx's name
        self.bodies.append(json)
        scripted = self.answerer(self.cell, json)
        if scripted.get("status"):
            return httpx.Response(scripted["status"], json={"error": "scripted"})
        chat = url.endswith("/chat/completions")
        payload = chat_payload(json, scripted) if chat else messages_payload(json, scripted)
        return httpx.Response(200, json=payload)


def scripted_http(answerer: Callable[[Any, dict], dict]) -> Callable[[Any], ScriptedHTTP]:
    """A per-cell factory of scripted transports (``Context.http``)."""
    return lambda cell: ScriptedHTTP(cell, answerer)
