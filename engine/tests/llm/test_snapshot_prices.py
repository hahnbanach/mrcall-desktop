"""Prices from the model snapshot (milestone 10, slice S3; brief D5, AC 4).

`roles/prices.py` reads the snapshot layers in force at every call
(`catalogue.rates`): a catalogue id at its model-level price on OpenRouter, a
direct id at its `anthropic` endpoint's price, a dated direct id as its alias.
`budget_pricing.PRICES` and `openrouter_pricing.RATES` / `LABELS` are views
over it, never copies made at import. On OpenRouter the reservation and
`max_price` are the price × the margin of `requirements.json`, and the
provider object also carries its quantizations and, where the snapshot read a
model's endpoints, `only` its admitted ones — the billing server's object for
the same model and snapshot. K3 is capped at its pinned endpoint's price ×
the margin, or its model-level price × the margin on a day that endpoint is
not admitted. The direct transport reserves at the list price. A `:free` id
the catalogue prices at 0 is held at 0 and capped at 0, never refused.

Every price is read from the committed fixture snapshot (`price_fixture`, the
2026-10-02 capture) or a variant derived from it, never from the build copy.
"""

from __future__ import annotations

import copy
import json
import logging
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from zylch.llm import k3_reasoning as k3
from zylch.llm import request_shape
from zylch.llm.budget import budget_snapshot
from zylch.llm.budget_pricing import PRICES, BudgetError, validate_response_model
from zylch.llm.budget_pricing import request_bound as direct_bound
from zylch.llm.client import LLMClient
from zylch.llm.model_policy import resolve_model
from zylch.llm.openrouter_pricing import LABELS, RATES, capped, provider_policy
from zylch.llm.openrouter_pricing import request_bound as routed_bound
from zylch.llm.roles import candidates, catalogue, gates, prices, table
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage

from . import price_fixture as fx
from .resolver_fixture import READ_AT, requirements, sources

D = Decimal
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
MESSAGES = [{"role": "user", "content": "Price this request."}]
OWNER = "uid-s3"


def _payload_tokens(request: dict) -> int:
    payload = len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return payload + 4096 + 1024 * (len(request["messages"]) + len(request.get("tools") or []))


def _ceil(amount: Decimal) -> int:
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def _direct_hold(request: dict, i: Decimal, o: Decimal) -> int:
    """`budget_pricing.request_bound`'s hold at the list price (no margin)."""
    return _ceil(_payload_tokens(request) * i * 2 + request["max_tokens"] * o)


def _routed_hold(request: dict, i: Decimal, o: Decimal) -> int:
    """`openrouter_pricing.request_bound`'s hold at a model-level price × 1.25."""
    i, o = i * D("1.25"), o * D("1.25")
    if request["model"].startswith("anthropic/"):
        i *= 2
    return _ceil(_payload_tokens(request) * i + request["max_tokens"] * o)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A disposable profile with its own SQLite ledger and a saved $5 budget."""
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", OWNER)
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    env = tmp_path / ".env"
    env.write_text("LLM_DAILY_BUDGET_USD=5\n")
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmUsage.__table__, LlmReservation.__table__]
    )
    yield env
    database.dispose_engine()


def _direct_client(model: str, answered_as: str, usage: dict) -> LLMClient:
    client = LLMClient(transport="direct", api_key="fake", model=model)
    client._client.messages.create = Mock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            model=answered_as,
            stop_reason="end_turn",
            usage=SimpleNamespace(**usage),
        )
    )
    return client


# ─── The fixture ──────────────────────────────────────────────────────


def test_the_fixture_is_the_capture_s_snapshot_and_passes_the_gates():
    committed = fx.fixture()
    assert committed == fx.select(fx.built())
    gates.check_snapshot(committed)
    assert committed["read_at"] == READ_AT
    for variant in (fx.successor(committed), fx.as_billed_by_10a(committed)):
        gates.check_snapshot(variant)


# ─── A saved model keeps running (AC 4, first clause) ─────────────────


@pytest.fixture
def successor_is_the_pick(price_snapshot, monkeypatch):
    """A newer Sonnet in the snapshot, and 10a's table picking it wherever it
    picked Sonnet 5.5 (the pick path stays 10a's until the switch-over)."""
    newer = fx.successor(price_snapshot)
    catalogue.set_layers(newer, build=False)
    text = json.dumps(table._load("resolved.json"))
    text = text.replace(f'"{fx.SONNET}"', f'"{fx.SUCCESSOR}"')
    text = text.replace('"claude-sonnet-5-5"', f'"{fx.SUCCESSOR_DIRECT}"')
    resolved, real = json.loads(text), table._load
    monkeypatch.setattr(
        table, "_load", lambda name: resolved if name == "resolved.json" else real(name)
    )
    return newer


def test_a_saved_sonnet_stays_priced_shaped_and_running_after_a_successor(
    successor_is_the_pick, ledger
):
    ledger.write_text(
        "LLM_DAILY_BUDGET_USD=5\nLLM_PROVIDER=anthropic\nANTHROPIC_API_KEY=fake\n"
        "LLM_MODEL_PRESET=economy\nMODEL_MNEMONIC=claude-sonnet-5-5\n"
    )
    # The successor is the pick; the saved model is still what its role runs.
    assert table.pick("economy", "MNEMONIC", "anthropic") == fx.SUCCESSOR_DIRECT
    assert resolve_model("MODEL_MEMORY_MERGE") == fx.SUCCESSOR_DIRECT
    saved = resolve_model("MODEL_MNEMONIC")
    assert saved == "claude-sonnet-5-5"
    # Priced, on both transports, at its own snapshot price.
    assert PRICES[saved] == (D(2), D(10))
    assert PRICES[fx.SUCCESSOR_DIRECT] == (D(3), D(15))
    assert RATES[fx.SONNET] == (D(2), D(10))
    assert capped(fx.SONNET) == (D("2.5"), D("12.5"))
    # Shaped from its own metadata: mandatory reasoning at the lowest effort.
    sent = request_shape.shaped({"model": saved, "max_tokens": 64, "messages": MESSAGES})
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "low"}
    # Running: reserved at that price, dispatched, settled.
    client = _direct_client(saved, saved, {"input_tokens": 1000, "output_tokens": 100})
    result = client.create_message_sync(messages=MESSAGES, max_tokens=64)
    assert result.content[0].text == "ok"
    assert client._client.messages.create.call_args.kwargs["model"] == saved
    state = budget_snapshot(OWNER)
    assert state["reserved_usd"] == 0
    assert state["spent_usd"] == pytest.approx((1000 * 2 + 100 * 10) / 1e6)


