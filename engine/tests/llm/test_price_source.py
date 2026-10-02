"""Milestone 10a slice 4: one price source, and nobody unpriced on upgrade.

`zylch/llm/roles/prices.py` prices an id on a transport; `budget_pricing.PRICES`,
`openrouter_pricing.RATES` and `usage.estimate_cost_usd` read it. The
literals below are the rates every model billed today was billed at before
the table existed: the contract that the upgrade changes no profile's price.

Since milestone 10 slice S3 the source is the model snapshot (brief D5), and
10a's allowlist answers only for an id no snapshot prices. Every price here is
read from the committed fixture snapshot as 10a billed it (`billed_snapshot`:
the 2026-10-02 capture, whose rates are 10a's for every id below but two
OpenRouter rates, put back), never from the build copy. The direct rates and
holds are unchanged; on OpenRouter the hold and the cap are the rate × the
margin (1.25), the one change the brief makes to these expected values.

Since the reference-price anchor (2026-10-02) an OpenRouter route is priced at
its reference endpoint, the lower median of its eligible endpoints: for an Opus
with more regional (+10%) and premium endpoints than global ones that is a
regional endpoint, so three routes move above 10a's rate
(`MOVED_BY_THE_ANCHOR`); every other expected value here is unchanged.
"""

import json
import re
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import pytest

from zylch.llm import budget_pricing, openrouter_pricing, usage
from zylch.llm.budget_pricing import BudgetError, request_bound
from zylch.llm.roles import catalogue, prices

ROLES = Path(prices.__file__).resolve().parent
D = Decimal
# requirements.json's margin: OpenRouter holds and caps are the rate × it.
MARGIN = D("1.25")

# Today's direct Anthropic rates, USD per million tokens (input, output).
TODAY_DIRECT = {
    "claude-opus-5": (D("5"), D("25")),
    "claude-opus-4-7": (D("5"), D("25")),
    "claude-opus-4-6": (D("5"), D("25")),
    "claude-opus-4-5": (D("5"), D("25")),
    "claude-opus-4-5-20251101": (D("5"), D("25")),
    "claude-sonnet-5": (D("2"), D("10")),
    "claude-sonnet-4-6": (D("3"), D("15")),
    "claude-sonnet-4-5": (D("3"), D("15")),
    "claude-sonnet-4-5-20250929": (D("3"), D("15")),
    "claude-haiku-4-5": (D("1"), D("5")),
    "claude-haiku-4-5-20251001": (D("1"), D("5")),
}
# Today's OpenRouter billed rates (K3's is the provider-pinned contract rate).
TODAY_OPENROUTER = {
    "moonshotai/kimi-k3": (D("2.648138063"), D("13.28272425")),
    "z-ai/glm-5.2": (D("0.6"), D("2")),
    "anthropic/claude-haiku-4.5": (D("1"), D("5")),
    "anthropic/claude-sonnet-5": (D("2"), D("10")),
    "anthropic/claude-opus-5": (D("5"), D("25")),
}
TODAY = {"direct": TODAY_DIRECT, "openrouter": TODAY_OPENROUTER}
# The OpenRouter routes priced at a regional reference endpoint (module docstring).
MOVED_BY_THE_ANCHOR = {
    "anthropic/claude-opus-4.8": (D("5.5"), D("27.5")),
    "anthropic/claude-opus-5": (D("5.5"), D("27.5")),
    "anthropic/claude-opus-5.5": (D("4.4"), D("22")),
}
MESSAGES = [{"role": "user", "content": "Price this request."}]


@pytest.fixture(autouse=True)
def snapshot_as_billed(billed_snapshot):
    """Every price below is read from the fixture snapshot as 10a billed it."""
    yield billed_snapshot


def _json(name):
    return json.loads((ROLES / name).read_text(encoding="utf-8"))


def _resolved_rows():
    """``(preset, role, kind, row)`` for every main, fallback and mrcall row."""
    for preset, body in _json("resolved.json")["presets"].items():
        for role, record in body["roles"].items():
            yield preset, role, "main", record
            for kind in ("anthropic_fallback", "mrcall"):
                if record.get(kind):
                    yield preset, role, kind, record[kind]


