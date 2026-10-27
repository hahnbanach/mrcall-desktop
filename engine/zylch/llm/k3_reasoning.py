"""Production K3 max-effort Chat wire adapter; no inference retries or repair."""

import json
from copy import deepcopy
from decimal import ROUND_CEILING, Decimal
from types import SimpleNamespace

from . import openrouter_pricing as pricing
from .budget_pricing import BudgetError

MODEL = "moonshotai/kimi-k3"
OUTPUT_CAP = 8192


def validate_controls(request):
    temperature = request.get("temperature", 1)
    if type(temperature) not in (int, float) or temperature != 1:
        raise BudgetError("K3 max reasoning requires default temperature 1.")
    if request.get("model") != MODEL:
        raise BudgetError("K3 reasoning controls require the exact K3 model.")
    if request.get("thinking") != {"type": "adaptive"} or request.get("output_config") != {
        "effort": "max"
    }:
        raise BudgetError("K3 supports only explicit adaptive/max reasoning.")
    if type(request.get("max_tokens")) is not int or not 1 <= request["max_tokens"] <= OUTPUT_CAP:
        raise BudgetError("K3 reasoning requires an output cap within 8192 tokens.")


def provider_policy():
    policy = pricing.provider_policy(MODEL)
    policy["only"] = ["digitalocean"]
    return policy


def request_bound(request):
    validate_controls(request)
    plain = {k: v for k, v in request.items() if k not in ("thinking", "output_config")}
    original = pricing.request_bound(plain)
    wire = chat_request(request)
    tokens = (
        len(json.dumps(wire, ensure_ascii=False, allow_nan=False).encode())
        + 4096
        + 1024 * (len(wire["messages"]) + len(wire.get("tools", [])))
    )
    if tokens + wire["max_tokens"] > 200000:
        raise BudgetError("K3 Chat request exceeds supported context bound.")
    i, o = pricing.RATES[MODEL]
    return max(
        original,
        int((tokens * i + wire["max_tokens"] * o).to_integral_value(rounding=ROUND_CEILING)),
    )


def _without_cache(request):
    from .openrouter_client import _without_cache as strip

    return strip(request)


SYSTEM_SEPARATOR = "\n\n"


def chat_request(request):
    """Translate only reviewed text/function requests; join system blocks in order.

    The delimiter is exactly two newlines. User text blocks keep their original
    order and representation. No role, instruction, schema, or text is invented.
    """
    validate_controls(request)
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
            raise BudgetError("K3 Chat supports text system blocks only.")
        messages.append({"role": "system", "content": text})
    from .k3_history import translate_messages

    messages.extend(translate_messages(source.get("messages", [])))
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": source["max_tokens"],
        "temperature": source.get("temperature", 1),
        "stream": False,
        "provider": provider_policy(),
        "reasoning": {"effort": "max"},
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
        if choice in ({"type": "auto"}, {"type": "any"}, {"type": "none"}):
            body["tool_choice"] = {"auto": "auto", "any": "required", "none": "none"}[
                choice["type"]
            ]
        elif (
            isinstance(choice, dict)
            and set(choice) == {"type", "name"}
            and choice["type"] == "tool"
            and choice["name"] in {t["function"]["name"] for t in body.get("tools", [])}
        ):
            body["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
        else:
            raise BudgetError("Unsupported K3 tool choice.")
    return body


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
    if finish not in ("stop", "tool_calls"):
        final = []  # Incomplete/unknown completion cannot produce an action.
    return SimpleNamespace(
        content=final,
        usage=usage,
        stop_reason="invalid_response" if validation_error else stop,
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
