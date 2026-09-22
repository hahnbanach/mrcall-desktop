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
# Input plus output tokens one request may occupy. This is the smallest
# window among the priced models — exact for Haiku 4.5, Sonnet 4.5 and
# Opus 4.5, and well inside the 1M the Opus 4.6+ and Sonnet 4.6+ families
# serve at standard rates — so it holds whichever of them a caller names.
CONTEXT_WINDOW_TOKENS = 200000
# Payload bytes per input token, and the provider's injected overhead in
# tokens. Both are admission figures; `_context_tokens` states their basis.
ADMISSION_BYTES_PER_TOKEN = 2
ADMISSION_PROTOCOL_TOKENS = 4096
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


def _context_tokens(payload_bytes):
    """Conservative input-token count of a payload, for admission only.

    Admission and pricing measure different things and must not share one
    number. The hold prices one token per payload byte, a figure no
    tokenizer can exceed; read as a token count the same figure is about
    three times the truth and refuses questions that fit the window.

    The divisor is the densest bytes-per-token ratio measured against
    Anthropic's own reported usage on the support@mrcall.ai grounding
    corpus — JSON tool results, UUIDs and Italian mail — which is 2.40: a
    prompt of about 106,000 characters came back counted as 44,134 input
    tokens. Two keeps a margin under it. Being wrong here costs no money:
    an admitted request that still overflows is refused by the provider
    before it is billed, while the reservation below stays byte-based.
    Evidence: `~/hb/docs/briefs/2026-09-22-support-operator-open-defects.md`.

    The flat allowance covers the wrappers and the tool-use preamble the
    provider injects, which the payload does not carry.
    """
    return -(-payload_bytes // ADMISSION_BYTES_PER_TOKEN) + ADMISSION_PROTOCOL_TOKENS


def request_bound(request, transport):
    """Return micro-USD hold; bytes + protocol allowance bound text input."""
    if transport == "openrouter":
        from .openrouter_pricing import request_bound as router_bound

        return router_bound(request)
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
    if _context_tokens(payload_bytes) + output > CONTEXT_WINDOW_TOKENS:
        raise BudgetError("AI paused: request exceeds the supported 200000-token context window.")
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
    # Anthropic reports the TTL split when cache creation is used. Reserve
    # the worst case, but settle the reported split rather than charging all
    # five-minute writes at the one-hour price. Missing split stays conservative.
    cache_cost = Decimal(counts["cache_creation_input_tokens"]) * i * 2
    split = usage.get("cache_creation")
    if split is not None:
        if not isinstance(split, dict) or set(split) - {
            "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"
        }:
            raise BudgetError("AI paused: invalid cache usage; reservation remains.")
        short = split.get("ephemeral_5m_input_tokens", 0)
        long = split.get("ephemeral_1h_input_tokens", 0)
        if (
            type(short) is not int or type(long) is not int
            or short < 0 or long < 0
            or short + long != counts["cache_creation_input_tokens"]
        ):
            raise BudgetError("AI paused: inconsistent cache usage; reservation remains.")
        cache_cost = Decimal(short) * i * Decimal("1.25") + Decimal(long) * i * 2
    cost = (
        Decimal(counts["input_tokens"]) * i
        + Decimal(counts["output_tokens"]) * o
        + cache_cost
        + Decimal(counts["cache_read_input_tokens"]) * Decimal(str(i)) / 10
    )
    return int(cost.to_integral_value(rounding=ROUND_CEILING)), counts


def validate_response_model(requested, returned):
    """Only the admitted model or a vetted same-price snapshot can settle."""
    snapshots = {
        "claude-haiku-4-5": "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5": "claude-sonnet-4-5-20250929",
        "claude-opus-4-5": "claude-opus-4-5-20251101",
    }
    if returned != requested and returned != snapshots.get(requested, requested):
        raise BudgetError("AI paused: response model differs from the authorized model; reservation retained.")
