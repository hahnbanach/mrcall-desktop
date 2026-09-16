"""Opt-in, evaluation-only K3 thinking transport; never imported by production.

The reviewed experiment runner must explicitly install ``pricing_override`` and
replace its client's transport. The context manager restores original pricing.
Malformed content with a valid receipt remains a recorded model response so
settlement runs; absent receipts retain the hold. HTTP archival is the runner's responsibility. No retries, fallbacks, or semantic repairs.
"""

import json
from contextlib import contextmanager
from copy import deepcopy
from decimal import ROUND_CEILING, Decimal
from types import SimpleNamespace

import httpx
from zylch.llm import openrouter_pricing as pricing
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.openrouter_client import OpenRouterClient, _without_cache

MODEL = "moonshotai/kimi-k3"
BASE_REQUEST_BOUND = pricing.request_bound
CAPS = (2048, 4096, 8192)


def validated_controls(request):
    """Accept only the two preregistered arms, with no implicit effort default."""
    if request.get("model") != MODEL:
        raise BudgetError("Reasoning experiment supports only the exact K3 model.")
    if type(request.get("max_tokens")) is not int or request["max_tokens"] not in CAPS:
        raise BudgetError("Unsupported reasoning experiment output cap.")
    thinking = request.get("thinking")
    output = request.get("output_config")
    if thinking == {"type": "disabled"} and "output_config" not in request:
        return {"thinking": deepcopy(thinking)}
    if thinking == {"type": "adaptive"} and output == {"effort": "max"}:
        return {"thinking": deepcopy(thinking), "output_config": deepcopy(output)}
    raise BudgetError("Use disabled without effort, or adaptive with exact max effort.")


def bound_with_reasoning(request):
    """Reserve the full combined output cap plus conservative control input bytes."""
    controls = validated_controls(request)
    plain = {k: v for k, v in request.items() if k not in controls}
    bound = BASE_REQUEST_BOUND(plain)
    control_bytes = len(json.dumps(controls, ensure_ascii=False, allow_nan=False).encode())
    # Base pricing budgets one token per payload byte. Preserve its 200k ceiling
    # including the additional controls rather than silently extending context.
    payload_bytes = len(json.dumps(plain, ensure_ascii=False, allow_nan=False).encode())
    context = payload_bytes + 4096 + 1024 * (len(plain["messages"]) + len(plain.get("tools") or []))
    if context + control_bytes + plain["max_tokens"] > 200000:
        raise BudgetError("Reasoning experiment exceeds supported context bound.")
    surcharge = (control_bytes * pricing.RATES[MODEL][0]).to_integral_value(rounding=ROUND_CEILING)
    return bound + int(surcharge)


@contextmanager
def pricing_override(*, reviewed_experiment=False, protocol="messages-v1"):
    """Process-local opt-in; caller must keep the context alive through all workers."""
    if reviewed_experiment is not True:
        raise BudgetError("Explicit reviewed reasoning experiment opt-in required.")
    wrappers = {"messages-v1": bound_with_reasoning, "chat-completions-v1": bound_chat_reasoning}
    if protocol not in wrappers:
        raise BudgetError("Unknown reasoning experiment protocol.")
    original = pricing.request_bound
    if original is not BASE_REQUEST_BOUND:
        raise BudgetError("Reasoning pricing wrapper cannot nest or replace another wrapper.")
    pricing.request_bound = wrappers[protocol]
    try:
        yield
    finally:
        pricing.request_bound = original


def decode_response(response, expected_model=MODEL):
    """Preserve thinking provenance separately; expose only validated final blocks."""
    exact = response.json(parse_float=Decimal)
    data = response.json()
    if not isinstance(data, dict) or data.get("model") != expected_model or expected_model != MODEL:
        raise BudgetError("Reasoning response model mismatch; reservation retained.")
    usage = data.get("usage")
    if isinstance(usage, dict) and isinstance(exact.get("usage"), dict):
        cost = exact["usage"].get("cost")
        if isinstance(cost, Decimal):
            usage["cost"] = str(cost)
    pricing.usage_cost(MODEL, usage)
    validation_error = None
    try:
        if data.get("refusal"):
            raise BudgetError("Refused response cannot be consumed.")
        final, thinking = _validated_blocks(data.get("content"))
    except BudgetError as exc:
        final, thinking = [], []
        validation_error = str(exc)
    return SimpleNamespace(
        content=final,
        raw_content=deepcopy(data.get("content")),
        validation_error=validation_error,
        thinking_content=thinking,
        usage=usage,
        stop_reason=data.get("stop_reason"),
        original_stop_reason=data.get("stop_reason"),
        model=data["model"],
        id=data.get("id"),
        provider=data.get("provider"),
        refusal=data.get("refusal"),
        openrouter_metadata=data.get("openrouter_metadata"),
    )


