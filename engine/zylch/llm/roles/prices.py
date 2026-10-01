"""The one price source: USD per million tokens for a model on a transport.

Two inputs, both reviewed and committed beside this module:

- `resolved.json`: every pick the resolver wrote, per preset and role — the
  main pick, its `anthropic_fallback` and its `mrcall` record — at the price
  the table carries. On `direct` a pick is priced under its `direct_id` (only
  Anthropic models have one); on `openrouter` under its `catalogue_id`.
- `requirements.json`'s `allowlist`: every model a `custom` profile may name
  today, on its own transport, at the price it is billed at today.

Where an id is in both, the allowlist's billed price wins. The table's price
is a comparison figure: the resolver ranks at max(billed, catalogue), and a
catalogue price moves with every resolver run. The allowlist is the reviewed
billing contract — what a hosted profile pays today and what the OpenRouter
provider cap (`max_price`) enforces — so a refreshed table can never move the
rate an existing profile is held and capped at. Two table rows naming one id
at different prices keep the higher one, so a hold never under-counts.

An id in neither input has no price; callers refuse it with their own
message. Prices are `Decimal`, read from the JSON text, never from a float.
"""

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

HERE = Path(__file__).resolve().parent
TRANSPORTS = ("direct", "openrouter")
Rate = tuple[Decimal, Decimal]


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"), parse_float=Decimal)


def _rate(price: dict) -> Rate:
    return Decimal(str(price["input"])), Decimal(str(price["output"]))


def _table_rows():
    for preset in _load("resolved.json")["presets"].values():
        for record in preset["roles"].values():
            yield record
            for key in ("anthropic_fallback", "mrcall"):
                if record.get(key):
                    yield record[key]


@lru_cache(maxsize=None)
def priced(transport: str) -> MappingProxyType:
    """Read-only ``{id: (input, output)}`` of every priced id on `transport`."""
    if transport not in TRANSPORTS:
        raise ValueError(f"Unknown priced transport {transport!r}")
    key = "direct_id" if transport == "direct" else "catalogue_id"
    rates: dict[str, Rate] = {}
    for row in _table_rows():
        if row.get(key):
            rate = _rate(row["price"])
            known = rates.get(row[key], rate)
            rates[row[key]] = (max(known[0], rate[0]), max(known[1], rate[1]))
    for model, row in _load("requirements.json").get("allowlist", {}).items():
        if row.get("transport") == transport:
            rates[model] = _rate(row["price"])  # the billed price wins (see above)
    return MappingProxyType(rates)


def price(model: str, transport: str) -> Rate | None:
    """``(input, output)`` per million tokens for `model` on `transport`, or None."""
    return priced(transport).get(model)
