"""Bounded OpenRouter Messages pricing: the snapshot's price × the margin, read at call time.

Rate sources: the model snapshot (`roles/prices.py` over `roles/catalogue.py`,
read at each call; built from https://openrouter.ai/api/v1/models and each
model's endpoint list) and the routing preferences of
https://openrouter.ai/docs/guides/routing/provider-selection .
Rates are USD per million tokens; provider caps enforce the catalog ceiling.

A request is reserved, and capped at the provider (`max_price`), at its
model's rate × the margin (`requirements.json`, brief D5; `capped`): a
premium endpoint above that is never routed to, and every endpoint the
snapshot admitted fits under it. `RATES` holds the rate before the margin:
the snapshot's price (a model's reference price: the lower-median eligible
endpoint's, or the model-level catalogue price when its endpoints were not
read or none is eligible), and for K3 its pinned endpoint's price
(`k3_reasoning.rates`). The provider policy also forbids fallbacks,
requires the request's parameters, sorts by price, admits only the
quantizations of `requirements.json` and, for a model whose endpoints the
snapshot read, routes only to the endpoints it admitted (`provider.only`): a
discounted `flex` service tier, which price sorting would otherwise always
pick, is never among them. The snapshot lists admitted endpoints only, so
`provider.ignore` could not name the excluded ones; the billing server
builds the same object for the same model and snapshot. Settlement stays on
the provider's `usage.cost`.
"""

import json
from collections.abc import Iterator, Mapping, MutableMapping
from decimal import ROUND_CEILING, Decimal

from .budget_pricing import PRICES, BudgetError, micro_usd
from .budget_pricing import request_bound as validate_direct
from .roles import label
from .roles.catalogue import endpoint_tags
from .roles.prices import margin, price, priced, quantizations

Rate = tuple[Decimal, Decimal]


def rate(model: object) -> Rate | None:
    """``(input, output)`` per million tokens a request for `model` is capped
    and reserved from, before the margin, or None when it is unpriced: the
    price source's OpenRouter price; for K3, its pinned endpoint's price."""
    from .k3_reasoning import MODEL as K3
    from .k3_reasoning import rates as k3_rates

    return k3_rates() if model == K3 else price(model, "openrouter")


class Rates(MutableMapping):
    """``{model: (input, output)}`` per million tokens, before the margin, that
    OpenRouter requests are reserved and capped from (`rate`), read at each
    lookup.

    A rate set here (``RATES[model] = rate``) replaces the computed one for
    this process, for the reservation and `max_price` alike, each still × the
    margin (`capped`): the seam reviewed evaluation runs use
    (`scripts/evaluate_model_quality.py` sets a reviewed provider's rate in
    place). Iteration lists the ids set here, then every id the price source
    prices on OpenRouter."""

    def __init__(self):
        self._set: dict[str, Rate] = {}

    def __getitem__(self, model: object) -> Rate:
        if isinstance(model, str) and model in self._set:
            return self._set[model]
        found = rate(model)
        if found is None:
            raise KeyError(model)
        return found

    def __setitem__(self, model: str, rate: Rate) -> None:
        self._set[model] = rate

    def __delitem__(self, model: str) -> None:
        del self._set[model]

    def __iter__(self) -> Iterator[str]:
        return iter(dict.fromkeys([*self._set, *priced("openrouter")]))

    def __len__(self) -> int:
        return sum(1 for _ in self)


class Labels(Mapping):
    """``{model: label}`` for every model `RATES` holds, read at each lookup."""

    def __getitem__(self, model: object) -> str:
        if model not in RATES:
            raise KeyError(model)
        return label(model)

    def __iter__(self) -> Iterator[str]:
        return iter(RATES)

    def __len__(self) -> int:
        return len(RATES)


# Rates and labels are read from the price source (`roles/prices.py`) when
# asked, never frozen at import, so a snapshot layer installed later (the
# run-time distribution's download) reaches every request. RATES stays a
# mutable mapping because reviewed evaluation runs override a rate in place.
RATES = Rates()
LABELS = Labels()


def capped(model: str) -> Rate:
    """``(input, output)`` per million tokens a request for `model` is reserved
    and capped at (`max_price`): its `RATES` rate × the margin."""
    i, o = RATES[model]
    factor = margin()
    return i * factor, o * factor


def price_text(value: Decimal) -> str:
    """A price as the contract writes one: no exponent, no trailing fractional zero."""
    return format(value.normalize(), "f")


def request_bound(request):
    if request.get("model") == "moonshotai/kimi-k3" and (
        "thinking" in request or "output_config" in request
    ):
        from .k3_reasoning import request_bound as reasoning_bound

        return reasoning_bound(request)
    model = request.get("model")
    if model not in RATES:
        raise BudgetError("AI paused: OpenRouter model has no verified price ceiling.")
    # Reuse the central text/function feature validation, never its model price.
    validate_direct({**request, "model": next(iter(PRICES))}, "direct")
    payload = len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode())
    tokens = payload + 4096 + 1024 * (len(request["messages"]) + len(request.get("tools") or []))
    if tokens + request["max_tokens"] > 200000:
        raise BudgetError("AI paused: OpenRouter request exceeds the supported context bound.")
    i, o = capped(model)
    # Anthropic cache writes may be introduced upstream even after dropping
    # caller cache hints. Reserve the documented one-hour write ceiling (2x).
    if model.startswith("anthropic/"):
        i *= 2
    return int((tokens * i + request["max_tokens"] * o).to_integral_value(rounding=ROUND_CEILING))


def provider_policy(model):
    """The OpenRouter `provider` object of a request for `model` (module docstring)."""
    if model not in RATES:
        raise BudgetError("AI paused: OpenRouter model has no verified price ceiling.")
    i, o = capped(model)
    policy = {
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "price",
        "quantizations": quantizations(),
        "max_price": {"prompt": price_text(i), "completion": price_text(o), "request": "0"},
    }
    admitted = endpoint_tags(model)
    if admitted:
        policy["only"] = admitted
    return policy


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
