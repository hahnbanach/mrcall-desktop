"""The sources the resolver reads, and the endpoints a request may reach.

OpenRouter publishes three things the resolver joins: the catalogue
(`/models`: prices, context, parameters, reasoning, expiry, aliases), the
benchmarks (`/benchmarks`: the Artificial Analysis indices) and, per model,
its endpoints (`/models/<id>/endpoints`: one per provider and service tier,
each with its own status, quantization, parameters and price). The payload
checks here refuse a source that cannot be read whole (`Refused`), so a
resolution never runs on part of one.

**The endpoint pool** (`endpoint_pool`) is the catalogue entries whose
endpoints are read: tools supported, the minimum context, no excluded
variant (`:free`, `:batch`) and no alias (`~`). Only for them does the
snapshot record admitted endpoints and the endpoint-level parameters.

**Admission of an endpoint** (`admitted`) applies the provider policy of
`requirements.json` (`policy`): the endpoint is up (status 0; the capture
of 2026-10-02 also holds -2 and -5, endpoints whose recent uptime is
degraded); its declared quantization is in the allow-list (an endpoint that
declares none is `unknown`, which the list admits: vendors rarely declare
theirs); it supports tools; no segment of its tag after the provider is an
excluded service tier (`flex`: discounted, slower tiers that price sorting
would always pick and whose latency can exceed the client's timeout); and
its input and output prices are at or under the model-level price × the
margin, the cap OpenRouter's `max_price` enforces, so a premium endpoint
priced above it is never one a request can reach. A model with no
model-level price has no cap and no admitted endpoint.

Pure: no file, network or environment access; prices are `Decimal`, read
from the payloads' decimal strings, never from a float.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation

MILLION = Decimal(10) ** 6
ALIAS = "~"
UP = 0
UNKNOWN = "unknown"


class Refused(Exception):
    """A source could not be read, or the data cannot resolve a role."""


def payload_list(raw: bytes | None, what: str) -> tuple[list, dict]:
    """The `data` list of a payload and the whole document; Refused when the
    payload is absent, not JSON, or has no non-empty `data` list."""
    if raw is None:
        raise Refused(f"cannot read the {what}: no payload")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Refused(f"cannot read the {what}: not JSON") from None
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, list) or not data:
        raise Refused(f"cannot read the {what}: its `data` list is missing or empty")
    return data, doc


def complete_catalogue(doc: dict, data: list) -> None:
    """Refuse a catalogue that is one page of several, or shorter than it says,
    or that lists an id twice."""
    links = doc.get("links") if isinstance(doc.get("links"), dict) else {}
    if links.get("next"):
        raise Refused("the catalogue came in pages (`links.next` is set), and a refresh reads one")
    total = doc.get("total_count")
    if isinstance(total, int) and total != len(data):
        raise Refused(f"the catalogue says it holds {total} entries and lists {len(data)}")
    counts = Counter(entry.get("id") for entry in data if isinstance(entry, dict))
    twice = sorted((model for model, n in counts.items() if n > 1), key=str)
    if twice:
        raise Refused(f"the catalogue lists {', '.join(map(str, twice))} more than once")


def complete_benchmarks(doc: dict, data: list) -> None:
    """Refuse benchmarks that cover fewer models than their `meta` counts."""
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    count = meta.get("model_count")
    listed = len({r.get("model_permaslug") for r in data if isinstance(r, dict)})
    if isinstance(count, int) and count != listed:
        raise Refused(f"the benchmarks say they cover {count} models and list {listed}")


def per_million(value: object) -> Decimal | None:
    """A catalogue price per token as dollars per million, or None when it is
    not a price: missing, unparseable, or negative (the catalogue writes -1 for
    a route whose price varies). The snapshot records every price through it,
    so a variable price is recorded as none, never as a negative one."""
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price < 0:
        return None
    return price * MILLION


def score(value: object) -> int | float | None:
    """A number as the source wrote it, or None when it is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def strings(value: object) -> list[str]:
    """The distinct non-empty strings of a list, in their order; [] for anything else."""
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return out


