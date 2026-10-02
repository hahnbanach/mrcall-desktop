"""Resolve each engine role's model, for every preset, from requirements.

Milestone 10a's resolver, moved here unchanged from
`zylch/llm/roles/resolver.py` when resolver v2 replaced it (milestone 10,
slice S2). It is kept only for the one-time differential against the kit
(`test_resolver_10a_kit.py`) and for the check that the frozen
`roles/resolved.json`, which 10a's readers use until the switch-over, still
follows from its frozen inputs (`test_resolved_table.py`,
`fixtures/llm/resolver/requirements-10a.json`). Nothing under `zylch/`
imports it.

Ported from `malemi/mrcall-ai-kit` (`shared/scripts/resolve-models.py`,
`c88b024`, MIT), and extended for the engine. A role declares requirements,
never a model: `requirements.json` beside this file holds each role's rule,
index and floor, each preset's price ceiling, and what every candidate must
meet. This module joins OpenRouter's catalogue (prices, context length, tool
support) with its benchmarks (the Artificial Analysis indices) on
`canonical_slug` and chooses a model for every preset and role:

- **maximise**: the highest score on the role's index among the candidates
  priced at or under the ceiling. A tie goes to the cheaper model.
- **satisfice**: the cheapest candidate at or under the ceiling whose score
  clears the role's floor. A tie goes to the higher score. When nothing clears
  the floor, the role takes the highest score under the ceiling, and the choice
  is marked below the floor.

When a role has no candidate under a preset's ceiling, that preset's ceiling is
raised to the lowest price at which every role has one, and the preset is
marked raised (`raised_to`). A role with no candidate at any price, or an index
no candidate is scored on, is a data failure: `Refused`.

A price is US dollars per million output tokens (`pricing.completion`); the
input price (`pricing.prompt`) is carried beside it. A candidate an allowlist row bills
above its catalogue output price is compared at the billed price (`billed`).

Ported as the kit has them: the payload checks, the candidate filter
(variants, tools, context, a fixed price, the required scores), the index
names (`INDEX_FIELDS`), the two rules and their tie-breaks, the ceiling raise,
the Claude id of an `anthropic/*` entry (`direct_id`, the kit's `model_id`).
Extended for the engine: the candidate filter also drops catalogue-id
prefixes (`excluded_prefixes`, which keeps every `anthropic/claude-haiku`
entry out of every pool); the kit's two runtimes become one pool and, per
preset and role, an `anthropic_fallback` chosen by the same rule over the
`anthropic/*` subset, bounded by the same ceiling and raising it the same way
(its own `anthropic_raised_to`); a `mrcall` column chosen the same way over
the candidates the credits server serves (`mrcall_served`: Anthropic's direct
ids, K3's catalogue id), raising as `mrcall_raised_to`, and null for a role no
served candidate fits at any price (not a refusal: the operator then names a
custom model); and the requirements carry the allowlist of priced custom choices, checked here for
shape. Pure: no file, network or environment access; the caller passes the
requirements and the raw payloads (`engine/scripts/resolve_models.py`).
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

SCORE_SOURCE = "artificial-analysis"
INDEX_FIELDS = {
    "intelligence": "intelligence_index",
    "coding": "coding_index",
    "agentic": "agentic_index",
}
RULES = ("maximise", "satisfice")
TRANSPORTS = ("direct", "openrouter")
ANTHROPIC = "anthropic/"
MILLION = Decimal(10) ** 6


class Refused(Exception):
    """A source could not be read, or the data cannot resolve a role."""


class ConfigError(Exception):
    """requirements.json is not what the resolver reads."""


def validate_requirements(req: object, name: str = "requirements.json") -> dict:
    """Return `req` when it is what the resolver reads, else raise ConfigError.

    The kit's `load_requirements` checks, on the engine's layout: `common`
    (plus `excluded_prefixes`), `presets` with a ceiling each, `roles` with a
    rule, an index and, for satisfice, a numeric floor; extended with the
    shape of `allowlist` (transport and decimal-string prices per id) and
    `mrcall_served` (a list of ids)."""
    if not isinstance(req, dict):
        raise ConfigError(f"{name}: not a JSON object")
    common = req.get("common") or {}
    fields = "tools min_context excluded_variants excluded_prefixes required_scores"
    for field in fields.split():
        if field not in common:
            raise ConfigError(f"{name}: common.{field} is missing")
    for index in common["required_scores"]:
        if index not in INDEX_FIELDS:
            raise ConfigError(f"{name}: common.required_scores names unknown index {index!r}")
    presets = req.get("presets") or {}
    if not presets:
        raise ConfigError(f"{name}: no presets")
    for preset, spec in presets.items():
        ceiling = (spec if isinstance(spec, dict) else {}).get("ceiling", "-")
        if ceiling is not None and (score(ceiling) is None or ceiling < 0):
            raise ConfigError(f"{name}: presets.{preset}.ceiling must be a price or null")
    roles = req.get("roles") or {}
    if not roles:
        raise ConfigError(f"{name}: no roles")
    for role, rule in roles.items():
        where = f"{name}: roles.{role}"
        if rule.get("rule") not in RULES:
            raise ConfigError(f"{where}: rule must be one of {', '.join(RULES)}")
        if rule.get("index") not in INDEX_FIELDS:
            raise ConfigError(f"{where}: index must be one of {', '.join(INDEX_FIELDS)}")
        if rule["rule"] == "satisfice" and (
            isinstance(rule.get("floor"), bool) or not isinstance(rule.get("floor"), (int, float))
        ):
            raise ConfigError(f"{where}: a satisfice rule needs a numeric floor")
    allowlist = req.get("allowlist")
    if not isinstance(allowlist, dict):
        raise ConfigError(f"{name}: allowlist must be an object keyed by model id")
    for model, row in allowlist.items():
        row = row if isinstance(row, dict) else {}
        price = row.get("price")
        if row.get("transport") not in TRANSPORTS or not isinstance(price, dict):
            raise ConfigError(f"{name}: allowlist.{model} needs a transport and a price")
        for side in ("input", "output"):
            if not isinstance(price.get(side), str) or per_million(price[side]) is None:
                raise ConfigError(f"{name}: allowlist.{model}.price.{side} is not a decimal")
    served = req.get("mrcall_served")
    if not isinstance(served, list) or not all(isinstance(m, str) for m in served):
        raise ConfigError(f"{name}: mrcall_served must be a list of ids")
    return req


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
    """Refuse a catalogue that is one page of several, or shorter than it says."""
    links = doc.get("links") if isinstance(doc.get("links"), dict) else {}
    if links.get("next"):
        raise Refused("the catalogue came in pages (`links.next` is set), and a refresh reads one")
    total = doc.get("total_count")
    if isinstance(total, int) and total != len(data):
        raise Refused(f"the catalogue says it holds {total} entries and lists {len(data)}")


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
    a route whose price varies). The allowlist check uses it only to tell a
    decimal string from anything else."""
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