def test_a_saved_sonnet_stays_priced_while_an_older_layer_still_lists_it(price_snapshot):
    # A newer snapshot no longer lists Sonnet 5.5: the older layer behind it
    # still prices the saved id (brief D5: refuse only an id in none of them).
    newest = copy.deepcopy(fx.successor(price_snapshot))
    del newest["models"][fx.SONNET]
    del newest["direct"]["claude-sonnet-5-5"]
    newest = gates.stamped(newest)
    catalogue.set_layers(newest, price_snapshot, build=False)
    assert PRICES["claude-sonnet-5-5"] == (D(2), D(10))
    assert RATES[fx.SONNET] == (D(2), D(10))
    catalogue.set_layers(newest, build=False)
    assert "claude-sonnet-5-5" not in PRICES
    request = {"model": "claude-sonnet-5-5", "max_tokens": 64, "messages": MESSAGES}
    with pytest.raises(BudgetError, match="model pricing is not configured for this model"):
        direct_bound(request, "direct")


# ─── A changed snapshot price moves the reservation ───────────────────


def test_a_changed_snapshot_price_moves_the_reservation(price_snapshot):
    direct = {"model": "claude-sonnet-5-5", "max_tokens": 1000, "messages": MESSAGES}
    routed = {"model": fx.GLM_5_2, "max_tokens": 1000, "messages": MESSAGES}
    claude = {"model": fx.SONNET, "max_tokens": 1000, "messages": MESSAGES}
    before = [direct_bound(direct, "direct"), routed_bound(routed), routed_bound(claude)]
    assert before == [
        _direct_hold(direct, D(2), D(10)),
        _routed_hold(routed, D("0.41"), D("3.99")),
        _routed_hold(claude, D(2), D(10)),
    ]
    dearer = fx.priced_at(price_snapshot, fx.GLM_5_2, input="0.9", output="4.5")
    dearer = fx.priced_at(dearer, fx.SONNET, input="3", output="15")
    dearer["direct"]["claude-sonnet-5-5"]["pricing"].update(input="3", output="15")
    catalogue.set_layers(gates.stamped(dearer), build=False)
    after = [direct_bound(direct, "direct"), routed_bound(routed), routed_bound(claude)]
    assert after == [
        _direct_hold(direct, D(3), D(15)),
        _routed_hold(routed, D("0.9"), D("4.5")),
        _routed_hold(claude, D(3), D(15)),
    ]
    assert all(a > b for a, b in zip(after, before))


# ─── Direct prices are the `anthropic` endpoint's ─────────────────────