def is_variant(model: str, common: dict) -> bool:
    """A catalogue id under an excluded variant suffix (`:free`, `:batch`)."""
    return any(model.endswith(variant) for variant in common["excluded_variants"])


def endpoint_pool(catalogue: list, common: dict) -> list[str]:
    """The catalogue ids whose endpoints the resolver reads, in catalogue order:
    tools (when required), the minimum context, no excluded variant, no alias."""
    out = []
    for entry in catalogue:
        model = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(model, str) or not model or model.startswith(ALIAS):
            continue
        if is_variant(model, common):
            continue
        if common["tools"] and "tools" not in strings(entry.get("supported_parameters")):
            continue
        context = score(entry.get("context_length"))
        if context is None or context < common["min_context"]:
            continue
        out.append(model)
    return out


def endpoints_by_model(raw: bytes | None, wanted: list[str]) -> dict[str, list[dict]]:
    """The endpoints payload as `{catalogue id: [endpoint, ...]}` for `wanted`.

    The payload is `{"data": {<catalogue id>: <the data of
    /models/<id>/endpoints>}}`. Refused when it is absent, not JSON, or lacks
    an endpoint list for any id of `wanted`: the pool's endpoints are read
    whole or not at all."""
    if raw is None:
        raise Refused("cannot read the endpoints: no payload")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Refused("cannot read the endpoints: not JSON") from None
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        raise Refused("cannot read the endpoints: its `data` object is missing")
    out, missing = {}, []
    for model in wanted:
        listed = data.get(model, {}).get("endpoints") if isinstance(data.get(model), dict) else None
        if not isinstance(listed, list):
            missing.append(model)
            continue
        out[model] = [endpoint for endpoint in listed if isinstance(endpoint, dict)]
    if missing:
        raise Refused(f"cannot read the endpoints of {', '.join(missing)}")
    return out


def policy(req: dict) -> dict:
    """The provider policy of `requirements.json`: the margin as a Decimal, the
    admitted quantizations and the excluded service tiers."""
    return {
        "margin": Decimal(str(req["margin"])),
        "quantizations": list(req["provider_policy"]["quantizations"]),
        "excluded_endpoint_variants": list(req["excluded_endpoint_variants"]),
    }


def is_excluded_tier(tag: str, variants: list[str]) -> bool:
    """A tag (`provider[/segment...]`) one of whose segments after the provider
    is an excluded service tier: `<provider>/flex` and
    `<provider>/<region>/flex` are both `flex`."""
    return any(segment in variants for segment in tag.split("/")[1:])


def price_cap(entry: dict, margin: Decimal) -> tuple[Decimal, Decimal] | None:
    """The model-level input and output prices × the margin, or None when the
    catalogue gives the model no fixed price."""
    pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
    prices = [per_million(pricing.get(field)) for field in ("prompt", "completion")]
    if None in prices:
        return None
    return prices[0] * margin, prices[1] * margin


def quantization(endpoint: dict) -> str:
    """The endpoint's declared quantization, `unknown` when it declares none."""
    declared = endpoint.get("quantization")
    return declared if isinstance(declared, str) and declared else UNKNOWN


def admitted(entry: dict, endpoints: list[dict], rules: dict) -> list[dict]:
    """The endpoints of `entry` the provider policy `rules` admits (see the
    module docstring), in the order the payload lists them."""
    cap = price_cap(entry, rules["margin"])
    if cap is None:
        return []
    out = []
    for endpoint in endpoints:
        tag, status = endpoint.get("tag"), endpoint.get("status")
        if (
            not isinstance(tag, str)
            or not tag
            or is_excluded_tier(tag, rules["excluded_endpoint_variants"])
        ):
            continue
        if isinstance(status, bool) or status != UP:
            continue
        if quantization(endpoint) not in rules["quantizations"]:
            continue
        if "tools" not in strings(endpoint.get("supported_parameters")):
            continue
        pricing = endpoint.get("pricing") if isinstance(endpoint.get("pricing"), dict) else {}
        prices = [per_million(pricing.get(field)) for field in ("prompt", "completion")]
        if None in prices or prices[0] > cap[0] or prices[1] > cap[1]:
            continue
        out.append(endpoint)
    return out