def scores_by_slug(benchmarks: list) -> tuple[dict, set]:
    """Artificial Analysis scores keyed by permaslug. A slug whose records
    disagree is returned apart, and no model is scored from it."""
    scores: dict[str, dict] = {}
    ambiguous: set[str] = set()
    for record in benchmarks:
        if not isinstance(record, dict) or record.get("source") != SCORE_SOURCE:
            continue
        slug = record.get("model_permaslug")
        if not slug:
            continue
        values = {name: score(record.get(field)) for name, field in INDEX_FIELDS.items()}
        if slug in scores and scores[slug] != values:
            ambiguous.add(slug)
        scores[slug] = values
    for slug in ambiguous:
        del scores[slug]
    return scores, ambiguous


def candidates(catalogue: list, benchmarks: list, common: dict) -> tuple[list[dict], set]:
    """Catalogue entries that meet what every role requires: the kit's filter
    (variant, a score record, tools, context, a fixed output price, the required
    scores) plus the engine's catalogue-id prefix exclusion."""
    scores, ambiguous = scores_by_slug(benchmarks)
    out = []
    for entry in catalogue:
        if not isinstance(entry, dict):
            continue
        model = entry.get("id") or ""
        if any(model.endswith(variant) for variant in common["excluded_variants"]):
            continue
        if any(model.startswith(prefix) for prefix in common["excluded_prefixes"]):
            continue
        slug_scores = scores.get(entry.get("canonical_slug"))
        if slug_scores is None:
            continue
        if common["tools"] and "tools" not in (entry.get("supported_parameters") or []):
            continue
        context = score(entry.get("context_length"))
        if context is None or context < common["min_context"]:
            continue
        pricing = entry.get("pricing") or {}
        price = per_million(pricing.get("completion"))
        if price is None:
            continue
        if any(slug_scores[name] is None for name in common["required_scores"]):
            continue
        input_price = per_million(pricing.get("prompt"))
        out.append(dict(id=model, price=price, input_price=input_price, scores=slug_scores))
    return out, ambiguous