def _expected_hold(model, transport, max_tokens=1000):
    """The hold `request_bound` must take, from the price source's rate."""
    request = {"model": model, "max_tokens": max_tokens, "messages": MESSAGES}
    payload = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    i, o = prices.price(model, transport)
    tokens = payload + 4096 + 1024 * len(MESSAGES)
    if transport == "openrouter":
        i, o = i * MARGIN, o * MARGIN  # brief D5: the OpenRouter hold gains the margin
    if transport == "direct":
        i *= 2
    elif model.startswith("anthropic/"):
        i *= 2
    return int((tokens * i + max_tokens * o).to_integral_value(rounding=ROUND_CEILING))


def _bound(model, transport):
    request = {"model": model, "max_tokens": 1000, "messages": MESSAGES}
    return request_bound(request, transport)


@pytest.mark.parametrize("transport", ["direct", "openrouter"])
def test_every_model_billed_today_is_priced_at_today_s_rate(transport):
    allowlisted = {
        m
        for m, row in _json("requirements.json")["allowlist"].items()
        if row["transport"] == transport
    }
    assert allowlisted == set(TODAY[transport])
    moved = MOVED_BY_THE_ANCHOR if transport == "openrouter" else {}
    expected = {m: moved.get(m, rate) for m, rate in TODAY[transport].items()}
    assert set(expected.items()) - set(TODAY[transport].items()) == (
        {("anthropic/claude-opus-5", (D("5.5"), D("27.5")))} if moved else set()
    )
    for model, rate in expected.items():
        assert prices.price(model, transport) == rate, model
        assert _bound(model, transport) == _expected_hold(model, transport), model
    module = budget_pricing.PRICES if transport == "direct" else openrouter_pricing.RATES
    assert {m: module[m] for m in TODAY[transport]} == expected


def test_every_resolved_row_prices_a_request_on_its_transport():
    seen = 0
    for preset, role, kind, row in _resolved_rows():
        where = (preset, role, kind)
        pairs = [("openrouter", row["catalogue_id"])]
        if row.get("direct_id"):
            pairs.append(("direct", row["direct_id"]))
        for transport, model in pairs:
            billed = TODAY[transport].get(model)
            table = (D(str(row["price"]["input"])), D(str(row["price"]["output"])))
            if transport == "openrouter":
                billed = MOVED_BY_THE_ANCHOR.get(model, billed)
            assert prices.price(model, transport) == (billed or table), where
            hold = _bound(model, transport)
            assert hold == _expected_hold(model, transport) and hold > 0, where
            seen += 1
    assert seen >= 2 * 16 * 3  # both presets, sixteen roles, three rows each


def test_table_picks_are_priced_at_the_table_s_price():
    """A pin of today's table: a price change here is a reviewed table change.

    Since slice S3 the snapshot prices these picks; the capture's prices are
    the table's, so the pin holds on the fixture snapshot."""
    assert prices.price("z-ai/glm-5.3-flash", "openrouter") == (D("0.15"), D("0.5"))
    assert prices.price("xiaomi/mimo-v2.6-flash", "openrouter") == (D("0.14"), D("0.28"))
    assert prices.price("qwen/qwen3.8-max-0902", "openrouter") == (D("2"), D("6"))
    assert prices.price("claude-sonnet-5-5", "direct") == (D("2"), D("10"))
    assert prices.price("claude-opus-5-5", "direct") == (D("4"), D("20"))
    assert _bound("z-ai/glm-5.3-flash", "openrouter") == _expected_hold(
        "z-ai/glm-5.3-flash", "openrouter"
    )


def test_an_id_in_neither_source_is_refused_with_the_existing_message():
    # Slice S3: the snapshot prices every catalogue model with an `anthropic`
    # endpoint, so Fable 5 (unpriced in 10a) is priced; an id in no source
    # is still refused, with the same message.
    assert prices.price("claude-fable-5", "direct") == (D("10"), D("50"))
    assert prices.price("claude-opus-9", "direct") is None
    with pytest.raises(BudgetError) as direct:
        _bound("claude-opus-9", "direct")
    assert str(direct.value) == "AI paused: model pricing is not configured for this model."
    with pytest.raises(BudgetError) as routed:
        _bound("vendor/unpriced-model", "openrouter")
    assert str(routed.value) == "AI paused: OpenRouter model has no verified price ceiling."
    # A direct id is not priced on OpenRouter, nor a catalogue id on direct.
    assert prices.price("claude-opus-5", "openrouter") is None
    assert prices.price("anthropic/claude-opus-5", "direct") is None


def _catalogue_form(direct_id):
    """``claude-haiku-4-5-20251001`` -> ``anthropic/claude-haiku-4.5``."""
    base = re.sub(r"-20\d{6}$", "", direct_id)
    return "anthropic/" + re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", base)