def _validated_blocks(content):
    final, thinking = [], []
    if not isinstance(content, list):
        raise BudgetError("Malformed reasoning response content.")
    for block in content:
        if not isinstance(block, dict):
            raise BudgetError("Malformed reasoning block.")
        if block.get("refusal"):
            raise BudgetError("Refused reasoning block cannot be consumed.")
        kind = block.get("type")
        valid = False
        if kind == "text":
            valid = isinstance(block.get("text"), str)
        elif kind == "tool_use":
            valid = all(
                isinstance(block.get(k), str) and block[k].strip() for k in ("id", "name")
            ) and isinstance(block.get("input"), dict)
        elif kind == "thinking":
            valid = isinstance(block.get("thinking"), str) and (
                "signature" not in block or isinstance(block["signature"], str)
            )
        elif kind == "redacted_thinking":
            valid = isinstance(block.get("data"), str) and bool(block["data"])
        if not valid:
            raise BudgetError("Unsupported/malformed reasoning block.")
        if kind in ("thinking", "redacted_thinking"):
            thinking.append(deepcopy(block))
        else:
            final.append(SimpleNamespace(**block))
    return final, thinking


class ReasoningEvaluationClient(OpenRouterClient):
    """Same injection interface as OpenRouterClient, restricted to this experiment."""

    def create(self, **request):
        bound_with_reasoning(request)
        body = _without_cache(deepcopy(request))
        body.pop("service_tier", None)
        body.update(provider=pricing.provider_policy(MODEL), stream=False)

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
            raise BudgetError(f"Reasoning request failed (HTTP {response.status_code}); no retry.")
        return decode_response(response)


SYSTEM_SEPARATOR = "\n\n"