def direct_id(catalogue_id: str) -> str | None:
    """Anthropic's own id for an `anthropic/*` entry (`anthropic/claude-opus-5.5`
    becomes `claude-opus-5-5`, as the kit's `model_id` writes Claude ids), or
    None for any other vendor."""
    if not catalogue_id.startswith(ANTHROPIC):
        return None
    return catalogue_id.split("/", 1)[1].replace(".", "-")


def served_id(catalogue_id: str) -> str:
    """The id the MrCall credits server is sent: Anthropic's direct id for an
    `anthropic/*` entry, the catalogue id for any other (K3's, today)."""
    return direct_id(catalogue_id) or catalogue_id


def billed(candidate: dict, allowlist: dict) -> dict:
    """The candidate at the price a ceiling compares: when an allowlist row
    bills it (by catalogue id or direct id) above its catalogue output price,
    the billed pair, with the catalogue pair kept as `catalogue_price`; the
    engine reserves at the billed price, so a model must fit at that."""
    rows = [allowlist.get(k) for k in (candidate["id"], direct_id(candidate["id"])) if k]
    pairs = [[Decimal(r["price"][s]) for s in ("input", "output")] for r in rows if r]
    top = max(pairs, key=lambda pair: pair[1], default=None)
    if top is None or top[1] <= candidate["price"]:
        return candidate
    catalogue = (candidate["input_price"], candidate["price"])
    return {**candidate, "input_price": top[0], "price": top[1], "catalogue_price": catalogue}


def choose(rule: dict, pool: list[dict]) -> tuple[dict, bool]:
    """The rule's choice from a non-empty pool, and whether it is below the
    floor. The last key of every ordering is the id, so a full tie still
    resolves the same way on every run."""
    index = rule["index"]

    def best(options: list[dict]) -> dict:
        return min(options, key=lambda c: (-c["scores"][index], c["price"], c["id"]))

    if rule["rule"] == "maximise":
        return best(pool), False
    clear = [c for c in pool if c["scores"][index] >= rule["floor"]]
    if clear:
        return min(clear, key=lambda c: (c["price"], -c["scores"][index], c["id"])), False
    return best(pool), True


def eligible_by_role(roles: dict, pool: list[dict], what: str | None) -> dict:
    """Per role, the candidates scored on its index; Refused when a role has
    none at any price (the kit's `eligible`: a None score leaves that index's
    pool, which also covers an index missing for every candidate), unless
    `what` is None, when such a role keeps an empty list."""
    eligible = {
        role: [c for c in pool if c["scores"][rule["index"]] is not None]
        for role, rule in roles.items()
    }
    empty = [role for role, options in eligible.items() if not options]
    if empty and what is not None:
        raise Refused(f"{what}: no candidate at any price for {', '.join(empty)}")
    return eligible


def pick_under(roles: dict, eligible: dict, ceiling) -> tuple[Decimal | None, dict]:
    """The kit's `resolve_runtime` for one budget: the ceiling raise, then each
    role's choice at or under the (possibly raised) cap. Returns `raised_to`
    (None when not raised) and, per role, the candidate and `below_floor`, or
    None for a role with no candidate (which then takes no part in the raise)."""
    cap = None if ceiling is None else Decimal(str(ceiling))
    raised_to, picks = None, {role: None for role in roles}
    eligible = {role: options for role, options in eligible.items() if options}
    if cap is not None and any(
        min(c["price"] for c in options) > cap for options in eligible.values()
    ):
        cap = max(min(c["price"] for c in options) for options in eligible.values())
        raised_to = cap
    for role, rule in roles.items():
        if role not in eligible:
            continue
        under = [c for c in eligible[role] if cap is None or c["price"] <= cap]
        pick, below = choose(rule, under)
        picks[role] = {"candidate": pick, "below_floor": below}
    return raised_to, picks


