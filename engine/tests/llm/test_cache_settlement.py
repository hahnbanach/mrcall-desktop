"""Reported cache TTLs settle accurately without lowering admission bounds."""
import pytest

from zylch.llm.budget_pricing import BudgetError, usage_cost


def usage(**changes):
    return dict(input_tokens=10, output_tokens=10, cache_creation_input_tokens=100,
                cache_creation={"ephemeral_5m_input_tokens": 80,
                                "ephemeral_1h_input_tokens": 20}, **changes)


def test_ttl_split_charges_each_rate():
    cost, counts = usage_cost("claude-haiku-4-5", usage())
    assert cost == 200  # 10 + 50 + 100 + 40 micro USD
    assert counts["cache_creation_input_tokens"] == 100


def test_missing_split_retains_conservative_settlement():
    raw = usage()
    del raw["cache_creation"]
    assert usage_cost("claude-haiku-4-5", raw)[0] == 260


@pytest.mark.parametrize("split", [[], {"ephemeral_5m_input_tokens": 99},
                                   {"ephemeral_5m_input_tokens": True},
                                   {"ephemeral_5m_input_tokens": 100, "other": 1}])
def test_bad_split_cannot_release_liability(split):
    raw = usage()
    raw["cache_creation"] = split
    with pytest.raises(BudgetError):
        usage_cost("claude-haiku-4-5", raw)
