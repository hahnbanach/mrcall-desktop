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

**Admission of an endpoint and the reference price** (`anchored`,
`admitted`) apply the provider policy of `requirements.json` (`policy`). An
endpoint is *eligible* (`eligible`) when it is up (status 0; the capture of
2026-10-02 also holds -2 and -5, endpoints whose recent uptime is
degraded); its declared quantization is in the allow-list (an endpoint that
declares none is `unknown`, which the list admits: vendors rarely declare
theirs); it supports tools; no segment of its tag after the provider is an
excluded service tier (`flex`: discounted, slower tiers that price sorting
would always pick and whose latency can exceed the client's timeout); and
it has a fixed input and output price. The model's *reference price*, which
the snapshot publishes as its `pricing` and the preset ceilings compare, is
its model-level price, cache prices included, when at least one eligible
endpoint's input and output prices are at or under it × the margin (`fits`).
The model-level price stays the anchor whenever it admits an endpoint
because it is the list price OpenRouter shows, and a median of the
endpoints flips with the count of regional premiums (Opus 5.5 on
2026-10-02: five endpoints at Anthropic's list price, five regional ones
10% above it). Otherwise — OpenRouter computes the model-level price over
every endpoint, those the policy excludes included, so an fp4 endpoint can
set it below every eligible one (the live read of 2026-10-02 17:24Z left
GLM 5.3 Flash none under it) — the reference price is the *reference
endpoint*'s (`reference`): the lower median, index (n - 1) // 2, of the
eligible endpoints ordered by Artificial Analysis's blended price, (3 ×
input + output) / 4, a tie going by output, then input, then tag; its cache
prices where it publishes them, else the model-level ones. A model-level
price that is not fixed admits nothing, so such a model takes the
reference endpoint's too (the screen never ranks it). An eligible endpoint
is *admitted* when its input and output prices are at or under the
reference price × the margin, the cap OpenRouter's `max_price` enforces, so
a premium endpoint priced above it is never one a request can reach; a
model with an eligible endpoint therefore always admits one. A model with
no eligible endpoint, or whose endpoints were not read, keeps its
model-level price and admits no endpoint.

