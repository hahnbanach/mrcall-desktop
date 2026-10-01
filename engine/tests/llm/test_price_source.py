"""Milestone 10a slice 4: one price source, and nobody unpriced on upgrade.

`zylch/llm/roles/prices.py` prices an id on a transport from the resolved
table plus the allowlist's billed rows; `budget_pricing.PRICES`,
`openrouter_pricing.RATES` and `usage.estimate_cost_usd` read it. The
literals below are the rates every model billed today was billed at before
the table existed: the contract that the upgrade changes no profile's price.
"""

import json
import re
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import pytest

from zylch.llm import budget_pricing, openrouter_pricing, usage
from zylch.llm.budget_pricing import BudgetError, request_bound
from zylch.llm.roles import prices

ROLES = Path(prices.__file__).resolve().parent
D = Decimal

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
MESSAGES = [{"role": "user", "content": "Price this request."}]


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
    for model, rate in TODAY[transport].items():
        assert prices.price(model, transport) == rate, model
        assert _bound(model, transport) == _expected_hold(model, transport), model
    module = budget_pricing.PRICES if transport == "direct" else openrouter_pricing.RATES
    assert {m: module[m] for m in TODAY[transport]} == TODAY[transport]


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
            assert prices.price(model, transport) == (billed or table), where
            hold = _bound(model, transport)
            assert hold == _expected_hold(model, transport) and hold > 0, where
            seen += 1
    assert seen >= 2 * 16 * 3  # both presets, sixteen roles, three rows each


def test_table_picks_are_priced_at_the_table_s_price():
    """A pin of today's table: a price change here is a reviewed table change."""
    assert prices.price("z-ai/glm-5.3-flash", "openrouter") == (D("0.15"), D("0.5"))
    assert prices.price("xiaomi/mimo-v2.6-flash", "openrouter") == (D("0.14"), D("0.28"))
    assert prices.price("qwen/qwen3.8-max-0902", "openrouter") == (D("2"), D("6"))
    assert prices.price("claude-sonnet-5-5", "direct") == (D("2"), D("10"))
    assert prices.price("claude-opus-5-5", "direct") == (D("4"), D("20"))
    assert _bound("z-ai/glm-5.3-flash", "openrouter") == _expected_hold(
        "z-ai/glm-5.3-flash", "openrouter"
    )


def test_an_id_in_neither_source_is_refused_with_the_existing_message():
    assert prices.price("claude-fable-5", "direct") is None
    with pytest.raises(BudgetError) as direct:
        _bound("claude-fable-5", "direct")
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
    """The brief's assumption 4: a direct id and its `anthropic/*` route cost the same."""
    pairs = {(d, _catalogue_form(d)) for d in prices.priced("direct")}
    pairs |= {
        (r["direct_id"], r["catalogue_id"]) for *_, r in _resolved_rows() if r.get("direct_id")
    }
    compared = 0
    for direct_id, catalogue_id in sorted(pairs):
        routed = prices.price(catalogue_id, "openrouter")
        if routed is not None:
            assert prices.price(direct_id, "direct") == routed, (direct_id, catalogue_id)
            compared += 1
    assert compared >= 6  # opus-5, sonnet-5, both haiku ids, sonnet-5-5, opus-5-5


def test_the_allowlist_s_billed_price_wins_over_the_table(monkeypatch):
    requirements = {
        "allowlist": {
            "vendor/both": {"transport": "openrouter", "price": {"input": "3", "output": "9"}},
            "claude-both": {"transport": "direct", "price": {"input": "1", "output": "2"}},
        }
    }
    resolved = {
        "presets": {
            "p": {
                "roles": {
                    "R": {
                        "catalogue_id": "vendor/both",
                        "direct_id": None,
                        "price": {"input": 7, "output": 70},
                        "anthropic_fallback": {
                            "catalogue_id": "anthropic/x",
                            "direct_id": "claude-both",
                            "price": {"input": 4, "output": 8},
                        },
                        "mrcall": {
                            "id": "vendor/only",
                            "catalogue_id": "vendor/only",
                            "direct_id": None,
                            "price": {"input": 0.5, "output": 1},
                        },
                    }
                }
            }
        }
    }
    files = {"requirements.json": requirements, "resolved.json": resolved}
    monkeypatch.setattr(prices, "_load", lambda name: files[name])
    prices.priced.cache_clear()
    try:
        assert prices.price("vendor/both", "openrouter") == (D("3"), D("9"))
        assert prices.price("claude-both", "direct") == (D("1"), D("2"))
        assert prices.price("vendor/only", "openrouter") == (D("0.5"), D("1"))
        assert prices.price("anthropic/x", "openrouter") == (D("4"), D("8"))
    finally:
        prices.priced.cache_clear()


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