def test_direct_prices_equal_the_anthropic_endpoint_s(price_snapshot):
    """Read from the capture's raw endpoint lists, not from the snapshot."""
    raw = sources()["endpoints"]
    compared = 0
    for direct_id, row in price_snapshot["direct"].items():
        own = [e for e in raw[row["catalogue_id"]] if e.get("tag") == "anthropic"]
        assert len(own) == 1, direct_id
        listed = tuple(
            candidates.per_million(own[0]["pricing"][k]) for k in ("prompt", "completion")
        )
        assert PRICES[direct_id] == listed, direct_id
        compared += 1
    assert compared == 13
    # The eleven direct ids billed before the snapshot keep their rate.
    billed = requirements()["allowlist"]
    for model, row in billed.items():
        if row["transport"] == "direct":
            assert PRICES[model] == (D(row["price"]["input"]), D(row["price"]["output"])), model


# ─── A dated snapshot settles as its alias ────────────────────────────


def test_claude_opus_4_5_settles_when_answered_as_claude_opus_4_5_20251101(price_snapshot, ledger):
    usage = {"input_tokens": 2000, "output_tokens": 300}
    client = _direct_client("claude-opus-4-5", "claude-opus-4-5-20251101", usage)
    client.create_message_sync(messages=MESSAGES, max_tokens=64)
    state = budget_snapshot(OWNER)
    assert state["reserved_usd"] == 0
    assert state["spent_usd"] == pytest.approx((2000 * 5 + 300 * 25) / 1e6)
    # Another model's answer is refused, whatever its date.
    other = _direct_client("claude-opus-4-5", "claude-opus-4-6-20251101", usage)
    with pytest.raises(BudgetError, match="response model differs"):
        other.create_message_sync(messages=MESSAGES, max_tokens=64)
    assert other._client.messages.create.call_count == 1


@pytest.mark.parametrize(
    "requested, returned, settles",
    [
        ("claude-opus-4-5", "claude-opus-4-5", True),
        ("claude-opus-4-5", "claude-opus-4-5-20251101", True),
        ("claude-sonnet-5-5", "claude-sonnet-5-5-20260928", True),
        ("claude-opus-4-5", "claude-opus-4-5-2025110", False),
        ("claude-opus-4-5", "claude-opus-4-5-20251101-x", False),
        ("claude-opus-4-5", "claude-opus-4-6-20251101", False),
        ("claude-opus-4-5", "claude-opus-4-5-20251101\n", False),
        ("claude-opus-4-5", None, False),
    ],
)
def test_the_response_model_is_the_requested_id_or_its_dated_snapshot(requested, returned, settles):
    if settles:
        validate_response_model(requested, returned)
    else:
        with pytest.raises(BudgetError, match="response model differs"):
            validate_response_model(requested, returned)


def test_a_dated_direct_id_is_priced_as_its_alias(price_snapshot):
    # Not one of 10a's allowlisted dated ids: only the alias rule prices it.
    dated = "claude-sonnet-5-5-20260928"
    assert dated not in requirements()["allowlist"]
    assert PRICES[dated] == PRICES["claude-sonnet-5-5"] == (D(2), D(10))
    request = {"model": dated, "max_tokens": 64, "messages": MESSAGES}
    assert direct_bound(request, "direct") == _direct_hold(request, D(2), D(10))


# ─── Nothing is frozen at import ──────────────────────────────────────


def test_a_price_read_after_the_snapshot_layer_changes_sees_the_change(price_snapshot):
    # PRICES, RATES and LABELS were imported with this module, before this test.
    assert PRICES["claude-sonnet-5-5"] == (D(2), D(10))
    assert RATES[fx.SONNET] == (D(2), D(10))
    assert capped(fx.SONNET) == (D("2.5"), D("12.5"))
    assert fx.SUCCESSOR not in RATES and fx.SUCCESSOR not in LABELS
    newer = fx.priced_at(fx.successor(price_snapshot), fx.SONNET, input="3", output="15")
    newer["direct"]["claude-sonnet-5-5"]["pricing"].update(input="3", output="15")
    catalogue.set_layers(gates.stamped(newer), build=False)
    assert PRICES["claude-sonnet-5-5"] == (D(3), D(15))
    assert prices.price("claude-sonnet-5-5", "direct") == (D(3), D(15))
    assert RATES[fx.SONNET] == (D(3), D(15))
    assert capped(fx.SONNET) == (D("3.75"), D("18.75"))
    assert provider_policy(fx.SONNET)["max_price"]["completion"] == "18.75"
    assert PRICES[fx.SUCCESSOR_DIRECT] == (D(3), D(15))
    assert LABELS[fx.SUCCESSOR] == "Claude Sonnet 6 (Anthropic)"


