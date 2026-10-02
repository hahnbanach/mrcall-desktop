"""The free cost projection of ``measure_roles.py --project`` (plan S4b; IR2 reads it).

No call is made and nothing is reserved. For every role and arm, over the
role's captured requests (or the corpus's requests, for the memory roles):

- **maximum** — what the reservations allow: the engine's own
  ``budget_pricing.request_bound`` of the dict the client would send (built by
  the client's own code up to the reservation: the one shape, the datetime
  line, K3's adapter controls). An arm the price source in force cannot price
  yet (before S3 the OpenRouter rates are 10a's table and allowlist) is bound
  by the same formula on the snapshot's model-level price × the margin, as S3
  prices it, and marked ``*``;
- **expected** — the spend to expect: input tokens estimated from the bytes
  of that dict at ``BYTES_PER_TOKEN`` (2.40, the densest ratio measured
  against Anthropic's reported usage, ``budget_pricing._context_tokens``);
  output at the request's ``max_tokens`` capped by the role's expected answer
  — derived from the tool schema the role answers through (``schema_tokens``:
  ``SCALAR_TOKENS`` per enum, boolean or number, ``STRING_TOKENS`` per free
  string, three items per array, plus ``ENVELOPE_TOKENS``), else from the
  label's length limits (``max_chars`` / ``min_chars`` at ``CHARS_PER_TOKEN``)
  or ``TEXT_TOKENS`` — plus the reasoning the request turns on
  (``REASONING_TOKENS``, the headroom the shape reserves; K3 at max effort
  ``K3_REASONING_TOKENS``, the mean of the 2026-09-16 record: 63,756 reasoning
  tokens over 60 responses); priced at the snapshot's model-level prices.
  CHAT and TASK_SOLVE count one dispatch when the label expects no tool and two
  otherwise (the call, then the answer after its result), each later one
  ``FOLLOW_UP_TOKENS`` longer. A corpus case counts its extraction (automatic
  cases) and one decision per expected child; its maximum, the runner's own
  intent bound (``EVENT_DISPATCH_ALLOWANCE`` decisions per child).

It prints a table per role and arm, the totals, the D7 priority order with the
cumulative expected spend, and IR2's rule: the expected total against the cap
less 20 %.
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, Decimal

import measurement_common as common

BYTES_PER_TOKEN = Decimal("2.40")
SCALAR_TOKENS, STRING_TOKENS, ENVELOPE_TOKENS = 3, 40, 20
CHARS_PER_TOKEN = Decimal("3")
TEXT_TOKENS = {"INTENT": 60, "WEB_SEARCH": 300, "CHAT": 150, "TASK_SOLVE": 150}
REASONING_TOKENS, K3_REASONING_TOKENS = 1024, 1063
FOLLOW_UP_TOKENS = 400
DECISION_TOKENS, EXTRACTION_TOKENS = 200, 300
NO_KEY = "projection-no-network"
CORPUS_LABEL = "MNEMONIC (+MEMORY_EXTRACT, MEMORY_MERGE)"


def schema_tokens(schema: object) -> int:
    """The expected length of a value of ``schema`` (see the module docstring)."""
    if not isinstance(schema, dict):
        return SCALAR_TOKENS
    kind = schema.get("type")
    kind = next((k for k in kind if k != "null"), "null") if isinstance(kind, list) else kind
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        return sum(SCALAR_TOKENS + schema_tokens(sub) for sub in properties.values())
    if kind == "array":
        return 3 * schema_tokens(schema.get("items"))
    if kind == "string" and not schema.get("enum"):
        return STRING_TOKENS
    return SCALAR_TOKENS


def answer_tokens(run, case: dict, sent: dict) -> int:
    """The role's expected answer, before reasoning."""
    tools = [tool.get("input_schema") for tool in sent.get("tools") or []]
    if run.role in common.DECISION_ROLES and tools:
        return ENVELOPE_TOKENS + max(schema_tokens(schema) for schema in tools)
    label = case["label"]
    if label.get("max_chars"):
        return int(Decimal(label["max_chars"]) / CHARS_PER_TOKEN)
    if label.get("min_chars"):
        return int(2 * Decimal(label["min_chars"]) / CHARS_PER_TOKEN)
    return TEXT_TOKENS.get(run.role, STRING_TOKENS)


