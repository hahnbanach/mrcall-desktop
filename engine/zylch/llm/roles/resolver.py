"""Resolve every role's rankings, per preset, from requirements, the catalogue and the measurement.

Resolver v2 (milestone 10; brief D1, D2, D4, D7, D8). It keeps 10a's
mechanism, ported from `malemi/mrcall-ai-kit` (`shared/scripts/resolve-models.py`,
`c88b024`, MIT): a role declares a rule and an index, never a model;
`requirements.json` holds the roster, each preset's output-price ceiling, the
candidate filter, the excluded families, the provider policy and the
margin. What v2 changes:

- **The pool** comes from `candidates.screen` (no variant, alias, announced
  expiry or excluded family; tools, context, a fixed price, an admitted
  endpoint) and `impute.scored` (the Artificial Analysis scores, a missing
  index imputed from intelligence, the unscored listed).
- **No typed floor.** A role ranks only once `measured.json` covers it
  (`validate_measured`), so the first table follows the measurement.
- **Rankings of five** per preset and role (`rank`), best first, the first
  being the pick: a `maximise` role ranks the models that passed its
  measurement by its index, a tie to the cheaper, then the id; a `satisfice`
  role ranks, cheapest first (a tie to the higher score, then the id), the
  models at or above its measured threshold, or, where it accepts measured
  models only, those that passed. A model measured as failing a role is
  never ranked for it. A second ranking applies the same rule to the
  Anthropic subset — the candidates with a direct id, what a personal
  Anthropic key runs — and may be empty.
- **The ceiling raise** stays for a run by hand: a preset where a covered
  role ranks nothing under the ceiling, though it would above it, is
  resolved under the lowest ceiling at which every such role ranks one
  (`raised_to`) and reported; a raised ceiling is never published (the
  gates refuse it, and `publishable` says so).
- **The bootstrap** (`bootstrap`, brief D7) chooses the measurement's arms
  before any threshold exists: for a `maximise` role the first three
  candidates by its index under each preset's ceiling, plus the first
  Anthropic candidate under each ceiling (so the Anthropic ranking can be
  built), deduplicated; for a `satisfice` role a ladder — the cheapest
  candidate scoring at least each step of its index, in steps of five
  points from the pool's lowest score to its highest under the highest
  preset ceiling (balanced's), the step widened by five until the ladder
  holds at most six distinct models; plus the reference (`reference` in
  `requirements.json`) for every role. Excluded families are never in the
  pool, so never an arm.
- **The decision record** (`document`, `decision`) is `table.json` of the
  contract (`contract/README.md`): rankings only, no price, score or
  metadata, so a refresh that moves no pick or order changes no record.

`allowlist`, `mrcall_served` and `request_rules` of `requirements.json` are
10a's and are ignored here (they go at the switch-over). Pure: no file,
network or environment access; the caller passes the requirements, the
measurement and the raw payloads (`engine/scripts/resolve_models.py`).
"""

from __future__ import annotations

from decimal import Decimal

from . import candidates, impute
from .candidates import Refused
from .gates import SCHEMA, stamped
from .snapshot import text

RULES = ("maximise", "satisfice")
RANKED = 5
TOP = 3
LADDER = 6
STEP = 5
HEX = frozenset("0123456789abcdef")