# ─── OpenRouter: the price × the margin, and the provider policy ──────


def test_openrouter_holds_and_caps_at_the_snapshot_price_times_the_margin(price_snapshot):
    assert prices.margin() == D("1.25") == D(str(requirements()["margin"]))
    assert RATES[fx.GLM_5_2] == (D("0.41"), D("3.99"))
    assert capped(fx.GLM_5_2) == (D("0.5125"), D("4.9875"))
    assert provider_policy(fx.GLM_5_2)["max_price"] == {
        "prompt": "0.5125",
        "completion": "4.9875",
        "request": "0",
    }
    request = {"model": fx.GLM_5_2, "max_tokens": 1000, "messages": MESSAGES}
    assert routed_bound(request) == _ceil(
        _payload_tokens(request) * D("0.5125") + 1000 * D("4.9875")
    )
    # The direct transport reserves at the list price: no margin there.
    direct = {"model": "claude-sonnet-5-5", "max_tokens": 1000, "messages": MESSAGES}
    assert direct_bound(direct, "direct") == _ceil(
        _payload_tokens(direct) * D(2) * 2 + 1000 * D(10)
    )


def test_the_margin_is_requirements_json_s(price_snapshot, monkeypatch):
    real = prices._load
    doubled = {**real("requirements.json"), "margin": D(2)}
    monkeypatch.setattr(
        prices, "_load", lambda name: doubled if name == "requirements.json" else real(name)
    )
    assert RATES[fx.GLM_5_2] == (D("0.41"), D("3.99"))
    assert capped(fx.GLM_5_2) == (D("0.82"), D("7.98"))
    assert provider_policy(fx.GLM_5_2)["max_price"]["completion"] == "7.98"


def test_the_provider_policy_admits_requirements_quantizations_and_the_admitted_endpoints(
    price_snapshot,
):
    assert provider_policy(fx.FLEX) == {
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "price",
        "quantizations": ["int8", "fp8", "mxfp8", "fp16", "bf16", "fp32", "unknown"],
        "max_price": {"prompt": "2.5", "completion": "12.5", "request": "0"},
        "only": ["azure", "azure/eu", "azure/us", "openai"],
    }
    assert provider_policy(fx.FLEX)["quantizations"] == (
        requirements()["provider_policy"]["quantizations"]
    )
    # The capture lists a `flex` tier for this model, cheaper than every
    # admitted endpoint, which price sorting would pick: it is never routable.
    raw = {e["tag"]: e for e in sources()["endpoints"][fx.FLEX]}
    flex = candidates.per_million(raw["openai/flex"]["pricing"]["completion"])
    admitted = price_snapshot["models"][fx.FLEX]["endpoints"]
    assert flex < min(D(e["pricing"]["output"]) for e in admitted)
    assert "openai/flex" not in provider_policy(fx.FLEX)["only"]
    # Endpoints not read, or read with none admitted: no `only`, as the server.
    assert price_snapshot["models"][fx.UNREAD]["endpoints"] is None
    assert price_snapshot["models"][fx.NONE_ADMITTED]["endpoints"] == []
    for model in (fx.UNREAD, fx.NONE_ADMITTED):
        assert "only" not in provider_policy(model), model
        assert provider_policy(model)["quantizations"] == provider_policy(fx.FLEX)["quantizations"]


def test_the_provider_object_is_the_billing_server_s(price_snapshot):
    """`server_provider_2d81bb5.json` is what mrcall-agent model-table-m10
    2d81bb5's `bounded_openrouter.provider_policy` built from this snapshot."""
    server = json.loads((FIXTURES / "server_provider_2d81bb5.json").read_text(encoding="utf-8"))
    assert server["snapshot_version"] == price_snapshot["version"]
    assert {fx.FLEX, fx.UNREAD, fx.NONE_ADMITTED} <= set(server["providers"])
    for model, provider in server["providers"].items():
        assert provider_policy(model) == provider, model


def test_an_unpriced_openrouter_id_is_refused_with_today_s_message(price_snapshot):
    assert price_snapshot["models"][fx.VARIABLE]["pricing"]["output"] is None
    for model in (fx.VARIABLE, "vendor/unpriced-model"):
        assert model not in RATES
        request = {"model": model, "max_tokens": 64, "messages": MESSAGES}
        with pytest.raises(BudgetError) as refused:
            routed_bound(request)
        assert str(refused.value) == "AI paused: OpenRouter model has no verified price ceiling."


