"""Explicit prices and conservative admission for supported text Messages calls.

USD per million tokens; verified against Anthropic's pricing page 2026-09-11.
Unknown billing shapes refuse admission. This does not model invoices or taxes.
"""

import json
from decimal import ROUND_CEILING, Decimal


class BudgetError(RuntimeError):
    """Paid work is paused; callers must preserve unfinished work."""


PRICES = {
    "claude-opus-5": (5, 25),
    "claude-opus-4-7": (5, 25),
    "claude-opus-4-6": (5, 25),
    "claude-opus-4-5": (5, 25),
    "claude-opus-4-5-20251101": (5, 25),
    "claude-sonnet-5": (2, 10),
    "claude-sonnet-4-6": (3, 15),
    "claude-sonnet-4-5": (3, 15),
    "claude-sonnet-4-5-20250929": (3, 15),
    "claude-haiku-4-5": (1, 5),
    "claude-haiku-4-5-20251001": (1, 5),
}
_ALLOWED = {
    "model",
    "messages",
    "system",
    "tools",
    "tool_choice",
    "max_tokens",
    "temperature",
    "top_p",
    "top_k",
    "stop_sequences",
    "metadata",
    "service_tier",
}


def micro_usd(value):
    """Round nonnegative finite dollar amounts upward, never down."""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError
        return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    except (ValueError, TypeError, ArithmeticError):
        raise BudgetError("AI paused: invalid budget or recorded cost.") from None


def _content(content):
    if isinstance(content, str):
        return
    if not isinstance(content, list):
        raise BudgetError("AI paused: unsupported request content for cost admission.")
    for block in content:
        if not isinstance(block, dict):
            raise BudgetError("AI paused: unsupported request content for cost admission.")
        kind = block.get("type")
        if kind == "text":
            if set(block) - {"type", "text", "cache_control"} or not isinstance(
                block.get("text"), str
            ):
                raise BudgetError("AI paused: unsupported text block.")
        elif kind == "tool_use":
            if set(block) - {"type", "id", "name", "input", "cache_control"}:
                raise BudgetError("AI paused: unsupported tool call block.")
        elif kind == "tool_result":
            if set(block) - {"type", "tool_use_id", "content", "is_error", "cache_control"}:
                raise BudgetError("AI paused: unsupported tool result block.")
            _content(block.get("content", ""))
        else:
            raise BudgetError("AI paused: multimodal or server-tool costs are not supported.")
        cache = block.get("cache_control")
        if cache is not None and (
            not isinstance(cache, dict)
            or set(cache) - {"type", "ttl"}
            or cache.get("type") != "ephemeral"
            or cache.get("ttl", "5m") not in ("5m", "1h")
        ):
            raise BudgetError("AI paused: unsupported cache pricing.")


def request_bound(request, transport):
    """Return micro-USD hold; bytes + protocol allowance bound text input."""
    if transport != "direct":
        raise BudgetError(
            "AI paused: MrCall credit pricing must include its markup before budgeted calls can resume."
        )
    if set(request) - _ALLOWED:
        raise BudgetError("AI paused: request includes an unpriced option.")
    if request.get("service_tier", "standard_only") != "standard_only":
        raise BudgetError("AI paused: only standard service-tier pricing is supported.")
    model = request.get("model")
    if model not in PRICES:
        raise BudgetError("AI paused: model pricing is not configured for this model.")
    output = request.get("max_tokens")
    if type(output) is not int or not 1 <= output <= 131072:
        raise BudgetError("AI paused: a supported output-token limit is required.")
    _content(request.get("system", ""))
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BudgetError("AI paused: invalid messages for cost admission.")
    for message in messages:
        if not isinstance(message, dict) or set(message) - {"role", "content"}:
            raise BudgetError("AI paused: unsupported message options.")
        _content(message.get("content", ""))
    tools = request.get("tools") or []
    if not isinstance(tools, list):
        raise BudgetError("AI paused: unsupported tools.")
    for tool in tools:
        if (
            not isinstance(tool, dict)
            or set(tool) - {"name", "description", "input_schema", "cache_control", "type"}
            or tool.get("type", "custom") != "custom"
        ):
            raise BudgetError("AI paused: server-tool costs require an explicit bound.")
        if "cache_control" in tool:
            _content([{"type": "text", "text": "", "cache_control": tool["cache_control"]}])
    try:
        # UTF-8 bytes conservatively cover text tokens; per-message/tool
        # protocol allowance includes provider-injected wrappers/tool prompts.
        payload_bytes = len(
            json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
        )
    except (TypeError, ValueError):
        raise BudgetError("AI paused: request cannot be priced safely.") from None
    input_bound = payload_bytes + 4096 + 1024 * (len(messages) + len(tools))
    if input_bound + output > 200000:
        raise BudgetError("AI paused: request exceeds the supported 200000-token cost bound.")
    in_rate, out_rate = PRICES[model]
    # All input at one-hour cache-write rate: no assumed cache hit savings.
    return input_bound * in_rate * 2 + output * out_rate


def usage_cost(model, usage):
    """Conservative settled micro-USD; absent/invalid usage retains the hold."""
    if model not in PRICES or not isinstance(usage, dict):
        raise BudgetError("AI paused: response usage cannot be reconciled.")
    if usage.get("service_tier") not in (None, "standard"):
        raise BudgetError(
            "AI paused: unexpected service-tier usage; its budget reservation remains."
        )
    for key in ("input_tokens", "output_tokens"):
        if key not in usage:
            raise BudgetError(
                "AI paused: response usage is missing; its budget reservation remains."
            )
    counts = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = usage.get(key, 0)
        if type(value) is not int or value < 0:
            raise BudgetError(
                "AI paused: response usage is invalid; its budget reservation remains."
            )
        counts[key] = value
    if usage.get("server_tool_use"):
        raise BudgetError("AI paused: unexpected paid tool usage; its budget reservation remains.")
    i, o = PRICES[model]
    cost = (
        Decimal(counts["input_tokens"]) * i
        + Decimal(counts["output_tokens"]) * o
        + Decimal(counts["cache_creation_input_tokens"]) * i * 2
        + Decimal(counts["cache_read_input_tokens"]) * Decimal(str(i)) / 10
    )
    return int(cost.to_integral_value(rounding=ROUND_CEILING)), counts