**The screen** (`screen`, `exclusion`) keeps the catalogue entries any role
may rank, before scores: not a variant, not an alias, no announced
`expiration_date`, not of an excluded family (`family_of`: the vendor and
token matched on the id, on the `canonical_slug` — Haiku's slug puts the
version first — and on an alias's `alias_target.slug`), tools and the
minimum context, a fixed model-level input and output price, and at least
one admitted endpoint. An alias or an entry with an announced expiry stays
priced in the snapshot (an explicit choice keeps running); it is only
never ranked, picked or measured. A kept entry is ranked at its reference
price, and carries its direct id when one of its endpoints is tagged
`anthropic` (the direct transport's), else None.

Pure: no file, network or environment access; prices are `Decimal`, read
from the payloads' decimal strings, never from a float.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation

from .gates import direct_id, excluded_family

MILLION = Decimal(10) ** 6
ALIAS = "~"
UP = 0
UNKNOWN = "unknown"
DIRECT_TAG = "anthropic"
# A price as the snapshot names it, and the payload field it is read from.
PRICE_FIELDS = (
    ("input", "prompt"),
    ("output", "completion"),
    ("cache_read", "input_cache_read"),
    ("cache_write", "input_cache_write"),
)


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
    admitted quantizations and the excluded service tiers; with the excluded
    families, which the snapshot publishes beside them."""
    return {
        "margin": Decimal(str(req["margin"])),
        "quantizations": list(req["provider_policy"]["quantizations"]),
        "excluded_endpoint_variants": list(req["excluded_endpoint_variants"]),
        "excluded_families": [
            {"vendor": family["vendor"], "token": family["token"]}
            for family in req["excluded_families"]
        ],
    }


def is_excluded_tier(tag: str, variants: list[str]) -> bool:
    """A tag (`provider[/segment...]`) one of whose segments after the provider
    is an excluded service tier: `<provider>/flex` and
    `<provider>/<region>/flex` are both `flex`."""
    return any(segment in variants for segment in tag.split("/")[1:])


def prices_of(pricing: object) -> dict[str, Decimal | None]:
    """A catalogue or endpoint `pricing` as the four prices per million
    (`PRICE_FIELDS`), None where it has none (absent, or variable)."""
    pricing = pricing if isinstance(pricing, dict) else {}
    return {name: per_million(pricing.get(field)) for name, field in PRICE_FIELDS}


def model_price(entry: dict) -> tuple[Decimal, Decimal] | None:
    """The model-level input and output prices per million, or None when the
    catalogue gives the model no fixed price."""
    prices = prices_of(entry.get("pricing"))
    if prices["input"] is None or prices["output"] is None:
        return None
    return prices["input"], prices["output"]


def quantization(endpoint: dict) -> str:
    """The endpoint's declared quantization, `unknown` when it declares none."""
    declared = endpoint.get("quantization")
    return declared if isinstance(declared, str) and declared else UNKNOWN


def eligible(endpoints: list[dict], rules: dict) -> list[tuple[dict, dict]]:
    """The endpoints that pass the provider policy `rules` before price (see
    the module docstring), each with its four prices (`prices_of`), in the
    order the payload lists them."""
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
        prices = prices_of(endpoint.get("pricing"))
        if prices["input"] is None or prices["output"] is None:
            continue
        out.append((endpoint, prices))
    return out


def blended(prices: dict) -> Decimal:
    """Artificial Analysis's blended price: three parts input to one part output."""
    return (3 * prices["input"] + prices["output"]) / 4


def reference(rows: list[tuple[dict, dict]]) -> tuple[dict, dict] | None:
    """The reference endpoint of eligible `rows` (`eligible`), whose price
    `anchored` takes when no eligible endpoint fits under the model-level
    price × the margin: the lower median by blended price, a tie by output,
    then input, then tag; None when no endpoint is eligible."""
    if not rows:
        return None
    ordered = sorted(
        rows, key=lambda row: (blended(row[1]), row[1]["output"], row[1]["input"], row[0]["tag"])
    )
    return ordered[(len(ordered) - 1) // 2]


def fits(prices: dict, price: dict, margin: Decimal) -> bool:
    """Whether an endpoint's `prices` are at or under `price` × `margin`,
    input and output; never under a `price` that is not fixed."""
    if price["input"] is None or price["output"] is None:
        return False
    return (
        prices["input"] <= price["input"] * margin and prices["output"] <= price["output"] * margin
    )


def anchored(entry: dict, endpoints: list[dict] | None, rules: dict) -> tuple[dict, list | None]:
    """The model's reference price (the four prices per million, None where
    absent) and its admitted endpoints, in the payload's order (see the
    module docstring): the model-level price when an eligible endpoint fits
    under it × the margin, else the reference endpoint's (`reference`, its
    cache prices where it publishes them, else the model-level ones). With
    no eligible endpoint the price is the model-level one and no endpoint is
    admitted; with its endpoints not read (`endpoints` None) the price is the
    model-level one and the endpoints None."""
    level = prices_of(entry.get("pricing"))
    if endpoints is None:
        return level, None
    rows = eligible(endpoints, rules)
    margin = rules["margin"]
    if any(fits(prices, level, margin) for _, prices in rows):
        price = dict(level)
    else:
        anchor = reference(rows)
        if anchor is None:
            return level, []
        price = dict(anchor[1])
        for side in ("cache_read", "cache_write"):
            if price[side] is None:
                price[side] = level[side]
    return price, [endpoint for endpoint, prices in rows if fits(prices, price, margin)]


def admitted(entry: dict, endpoints: list[dict], rules: dict) -> list[dict]:
    """The endpoints of `entry` the provider policy `rules` admits (see the
    module docstring), in the order the payload lists them."""
    return anchored(entry, endpoints, rules)[1] or []


def family_of(entry: dict, families: list) -> dict | None:
    """The excluded family `entry` belongs to through its id, its
    `canonical_slug` or, for an alias, its target's slug; None when none."""
    target = entry.get("alias_target") if isinstance(entry.get("alias_target"), dict) else {}
    for name in (entry.get("id"), entry.get("canonical_slug"), target.get("slug")):
        family = excluded_family(name, families)
        if family:
            return family
    return None


def exclusion(entry: dict, listed: list[dict] | None, req: dict, rules: dict) -> str | None:
    """Why `entry` can be no candidate, or None when the screen keeps it.

    `listed` is its endpoint list as read (None when its endpoints were not
    read), `rules` the provider policy."""
    model, common = entry.get("id"), req["common"]
    if not isinstance(model, str) or not model:
        return "no id"
    if is_variant(model, common):
        return "a variant"
    if model.startswith(ALIAS):
        return "an alias"
    if entry.get("expiration_date"):
        return f"expires on {entry['expiration_date']}"
    family = family_of(entry, req["excluded_families"])
    if family:
        return f"of the excluded family {family['vendor']} + {family['token']}"
    if common["tools"] and "tools" not in strings(entry.get("supported_parameters")):
        return "no tools"
    context = score(entry.get("context_length"))
    if context is None or context < common["min_context"]:
        return f"a context under {common['min_context']}"
    if model_price(entry) is None:
        return "no fixed price"
    if listed is None:
        return "its endpoints were not read"
    if not admitted(entry, listed, rules):
        return "no admitted endpoint"
    return None


def screen(catalogue: list, endpoints: dict[str, list[dict]], req: dict) -> tuple[list, dict]:
    """The entries the screen keeps, in catalogue order, as `{entry, id,
    price, input_price, direct_id}` (the reference price per million, output
    and input), and `{id: reason}` for every entry it drops."""
    rules = policy(req)
    kept, dropped = [], {}
    for entry in catalogue:
        if not isinstance(entry, dict):
            continue
        listed = endpoints.get(entry.get("id"))
        reason = exclusion(entry, listed, req, rules)
        if reason:
            dropped[str(entry.get("id"))] = reason
            continue
        own = any(endpoint.get("tag") == DIRECT_TAG for endpoint in listed)
        price, _ = anchored(entry, listed, rules)
        kept.append(
            {
                "entry": entry,
                "id": entry["id"],
                "price": price["output"],
                "input_price": price["input"],
                "direct_id": direct_id(entry["id"]) if own else None,
            }
        )
    return kept, dropped