def test_direct_rates_equal_the_openrouter_anthropic_rates():
    """The brief's assumption 4: a direct id and its `anthropic/*` route cost the same.

    Since the reference-price anchor the route is priced at its reference
    endpoint, so the comparison holds against its `anthropic` endpoint
    (Anthropic's list price), and the route's own price equals the direct one
    except for the three routes priced at a regional endpoint."""
    pairs = {(d, _catalogue_form(d)) for d in prices.priced("direct")}
    pairs |= {
        (r["direct_id"], r["catalogue_id"]) for *_, r in _resolved_rows() if r.get("direct_id")
    }
    compared = 0
    for direct_id, catalogue_id in sorted(pairs):
        routed = prices.price(catalogue_id, "openrouter")
        if routed is not None:
            own = catalogue.endpoint_rates(catalogue_id, "anthropic")
            assert prices.price(direct_id, "direct") == own, (direct_id, catalogue_id)
            direct = prices.price(direct_id, "direct")
            assert routed == MOVED_BY_THE_ANCHOR.get(catalogue_id, direct), (
                direct_id,
                catalogue_id,
            )
            compared += 1
    assert compared >= 6  # opus-5, sonnet-5, both haiku ids, sonnet-5-5, opus-5-5


def _priced_row(i, o):
    return {"pricing": {"input": i, "output": o, "cache_read": None, "cache_write": None}}


def test_the_snapshot_wins_and_the_allowlist_answers_only_for_what_no_snapshot_prices(
    monkeypatch,
):
    """Slice S3 replaced 10a's rule (the allowlist's billed price won over the
    table): an id a snapshot prices is priced by the snapshot, whatever the
    allowlist billed; the allowlist answers, on its own transport, only for an
    id no snapshot layer prices; the resolved table prices nothing."""
    requirements = {
        "allowlist": {
            "vendor/both": {"transport": "openrouter", "price": {"input": "3", "output": "9"}},
            "claude-both": {"transport": "direct", "price": {"input": "1", "output": "2"}},
            "vendor/only": {"transport": "openrouter", "price": {"input": "0.5", "output": "1"}},
        }
    }
    resolved = {
        "presets": {
            "p": {
                "roles": {
                    "R": {
                        "catalogue_id": "vendor/table-row-only",
                        "direct_id": None,
                        "price": {"input": 0.5, "output": 1},
                    }
                }
            }
        }
    }
    layer = {
        "models": {"vendor/both": _priced_row("7", "70"), "anthropic/x": _priced_row("4", "8")},
        "direct": {"claude-both": {"catalogue_id": "anthropic/x", **_priced_row("4", "8")}},
    }
    files = {"requirements.json": requirements, "resolved.json": resolved}
    monkeypatch.setattr(prices, "_load", lambda name: files[name])
    prices._allowlist.cache_clear()
    catalogue.set_layers(layer, build=False)
    try:
        assert prices.price("vendor/both", "openrouter") == (D("7"), D("70"))
        assert prices.price("claude-both", "direct") == (D("4"), D("8"))
        assert prices.price("vendor/only", "openrouter") == (D("0.5"), D("1"))
        assert prices.price("vendor/only", "direct") is None
        assert prices.price("anthropic/x", "openrouter") == (D("4"), D("8"))
        assert prices.price("vendor/table-row-only", "openrouter") is None
        assert dict(prices.priced("openrouter")) == {
            "vendor/both": (D("7"), D("70")),
            "anthropic/x": (D("4"), D("8")),
            "vendor/only": (D("0.5"), D("1")),
        }
    finally:
        prices._allowlist.cache_clear()


def test_usage_estimates_a_table_pick_at_its_table_price():
    million = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert usage.estimate_cost_usd("xiaomi/mimo-v2.6-flash", million) == pytest.approx(0.42)
    assert usage.estimate_cost_usd("z-ai/glm-5.3-flash", million) == pytest.approx(0.65)
    assert usage.estimate_cost_usd("z-ai/glm-5.2", million) == pytest.approx(2.6)
    # Sonnet 5 at its own 2/10, not the sonnet family's 3/15.
    assert usage.estimate_cost_usd("claude-sonnet-5", million) == pytest.approx(12.0)
    for _, _, _, row in _resolved_rows():
        for transport, model in (("openrouter", row["catalogue_id"]), ("direct", row["direct_id"])):
            if model:
                i, o = prices.price(model, transport)
                assert usage.estimate_cost_usd(model, million) == pytest.approx(float(i + o))
