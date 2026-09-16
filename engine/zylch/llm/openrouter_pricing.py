"""Bounded OpenRouter Messages pricing, checked 2026-09-13.

Sources: https://openrouter.ai/api/v1/models and
https://openrouter.ai/docs/guides/routing/provider-selection .
Rates are USD per million tokens; provider caps enforce the catalog ceiling.
"""

import json
from decimal import ROUND_CEILING, Decimal

from .budget_pricing import BudgetError, micro_usd
from .budget_pricing import request_bound as validate_direct

MODEL = "z-ai/glm-5.2"
RATES = {
    MODEL: (Decimal("0.6"), Decimal("2")),
    "moonshotai/kimi-k3": (Decimal("2.648138063"), Decimal("13.28272425")),
    "anthropic/claude-opus-5": (Decimal("5"), Decimal("25")),
    "anthropic/claude-sonnet-5": (Decimal("2"), Decimal("10")),
    "anthropic/claude-haiku-4.5": (Decimal("1"), Decimal("5")),
}
LABELS = {
    MODEL: "GLM 5.2",
    "moonshotai/kimi-k3": "Kimi K3",
    "anthropic/claude-opus-5": "Claude Opus 5",
    "anthropic/claude-sonnet-5": "Claude Sonnet 5",
    "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
}


def request_bound(request):
    if request.get("model") == "moonshotai/kimi-k3" and ("thinking" in request or "output_config" in request):
        from .k3_reasoning import request_bound as reasoning_bound
        return reasoning_bound(request)
    model = request.get("model")
    if model not in RATES:
        raise BudgetError("AI paused: OpenRouter model has no verified price ceiling.")
    if model == "anthropic/claude-sonnet-5":
        temperature = request.get("temperature", 1)
        if (type(temperature) not in (int, float) or temperature != 1
                or "top_p" in request or "top_k" in request):
            raise BudgetError("AI paused: OpenRouter Sonnet 5 supports only default sampling (temperature 1, no top_p/top_k).")
    # Reuse the central text/function feature validation, never its model price.
    validate_direct({**request, "model": "claude-haiku-4-5"}, "direct")
    payload = len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode())
    tokens = payload + 4096 + 1024 * (len(request["messages"]) + len(request.get("tools") or []))
    if tokens + request["max_tokens"] > 200000:
        raise BudgetError("AI paused: OpenRouter request exceeds the supported context bound.")
    i, o = RATES[model]
    # Anthropic cache writes may be introduced upstream even after dropping
    # caller cache hints. Reserve the documented one-hour write ceiling (2x).
    if model.startswith("anthropic/"):
        i *= 2
    return int((tokens * i + request["max_tokens"] * o).to_integral_value(rounding=ROUND_CEILING))


def provider_policy(model):
    if model not in RATES:
        raise BudgetError("AI paused: OpenRouter model has no verified price ceiling.")
    i, o = RATES[model]
    return {
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "price",
        "max_price": {"prompt": str(i), "completion": str(o), "request": "0"},
    }


def usage_cost(model, usage):
    if model not in RATES or not isinstance(usage, dict) or usage.get("cost") is None:
        raise BudgetError("AI paused: OpenRouter charge receipt missing; reservation retained.")
    if isinstance(usage["cost"], bool):
        raise BudgetError("AI paused: invalid OpenRouter charge receipt.")
    counts = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = usage.get(key, 0 if key.startswith("cache_") else None)
        if key.startswith("cache_") and value is None:
            value = 0
        if type(value) is not int or value < 0:
            raise BudgetError("AI paused: invalid OpenRouter usage; reservation retained.")
        counts[key] = value
    if usage.get("server_tool_use") or usage.get("iterations"):
        raise BudgetError("AI paused: unsupported OpenRouter server work; reservation retained.")
    return micro_usd(usage["cost"]), counts
