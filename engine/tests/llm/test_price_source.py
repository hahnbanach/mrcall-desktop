"""Milestone 10a slice 4: one price source, and nobody unpriced on upgrade.

`zylch/llm/roles/prices.py` prices an id on a transport; `budget_pricing.PRICES`,
`openrouter_pricing.RATES` and `usage.estimate_cost_usd` read it. The
literals below are the rates every model billed today was billed at before
the table existed: the contract that the upgrade changes no profile's price.

Since milestone 10 slice S3 the source is the model snapshot (brief D5), and
since the switch-over (slice S6) the only one: 10a's allowlist and resolved
table are gone, and the models the table ranks are those of the table in
force (the fixture table the root conftest puts in force). Every price here is
read from the committed fixture snapshot as 10a billed it (`billed_snapshot`:
the 2026-10-02 capture, whose rates are 10a's for every id below but two
OpenRouter rates, put back), never from the build copy. The direct rates and
holds are unchanged. On OpenRouter the hold and the cap use the rate × the
margin (1.25). The hold covers the larger original or dispatched body,
including the explicit policy that disables context compression.
"""

import json
import re
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import pytest

from zylch.llm import budget_pricing, openrouter_pricing, usage
from zylch.llm.budget_pricing import BudgetError, request_bound
from zylch.llm.openrouter_client import messages_request
from zylch.llm.roles import catalogue, prices, table

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
MESSAGES = [{"role": "user", "content": "Price this request."}]


@pytest.fixture(autouse=True)
def snapshot_as_billed(billed_snapshot):
    """Every price below is read from the fixture snapshot as 10a billed it."""
    yield billed_snapshot


def _json(name):
    return json.loads((ROLES / name).read_text(encoding="utf-8"))


def _ranked_rows():
    """``(preset, role, column, entry)`` for every entry of both rankings of
    the table in force (the fixture table: `model_table_fixture`)."""
    for preset, body in table.document()["presets"].items():
        for role, record in body["roles"].items():
            for column in ("ranking", "anthropic_ranking"):
                for entry in record[column]:
                    yield preset, role, column, entry


def _snapshot_rate(snapshot, model, transport):
    """`model`'s pair as the snapshot document itself states it (not through the source)."""
    row = snapshot["direct" if transport == "direct" else "models"][model]
    return D(row["pricing"]["input"]), D(row["pricing"]["output"])


def _expected_hold(model, transport, max_tokens=1000):
    """The hold `request_bound` must take, from the price source's rate."""
    request = {"model": model, "max_tokens": max_tokens, "messages": MESSAGES}
    payload = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    if transport == "openrouter":
        payload = max(
            payload, len(json.dumps(messages_request(request), ensure_ascii=False).encode("utf-8"))
        )
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
    # 10a's allowlist, which listed exactly these ids, is gone (slice S6, brief
    # D1); the snapshot still prices every one of them at today's rate.
    assert "allowlist" not in _json("requirements.json")
    for model, rate in TODAY[transport].items():
        assert prices.price(model, transport) == rate, model
        assert _bound(model, transport) == _expected_hold(model, transport), model
    module = budget_pricing.PRICES if transport == "direct" else openrouter_pricing.RATES
    assert {m: module[m] for m in TODAY[transport]} == TODAY[transport]


def test_every_ranked_model_prices_a_request_on_its_transport(snapshot_as_billed):
    seen = 0
    for preset, role, column, entry in _ranked_rows():
        where = (preset, role, column)
        pairs = [("openrouter", entry["id"])]
        if entry.get("direct_id"):
            pairs.append(("direct", entry["direct_id"]))
        for transport, model in pairs:
            stated = _snapshot_rate(snapshot_as_billed, model, transport)
            assert prices.price(model, transport) == stated, where
            assert TODAY[transport].get(model, stated) == stated, where  # 10a's rate where billed
            hold = _bound(model, transport)
            assert hold == _expected_hold(model, transport) and hold > 0, where
            seen += 1
    assert seen >= 2 * 16 * 2  # both presets, sixteen roles, both rankings at least once each


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
    """The brief's assumption 4: a direct id and its `anthropic/*` route cost the same."""
    pairs = {(d, _catalogue_form(d)) for d in prices.priced("direct")}
    pairs |= {(e["direct_id"], e["id"]) for *_, e in _ranked_rows() if e.get("direct_id")}
    compared = 0
    for direct_id, catalogue_id in sorted(pairs):
        routed = prices.price(catalogue_id, "openrouter")
        if routed is not None:
            assert prices.price(direct_id, "direct") == routed, (direct_id, catalogue_id)
            compared += 1
    assert compared >= 6  # opus-5, sonnet-5, both haiku ids, sonnet-5-5, opus-5-5


def _priced_row(i, o):
    return {"pricing": {"input": i, "output": o, "cache_read": None, "cache_write": None}}


def test_only_a_snapshot_prices_an_id_whatever_10a_billed(monkeypatch):
    """Slice S3 replaced 10a's rule (the allowlist's billed price won over the
    table): an id a snapshot prices is priced by the snapshot, whatever the
    allowlist billed. Since the switch-over (slice S6, brief D1: the allowlist
    and its frozen prices removed) nothing else prices an id: a requirements
    file that still carried an allowlist, or a resolved table beside it, prices
    nothing, so an id no snapshot layer lists is unpriced on every transport."""
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
    catalogue.set_layers(layer, build=False)
    assert prices.price("vendor/both", "openrouter") == (D("7"), D("70"))
    assert prices.price("claude-both", "direct") == (D("4"), D("8"))
    # 10a billed it at 0.5/1; no snapshot lists it: unpriced (it was priced before S6).
    assert prices.price("vendor/only", "openrouter") is None
    assert prices.price("vendor/only", "direct") is None
    assert prices.price("anthropic/x", "openrouter") == (D("4"), D("8"))
    assert prices.price("vendor/table-row-only", "openrouter") is None
    assert dict(prices.priced("openrouter")) == {
        "vendor/both": (D("7"), D("70")),
        "anthropic/x": (D("4"), D("8")),
    }


def test_usage_estimates_a_table_pick_at_its_table_price():
    million = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert usage.estimate_cost_usd("xiaomi/mimo-v2.6-flash", million) == pytest.approx(0.42)
    assert usage.estimate_cost_usd("z-ai/glm-5.3-flash", million) == pytest.approx(0.65)
    assert usage.estimate_cost_usd("z-ai/glm-5.2", million) == pytest.approx(2.6)
    # Sonnet 5 at its own 2/10, not the sonnet family's 3/15.
    assert usage.estimate_cost_usd("claude-sonnet-5", million) == pytest.approx(12.0)
    for _, _, _, entry in _ranked_rows():
        for transport, model in (("openrouter", entry["id"]), ("direct", entry["direct_id"])):
            if model:
                i, o = prices.price(model, transport)
                assert usage.estimate_cost_usd(model, million) == pytest.approx(float(i + o))