def resolve(req: dict, raw: dict) -> dict:
    """Resolve every preset and role from the raw payloads.

    `raw` holds `catalogue` and `benchmarks` (bytes) and `read_at` (the
    catalogue's read time, or None). Returns the pool, the ambiguous slugs,
    the stamps, and per preset its ceiling, the three raises and per role the
    main pick, the Anthropic fallback and the MrCall pick (or None)."""
    catalogue, cat_doc = payload_list(raw.get("catalogue"), "catalogue")
    complete_catalogue(cat_doc, catalogue)
    benchmarks, bench_doc = payload_list(raw.get("benchmarks"), "benchmarks")
    complete_benchmarks(bench_doc, benchmarks)
    pool, ambiguous = candidates(catalogue, benchmarks, req["common"])
    pool = [billed(c, req["allowlist"]) for c in pool]
    roles = req["roles"]
    eligible = eligible_by_role(roles, pool, "every vendor")
    anthropic = [c for c in pool if c["id"].startswith(ANTHROPIC)]
    fallback_eligible = eligible_by_role(roles, anthropic, "the Anthropic fallback")
    served = [c for c in pool if served_id(c["id"]) in set(req["mrcall_served"])]
    served_eligible = eligible_by_role(roles, served, None)
    presets = {}
    for preset, spec in req["presets"].items():
        raised_to, picks = pick_under(roles, eligible, spec["ceiling"])
        fb, fallbacks = pick_under(roles, fallback_eligible, spec["ceiling"])
        mc, mrcall = pick_under(roles, served_eligible, spec["ceiling"])
        rows = {r: {**picks[r], "fallback": fallbacks[r], "mrcall": mrcall[r]} for r in roles}
        raises = dict(raised_to=raised_to, anthropic_raised_to=fb, mrcall_raised_to=mc)
        presets[preset] = dict(ceiling=spec["ceiling"], **raises, roles=rows)
    meta = bench_doc.get("meta") if isinstance(bench_doc.get("meta"), dict) else {}
    stamps = dict(benchmarks_as_of=meta.get("as_of"), read_at=raw.get("read_at"))
    return dict(stamps, pool=pool, ambiguous=ambiguous, presets=presets)


def number(value: Decimal | None) -> int | float | None:
    """A Decimal as the JSON number the kit writes (an int when integral)."""
    if value is None:
        return None
    value = value.normalize()
    return int(value) if value == value.to_integral_value() else float(format(value, "f"))


def _pair(input_price: Decimal | None, output_price: Decimal) -> dict:
    return {"input": number(input_price), "output": number(output_price)}


def _pick(rule: dict, picked: dict) -> dict:
    c = picked["candidate"]
    out = dict(catalogue_id=c["id"], direct_id=direct_id(c["id"]), score=c["scores"][rule["index"]])
    out.update(scores=c["scores"], price=_pair(c["input_price"], c["price"]))
    out.update(below_floor=picked["below_floor"])
    if "catalogue_price" in c:
        out["catalogue_price"] = _pair(*c["catalogue_price"])
    return out


def document(req: dict, result: dict) -> dict:
    """What resolved.json holds: per preset and role the pick, its Anthropic
    fallback, the MrCall pick (its `id` the one the credits server is sent;
    null when no served model fits), and what each choice was made on."""
    presets = {}
    for preset, outcome in result["presets"].items():
        roles = {}
        for role, picked in outcome["roles"].items():
            rule = req["roles"][role]
            fallback = _pick(rule, picked["fallback"])
            served = picked["mrcall"] and _pick(rule, picked["mrcall"])
            roles[role] = {
                "rule": rule["rule"],
                "index": rule["index"],
                **_pick(rule, picked),
                "anthropic_fallback": fallback,
                "mrcall": served and {"id": served_id(served["catalogue_id"]), **served},
            }
        presets[preset] = {
            "ceiling": outcome["ceiling"],
            "raised_to": number(outcome["raised_to"]),
            "anthropic_raised_to": number(outcome["anthropic_raised_to"]),
            "mrcall_raised_to": number(outcome["mrcall_raised_to"]),
            "roles": roles,
        }
    return {
        "as_of": {"benchmarks": result["benchmarks_as_of"], "catalogue": result["read_at"]},
        "presets": presets,
    }