def reasoning_tokens(model: str, sent: dict) -> int:
    from zylch.llm.roles import catalogue

    if (sent.get("output_config") or {}).get("effort") == "max":
        return K3_REASONING_TOKENS
    meta = catalogue.metadata(model) or {}
    mandatory = (meta.get("reasoning") or {}).get("mandatory")
    on = (sent.get("thinking") or {}).get("type") == "adaptive" or mandatory
    return REASONING_TOKENS if on else 0


def expected_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    from zylch.llm.roles import catalogue

    rates = catalogue.rates(model, "openrouter") or (Decimal(0), Decimal(0))
    return (input_tokens * rates[0] + output_tokens * rates[1]) / Decimal(1_000_000)


def input_tokens(sent: dict) -> int:
    import json

    size = len(json.dumps(sent, ensure_ascii=False).encode("utf-8"))
    return math.ceil(Decimal(size) / BYTES_PER_TOKEN)


def maximum_usd(model: str, sent: dict) -> tuple[Decimal, bool]:
    """``(bound, priced_here)``: the engine's bound, or S3's formula on the snapshot.

    Raises ``BudgetError`` when neither prices the model.
    """
    import json

    from zylch.llm.budget_pricing import BudgetError, request_bound
    from zylch.llm.roles import catalogue

    try:
        return Decimal(request_bound(sent, "openrouter")) / Decimal(1_000_000), False
    except BudgetError:
        rates, margin = catalogue.rates(model, "openrouter"), catalogue.policy()["margin"]
        if rates is None:
            raise
    payload = len(json.dumps(sent, ensure_ascii=False, allow_nan=False).encode())
    tokens = payload + 4096 + 1024 * (len(sent["messages"]) + len(sent.get("tools") or []))
    in_rate, out_rate = rates[0] * margin, rates[1] * margin
    if model.startswith("anthropic/"):
        in_rate *= 2
    micro = (tokens * in_rate + sent["max_tokens"] * out_rate).to_integral_value(ROUND_CEILING)
    return micro / Decimal(1_000_000), True


def client_for(model: str):
    from zylch.llm.client import LLMClient

    return LLMClient(transport="openrouter", api_key=NO_KEY, model=model)


def harness_cell(run, arm: str, case: dict, client) -> tuple[Decimal, Decimal, bool]:
    """``(maximum, expected, priced_here)`` of one arm on one case of a harness role."""
    from zylch.llm.client import RunClock

    import measurement_runtime

    entry = run.entry(case["id"])
    clock = RunClock(line=common.datetime_line(entry["capture_now"]))
    kwargs = measurement_runtime.replay_kwargs(entry, arm)
    sent = common.reserved_request(client, **kwargs, run_clock=clock)
    bound, fallback = maximum_usd(arm, sent)
    output = min(sent["max_tokens"], answer_tokens(run, case, sent) + reasoning_tokens(arm, sent))
    dispatches = 1
    if run.role in common.AGENT_ROLES and case["label"].get("first_call"):
        dispatches = 2
    tokens = input_tokens(sent)
    expected = sum(
        expected_usd(arm, tokens + n * FOLLOW_UP_TOKENS, output) for n in range(dispatches)
    )
    return bound * dispatches, expected, fallback


def corpus_arm(arm: str) -> tuple[int, Decimal, Decimal, bool]:
    """``(cases, maximum, expected, priced_here)`` of one corpus run on ``arm`` (three roles)."""
    common.importable()
    # The corpus bench's own modules, by their full path (as scripts/voice_m2_demo.py
    # imports its fixture): the projection reads the requests the runner admits.
    from tests.memory.corpus_live_env import EXCLUDED, EXTRACTION_PROMPT, Seeded
    from tests.memory.corpus_live_provider import Arm, decision_request, extraction_request
    from tests.memory.corpus_live_provider import sent as client_sent
    from tests.memory.mnemonic_cases import load_incidents
    from zylch.memory.mnemonic.contracts import AUTOMATIC_OBSERVATION, EVENT_DISPATCH_ALLOWANCE

    target = Arm("openrouter", arm, "projection", arm)
    maximum = expected = Decimal(0)
    fallback = False
    corpus = [c for c in load_incidents()["cases"] if c["id"] not in EXCLUDED]
    for spec in corpus:
        requests = [(decision_request(spec["id"]), DECISION_TOKENS)]
        requests *= len(Seeded.decision_keys(spec))
        if spec["caller_class"] == AUTOMATIC_OBSERVATION:
            requests.append((extraction_request(spec, EXTRACTION_PROMPT), EXTRACTION_TOKENS))
        for n, (request, answer) in enumerate(requests):
            sent = client_sent(target, request)
            bound, here = maximum_usd(arm, sent)
            fallback |= here
            decision = n < len(requests) - (spec["caller_class"] == AUTOMATIC_OBSERVATION)
            maximum += bound * (EVENT_DISPATCH_ALLOWANCE if decision else 1)
            output = min(sent["max_tokens"], answer + reasoning_tokens(arm, sent))
            expected += expected_usd(arm, input_tokens(sent), output)
    return len(corpus), maximum, expected, fallback