def chat_request(request):
    """Translate only reviewed text/function requests; join system blocks in order.

    The delimiter is exactly two newlines. User text blocks keep their original
    order and representation. No role, instruction, schema, or text is invented.
    """
    validated_controls(request)
    allowed = {
        "model",
        "messages",
        "system",
        "tools",
        "tool_choice",
        "max_tokens",
        "temperature",
        "service_tier",
        "thinking",
        "output_config",
    }
    if set(request) - allowed:
        raise BudgetError("Untranslated Chat request options.")
    source = _without_cache(request)
    messages = []
    system = source.get("system")
    if system is not None:
        if isinstance(system, str):
            text = system
        elif isinstance(system, list) and all(
            isinstance(b, dict)
            and set(b) == {"type", "text"}
            and b["type"] == "text"
            and isinstance(b["text"], str)
            for b in system
        ):
            text = SYSTEM_SEPARATOR.join(b["text"] for b in system)
        else:
            raise BudgetError("Chat experiment supports text system blocks only.")
        messages.append({"role": "system", "content": text})
    for message in source.get("messages", []):
        if set(message) != {"role", "content"} or message["role"] not in ("user", "assistant"):
            raise BudgetError("Unsupported Chat message shape/role.")
        content = message["content"]
        if not isinstance(content, str) and not (
            isinstance(content, list)
            and all(
                isinstance(b, dict)
                and set(b) == {"type", "text"}
                and b["type"] == "text"
                and isinstance(b["text"], str)
                for b in content
            )
        ):
            raise BudgetError("Chat experiment supports text messages only.")
        messages.append(deepcopy(message))
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": source["max_tokens"],
        "temperature": source.get("temperature", 1),
        "stream": False,
        "provider": pricing.provider_policy(MODEL),
        "reasoning": {"enabled": False}
        if source["thinking"]["type"] == "disabled"
        else {"effort": "max"},
    }
    if source.get("tools"):
        translated = []
        for tool in source["tools"]:
            if set(tool) - {"name", "description", "input_schema"} or not {
                "name",
                "input_schema",
            }.issubset(tool):
                raise BudgetError("Untranslated tool fields.")
            function = {"name": tool["name"], "parameters": deepcopy(tool["input_schema"])}
            if "description" in tool:
                function["description"] = tool["description"]
            translated.append({"type": "function", "function": function})
        body["tools"] = translated
    if source.get("tool_choice"):
        choice = source["tool_choice"]
        if (
            set(choice) != {"type", "name"}
            or choice["type"] != "tool"
            or choice["name"] not in {t["function"]["name"] for t in body.get("tools", [])}
        ):
            raise BudgetError("Chat experiment requires a named captured tool choice.")
        body["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    return body


def bound_chat_reasoning(request):
    base = bound_with_reasoning(request)
    wire = chat_request(request)
    tokens = (
        len(json.dumps(wire, ensure_ascii=False, allow_nan=False).encode())
        + 4096
        + 1024 * (len(wire["messages"]) + len(wire.get("tools", [])))
    )
    if tokens + wire["max_tokens"] > 200000:
        raise BudgetError("Translated Chat request exceeds context bound.")
    i, o = pricing.RATES[MODEL]
    translated = int(
        (tokens * i + wire["max_tokens"] * o).to_integral_value(rounding=ROUND_CEILING)
    )
    return max(base, translated)


def decode_chat_response(response):
    """Normalize wire syntax only; malformed final output cannot become an action."""
    exact, data = response.json(parse_float=Decimal), response.json()
    if not isinstance(data, dict) or data.get("model") != MODEL:
        raise BudgetError("Chat response model mismatch; reservation retained.")
    raw_usage = data.get("usage")
    if not isinstance(raw_usage, dict):
        raise BudgetError("Chat response usage absent; reservation retained.")
    prompt_details = raw_usage.get("prompt_tokens_details") or {}
    completion_details = raw_usage.get("completion_tokens_details") or {}
    if not isinstance(prompt_details, dict) or not isinstance(completion_details, dict):
        raise BudgetError("Invalid Chat token details; reservation retained.")
    cached = prompt_details.get("cached_tokens", 0)
    reasoning = completion_details.get("reasoning_tokens", 0)
    if any(type(v) is not int or v < 0 for v in (cached, reasoning)):
        raise BudgetError("Invalid Chat reasoning/cache counts; reservation retained.")
    cost = exact.get("usage", {}).get("cost")
    usage = {
        **deepcopy(raw_usage),
        "input_tokens": raw_usage.get("prompt_tokens"),
        "output_tokens": raw_usage.get("completion_tokens"),
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
        "output_tokens_details": {"thinking_tokens": reasoning},
        "cost": str(cost) if isinstance(cost, Decimal) else cost,
    }
    pricing.usage_cost(MODEL, usage)
    if cached > usage["input_tokens"] or reasoning > usage["output_tokens"]:
        raise BudgetError("Inconsistent Chat token counts; reservation retained.")
    final, validation_error, finish, message = [], None, None, {}
    try:
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise BudgetError("Expected exactly one Chat choice.")
        choice = choices[0]
        finish, message = choice.get("finish_reason"), choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise BudgetError("Invalid Chat assistant message.")
        if data.get("refusal") or message.get("refusal"):
            raise BudgetError("Refused Chat response cannot be consumed.")
        text = message.get("content")
        if text is not None:
            if not isinstance(text, str):
                raise BudgetError("Unsupported Chat final content.")
            final.append(SimpleNamespace(type="text", text=text))
        calls = message.get("tool_calls", [])
        if not isinstance(calls, list):
            raise BudgetError("Invalid Chat tool calls.")
        for call in calls:
            if not isinstance(call, dict) or call.get("type") != "function":
                raise BudgetError("Unsupported Chat tool call.")
            function = call.get("function")
            if not isinstance(function, dict) or not all(
                isinstance(v, str) and v.strip() for v in (call.get("id"), function.get("name"))
            ):
                raise BudgetError("Malformed Chat function identity.")
            arguments = function.get("arguments")
            if not isinstance(arguments, str):
                raise BudgetError("Chat arguments must be serialized JSON.")
            try:
                arguments = json.loads(
                    arguments,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")),
                )
            except (ValueError, TypeError) as exc:
                raise BudgetError("Invalid Chat function JSON.") from exc
            if not isinstance(arguments, dict):
                raise BudgetError("Chat function arguments must be an object.")
            final.append(
                SimpleNamespace(
                    type="tool_use", id=call["id"], name=function["name"], input=arguments
                )
            )
    except BudgetError as exc:
        final, validation_error = [], str(exc)
    stop = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}.get(
        finish, "unsupported_chat_finish"
    )
    return SimpleNamespace(
        content=final,
        usage=usage,
        stop_reason=stop,
        original_stop_reason=finish,
        validation_error=validation_error,
        model=MODEL,
        id=data.get("id"),
        raw_content=deepcopy(message),
        raw_chat_response=deepcopy(data),
        raw_wire_json=response.text,
        thinking_content={
            k: deepcopy(message[k])
            for k in ("reasoning", "reasoning_details")
            if isinstance(message, dict) and k in message
        },
        refusal=data.get("refusal")
        or (message.get("refusal") if isinstance(message, dict) else None),
        provider=data.get("provider"),
        openrouter_metadata=data.get("openrouter_metadata"),
    )


class ChatReasoningEvaluationClient(OpenRouterClient):
    """Evaluation-only Chat protocol shared by disabled and max-effort arms."""

    def create(self, **request):
        bound_chat_reasoning(request)
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
            with httpx.Client(timeout=180, follow_redirects=False) as client:
                response = dispatch(client)
        if response.status_code != 200:
            raise BudgetError(
                f"Chat reasoning request failed (HTTP {response.status_code}); no retry."
            )
        return decode_chat_response(response)