def test_a_saved_free_id_is_admitted_with_a_zero_hold_and_a_zero_cap(price_snapshot, ledger):
    """A `:free` catalogue id is priced at 0 like any snapshot price (the gates
    never rank it: they require positive prices). A saved one, on the personal
    OpenRouter key, is held at 0 and capped at `max_price` 0, so OpenRouter can
    route it only to a free endpoint; the billing server's refusal of
    non-positive prices is its own credits policy."""
    from zylch.llm.client import make_llm_client
    from zylch.llm.openrouter_client import OpenRouterClient

    ledger.write_text(
        "LLM_DAILY_BUDGET_USD=5\nLLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=fake\n"
        f"OPENROUTER_MODEL={fx.FREE}\n"
    )
    assert price_snapshot["models"][fx.FREE]["pricing"]["output"] == "0"
    assert RATES[fx.FREE] == (D(0), D(0))
    seen = []

    def upstream(request):
        with database.get_session() as session:
            holds = [row.reserved_micro_usd for row in session.query(LlmReservation)]
        seen.append((json.loads(request.content), holds))
        usage = {"input_tokens": 10, "output_tokens": 2, "cost": 0}
        return httpx.Response(
            200,
            json={
                "id": "free",
                "model": fx.FREE,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": usage,
            },
        )

    client = make_llm_client()
    assert (client.transport, client.model) == ("openrouter", fx.FREE)
    http = httpx.Client(transport=httpx.MockTransport(upstream))
    client._client = OpenRouterClient("fake", http_client=http)
    assert client.create_message_sync(messages=MESSAGES, max_tokens=64).content[0].text == "ok"
    ((body, holds),) = seen
    assert holds == [0]  # admitted, held at 0 while the call ran
    assert body["provider"]["max_price"] == {"prompt": "0", "completion": "0", "request": "0"}
    assert "only" not in body["provider"]  # a variant's endpoints are not read
    state = budget_snapshot(OWNER)
    assert (state["reserved_usd"], state["spent_usd"], state["pricing_fault"]) == (0, 0, False)


# ─── K3: its pinned endpoint's price × the margin ─────────────────────


K3_REQUEST = {
    "model": fx.K3,
    "messages": [{"role": "user", "content": "Price this request."}],
    "max_tokens": 8192,
    "thinking": {"type": "adaptive"},
    "output_config": {"effort": "max"},
}


def _k3_hold(i: Decimal, o: Decimal) -> int:
    """K3's reservation: the larger of the Messages and the Chat wire bounds."""
    plain = {k: v for k, v in K3_REQUEST.items() if k not in ("thinking", "output_config")}
    wire = k3.chat_request(K3_REQUEST)
    return max(
        _ceil(_payload_tokens(plain) * i + 8192 * o),
        _ceil(_payload_tokens(wire) * i + 8192 * o),
    )


def test_k3_is_capped_and_held_at_its_pinned_endpoint_s_price_times_the_margin(price_snapshot):
    assert catalogue.endpoint_rates(fx.K3, "digitalocean") == (D("2.55"), D("12.95"))
    assert k3.rates() == (D("2.55"), D("12.95"))
    assert RATES[fx.K3] == (D("2.55"), D("12.95"))
    assert capped(fx.K3) == (D("3.1875"), D("16.1875"))
    assert k3.provider_policy() == {
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "price",
        "max_price": {"prompt": "3.1875", "completion": "16.1875", "request": "0"},
        "only": ["digitalocean"],
    }
    assert k3.chat_request(K3_REQUEST)["provider"] == k3.provider_policy()
    assert routed_bound(K3_REQUEST) == _k3_hold(D("3.1875"), D("16.1875"))


def test_k3_s_cap_falls_back_to_its_model_level_price_when_its_endpoint_is_degraded(
    price_snapshot, caplog
):
    catalogue.set_layers(fx.degraded(price_snapshot, fx.K3, "digitalocean"), build=False)
    assert catalogue.endpoint_rates(fx.K3, "digitalocean") is None
    with caplog.at_level(logging.WARNING, logger="zylch.llm.k3_reasoning"):
        assert k3.rates() == (D("2.7"), D("13.5"))
    assert "falls back to the model-level price" in caplog.text
    assert RATES[fx.K3] == (D("2.7"), D("13.5"))
    assert capped(fx.K3) == (D("3.375"), D("16.875"))
    # Still priced and still pinned: a request its pin cannot route fails at
    # the provider, as it would today.
    assert k3.provider_policy() == {
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "price",
        "max_price": {"prompt": "3.375", "completion": "16.875", "request": "0"},
        "only": ["digitalocean"],
    }
    assert routed_bound(K3_REQUEST) == _k3_hold(D("3.375"), D("16.875"))
