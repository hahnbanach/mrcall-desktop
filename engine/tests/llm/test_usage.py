"""Unit tests for zylch.llm.usage — cost math, record(), and the cap.

Covers (support-llm-cost-fix / T1):
- estimate_cost_usd hand-computed against the price table, including the
  cache write/read multipliers and unknown-model -> Opus fallback;
- record() never raising when the DB is unavailable;
- record() persisting a row + today's running total;
- budget_state: over-budget -> exceeded; cap 0 -> never exceeded;
  and a live os.environ change flipping the result (proves the budget is
  read at call time, not from a frozen settings snapshot).
"""

from datetime import datetime, timedelta

import pytest

from zylch.llm import usage

# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB with the llm_usage table. Disposes on teardown."""
    db_path = tmp_path / "usage_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _seed(owner_id: str, est_cost_usd: float, *, days_ago: int = 0) -> None:
    """Insert one llm_usage row with a given cost and age (in UTC days)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import LlmUsage

    ts = datetime.utcnow() - timedelta(days=days_ago)
    with get_session() as s:
        s.add(
            LlmUsage(
                owner_id=owner_id,
                ts=ts,
                call_site="seed",
                transport="direct",
                model="claude-opus-4-6",
                input_tokens=0,
                output_tokens=0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                est_cost_usd=est_cost_usd,
            )
        )


# ─────────────────────────────────────────────────────────────────────
# Cost math
# ─────────────────────────────────────────────────────────────────────


def test_cost_opus_input_output():
    # Opus: 5 in / 25 out per MTok. 1M in + 1M out = 5 + 25 = $30.
    cost = usage.estimate_cost_usd(
        "claude-opus-4-6",
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )
    assert cost == pytest.approx(30.0)


def test_cost_sonnet_input_output():
    # Sonnet: 3 in / 15 out. 2M in + 1M out = 6 + 15 = $21.
    cost = usage.estimate_cost_usd(
        "claude-sonnet-4-5",
        {"input_tokens": 2_000_000, "output_tokens": 1_000_000},
    )
    assert cost == pytest.approx(21.0)


def test_cost_haiku_input_output():
    # Haiku: 1 in / 5 out. 1M in + 1M out = 1 + 5 = $6.
    cost = usage.estimate_cost_usd(
        "claude-haiku-4-5",
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )
    assert cost == pytest.approx(6.0)


def test_cost_cache_write_and_read_rates_opus():
    # Opus in_rate=5. Cache-write bills at 1.25x input, cache-read at 0.10x.
    #   input:       1000  * 5              = 5000
    #   output:       500  * 25             = 12500
    #   cache_write: 2000  * 5 * 1.25       = 12500
    #   cache_read: 10000  * 5 * 0.10       = 5000
    #   total 35000 / 1e6                    = $0.035
    cost = usage.estimate_cost_usd(
        "claude-opus-4-6",
        {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 2000,
            "cache_read_input_tokens": 10000,
        },
    )
    assert cost == pytest.approx(0.035)


def test_cost_unknown_model_bills_at_opus():
    usage_dict = {"input_tokens": 1_000_000}
    unknown = usage.estimate_cost_usd("claude-fable-5", usage_dict)
    opus = usage.estimate_cost_usd("claude-opus-4-6", usage_dict)
    sonnet = usage.estimate_cost_usd("claude-sonnet-4-5", usage_dict)
    # Unknown -> Opus pricing ($5), NOT the cheaper Sonnet ($3).
    assert unknown == pytest.approx(5.0)
    assert unknown == pytest.approx(opus)
    assert unknown != pytest.approx(sonnet)


@pytest.mark.parametrize("model", ["", None, "gpt-4o-mini"])
def test_cost_empty_or_foreign_model_bills_at_opus(model):
    # Empty / None / non-Anthropic id -> Opus (overestimate, never under).
    cost = usage.estimate_cost_usd(model, {"input_tokens": 1_000_000})
    assert cost == pytest.approx(5.0)


def test_cost_model_match_is_case_insensitive():
    cost = usage.estimate_cost_usd("Claude-3-5-SONNET", {"input_tokens": 1_000_000})
    assert cost == pytest.approx(3.0)  # sonnet input rate


def test_cost_empty_usage_is_zero():
    assert usage.estimate_cost_usd("claude-opus-4-6", {}) == pytest.approx(0.0)
    assert usage.estimate_cost_usd("claude-opus-4-6", None) == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────
# record()
# ─────────────────────────────────────────────────────────────────────


def test_record_never_raises_on_broken_db(monkeypatch):
    """A metering-store failure can never break an LLM call."""
    import zylch.storage.database as db_mod

    def boom(*a, **k):
        raise RuntimeError("db is down")

    monkeypatch.setattr(db_mod, "get_session", boom)

    # Must return normally despite the DB being unavailable.
    usage.record(
        "claude-opus-4-6",
        "direct",
        {"input_tokens": 10, "output_tokens": 5},
    )


def test_record_never_raises_on_junk_usage(fresh_db, monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "rec-junk@example.com")
    # None usage dict and a weird model must not raise.
    usage.record("claude-opus-4-6", "direct", None)
    usage.record(None, "proxy", {"input_tokens": "not-a-number"})


def test_record_persists_row_and_updates_today(fresh_db, monkeypatch):
    owner = "rec-owner@example.com"
    monkeypatch.setenv("EMAIL_ADDRESS", owner)

    assert usage.spent_today_usd(owner) == pytest.approx(0.0)

    # Opus 1M in + 1M out = $30.
    usage.record(
        "claude-opus-4-6",
        "direct",
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )

    from zylch.storage.database import get_session
    from zylch.storage.models import LlmUsage

    with get_session() as s:
        rows = s.query(LlmUsage).filter(LlmUsage.owner_id == owner).all()
    assert len(rows) == 1
    assert rows[0].call_site == "untagged"
    assert rows[0].transport == "direct"
    assert rows[0].est_cost_usd == pytest.approx(30.0)

    assert usage.spent_today_usd(owner) == pytest.approx(30.0)


def test_record_honours_call_site_tag(fresh_db, monkeypatch):
    owner = "rec-tag@example.com"
    monkeypatch.setenv("EMAIL_ADDRESS", owner)

    with usage.call_site("preflight"):
        usage.record("claude-opus-4-6", "direct", {"input_tokens": 10})

    from zylch.storage.database import get_session
    from zylch.storage.models import LlmUsage

    with get_session() as s:
        row = s.query(LlmUsage).filter(LlmUsage.owner_id == owner).one()
    assert row.call_site == "preflight"
    # Tag is restored to the default after the block.
    assert usage.current_call_site() == "untagged"


# ─────────────────────────────────────────────────────────────────────
# Budget
# ─────────────────────────────────────────────────────────────────────


def test_budget_over_budget_is_exceeded(fresh_db, monkeypatch):
    owner = "bud-over@example.com"
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "3")
    _seed(owner, 2.5)
    _seed(owner, 1.0)  # total 3.5 > 3

    state = usage.budget_state(owner)
    assert state["spent_usd"] == pytest.approx(3.5)
    assert state["budget_usd"] == pytest.approx(3.0)
    assert state["exceeded"] is True


def test_budget_under_budget_not_exceeded(fresh_db, monkeypatch):
    owner = "bud-under@example.com"
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "3")
    _seed(owner, 1.0)
    state = usage.budget_state(owner)
    assert state["exceeded"] is False


def test_budget_exactly_at_cap_is_exceeded(fresh_db, monkeypatch):
    # "reaches the limit" == spent >= budget.
    owner = "bud-exact@example.com"
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "3")
    _seed(owner, 3.0)
    assert usage.budget_state(owner)["exceeded"] is True


def test_budget_zero_means_uncapped(fresh_db, monkeypatch):
    owner = "bud-zero@example.com"
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    _seed(owner, 1000.0)  # miles over any sane cap
    state = usage.budget_state(owner)
    assert state["budget_usd"] == pytest.approx(0.0)
    assert state["exceeded"] is False


def test_budget_negative_means_uncapped(fresh_db, monkeypatch):
    owner = "bud-neg@example.com"
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "-1")
    _seed(owner, 1000.0)
    assert usage.budget_state(owner)["exceeded"] is False


def test_budget_default_when_unset(fresh_db, monkeypatch):
    owner = "bud-default@example.com"
    monkeypatch.delenv("LLM_DAILY_BUDGET_USD", raising=False)
    assert usage.daily_budget_usd() == pytest.approx(usage.DEFAULT_DAILY_BUDGET_USD)
    _seed(owner, usage.DEFAULT_DAILY_BUDGET_USD + 1.0)
    assert usage.budget_state(owner)["exceeded"] is True


def test_budget_invalid_value_falls_back_to_default(fresh_db, monkeypatch):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "not-a-number")
    assert usage.daily_budget_usd() == pytest.approx(usage.DEFAULT_DAILY_BUDGET_USD)


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf"])
def test_budget_non_finite_falls_back_to_default(fresh_db, monkeypatch, raw):
    """float() accepts 'nan'/'inf'; nan would make `budget > 0` False and
    silently DISABLE the cap (T5 review, finding e). Non-finite values
    must degrade to the default — the capped direction, never uncapped."""
    owner = "bud-nan@example.com"
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", raw)
    assert usage.daily_budget_usd() == pytest.approx(usage.DEFAULT_DAILY_BUDGET_USD)
    _seed(owner, usage.DEFAULT_DAILY_BUDGET_USD + 1.0)
    assert usage.budget_state(owner)["exceeded"] is True  # cap still bites


def test_budget_reads_env_live_mid_test(fresh_db, monkeypatch):
    """Changing os.environ mid-run changes the verdict — proves the cap
    is read at call time, not from a frozen pydantic settings snapshot."""
    owner = "bud-live@example.com"
    _seed(owner, 5.0)

    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "100")
    assert usage.budget_state(owner)["exceeded"] is False  # 5 < 100

    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "3")
    assert usage.budget_state(owner)["exceeded"] is True  # 5 >= 3


def test_spent_today_excludes_prior_days(fresh_db, monkeypatch):
    owner = "bud-window@example.com"
    _seed(owner, 4.0, days_ago=0)  # today
    _seed(owner, 99.0, days_ago=2)  # two days ago — must not count
    assert usage.spent_today_usd(owner) == pytest.approx(4.0)


def test_spent_today_is_owner_scoped(fresh_db):
    _seed("owner-a@example.com", 2.0)
    _seed("owner-b@example.com", 9.0)
    assert usage.spent_today_usd("owner-a@example.com") == pytest.approx(2.0)
    assert usage.spent_today_usd("owner-b@example.com") == pytest.approx(9.0)
