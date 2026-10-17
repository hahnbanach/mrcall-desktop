"""The run-time snapshot reader (`roles/catalogue.py`): metadata and prices for any id (brief D5, D9).

`metadata()` is what the request shape reads and `rates()` what the price
source will (slice S3); both answer at call time from the layers in force —
the snapshots the distribution puts in front (downloaded, last good) and the
build copy behind — taking an id from the first layer that holds it. Prices
pinned here come from a snapshot built from the committed 2026-10-02 capture,
never from the build copy, which the coordinator refreshes from live reads.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from zylch.llm.roles import candidates, catalogue, gates, snapshot

from .resolver_fixture import K3, OPUS, QWEN, SONNET, requirements, sources

D = Decimal


@pytest.fixture(scope="module")
def fixture_snapshot() -> dict:
    src = sources()
    rules = candidates.policy(requirements())
    return snapshot.build(src["catalogue"], src["endpoints"], rules, src["read_at"])


@pytest.fixture(autouse=True)
def build_copy_after_each_test():
    yield
    catalogue.set_layers()


@pytest.fixture
def pinned(fixture_snapshot):
    catalogue.set_layers(fixture_snapshot, build=False)
    return fixture_snapshot


def test_metadata_for_catalogue_direct_and_dated_ids(pinned):
    assert catalogue.metadata(OPUS) == pinned["models"][OPUS]["metadata"]
    assert catalogue.metadata("claude-opus-5-5") == pinned["direct"]["claude-opus-5-5"]["metadata"]
    dated = catalogue.metadata("claude-opus-4-5-20251101")
    assert dated == pinned["direct"]["claude-opus-4-5"]["metadata"]
    assert catalogue.metadata("claude-haiku-4-5-20251001")["reasoning"]["mandatory"] is False
    for unknown in ("claude-opus-6", "claude-opus-6-20270101", "vendor/none-1", "", None):
        assert catalogue.metadata(unknown) is None
    assert catalogue.metadata("~anthropic/claude-opus-latest")["context_length"] == 1000000


def test_metadata_is_a_copy_of_the_exact_shape(pinned):
    meta = catalogue.metadata(SONNET)
    assert set(meta) == {
        "reasoning",
        "parameters",
        "forced_tool",
        "structured_outputs",
        "context_length",
        "expiration_date",
    }
    assert set(meta["reasoning"]) == {"mandatory", "efforts", "default_enabled"}
    meta["reasoning"]["efforts"].clear()
    assert catalogue.metadata(SONNET)["reasoning"]["efforts"] == [
        "max",
        "xhigh",
        "high",
        "medium",
        "low",
    ]


def test_rates_per_transport(pinned):
    assert catalogue.rates(SONNET, "openrouter") == (D(2), D(10))
    assert catalogue.rates("claude-sonnet-5-5", "direct") == (D(2), D(10))
    assert catalogue.rates("claude-opus-4-5-20251101", "direct") == (D(5), D(25))
    assert catalogue.rates(K3, "openrouter") == (D("2.7"), D("13.5"))
    assert catalogue.rates(SONNET, "direct") is None  # a catalogue id is not a direct id
    assert catalogue.rates("claude-sonnet-5-5", "openrouter") is None
    assert catalogue.rates("openrouter/auto", "openrouter") is None  # a variable price
    assert catalogue.rates("claude-opus-4-1", "direct") is None  # no anthropic endpoint
    full = catalogue.pricing(QWEN, "openrouter")
    assert full == {"input": D(2), "output": D(6), "cache_read": D("0.25"), "cache_write": D("2.5")}
    with pytest.raises(ValueError, match="Unknown priced transport"):
        catalogue.rates(SONNET, "mrcall")


def test_k3s_pinned_endpoint_and_the_policy(pinned):
    assert catalogue.endpoint_rates(K3, "digitalocean") == (D("2.55"), D("12.95"))
    assert catalogue.endpoint_rates(K3, "inference-net/fp4") is None  # not admitted
    assert catalogue.endpoint_rates("vendor/none-1", "digitalocean") is None
    assert catalogue.policy()["margin"] == D("1.25")


def test_a_front_layer_answers_first_and_an_older_one_keeps_an_id(fixture_snapshot):
    newer = copy.deepcopy(fixture_snapshot)
    newer["models"][K3]["pricing"]["output"] = "14"
    del newer["models"][QWEN]
    del newer["direct"]["claude-sonnet-5-5"]
    newer = gates.stamped(newer)
    catalogue.set_layers(newer, fixture_snapshot, build=False)
    assert catalogue.rates(K3, "openrouter") == (D("2.7"), D("14"))
    assert catalogue.rates(QWEN, "openrouter") == (D(2), D(6))  # from the older copy
    assert catalogue.rates("claude-sonnet-5-5", "direct") == (D(2), D(10))
    catalogue.set_layers(newer, build=False)
    assert catalogue.rates(QWEN, "openrouter") is None and catalogue.metadata(QWEN) is None


def test_a_price_read_after_the_layers_change_sees_the_change(fixture_snapshot):
    catalogue.set_layers(fixture_snapshot, build=False)
    before = catalogue.rates(K3, "openrouter")
    dearer = copy.deepcopy(fixture_snapshot)
    dearer["models"][K3]["pricing"]["input"] = "3"
    catalogue.set_layers(gates.stamped(dearer), build=False)
    assert before == (D("2.7"), D("13.5")) and catalogue.rates(K3, "openrouter") == (
        D(3),
        D("13.5"),
    )


def test_the_build_copy_is_the_last_layer():
    assert catalogue.layers() == (catalogue._build(),)
    gates.check_snapshot(catalogue._build())
    assert catalogue.rates("claude-sonnet-5-5", "direct") is not None
    assert catalogue.metadata(SONNET) is not None
    front = {"models": {}, "direct": {}}
    catalogue.set_layers(front)
    assert catalogue.layers() == (front, catalogue._build())
    assert catalogue.metadata(SONNET) is not None  # answered by the build copy behind
    catalogue.set_layers(front, build=False)
    assert catalogue.metadata(SONNET) is None
