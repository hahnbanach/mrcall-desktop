"""Build the snapshot (contract schema 1): every catalogue model's price and request metadata.

The snapshot is what consumers price and shape a request from, for any
model a profile names — picked, ranked or saved by hand — so it covers every
catalogue entry, aliases, variants and excluded families included (an
explicit choice keeps running whatever the picks are). Per entry:

- `pricing`: the reference price (input, output, cache read, cache write;
  `candidates.anchored`), USD per million tokens as canonical decimal
  strings (`text`), null where there is none. It is the model-level
  catalogue price — the list price OpenRouter shows — unless the entry is of
  the endpoint pool, has a fixed model-level input and output price and an
  eligible endpoint, and fewer than half its eligible endpoints are priced
  within the model-level price × the margin (an fp4 endpoint, say, set that
  price); then it is the reference
  endpoint's — the lower median of the eligible endpoints by Artificial
  Analysis's blended price, its cache prices where it publishes them, else
  the model-level ones. An entry whose endpoints were not read, with none
  eligible, or whose model-level price is absent or variable keeps the
  model-level price (null for the last, with no endpoint admitted).
  Ceilings compare it, and the margin multiplies it for OpenRouter's
  `max_price` and the reservation.
- `metadata` (`metadata`): reasoning as published (`mandatory`, the
  efforts in the catalogue's order, `default_enabled`); `parameters`, the
  intersection of the admitted endpoints' `supported_parameters` when the
  endpoints were read and one is admitted, else the model-level list;
  `forced_tool`, true only when an admitted endpoint accepts a forced named
  tool choice (`supports_tool_choice.function`); `structured_outputs`;
  `context_length`; `expiration_date`.
- `endpoints`: for the endpoint pool, the endpoints the provider policy
  admits (`candidates.anchored`: eligible, and priced at or under the
  reference price × the margin) as `{tag, quantization, pricing}`, sorted
  by tag and price, exact duplicates once; null for an entry whose
  endpoints were not read.

`direct`, keyed by Anthropic's direct id (`gates.direct_id`), holds the
`anthropic/*` entries of the pool with an endpoint tagged `anthropic`: its
price (Anthropic's list price), its parameters, forced tool choice and
context; reasoning and expiry from the catalogue entry. The direct transport
does not route through OpenRouter, so that endpoint is read whatever its
status. `policy` records the provider policy the endpoints were admitted
under and the excluded families (a consumer without `requirements.json`,
the billing server, gates a table with them: `gates.check_table_standalone`),
and `version` the content (`gates.stamped`).

Pure: the caller passes the parsed catalogue, the endpoint lists of the
pool, the policy (`candidates.policy`) and the read time.
"""

from __future__ import annotations

from decimal import Decimal

from . import candidates
from .gates import SCHEMA, direct_id, stamped

PRICES = candidates.PRICE_FIELDS


def text(price: Decimal | None) -> str | None:
    """A price as the contract writes it: a canonical decimal string (no sign,
    exponent, leading zero or trailing fractional zero), or None."""
    if price is None:
        return None
    if price == 0:
        return "0"
    return format(price.normalize(), "f")


def pricing(raw: object) -> dict:
    """A catalogue or endpoint `pricing` as the snapshot's four prices."""
    return written(candidates.prices_of(raw))


def written(prices: dict) -> dict:
    """Four prices per million (`candidates.prices_of`, `candidates.anchored`)
    as the snapshot writes them."""
    return {name: text(prices[name]) for name, _ in PRICES}


def metadata(entry: dict, endpoints: list[dict] | None, context: object) -> dict:
    """The request metadata of `entry`: reasoning and expiry from the entry;
    parameters and the forced tool choice from `endpoints` when there are any
    (the admitted ones, or the `anthropic` one for a direct id), else the
    entry's parameters and no forced tool choice; `context` as given."""
    reasoning = entry.get("reasoning") if isinstance(entry.get("reasoning"), dict) else {}
    default = reasoning.get("default_enabled")
    if endpoints:
        lists = [set(candidates.strings(e.get("supported_parameters"))) for e in endpoints]
        parameters = sorted(set.intersection(*lists))
        forced = any(
            isinstance(e.get("supports_tool_choice"), dict)
            and e["supports_tool_choice"].get("function") is True
            for e in endpoints
        )
    else:
        parameters = sorted(candidates.strings(entry.get("supported_parameters")))
        forced = False
    expiry = entry.get("expiration_date")
    return {
        "reasoning": {
            "mandatory": reasoning.get("mandatory") is True,
            "efforts": candidates.strings(reasoning.get("supported_efforts")),
            "default_enabled": default if isinstance(default, bool) else None,
        },
        "parameters": parameters,
        "forced_tool": forced,
        "structured_outputs": "structured_outputs" in parameters,
        "context_length": candidates.score(context) if isinstance(context, int) else None,
        "expiration_date": expiry if isinstance(expiry, str) and expiry else None,
    }


def _endpoint_rows(endpoints: list[dict]) -> list[dict]:
    rows = []
    for endpoint in endpoints:
        row = {
            "tag": endpoint["tag"],
            "quantization": candidates.quantization(endpoint),
            "pricing": pricing(endpoint.get("pricing")),
        }
        if row not in rows:
            rows.append(row)

    def order(row: dict) -> tuple:
        prices = row["pricing"]
        return (row["tag"], Decimal(prices["input"]), Decimal(prices["output"]), str(row))

    return sorted(rows, key=order)


def build(catalogue: list, endpoints: dict[str, list[dict]], rules: dict, read_at: str) -> dict:
    """The snapshot document, stamped with its `version`.

    `catalogue` is the catalogue's `data` list, `endpoints` the endpoint
    lists of the pool keyed by catalogue id (`candidates.endpoints_by_model`),
    `rules` the provider policy (`candidates.policy`), `read_at` the
    catalogue's read time."""
    models, direct = {}, {}
    for entry in catalogue:
        model = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(model, str) or not model:
            continue
        listed = endpoints.get(model)
        price, admitted = candidates.anchored(entry, listed, rules)
        models[model] = {
            "pricing": written(price),
            "metadata": metadata(entry, admitted, entry.get("context_length")),
            "endpoints": None if admitted is None else _endpoint_rows(admitted),
        }
        own = [e for e in listed or [] if e.get("tag") == candidates.DIRECT_TAG]
        if direct_id(model) and own:
            direct[direct_id(model)] = {
                "catalogue_id": model,
                "pricing": pricing(own[0].get("pricing")),
                "metadata": metadata(entry, own[:1], own[0].get("context_length")),
            }
    policy = {
        "margin": text(rules["margin"]),
        "quantizations": list(rules["quantizations"]),
        "excluded_endpoint_variants": list(rules["excluded_endpoint_variants"]),
        "excluded_families": [
            {"vendor": family["vendor"], "token": family["token"]}
            for family in rules["excluded_families"]
        ],
    }
    doc = {"schema": SCHEMA, "read_at": read_at, "policy": policy, "models": models}
    return stamped({**doc, "direct": direct})