class ConfigError(Exception):
    """requirements.json or measured.json is not what the resolver reads."""


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _names(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def validate_requirements(req: object, name: str = "requirements.json") -> dict:
    """Return `req` when it is what the resolver reads, else raise ConfigError.

    `common` (tools, min_context, excluded_variants, required_scores),
    `presets` each with a numeric ceiling, `roles` each with a rule and an
    index and no typed floor (thresholds come from `measured.json`),
    `excluded_families` as `{vendor, token}`, a `margin` of at least 1, the
    provider policy's quantizations, the excluded endpoint variants and the
    measurement `reference`."""
    if not isinstance(req, dict):
        raise ConfigError(f"{name}: not a JSON object")
    common = req.get("common") if isinstance(req.get("common"), dict) else {}
    if not isinstance(common.get("tools"), bool) or not _number(common.get("min_context")):
        raise ConfigError(f"{name}: common needs tools (true or false) and a numeric min_context")
    if not _names(common.get("excluded_variants")):
        raise ConfigError(f"{name}: common.excluded_variants must be a list of suffixes")
    if not _names(common.get("required_scores")) or set(common["required_scores"]) - set(
        impute.INDEX_FIELDS
    ):
        raise ConfigError(f"{name}: common.required_scores must name known indices")
    presets = req.get("presets") if isinstance(req.get("presets"), dict) else {}
    if not presets:
        raise ConfigError(f"{name}: no presets")
    for preset, spec in presets.items():
        ceiling = spec.get("ceiling") if isinstance(spec, dict) else None
        if not _number(ceiling) or ceiling < 0:
            raise ConfigError(f"{name}: presets.{preset}.ceiling must be a price")
    roles = req.get("roles") if isinstance(req.get("roles"), dict) else {}
    if not roles:
        raise ConfigError(f"{name}: no roles")
    for role, rule in roles.items():
        where = f"{name}: roles.{role}"
        if not isinstance(rule, dict) or rule.get("rule") not in RULES:
            raise ConfigError(f"{where}: rule must be one of {', '.join(RULES)}")
        if rule.get("index") not in impute.INDEX_FIELDS:
            raise ConfigError(f"{where}: index must be one of {', '.join(impute.INDEX_FIELDS)}")
        if "floor" in rule:
            raise ConfigError(f"{where}: a floor is measured (measured.json), never typed")
    families = req.get("excluded_families")
    if not isinstance(families, list) or not all(
        isinstance(f, dict) and _names([f.get("vendor"), f.get("token")]) for f in families
    ):
        raise ConfigError(f"{name}: excluded_families must be a list of {{vendor, token}}")
    if not _number(req.get("margin")) or req["margin"] < 1:
        raise ConfigError(f"{name}: margin must be a number of at least 1")
    policy = req.get("provider_policy") if isinstance(req.get("provider_policy"), dict) else {}
    if not _names(policy.get("quantizations")) or not policy["quantizations"]:
        raise ConfigError(f"{name}: provider_policy.quantizations must list quantizations")
    pins = policy.get("pinned_endpoints", {})
    if not isinstance(pins, dict) or not _names([*pins.keys(), *pins.values()]):
        raise ConfigError(f"{name}: provider_policy.pinned_endpoints must map ids to endpoint tags")
    if not _names(req.get("excluded_endpoint_variants")):
        raise ConfigError(f"{name}: excluded_endpoint_variants must be a list of tiers")
    if not isinstance(req.get("reference"), str) or not req["reference"]:
        raise ConfigError(f"{name}: reference must name the measurement's reference model")
    return req


def validate_measured(doc: object, roles: dict, name: str = "measured.json") -> dict:
    """Return `doc` when it is a measurement the resolver reads, else raise
    ConfigError: `{schema: 1, roles: {ROLE: {threshold, measured_only,
    results: {id: {pass, ...}}, case_set_sha256, prompt_sha256}}}` over roles
    of the roster."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ConfigError(f"{name}: not a schema {SCHEMA} measurement")
    measured = doc.get("roles")
    if not isinstance(measured, dict):
        raise ConfigError(f"{name}: roles must be an object")
    for role, body in measured.items():
        where = f"{name}: roles.{role}"
        if role not in roles:
            raise ConfigError(f"{where}: not a role of the roster")
        if not isinstance(body, dict):
            raise ConfigError(f"{where}: not an object")
        threshold = body.get("threshold")
        if threshold is not None and not _number(threshold):
            raise ConfigError(f"{where}: threshold must be a number or null")
        if not isinstance(body.get("measured_only"), bool):
            raise ConfigError(f"{where}: measured_only must be true or false")
        results = body.get("results")
        if not isinstance(results, dict) or not all(
            isinstance(r, dict) and isinstance(r.get("pass"), bool) for r in results.values()
        ):
            raise ConfigError(f"{where}: results must map ids to {{pass: true|false, ...}}")
        for field in ("case_set_sha256", "prompt_sha256"):
            value = body.get(field)
            if not isinstance(value, str) or len(value) != 64 or set(value) - HEX:
                raise ConfigError(f"{where}: {field} must be a SHA-256")
    return doc


def read(req: dict, raw: dict) -> dict:
    """The parsed sources: the catalogue, the benchmarks and the endpoints of
    the pool, each checked whole (Refused otherwise), and the read time."""
    catalogue, cat_doc = candidates.payload_list(raw.get("catalogue"), "catalogue")
    candidates.complete_catalogue(cat_doc, catalogue)
    benchmarks, bench_doc = candidates.payload_list(raw.get("benchmarks"), "benchmarks")
    candidates.complete_benchmarks(bench_doc, benchmarks)
    wanted = candidates.endpoint_pool(catalogue, req["common"])
    endpoints = candidates.endpoints_by_model(raw.get("endpoints"), wanted)
    meta = bench_doc.get("meta") if isinstance(bench_doc.get("meta"), dict) else {}
    return {
        "catalogue": catalogue,
        "benchmarks": benchmarks,
        "endpoints": endpoints,
        "read_at": raw.get("read_at"),
        "benchmarks_as_of": meta.get("as_of"),
    }


def pool(req: dict, sources: dict) -> dict:
    """The candidate pool (`impute.scored` over `candidates.screen`) with the
    screen's `dropped` reasons; Refused when a role has no candidate scored
    on its index at any price."""
    kept, dropped = candidates.screen(sources["catalogue"], sources["endpoints"], req)
    indices = {rule["index"] for rule in req["roles"].values()}
    result = impute.scored(kept, sources["benchmarks"], indices, req["common"])
    empty = [
        role
        for role, rule in req["roles"].items()
        if not any(c["scores"][rule["index"]] is not None for c in result["pool"])
    ]
    if empty:
        raise Refused(f"no candidate at any price for {', '.join(empty)}")
    return {**result, "dropped": dropped}


def qualifies(rule: dict, outcome: dict, candidate: dict) -> bool:
    """Whether the measurement `outcome` of a role admits `candidate` to its
    ranking (see the module docstring)."""
    result = outcome["results"].get(candidate["id"], {}).get("pass")
    if rule["rule"] == "maximise" or outcome["measured_only"]:
        return result is True
    if result is False:
        return False
    threshold = outcome["threshold"]
    return threshold is not None and candidate["scores"][rule["index"]] >= threshold


def order(rule: dict):
    """The sort key of a rule: maximise by score, satisfice by price."""
    index = rule["index"]
    if rule["rule"] == "maximise":
        return lambda c: (-c["scores"][index], c["price"], c["id"])
    return lambda c: (c["price"], -c["scores"][index], c["id"])


def rank(rule: dict, options: list[dict], outcome: dict, ceiling: Decimal) -> list[dict]:
    """The first five of `options` the measurement admits at or under `ceiling`."""
    index = rule["index"]
    fit = [
        c
        for c in options
        if c["scores"][index] is not None and c["price"] <= ceiling and qualifies(rule, outcome, c)
    ]
    return sorted(fit, key=order(rule))[:RANKED]


def _raise(
    req: dict, options: list[dict], measured: dict, roles: list[str], ceiling: Decimal
) -> Decimal | None:
    """The hand-run raise: the lowest ceiling at which every covered role
    that ranks something at some price ranks one, or None when `ceiling`
    already does."""
    lowest = []
    for role in roles:
        rule, outcome = req["roles"][role], measured["roles"][role]
        index = rule["index"]
        prices = [
            c["price"]
            for c in options
            if c["scores"][index] is not None and qualifies(rule, outcome, c)
        ]
        if prices:
            lowest.append(min(prices))
    need = max(lowest, default=None)
    return need if need is not None and need > ceiling else None


def rankings(req: dict, options: list[dict], measured: dict | None) -> dict:
    """Per preset its ceiling, `raised_to` (None unless raised) and, for every
    role `measured` covers, its `ranking` and `anthropic_ranking`; `blocked`,
    the roles it does not cover (no ranking, so no table)."""
    covered_roles = (measured or {}).get("roles", {})
    covered = [role for role in req["roles"] if role in covered_roles]
    anthropic = [c for c in options if c["direct_id"]]
    presets = {}
    for preset, spec in req["presets"].items():
        ceiling = Decimal(str(spec["ceiling"]))
        raised = _raise(req, options, measured, covered, ceiling) if covered else None
        cap = raised or ceiling
        roles = {}
        for role in covered:
            rule, outcome = req["roles"][role], covered_roles[role]
            roles[role] = {
                "ranking": rank(rule, options, outcome, cap),
                "anthropic_ranking": rank(rule, anthropic, outcome, cap),
            }
        presets[preset] = {"ceiling": ceiling, "raised_to": raised, "roles": roles}
    blocked = [role for role in req["roles"] if role not in covered]
    return {"presets": presets, "blocked": blocked}


def publishable(ranked: dict) -> list[str]:
    """Why these rankings cannot be published as a table (empty when they can)."""
    reasons = []
    if ranked["blocked"]:
        reasons.append(f"measured.json does not cover {', '.join(ranked['blocked'])}")
    for preset, body in ranked["presets"].items():
        if body["raised_to"] is not None:
            reasons.append(
                f"{preset}'s ceiling of {text(body['ceiling'])} would be raised to "
                f"{text(body['raised_to'])}, and a raised ceiling is never published"
            )
        empty = [role for role, row in body["roles"].items() if not row["ranking"]]
        if empty:
            reasons.append(f"{preset}: no measured model qualifies for {', '.join(empty)}")
    return reasons


def _arm(arms: dict, model: str, candidate: dict | None, why: str) -> None:
    arms.setdefault(model, {"id": model, "candidate": candidate, "why": []})["why"].append(why)


def ladder(options: list[dict], index: str, ceiling: Decimal) -> list[tuple[dict, float]]:
    """The satisfice ladder under `ceiling`: `(cheapest candidate, step)` for
    each step from the lowest score to the highest, five points apart, the
    step widened by five until at most six distinct models remain."""
    under = [c for c in options if c["scores"][index] is not None and c["price"] <= ceiling]
    if not under:
        return []
    low = min(c["scores"][index] for c in under)
    high = max(c["scores"][index] for c in under)
    cheapest = order({"rule": "satisfice", "index": index})
    step = STEP
    while True:
        rungs: list[tuple[dict, float]] = []
        k = 0
        while low + k * step <= high:
            floor = low + k * step
            best = min((c for c in under if c["scores"][index] >= floor), key=cheapest)
            if best["id"] not in [c["id"] for c, _ in rungs]:
                rungs.append((best, floor))
            k += 1
        if len(rungs) <= LADDER:
            return rungs
        step += STEP


def bootstrap(req: dict, options: list[dict]) -> dict:
    """The measurement's arms per role (brief D7; see the module docstring):
    `{reference, roles: {ROLE: {rule, index, arms: [{id, candidate, why}]}}}`,
    where `candidate` is None only for a reference outside the pool."""
    ceilings = {p: Decimal(str(spec["ceiling"])) for p, spec in req["presets"].items()}
    reference = req["reference"]
    known = {c["id"]: c for c in options}
    out = {}
    for role, rule in req["roles"].items():
        index, arms = rule["index"], {}
        scored = [c for c in options if c["scores"][index] is not None]
        if rule["rule"] == "maximise":
            for preset, ceiling in ceilings.items():
                under = sorted((c for c in scored if c["price"] <= ceiling), key=order(rule))
                for candidate in under[:TOP]:
                    _arm(arms, candidate["id"], candidate, f"top {TOP} under {preset}")
                own = [c for c in under if c["direct_id"]]
                if own:
                    _arm(arms, own[0]["id"], own[0], f"first Anthropic under {preset}")
        else:
            highest = max(ceilings.values())
            for candidate, floor in ladder(scored, index, highest):
                _arm(arms, candidate["id"], candidate, f"ladder step {floor:g}")
        _arm(arms, reference, known.get(reference), "reference")
        out[role] = {"rule": rule["rule"], "index": index, "arms": list(arms.values())}
    return {"reference": reference, "roles": out}


def document(ranked: dict, stamps: dict) -> dict:
    """`table.json` (contract schema 1) for publishable rankings, stamped with
    its `version`. `stamps` holds `resolved_at`, `catalogue_read_at`,
    `requirements_sha256` and `measured_sha256`."""
    presets = {}
    for preset, body in ranked["presets"].items():
        roles = {
            role: {
                column: [{"id": c["id"], "direct_id": c["direct_id"]} for c in row[column]]
                for column in ("ranking", "anthropic_ranking")
            }
            for role, row in body["roles"].items()
        }
        presets[preset] = {"ceiling": text(body["ceiling"]), "roles": roles}
    fields = ("resolved_at", "catalogue_read_at", "requirements_sha256", "measured_sha256")
    return stamped({"schema": SCHEMA, **{k: stamps[k] for k in fields}, "presets": presets})


def decision(table: dict) -> dict:
    """The decision record of a table — per preset its ceiling and per role
    both rankings as `(id, direct_id)` in order — what `--check` compares, so
    a refresh that moves no pick and no order is no drift."""
    out = {}
    for preset, body in (table.get("presets") or {}).items():
        roles = {
            role: {
                column: [(e.get("id"), e.get("direct_id")) for e in row.get(column) or []]
                for column in ("ranking", "anthropic_ranking")
            }
            for role, row in (body.get("roles") or {}).items()
        }
        out[preset] = {"ceiling": body.get("ceiling"), "roles": roles}
    return out