def corpus_arms(arms: dict) -> list[str]:
    """Every arm of the three memory roles, the reference first: one corpus run each."""
    seen: list[str] = []
    for role in common.CORPUS_ROLES:
        for arm in arms.get(role, []):
            if arm["id"] not in seen:
                seen.append(arm["id"])
    return seen


def role_arm(run, arm: str) -> tuple[int, Decimal, Decimal, bool]:
    """``(cases, maximum, expected, priced_here)`` of one arm over one role's cases."""
    client = client_for(arm)
    maximum = expected = Decimal(0)
    fallback = False
    for case in run.document["cases"]:
        bound, spend, here = harness_cell(run, arm, case, client)
        maximum, expected, fallback = maximum + bound, expected + spend, fallback or here
    return len(run.document["cases"]), maximum, expected, fallback


def main(runs: list, arms: dict, cap: Decimal, corpus_roles: bool = True) -> int:
    """Print the projection of ``runs`` (and of the corpus runs, ``corpus_roles``)."""
    from zylch.llm.budget_pricing import BudgetError
    from zylch.llm.roles import catalogue

    rows: list[tuple[str, str, int, Decimal, Decimal, bool]] = []
    unpriced: list[str] = []
    reference = common.reference_model()
    work = [(run.role, arm["id"], run) for run in runs for arm in run.arms]
    corpus = CORPUS_LABEL if corpus_roles else None
    work += [(CORPUS_LABEL, arm, None) for arm in (corpus_arms(arms) if corpus_roles else [])]
    for role, arm, run in work:
        try:
            rows.append((role, arm, *(role_arm(run, arm) if run else corpus_arm(arm))))
        except BudgetError as refused:  # no price anywhere: listed, left out of the totals
            unpriced.append(f"{role} / {arm}: {refused}")
    snapshot = catalogue.layers()[0]
    print(f"snapshot {snapshot['version']} read {snapshot['read_at']}\n")
    print(f"{'role':38} {'arm':40} {'cases':>5} {'max USD':>11} {'expected USD':>13}")
    for role, arm, n, maximum, expected, fallback in rows:
        mark = "*" if fallback else " "
        name = f"{arm} (reference)" if arm == reference else arm
        print(f"{role:38} {name:40} {n:5d} {maximum:10.4f}{mark} {expected:13.4f}")
    total_max = sum(r[3] for r in rows)
    total_expected = sum(r[4] for r in rows)
    print(f"\ntotal: maximum USD {total_max:.4f}, expected USD {total_expected:.4f}")
    print("* priced on the snapshot × the margin (the price source in force cannot price it yet)")
    for line in unpriced:
        print(f"not priced anywhere, not projected: {line}")
    print("\nD7 priority, cumulative expected spend:")
    cumulative = Decimal(0)
    order = ([corpus] if corpus else []) + [run.role for run in runs]
    for role in order:
        spend = sum(r[4] for r in rows if r[0] == role)
        cumulative += spend
        print(f"  {role:42} {spend:9.4f}  cumulative {cumulative:9.4f}")
    first = cumulative
    second = sum(r[4] for r in rows if r[1] == reference)
    cumulative += second
    print(f"  {'the reference second repetition':42} {second:9.4f}  cumulative {cumulative:9.4f}")
    budget = cap * Decimal("0.8")
    for label, spend in (("one repetition", first), ("with the reference's second", cumulative)):
        verdict = "within" if spend <= budget else "OVER"
        print(f"IR2: expected {label}: USD {spend:.4f}, {verdict} USD {budget} (the cap less 20 %)")
    return 0
