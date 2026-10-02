"""Resolver v2: the snapshot builder (`roles/snapshot.py`) on the 2026-10-02 capture (brief D5).

The snapshot prices and describes every catalogue entry, so a model a
profile saved keeps running whatever the picks are; its metadata has the
exact shape the request shape (slice S1) reads; the direct ids are priced
from the `anthropic` endpoint, which must equal Anthropic's list price
(material assumption 4: this file fails when they diverge); K3's pinned
endpoint is there for its cap. Prices pinned here come from the committed
capture, never from the build copy, which the coordinator refreshes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from zylch.llm.roles import candidates, gates, snapshot

from .resolver_fixture import (
    HAIKU,
    K3,
    OPUS,
    QWEN,
    READ_AT,
    SONNET,
    by_id,
    endpoint,
    entry,
    requirements,
    sources,
)

# Anthropic's list prices (input, output per million) as 10a's price test
# records them, for the direct ids the capture prices.
ANTHROPIC_LIST = {
    "claude-opus-5": ("5", "25"),
    "claude-opus-4-7": ("5", "25"),
    "claude-opus-4-6": ("5", "25"),
    "claude-opus-4-5": ("5", "25"),
    "claude-sonnet-5": ("2", "10"),
    "claude-sonnet-4-6": ("3", "15"),
    "claude-sonnet-4-5": ("3", "15"),
    "claude-haiku-4-5": ("1", "5"),
}
METADATA = {
    "reasoning",
    "parameters",
    "forced_tool",
    "structured_outputs",
    "context_length",
    "expiration_date",
}


@pytest.fixture(scope="module")
def built() -> dict:
    src = sources()
    rules = candidates.policy(requirements())
    return snapshot.build(src["catalogue"], src["endpoints"], rules, src["read_at"])


def test_the_snapshot_covers_every_entry_and_passes_its_gates(built):
    gates.check_snapshot(built)
    src = sources()
    assert (
        set(built["models"]) == {e["id"] for e in src["catalogue"]} and len(built["models"]) == 464
    )
    assert built["read_at"] == READ_AT and built["schema"] == 1
    assert built["policy"]["margin"] == "1.25" and built["policy"][
        "excluded_endpoint_variants"
    ] == ["flex"]
    read = {m for m, row in built["models"].items() if row["endpoints"] is not None}
    assert read == set(src["endpoints"]) and len(read) == 218


def test_metadata_has_exactly_the_shape_the_request_shape_reads(built):
    rows = [row["metadata"] for row in built["models"].values()]
    rows += [row["metadata"] for row in built["direct"].values()]
    for meta in rows:
        assert set(meta) == METADATA
        assert set(meta["reasoning"]) == {"mandatory", "efforts", "default_enabled"}
        assert isinstance(meta["reasoning"]["mandatory"], bool)
        assert all(isinstance(e, str) for e in meta["reasoning"]["efforts"])
        assert meta["reasoning"]["default_enabled"] in (True, False, None)
        assert meta["parameters"] == sorted(set(meta["parameters"]))
        assert isinstance(meta["forced_tool"], bool)
        assert meta["structured_outputs"] is ("structured_outputs" in meta["parameters"])
        assert meta["context_length"] is None or type(meta["context_length"]) is int
        assert meta["expiration_date"] is None or isinstance(meta["expiration_date"], str)


def test_parameters_are_the_intersection_over_the_admitted_endpoints(built):
    src = sources()
    rules = candidates.policy(requirements())
    sonnet = by_id(src["catalogue"])[SONNET]
    listed = candidates.admitted(sonnet, src["endpoints"][SONNET], rules)
    common = set.intersection(*(set(e["supported_parameters"]) for e in listed))
    assert built["models"][SONNET]["metadata"]["parameters"] == sorted(common)
    # The catalogue lists structured outputs; one admitted endpoint lacks them.
    assert "structured_outputs" in sonnet["supported_parameters"]
    assert built["models"][SONNET]["metadata"]["structured_outputs"] is False
    # Not read (an alias): the model-level list.
    alias = by_id(src["catalogue"])["~anthropic/claude-opus-latest"]
    meta = built["models"]["~anthropic/claude-opus-latest"]["metadata"]
    assert meta["parameters"] == sorted(set(alias["supported_parameters"]))
    assert meta["forced_tool"] is False


def test_forced_tool_needs_an_admitted_endpoint_that_accepts_a_named_choice(built):
    assert built["models"]["anthropic/claude-sonnet-5"]["metadata"]["forced_tool"] is True
    assert built["models"][OPUS]["metadata"]["forced_tool"] is False
    assert built["models"][QWEN]["metadata"]["forced_tool"] is False
    rules = candidates.policy(requirements())
    named = {"auto": True, "function": True, "none": True, "required": True}
    auto = {"auto": True, "function": False, "none": True, "required": False}
    down = endpoint("acme/a", status=-2, supports_tool_choice=named)
    up = endpoint("acme/b", supports_tool_choice=auto)
    model = entry()
    built_one = snapshot.build([model], {model["id"]: [down, up]}, rules, READ_AT)
    assert built_one["models"][model["id"]]["metadata"]["forced_tool"] is False
    built_two = snapshot.build(
        [model], {model["id"]: [down, {**up, "supports_tool_choice": named}]}, rules, READ_AT
    )
    assert built_two["models"][model["id"]]["metadata"]["forced_tool"] is True


def test_reasoning_is_as_published(built):
    opus = built["models"][OPUS]["metadata"]["reasoning"]
    assert opus == {
        "mandatory": True,
        "efforts": ["max", "xhigh", "high", "medium", "low"],
        "default_enabled": None,
    }
    assert built["models"][K3]["metadata"]["reasoning"] == {
        "mandatory": False,
        "efforts": ["max", "high", "low"],
        "default_enabled": True,
    }
    src = sources()
    plain = next(e for e in src["catalogue"] if "reasoning" not in e)
    assert built["models"][plain["id"]]["metadata"]["reasoning"] == {
        "mandatory": False,
        "efforts": [],
        "default_enabled": None,
    }


def test_direct_ids_are_priced_from_the_anthropic_endpoint_at_the_list_price(built):
    src = sources()
    assert len(built["direct"]) == 13 and "claude-opus-4-1" not in built["direct"]
    for direct, row in built["direct"].items():
        own = [e for e in src["endpoints"][row["catalogue_id"]] if e["tag"] == "anthropic"]
        assert row["pricing"] == snapshot.pricing(own[0]["pricing"]), direct
        assert row["pricing"] == built["models"][row["catalogue_id"]]["pricing"], direct
        assert gates.direct_id(row["catalogue_id"]) == direct
    for direct, (prompt, completion) in ANTHROPIC_LIST.items():
        pricing = built["direct"][direct]["pricing"]
        assert (pricing["input"], pricing["output"]) == (prompt, completion), direct
    assert built["direct"]["claude-sonnet-5-5"]["metadata"]["structured_outputs"] is True
    assert built["direct"]["claude-haiku-4-5"]["catalogue_id"] == HAIKU  # priced, never ranked


def test_a_direct_id_takes_its_own_endpoint_whatever_its_status():
    rules = candidates.policy(requirements())
    model = entry(
        "anthropic/claude-test-1.5", pricing={"prompt": "0.000003", "completion": "0.000015"}
    )
    own = endpoint(
        "anthropic",
        status=-2,
        pricing={"prompt": "0.000002", "completion": "0.00001"},
        supported_parameters=["structured_outputs", "tools"],
        context_length=1000000,
    )
    other = endpoint("acme", pricing={"prompt": "0.000003", "completion": "0.000015"})
    built_one = snapshot.build([model], {model["id"]: [other, own]}, rules, READ_AT)
    direct = built_one["direct"]["claude-test-1-5"]
    assert (direct["pricing"]["input"], direct["pricing"]["output"]) == ("2", "10")
    assert direct["metadata"]["parameters"] == ["structured_outputs", "tools"]
    assert direct["metadata"]["context_length"] == 1000000
    assert [row["tag"] for row in built_one["models"][model["id"]]["endpoints"]] == ["acme"]
    unread = snapshot.build([model], {}, rules, READ_AT)
    assert unread["direct"] == {} and unread["models"][model["id"]]["endpoints"] is None


def test_k3s_pinned_endpoint_is_admitted_for_its_cap(built):
    rows = {row["tag"]: row for row in built["models"][K3]["endpoints"]}
    assert rows["digitalocean"]["pricing"]["input"] == "2.55"
    assert rows["digitalocean"]["pricing"]["output"] == "12.95"
    assert all(row["quantization"] not in ("fp4", "mxfp4") for row in rows.values())


def test_endpoint_rows_are_sorted_and_each_once(built):
    src = sources()
    payload = [e["tag"] for e in src["endpoints"]["z-ai/glm-5.3-flash"]]
    assert payload.count("baseten/fp8") == 2
    rows = built["models"]["z-ai/glm-5.3-flash"]["endpoints"]
    tags = [row["tag"] for row in rows]
    assert tags.count("baseten/fp8") == 1 and tags == sorted(tags)


def test_aliases_and_expiring_models_keep_a_price(built):
    alias = built["models"]["~anthropic/claude-haiku-latest"]
    assert (alias["pricing"]["input"], alias["pricing"]["output"]) == ("1", "5")
    assert alias["endpoints"] is None
    expiring = built["models"]["qwen/qwen3-max"]
    assert expiring["metadata"]["expiration_date"] == "2026-10-09"
    assert expiring["pricing"]["output"] is not None


def test_prices_are_canonical_decimal_strings():
    assert snapshot.pricing({"prompt": "0.000004", "completion": "0.00002"}) == {
        "input": "4",
        "output": "20",
        "cache_read": None,
        "cache_write": None,
    }
    assert (
        snapshot.pricing({"prompt": "0.00000002625", "completion": "2.5e-7"})["input"] == "0.02625"
    )
    assert snapshot.pricing({"prompt": "0", "completion": "-1"}) == {
        "input": "0",
        "output": None,
        "cache_read": None,
        "cache_write": None,
    }
    assert snapshot.text(Decimal("-0")) == "0" and snapshot.text(Decimal("12.9500")) == "12.95"
    assert snapshot.text(None) is None
